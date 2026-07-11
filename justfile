# pct-eval — E1 benchmark harness (presidio-v conventions).
#
# The OFFICIAL numbers are produced on the owner's Apple-silicon Mac mini; this
# justfile selects the darwin-arm64 OPA binary there automatically. In the Linux
# sandbox the same targets run with reduced exercise counts (export the PCT_*
# vars below) and every CSV is stamped SANDBOX. See README.md.

set shell := ["bash", "-uc"]

workloads := "workloads"
results := "results"
plots_dir := "plots"

# Exercise counts. Mac defaults model the plan's 10^5; override for the sandbox:
#   PCT_N_ALLOW=3000 PCT_OPA_LOCAL=500 PCT_OPA_DELAY=120 PCT_SANDBOX=true just bench-e1
n_allow := env_var_or_default("PCT_N_ALLOW", "100000")

host := `hostname`
stamp := `date -u +%Y%m%dT%H%M%SZ`

# Platform metadata stamped into every CSV row (Rust + Python read these).
export PCT_HOST := env_var_or_default("PCT_HOST", `hostname`)
export PCT_SANDBOX := env_var_or_default("PCT_SANDBOX", "false")
export PCT_CPU := env_var_or_default("PCT_CPU", "unknown")

# --- workload ---------------------------------------------------------------

# Generate the canonical seeded fixtures (committed to workloads/).
gen:
    cargo run -p workload-gen --release -- {{workloads}} {{n_allow}}

build:
    cargo build --release

# --- correctness gate (must pass before any timing run) ---------------------

# All three systems must agree (ALLOW on the happy set, DENY on the crafted
# violations) or the gate fails closed and the benches refuse to run.
verify: build gen
    ./target/release/e1-biscuit verify {{workloads}} {{results}}/biscuit-verdicts.json
    python3 python/grant_bench.py verdicts {{workloads}} {{results}}/grant-verdicts.json
    ./scripts/opa_e1.sh verdicts
    python3 python/verify_gate.py {{workloads}} {{results}}

# --- benches (each depends on the gate) -------------------------------------

bench-e1-biscuit: verify
    ./target/release/e1-biscuit bench {{workloads}} {{results}}/e1-biscuit_{{host}}_{{stamp}}.csv

bench-e1-grant: verify
    python3 python/grant_bench.py bench {{workloads}} {{results}}/e1-grant_{{host}}_{{stamp}}.csv

bench-e1-opa: verify
    ./scripts/opa_e1.sh bench

# Run the whole E1 sweep (gate once, then all three systems).
bench-e1: verify bench-e1-biscuit bench-e1-grant bench-e1-opa
    @echo "E1 complete — CSVs in {{results}}/"

# Criterion cross-check (single depth-4 config; methodological sanity).
bench-criterion:
    cargo bench -p e1-biscuit

# --- plots ------------------------------------------------------------------

plots:
    python3 python/plot.py {{results}} {{plots_dir}}

# --- E3 (cut-first skeleton) ------------------------------------------------

# Type-check the E3 crate (deps + bench compile).
e3-check:
    cargo check -p e3-accumulator

# Run the E3 accumulator revocation microbenchmark (single-core, parallel off).
# Measures non-membership gen/verify + epoch-root / omega-publish / witness-update
# for batch revocations 10^2/10^3/10^4 against vb_accumulator 0.29. Correctness
# gates run before every timing loop (measured, never estimated).
bench-e3:
    cargo build -p e3-accumulator --release --bin e3-bench
    ./target/release/e3-bench {{results}}/e3-accum_{{host}}_{{stamp}}.csv

clean:
    rm -rf {{plots_dir}}/*.png
