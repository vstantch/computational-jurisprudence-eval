#!/usr/bin/env bash
# OPA baseline orchestration for E1: fetch the OPA static binary for this
# platform, serve policies/capability.rego over localhost, and either emit
# verdicts (for the correctness gate) or run the decision-latency bench in the
# {local, 5ms, 20ms} configs.
#
# Delay injection (PCT_DELAY_METHOD): "toxiproxy" uses a native toxiproxy latency
# toxic (upstream, in front of the PDP) — the plan's chosen method; any other
# value falls back to python/delay_proxy.py (asyncio one-way delay on the request
# path). The CSV `config` column records the target delay (local/5ms/20ms).
#
# Usage: scripts/opa_e1.sh {verdicts|bench}
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODE="${1:-bench}"
WORKLOADS="${PCT_WORKLOADS:-$ROOT/workloads}"
RESULTS="${PCT_RESULTS:-$ROOT/results}"
OPA_BIN="$ROOT/bin/opa"
OPA_PORT="${OPA_PORT:-8181}"
PROXY5="${PROXY5:-18185}"
PROXY20="${PROXY20:-18186}"
# Exercise counts per config. Mac defaults model the plan's 10^5; the sandbox
# overrides these down (see README) so each run fits the environment.
OPA_LOCAL="${PCT_OPA_LOCAL:-100000}"
OPA_DELAY="${PCT_OPA_DELAY:-10000}"

mkdir -p "$RESULTS" "$ROOT/bin"

# --- fetch OPA static binary for this platform if missing --------------------
if [[ ! -x "$OPA_BIN" ]]; then
  os=$(uname -s | tr '[:upper:]' '[:lower:]')
  arch=$(uname -m)
  case "$os-$arch" in
    darwin-arm64)          url="https://openpolicyagent.org/downloads/latest/opa_darwin_arm64" ;;
    darwin-x86_64)         url="https://openpolicyagent.org/downloads/latest/opa_darwin_amd64" ;;
    linux-aarch64|linux-arm64) url="https://openpolicyagent.org/downloads/latest/opa_linux_arm64_static" ;;
    linux-x86_64)          url="https://openpolicyagent.org/downloads/latest/opa_linux_amd64_static" ;;
    *) echo "unknown platform $os-$arch" >&2; exit 1 ;;
  esac
  echo "fetching OPA static binary: $url"
  curl -fSL -o "$OPA_BIN" "$url"
  chmod +x "$OPA_BIN"
fi

PIDS=()
cleanup() { for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT

# --- serve the published Rego policy -----------------------------------------
"$OPA_BIN" run --server --addr "127.0.0.1:$OPA_PORT" "$ROOT/policies/capability.rego" \
  >/tmp/opa-server.log 2>&1 &
PIDS+=($!)
for _ in $(seq 1 60); do
  curl -sf "http://127.0.0.1:$OPA_PORT/health" >/dev/null 2>&1 && break
  sleep 0.25
done
OPA_VER=$("$OPA_BIN" version 2>/dev/null | awk '/^Version:/{print $2}')
export PCT_RUNTIME="${PCT_RUNTIME:-opa-${OPA_VER:-unknown}}"

if [[ "$MODE" == "verdicts" ]]; then
  OPA_PORT="$OPA_PORT" python3 "$ROOT/python/opa_bench.py" verdicts "$WORKLOADS" "$RESULTS/opa-verdicts.json"
  exit 0
fi

# --- bench: local, then +5ms, then +20ms -------------------------------------
OUT="$RESULTS/e1-opa_$(hostname)_$(date -u +%Y%m%dT%H%M%SZ).csv"
OPA_PORT="$OPA_PORT" python3 "$ROOT/python/opa_bench.py" bench "$WORKLOADS" "$OUT" local "$OPA_LOCAL"

DELAY_METHOD="${PCT_DELAY_METHOD:-asyncio}"
if [[ "$DELAY_METHOD" == "toxiproxy" ]]; then
  # Native toxiproxy: one latency toxic per config, on the upstream stream so the
  # delay sits in front of the PDP (client -> OPA). Driven over the REST API.
  TOXI_URL="${TOXIPROXY_URL:-http://127.0.0.1:8474}"
  if ! curl -sf "$TOXI_URL/version" >/dev/null 2>&1; then
    command -v toxiproxy-server >/dev/null 2>&1 || { echo "toxiproxy-server not found on PATH" >&2; exit 1; }
    toxiproxy-server >/tmp/toxiproxy-server.log 2>&1 &
    PIDS+=($!)
    for _ in $(seq 1 40); do curl -sf "$TOXI_URL/version" >/dev/null 2>&1 && break; sleep 0.25; done
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
