#!/usr/bin/env bash
# R2 cross-platform replication of E1 and E3 on x86-64 Linux in a container.
#
# Runs the published harness (computational-jurisprudence-eval, commit b42ae1b,
# tag v1-fi-revision-2026-08-03) unmodified, against the committed seeded
# fixtures, on a platform class the article had not measured: x86-64, Linux,
# containerized, under a hypervisor, four vCPUs.
#
# What is held identical to the reference (Apple M4 Mac mini) run:
#   * the committed workload fixtures (same generator, same seed, same corpus)
#   * OPA 1.18.2, the same version the reference run used
#   * toxiproxy latency toxics for the +5 ms and +20 ms configurations
#   * exercise counts: 10^5 for the local configurations, 10^4 for the delay ones
#   * warm-up, keep-alive, and pre-materialization behaviour (harness defaults)
#
# What differs, and is recorded in every CSV row:
#   * host / os / arch / cpu
#   * the sweep covers fanout 1 only, the configuration the article reports
#   * the correctness gate is two-way (Biscuit, OPA), because grant@1's artifact
#     is not public — see python/verify_gate_2way.py
#
# Usage: bash run-cloud-x86.sh /path/to/computational-jurisprudence-eval
set -euo pipefail

ROOT="${1:-/workspace/vstantch/computational-jurisprudence-eval}"
cd "$ROOT"

export PATH="$ROOT/bin:$PATH"
export PCT_HOST="cj-cloud-x86"
export PCT_CPU="Intel Xeon @ 2.10GHz (4 vCPU)"
export PCT_SANDBOX=false
export PCT_DELAY_METHOD=toxiproxy
export PCT_WORKLOADS="$ROOT/workloads-f1"
export PCT_RESULTS="$ROOT/results/cloud-x86"
export PCT_OPA_LOCAL="${PCT_OPA_LOCAL:-100000}"
export PCT_OPA_DELAY="${PCT_OPA_DELAY:-10000}"

mkdir -p "$PCT_RESULTS" "$ROOT/bin"

# Fanout-1 view of the committed fixtures (symlinks; the fixtures are untouched).
if [ ! -d "$PCT_WORKLOADS" ]; then
  mkdir -p "$PCT_WORKLOADS"
  for f in "$ROOT"/workloads/graph_d*_f1.json; do ln -sf "$f" "$PCT_WORKLOADS/"; done
fi

# toxiproxy is the delay method the reference run used; opa_e1.sh fetches OPA itself.
if ! command -v toxiproxy-server >/dev/null 2>&1; then
  echo "fetching toxiproxy-server"
  curl -fsSL -o "$ROOT/bin/toxiproxy-server" \
    "https://github.com/Shopify/toxiproxy/releases/download/v2.12.0/toxiproxy-server-linux-amd64"
  chmod +x "$ROOT/bin/toxiproxy-server"
fi

cargo build --release -p e1-biscuit
cargo build --release -p e3-accumulator --bin e3-bench

echo "=== gate (2-way: biscuit == OPA == expected) ==="
./target/release/e1-biscuit verify "$PCT_WORKLOADS" "$PCT_RESULTS/biscuit-verdicts.json"
./scripts/opa_e1.sh verdicts
python3 python/verify_gate_2way.py "$PCT_WORKLOADS" "$PCT_RESULTS"

echo "=== E1: Biscuit (local, in-process) ==="
./target/release/e1-biscuit bench "$PCT_WORKLOADS" \
  "$PCT_RESULTS/e1-biscuit_${PCT_HOST}_$(date -u +%Y%m%dT%H%M%SZ).csv"

echo "=== E1: OPA (local / +5 ms / +20 ms via toxiproxy) ==="
./scripts/opa_e1.sh bench

echo "=== E3: accumulator revocation ==="
./target/release/e3-bench "$PCT_RESULTS/e3-accum_${PCT_HOST}_$(date -u +%Y%m%dT%H%M%SZ).csv"

echo "=== done — CSVs in $PCT_RESULTS ==="
ls -la "$PCT_RESULTS"
