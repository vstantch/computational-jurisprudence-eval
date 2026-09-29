#!/usr/bin/env bash
# Repeated-execution variability sweep for E1 (reviewer request: run-to-run
# uncertainty, not just within-run percentiles).
#
# Runs the whole E1 sweep R times, each repetition in a FRESH process, with a
# fresh OPA server and fresh toxiproxy proxies, writing one CSV per system per
# repetition into results/variability/. The exercise count per configuration is
# reduced (PCT_MAX_PER_CONFIG / PCT_OPA_LOCAL / PCT_OPA_DELAY) so that R
# independent executions are affordable; the official single-execution run at
# 10^5 remains the headline table. python/variability.py aggregates.
#
# Usage: scripts/repeat_e1.sh [R] [MAX_LOCAL] [MAX_DELAY]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
R="${1:-5}"
MAX_LOCAL="${2:-10000}"
MAX_DELAY="${3:-2000}"
OUT="$ROOT/results/variability"
mkdir -p "$OUT"

export PCT_HOST="${PCT_HOST:-anon}"
export PCT_SANDBOX="${PCT_SANDBOX:-false}"
export PCT_CPU="${PCT_CPU:-unknown}"
export PCT_DELAY_METHOD="${PCT_DELAY_METHOD:-toxiproxy}"
export PCT_MAX_PER_CONFIG="$MAX_LOCAL"
export PCT_OPA_LOCAL="$MAX_LOCAL"
export PCT_OPA_DELAY="$MAX_DELAY"
export PCT_RESULTS="$OUT"

cd "$ROOT"
cargo build --release --bin e1-biscuit >/dev/null

for i in $(seq 1 "$R"); do
  echo "=== repetition $i/$R (local=$MAX_LOCAL, delay=$MAX_DELAY) ==="
  ./target/release/e1-biscuit bench workloads "$OUT/rep${i}-biscuit.csv"
  python3 python/grant_bench.py bench workloads "$OUT/rep${i}-grant.csv"
  # opa_e1.sh names its own output; capture and rename to the repetition slot.
  ./scripts/opa_e1.sh bench
  newest=$(ls -t "$OUT"/e1-opa_*.csv 2>/dev/null | head -1)
  if [[ -n "$newest" ]]; then mv "$newest" "$OUT/rep${i}-opa.csv"; else echo "WARNING: no OPA CSV for rep $i"; fi
  echo "=== repetition $i complete ==="
done

echo "all $R repetitions written to $OUT"
