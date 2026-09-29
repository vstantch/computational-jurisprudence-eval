#!/usr/bin/env bash
# OPA baseline orchestration for E1: fetch the OPA static binary for this
# platform, serve policies/capability.rego over localhost, and either emit
# verdicts (for the correctness gate) or run the decision-latency bench in the
# {local, 5ms, 20ms} configs.
#
# Delay injection (PCT_DELAY_METHOD): "toxiproxy" uses a native toxiproxy latency
# toxic (upstream, in front of the PDP); per commit 2b424a2, the official
# 2026-07-11 OPA run used it. Unset or any other value falls back to python/delay_proxy.py
# (asyncio one-way delay on the request path). The CSV `config` column records
# the target delay (local/5ms/20ms), not the method.
#
# OPA 1.18.2 and toxiproxy 2.12.0 are pinned: fetched by exact version into
# bin/, and their SHA-256 is checked on every run (a mismatch aborts). OPA runs
# with --skip-version-check, so it makes no outbound call at startup.
# PCT_OPA_LOG_LEVEL (unset = OPA's default, info, as in every committed run)
# is passed to `opa run --log-level` when set.
#
# Usage: scripts/opa_e1.sh {verdicts|bench}
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODE="${1:-bench}"
WORKLOADS="${PCT_WORKLOADS:-$ROOT/workloads}"
RESULTS="${PCT_RESULTS:-$ROOT/results}"
OPA_BIN="$ROOT/bin/opa"
TOXI_BIN="$ROOT/bin/toxiproxy-server"
OPA_VERSION=1.18.2
TOXI_VERSION=2.12.0
HOST_LABEL="${PCT_HOST:-anon}"
OPA_PORT="${OPA_PORT:-8181}"
PROXY5="${PROXY5:-18185}"
PROXY20="${PROXY20:-18186}"
# Exercise counts per config. Mac defaults model the plan's 10^5; the sandbox
# overrides these down (see README) so each run fits the environment.
OPA_LOCAL="${PCT_OPA_LOCAL:-100000}"
OPA_DELAY="${PCT_OPA_DELAY:-10000}"

mkdir -p "$RESULTS" "$ROOT/bin"

# --- pinned binaries: exact version, SHA-256 checked on every run ------------
sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}
fetch_pinned() { # dest url sha256
  if [[ ! -f "$1" ]]; then
    echo "fetching $2"
    curl -fSL -o "$1.part" "$2"
    mv "$1.part" "$1"
  fi
  local got
  got="$(sha256_of "$1")"
  if [[ "$got" != "$3" ]]; then
    echo "SHA-256 mismatch for $1: got $got, want $3 (delete it to re-fetch)" >&2
    exit 1
  fi
  chmod +x "$1"
}
platform="$(uname -s | tr '[:upper:]' '[:lower:]')-$(uname -m)"
case "$platform" in
  darwin-arm64)
    opa_file=opa_darwin_arm64;         opa_sha=b3f19f0ecf1ffcea9c36d29e43dfe3b718cd59fa12859fe86975b536889590e4
    toxi_file=toxiproxy-server-darwin-arm64; toxi_sha=aa299966b52f16a8594f1cd0d1e9049dc2e8fe2c04a90c19860e2719b2b95d15 ;;
  darwin-x86_64)
    opa_file=opa_darwin_amd64;         opa_sha=e7090da5f3791c71b74e6f0a5703b37f32ab3eb5916abc227f8da9f6773d44be
    toxi_file=toxiproxy-server-darwin-amd64; toxi_sha=9625bba4bd96117eedae49f982aba4c2f462b268dd406c9ff18186f9b1ef8afe ;;
  linux-aarch64|linux-arm64)
    opa_file=opa_linux_arm64_static;   opa_sha=9cad2e67d375aded483823349173fe100d9701d37635908edadeb0298603c58c
    toxi_file=toxiproxy-server-linux-arm64;  toxi_sha=53e770c1c3035b5a9f1bc629fce537db1f95f62b26f4ebe6e756afd701cf077c ;;
  linux-x86_64)
    opa_file=opa_linux_amd64_static;   opa_sha=9903e5125ac281104f2c4b7371d10cc3b74a98933743fcbfc174f9bf0ab20de8
    toxi_file=toxiproxy-server-linux-amd64;  toxi_sha=556d891134a3c582dc1e1a3f7335fd55142e5965769855a00b944e13e48302fc ;;
  *) echo "unsupported platform $platform" >&2; exit 1 ;;
esac
fetch_pinned "$OPA_BIN" "https://github.com/open-policy-agent/opa/releases/download/v$OPA_VERSION/$opa_file" "$opa_sha"

PIDS=()
cleanup() { for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT

# --- serve the published Rego policy -----------------------------------------
# The port must be free first (a previous OPA may still be shutting down),
# and OPA must answer /health within 15 s; otherwise fail rather than bench.
for _ in $(seq 1 60); do
  curl -s -o /dev/null "http://127.0.0.1:$OPA_PORT/" || break
  sleep 0.25
done
if curl -s -o /dev/null "http://127.0.0.1:$OPA_PORT/"; then
  echo "port $OPA_PORT is still in use after 15 s; stop the process holding it" >&2
  exit 1
fi
OPA_FLAGS=(--skip-version-check)
[[ -n "${PCT_OPA_LOG_LEVEL:-}" ]] && OPA_FLAGS+=(--log-level "$PCT_OPA_LOG_LEVEL")
"$OPA_BIN" run --server "${OPA_FLAGS[@]}" --addr "127.0.0.1:$OPA_PORT" "$ROOT/policies/capability.rego" \
  >/tmp/opa-server.log 2>&1 &
PIDS+=($!)
healthy=0
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:$OPA_PORT/health" >/dev/null 2>&1; then healthy=1; break; fi
  sleep 0.25
done
if [[ "$healthy" != 1 ]]; then
  echo "OPA did not become healthy on port $OPA_PORT within 15 s; log:" >&2
  tail -20 /tmp/opa-server.log >&2
  exit 1
fi
OPA_VER=$("$OPA_BIN" version 2>/dev/null | awk '/^Version:/{print $2}')
export PCT_RUNTIME="${PCT_RUNTIME:-opa-${OPA_VER:-unknown}}"

if [[ "$MODE" == "verdicts" ]]; then
  OPA_PORT="$OPA_PORT" python3 "$ROOT/python/opa_bench.py" verdicts "$WORKLOADS" "$RESULTS/opa-verdicts.json"
  exit 0
fi

# --- bench: local, then +5ms, then +20ms -------------------------------------
OUT="$RESULTS/e1-opa_${HOST_LABEL}_$(date -u +%Y%m%dT%H%M%SZ).csv"
OPA_PORT="$OPA_PORT" python3 "$ROOT/python/opa_bench.py" bench "$WORKLOADS" "$OUT" local "$OPA_LOCAL"

DELAY_METHOD="${PCT_DELAY_METHOD:-asyncio}"
if [[ "$DELAY_METHOD" == "toxiproxy" ]]; then
  # Native toxiproxy: one latency toxic per config, on the upstream stream so the
  # delay sits in front of the PDP (client -> OPA). Driven over the REST API.
  TOXI_URL="${TOXIPROXY_URL:-http://127.0.0.1:8474}"
  if ! curl -sf "$TOXI_URL/version" >/dev/null 2>&1; then
    fetch_pinned "$TOXI_BIN" "https://github.com/Shopify/toxiproxy/releases/download/v$TOXI_VERSION/$toxi_file" "$toxi_sha"
    "$TOXI_BIN" -host 127.0.0.1 >/tmp/toxiproxy-server.log 2>&1 &
    PIDS+=($!)
    for _ in $(seq 1 40); do curl -sf "$TOXI_URL/version" >/dev/null 2>&1 && break; sleep 0.25; done
  fi
  toxi_ver="$(curl -sf "$TOXI_URL/version" || true)"
  if [[ "$toxi_ver" != *"$TOXI_VERSION"* ]]; then
    echo "toxiproxy at $TOXI_URL reports version '$toxi_ver', want $TOXI_VERSION" >&2
    exit 1
  fi
  make_proxy() { # name listen_port latency_ms
    curl -sf -XDELETE "$TOXI_URL/proxies/$1" >/dev/null 2>&1 || true
    curl -sf -XPOST "$TOXI_URL/proxies" \
      -d "{\"name\":\"$1\",\"listen\":\"127.0.0.1:$2\",\"upstream\":\"127.0.0.1:$OPA_PORT\",\"enabled\":true}" >/dev/null
    curl -sf -XPOST "$TOXI_URL/proxies/$1/toxics" \
      -d "{\"name\":\"lat\",\"type\":\"latency\",\"stream\":\"upstream\",\"attributes\":{\"latency\":$3,\"jitter\":0}}" >/dev/null
  }
  make_proxy opa5  "$PROXY5"  5
  make_proxy opa20 "$PROXY20" 20
  toxi_cleanup() {
    curl -sf -XDELETE "$TOXI_URL/proxies/opa5"  >/dev/null 2>&1 || true
    curl -sf -XDELETE "$TOXI_URL/proxies/opa20" >/dev/null 2>&1 || true
  }
  trap 'toxi_cleanup; cleanup' EXIT
  echo "delay injection: toxiproxy ($TOXI_URL) — opa5=+5ms opa20=+20ms (upstream latency toxic)"
else
  python3 "$ROOT/python/delay_proxy.py" "$PROXY5"  127.0.0.1 "$OPA_PORT" 5  >/tmp/proxy5.log 2>&1 &
  PIDS+=($!)
  python3 "$ROOT/python/delay_proxy.py" "$PROXY20" 127.0.0.1 "$OPA_PORT" 20 >/tmp/proxy20.log 2>&1 &
  PIDS+=($!)
  echo "delay injection: asyncio delay_proxy.py — +5ms/+20ms (one-way request path)"
fi
sleep 1

OPA_PORT="$PROXY5"  python3 "$ROOT/python/opa_bench.py" bench "$WORKLOADS" "$OUT" 5ms  "$OPA_DELAY"
OPA_PORT="$PROXY20" python3 "$ROOT/python/opa_bench.py" bench "$WORKLOADS" "$OUT" 20ms "$OPA_DELAY"
echo "wrote $OUT"
