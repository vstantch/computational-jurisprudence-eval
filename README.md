# pct-eval — E1 benchmark harness

Evaluation harness for **E1** of *Proof-Carrying Transactions for Agentic
Payments: Design and First Evaluation* (arXiv resubmission). E1 is the
Pillar-I microbenchmark: **delegation-chain verification vs. a centralized PDP**.

**Claim under test (paper §3.3, "performance dividend"):** capability
verification is *local* and O(1)-ish per exercise, whereas a centralized PDP
pays a network round-trip and an availability dependency.

E1 is a **three-way comparison** over one canonical, seeded workload:

| system | what it is | where it runs |
|---|---|---|
| **Biscuit** | `biscuit-auth` (Rust) tokens with attenuation caveats | local, in-process |
| **capability-grant@1** | the shipped `presidio_x402.capability` artifact, **benched as-is** (a Python artifact — the paper says so) | local, in-process |
| **OPA** | Open Policy Agent as a centralized PDP; the published Rego policy over localhost HTTP; `local`, `+5ms`, `+20ms` injected-delay configs | localhost + delay proxy |

---

## Integrity rule (non-negotiable)

Synthetic **workloads** are standard and declared as such (see
`crates/workload-gen`). Synthetic **results are forbidden** — the harness only
ever reports what it measured. Every CSV row carries platform metadata
(`host,os,arch,cpu,runtime,sandbox`) and a `sandbox` flag. There is no code path
that emits an estimated or extrapolated number.

**Sandbox vs. official numbers.** The CSVs and PNGs currently in `results/` and
`plots/` were produced in a Linux **aarch64 sandbox** with *reduced* exercise
counts and an in-repo asyncio delay proxy (not toxiproxy). They are
**indicative shape-numbers only** and every row is stamped `sandbox=true`. The
**official** numbers are produced on the owner's Apple-silicon **Mac mini** with
the full 10⁵-exercise counts and toxiproxy; see "Re-running" below. Do not cite
sandbox rows in the paper.

---

## Repository layout

```
pct-eval/
├── Cargo.toml / Cargo.lock        # Rust workspace; lockfile committed (pinned deps)
├── rust-toolchain.toml            # pins the toolchain (channel 1.96.1)
├── justfile                       # gen / verify / bench-e1(-biscuit|-grant|-opa) / plots
├── crates/
│   ├── workload-gen/              # THE canonical seeded generator (one source of truth)
│   ├── e1-biscuit/                # Biscuit bench (bin + criterion bench) + verdicts
│   └── e3-accumulator/            # E3 SKELETON ONLY (cut-first); crate choice + rationale
├── python/
│   ├── common.py                  # shared CSV schema + platform stamp + gate subset
│   ├── grant_bench.py             # capability-grant@1 bench + verdicts
│   ├── opa_bench.py               # OPA decision-latency client + verdicts
│   ├── delay_proxy.py             # asyncio TCP delay proxy (toxiproxy fallback)
│   ├── verify_gate.py             # 3-way correctness gate (fail-closed)
│   ├── plot.py                    # one PNG per metric family
│   └── requirements.txt           # pinned Python deps
├── policies/capability.rego       # published Rego policy (same caveat semantics)
├── scripts/opa_e1.sh              # fetch OPA, serve policy, run local/5ms/20ms
├── workloads/                     # generated seeded fixtures (committed) + manifest
├── results/                       # CSV per run (host+timestamp) + verdict JSONs
└── plots/                         # generated PNGs
```

## The canonical workload (one generator, three consumers)

`crates/workload-gen` emits **system-neutral** delegation-graph fixtures:
per-hop caveats plus an exercise stream of `(resource_url, amount, time,
jurisdiction)` tuples with expected verdicts. Each system materialises its own
token / grant / input document from the *same* fixture, so semantic equivalence
is by construction, not by parallel hand-coding.

* Chain **depths** {1, 2, 4, 6, 8, 10}; orchestrator **fan-out** N ∈ {1, 10, 100}.
* Per-hop caveats, monotone-narrowing (child ⊆ parent), matching the
  `capability-grant@1` fragment exactly: per-call cap, daily aggregate cap,
  rolling-window seconds, validity window (`valid_from`/`valid_until`), endpoint
  URL prefixes.
* **Amounts are integer micro-USD everywhere** (1_000_000 = \$1.00), so the whole
  pipeline is float-free (grant@1 rejects floats; Biscuit datalog is i64; Rego
  does integer comparison) — no unit or rounding divergence between systems.
* Exercise stream: allow-stream (timing) + a crafted violation set
  (`over_budget`, `out_of_prefix`, `expired`, `attenuated_depth`) for the gate.
* Seeded (SplitMix64, no external RNG) and **committed** to `workloads/`.

## Correctness gate before timing (fail-closed)

`just verify` makes all three systems emit ALLOW/DENY verdicts over a fixed
subset (first 50 allow + every crafted violation of every config) and asserts

```
biscuit == grant@1 == OPA == expected
```

on every one. Timing targets **depend on** `verify` in the justfile, so a bench
refuses to start unless the three agree. The crafted violations must all be
DENIED by all three; the allow set must all be ALLOWED by all three.

## Semantic equivalence — and the documented divergences

The three systems enforce the SAME per-exercise decision on `(url, amount,
time)`: amount ≤ the tightest per-call cap across the chain, URL under every
hop's endpoint prefix, and time inside every hop's validity window. Biscuit
checks every block; grant@1 checks the intersection (`_intersect` +
`check_payment`); Rego quantifies `every hop`. Two divergences are called out
here because a reviewer will look for exactly this (plan §5 risk table:
"strawmanning"):

1. **jurisdiction.** Biscuit and Rego check `jurisdiction == J` (equality
   caveat). grant@1's `@1` fragment deliberately **omits jurisdiction** (design
   doc "Out of scope for @1"). It is therefore held **constant** across every hop
   and every exercise, so it can never flip a verdict, and it is **not** part of
   the cross-system violation set. This is the one axis where the systems' *ex­­
   pressible* caveats differ; it is neutralised, not hidden.
2. **prefix matching.** grant@1 and Rego match endpoint prefixes on a URL
   host/path boundary (`policy_engine._endpoint_prefix_matches`). Biscuit's
   `starts_with` is a raw string-prefix test. The workload never puts a
   boundary-confusion URL (e.g. `…/inference-evil`) in the cross-system gate —
   `out_of_prefix` uses a *different host*, which all three reject identically —
   so the divergence cannot cause a gate disagreement here. Boundary-confusion
   is exercised only in grant@1's own test suite.

**OPA scope (honest baseline, not a strawman).** The Rego policy models the PDP
*decision*; it does **not** re-verify Ed25519 signatures (a centralized PDP
evaluates policy over an input it trusts). That gives OPA *less* work than the
capability systems, which biases the comparison **in OPA's favour** — the
conservative direction for our thesis. The claim under test is the round-trip and
availability cost, not raw crypto speed. The Rego policy is published in full
(`policies/capability.rego`).

---

## Re-running (macOS, the official path)

Prereqs: Rust (via the pinned `rust-toolchain.toml`), Python 3.11, `just`,
`curl`. The `capability-grant@1` artifact is imported from the sibling x402
checkout — point `PCT_X402_SRC` at it (default `../presidio-hardened-x402/tools/src`).

```bash
pip install -r python/requirements.txt
export PCT_X402_SRC=/path/to/presidio-hardened-x402/tools/src
export PCT_CPU="Apple M-series"        # recorded verbatim in every CSV row
# PCT_SANDBOX defaults to false on the Mac -> rows stamped official.

just gen           # generate + commit fixtures (defaults to 10^5 exercises/config)
just verify        # 3-way correctness gate (fail-closed); required before timing
just bench-e1      # gate, then Biscuit + grant@1 + OPA(local/5ms/20ms)
just plots         # PNGs into plots/
```

`scripts/opa_e1.sh` auto-selects the **darwin-arm64** OPA binary on the Mac and
the linux-arm64 static binary in the sandbox. For the delay configs it uses the
in-repo `python/delay_proxy.py`; substitute **toxiproxy** on the Mac by pointing
`opa_bench.py`'s `OPA_PORT` at the toxiproxy listener (the CSV `config` column
records which delay was in force either way).

**Sandbox reduced-count invocation** (what produced the committed indicative CSVs):

```bash
PCT_SANDBOX=true PCT_N_ALLOW=3000 PCT_OPA_LOCAL=500 PCT_OPA_DELAY=120 just bench-e1
```

---

## First indicative results (SANDBOX — aarch64, do not cite)

Exercise-time verification latency, **p50, fanout=1**, in microseconds:

| system / config | d1 | d2 | d4 | d6 | d8 | d10 |
|---|---|---|---|---|---|---|
| biscuit            | 43 | 76 | 141 | 203 | 268 | 332 |
| grant@1 (Python)   | 65 | 127 | 258 | 373 | 506 | 632 |
| opa / local        | 136 | 153 | 174 | 220 | 253 | 273 |
| opa / +5ms         | 6230 | 6688 | 6454 | 6961 | 6353 | 6401 |
| opa / +20ms        | 24421 | 25002 | 24441 | 24814 | 25039 | 25341 |

Token / message bytes vs depth: biscuit 387→3285 B, grant@1 chain 665→7343 B,
OPA input doc 378→2529 B — all linear in depth.

**Shape (honest read):** both capability systems are in the **µs** range and grow
mildly with depth (Biscuit ≈ half of the Python grant@1). Local OPA is
**sub-millisecond and roughly flat in depth**, and at depth 10 it actually *edges
past* Biscuit (273 vs 332 µs) — reported openly: the argument is round-trips and
availability, not raw crypto speed. The **injected delay dominates everything**:
+5 ms → ~6.4 ms, +20 ms → ~25 ms per decision, ~20–75× the local capability path.
That is the performance dividend the paper claims, measured.

---

## E3 — accumulator revocation (cut-first: SKELETON ONLY)

Per the plan, E3 is optional and cut first. `crates/e3-accumulator` records the
**crate choice** — [`vb_accumulator`](https://crates.io/crates/vb_accumulator)
(Dock Network's pairing-based universal accumulator) — with rationale, and is
**locked in `Cargo.lock` but not wired** (excluded from `default-members` so the
E1 benches never compile the arkworks tree). It provides membership **and
non-membership** witnesses plus batch witness-update and epoch-root update —
exactly E3's surface. The crates.io crate literally named `accumulator` is an
unrelated key-value store and is the wrong artifact. Wiring + measurement is a
Mac-mini follow-up; no number it could produce enters the paper until measured.

## What remains for the Mac-mini run

* Re-run `just bench-e1` at full 10⁵ counts with `PCT_SANDBOX=false`,
  `PCT_CPU` set, and toxiproxy for the delay configs → the official CSVs/plots.
* Optionally wire E3 against `vb_accumulator` and add measured Table-1 rows.
* Commit the official `results/*.csv` + `plots/*.png` alongside these indicative
  ones (clearly separated by the `sandbox` column).
