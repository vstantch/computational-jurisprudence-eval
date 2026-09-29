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

stamp := `date -u +%Y%m%dT%H%M%SZ`

# Platform metadata stamped into every CSV row (Rust + Python read these).
# PCT_HOST labels rows and file names; it defaults to "anon", never `hostname`.
export PCT_HOST := env_var_or_default("PCT_HOST", "anon")
host := PCT_HOST
export PCT_SANDBOX := env_var_or_default("PCT_SANDBOX", "false")
export PCT_CPU := env_var_or_default("PCT_CPU", "unknown")

# --- workload ---------------------------------------------------------------

# Regenerate the canonical seeded fixtures. They are committed; this overwrites
# workloads/ and is never run by verify. Afterwards, `just verify-fixtures`
# shows whether the output is byte-identical to the committed set.
gen:
    cargo run -p workload-gen --release -- {{workloads}} {{n_allow}}

# The committed fixtures must match workloads/SHA256SUMS.
verify-fixtures:
    python3 python/check_fixtures.py {{workloads}}

build:
    cargo build --release --locked

# --- correctness gate (must pass before any timing run) ---------------------

# All three systems must agree (ALLOW on the happy set, DENY on the crafted
# violations) or the gate fails closed and the benches refuse to run.
# REQUIRES the private presidio-hardened-x402 checkout (PCT_X402_SRC) for
# capability-grant@1; without it, use verify-public.
verify: build verify-fixtures
    ./target/release/e1-biscuit verify {{workloads}} {{results}}/biscuit-verdicts.json
    python3 python/grant_bench.py verdicts {{workloads}} {{results}}/grant-verdicts.json
    ./scripts/opa_e1.sh verdicts
    python3 python/verify_gate.py {{workloads}} {{results}}

# Two-way gate (Biscuit and OPA) that runs without the private x402 checkout:
# biscuit == OPA == expected on the same gate subset as `verify`.
# Its verdict files go to target/gate/, never over the committed results/ ones.
verify-public: build verify-fixtures
    mkdir -p target/gate
    ./target/release/e1-biscuit verify {{workloads}} target/gate/biscuit-verdicts.json
    PCT_RESULTS=target/gate ./scripts/opa_e1.sh verdicts
    python3 python/verify_gate_2way.py {{workloads}} target/gate

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

# E1 sweep for the two public systems (Biscuit, OPA) behind the two-way gate.
bench-e1-public: verify-public
    ./target/release/e1-biscuit bench {{workloads}} {{results}}/e1-biscuit_{{host}}_{{stamp}}.csv
    PCT_RESULTS={{results}} ./scripts/opa_e1.sh bench

# Criterion cross-check (single depth-4 config; methodological sanity).
bench-criterion:
    cargo bench -p e1-biscuit

# --- plots ------------------------------------------------------------------

# Plots of the reference platform's official E1 files (results/MANIFEST.toml).
# The committed plots/*.png predate this recipe: they mix the sandbox rows and
# the official rows of results/ in one series (see ERRATA-DRAFT.md).
plots:
    python3 python/plot.py --platform apple-m4 {{plots_dir}}

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
