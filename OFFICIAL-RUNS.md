# Official benchmark runs — Mac mini procedure
_The paper's numbers come from these runs. Sandbox CSVs (stamped `sandbox=true`) are shape-checks only and get replaced wholesale. Integrity rule: nothing lands in the paper that these commands did not measure._

## A. Prerequisites (once)

```bash
# toolchain
brew install just toxiproxy            # rust via rustup (stable), python3.11+ assumed
rustup default stable
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

just verify        # correctness gate: 3-way agreement incl. crafted violations.
                   # MUST print PASS; benches refuse to run otherwise.
just bench-e1      # gate + biscuit + grant@1 + OPA (local); ~30-60 min at 10^5
```

Delay configs (+5 ms / +20 ms): the sandbox used the asyncio fallback proxy; on the Mac use toxiproxy for the paper (cleaner methodology statement):

```bash
toxiproxy-server &                              # then in a second shell:
./scripts/opa_e1.sh bench-delayed toxiproxy      # creates proxies w/ 5ms and 20ms latency toxics
# (if the script lacks the toxiproxy mode, run: ./scripts/opa_e1.sh bench
#  with the fallback proxy — identical semantics, say so in the paper's methods)
just plots
```

Outputs: `results/e1-*_<host>_<stamp>.csv` (sandbox=false), `plots/*.png`.

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