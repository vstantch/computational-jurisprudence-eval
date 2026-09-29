# Official benchmark runs — Mac mini procedure
_The paper's numbers come from these runs. Sandbox CSVs (stamped `sandbox=true`) are shape-checks only and get replaced wholesale. Integrity rule: nothing lands in the paper that these commands did not measure._

## A. Prerequisites (once)

```bash
# toolchain
brew install just                     # rust via rustup, python3.11+ assumed
rustup toolchain install 1.96.1       # the channel rust-toolchain.toml pins
pip install -r python/requirements.txt # hashed lock (python/requirements.in lists the direct deps)
# OPA 1.18.2 and toxiproxy 2.12.0 are NOT installed by hand: scripts/opa_e1.sh
# fetches both into bin/ by exact version and checks their SHA-256.
# quiet machine per the OOM-guard rule: Ollama/agents OFF, power connected,
# no Time Machine backup running; keep the lid closed / display sleep off.
```

## B. E1 — three-way microbenchmark (`~/projects/pct-eval`)

```bash
cd ~/projects/pct-eval

# platform metadata stamped into every CSV row — set BOTH:
export PCT_SANDBOX=false
export PCT_CPU="Apple M2 Pro (10 cores)"        # adjust to the real chip/cores
export PCT_N_ALLOW=100000                       # the plan's 10^5 (Mac default anyway)
export PCT_DELAY_METHOD=toxiproxy               # REQUIRED for the paper's delay rows (see below)
export PCT_HOST=mac-mini                        # label for rows and file names (default "anon")

just verify        # correctness gate: 3-way agreement incl. crafted violations.
                   # Needs the private x402 checkout (PCT_X402_SRC). Checks the
                   # fixtures against workloads/SHA256SUMS; never regenerates them.
                   # MUST print PASS; benches refuse to run otherwise.
just bench-e1      # gate + biscuit + grant@1 + OPA (local, +5 ms, +20 ms)
```

Delay configs (+5 ms / +20 ms): `scripts/opa_e1.sh bench` runs them after the
local configuration. The method is chosen by `PCT_DELAY_METHOD`: `toxiproxy`
puts an upstream latency toxic in front of OPA (the script starts
`bin/toxiproxy-server` on 127.0.0.1 unless one already answers on :8474, and
checks that it reports version 2.12.0); unset or any other value uses the
asyncio fallback `python/delay_proxy.py`, which delays each relayed chunk in
turn. Per commit 2b424a2, the official 2026-07-11 OPA run used toxiproxy. There is
no `bench-delayed` mode, and the CSVs have no method column: the `config`
column records only the target delay, so record the method with the run.

```bash
just plots         # PNGs of the reference platform's official files (manifest)
```

Outputs: `results/e1-*_<PCT_HOST>_<stamp>.csv` (sandbox=false), `plots/*.png`.
List every file that a table will use in `results/MANIFEST.toml` (path, sha256,
platform, system, role) and run `python3 python/results_manifest.py check`.

## C. E2 — end-to-end capability-enforced payments (`~/projects/presidio-hardened-x402/tools`)

```bash
cd ~/projects/presidio-hardened-x402/tools
python3 -m venv .venv-bench && .venv-bench/bin/pip install -e ".[dev,evidence]"

# full corpus replay, both PII modes, depths 1-6, full corpus (limit 0):
.venv-bench/bin/python experiments/e2_replay.py --depths 1 2 4 6 --limit 0 \
  --pii-mode regex --seed 42 --out experiments/results/e2_replay_regex_official.csv
.venv-bench/bin/python experiments/e2_replay.py --depths 1 2 4 6 --limit 0 \
  --pii-mode nlp   --seed 42 --out experiments/results/e2_replay_nlp_official.csv
#   nlp mode is the one comparable to the published 5.73 ms p99 baseline.

# 50-case violation detection table:
.venv-bench/bin/python experiments/e2_violations.py \
  --json-out experiments/results/e2_detection_official.json
```

## D. E3 decision point (opt