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

**Cross-platform rows are a third category.** `results/cloud-x86/` holds an E1 and
E3 replication on **x86-64 Linux in a container**, added for the second *Future
Internet* revision. It ran the full counts with real toxiproxy, so its rows are
stamped `sandbox=false` — but they are **not** the official Mac-mini numbers
either. Tell the two apart by `host`/`os`/`arch`/`cpu`, never by `sandbox` alone.
Its correctness gate is **two-way** (Biscuit and OPA; `capability-grant@1` is
imported from the non-public x402 checkout and cannot be exercised off the owner's
machine) — see `python/verify_gate_2way.py`. What was run, what was held
identical, the results, and the caveats are in
[`docs/CROSS-PLATFORM.md`](docs/CROSS-PLATFORM.md).

---

## Repository layout

```
pct-eval/
├── Cargo.toml / Cargo.lock        # Rust workspace; lockfile committed (pinned deps)
├── rust-toolchain.toml            # pins the toolchain (channel 1.96.1)
├── justfile                       # gen / verify(-public|-fixtures) / bench-e1(-public) / plots
├── crates/
│   ├── workload-gen/              # THE canonical seeded generator (one source of truth)
│   ├── e1-biscuit/                # Biscuit bench (bin + criterion bench) + verdicts
│   └── e3-accumulator/            # E3 SKELETON ONLY (cut-first); crate choice + rationale
├── python/
│   ├── common.py                  # shared CSV schema + platform stamp + gate subset
│   ├── grant_bench.py             # capability-grant@1 bench + verdicts
│   ├── opa_bench.py               # OPA decision-latency client + verdicts
│   ├── delay_proxy.py             # asyncio TCP delay proxy (toxiproxy fallback)
│   ├── verify_gate.py             # 3-way correctness gate (fail-closed; private x402)
│   ├── verify_gate_2way.py        # 2-way gate, Biscuit and OPA (public)
│   ├── check_fixtures.py          # fixtures vs workloads/SHA256SUMS
│   ├── results_manifest.py        # results/MANIFEST.toml loader + check
│   ├── mkcrossplatform.py         # cross-platform E1 table (LaTeX)
│   ├── mkvariability_table.py     # variability table (LaTeX)
│   ├── variability.py             # per-configuration variability CSV
│   ├── plot.py                    # one PNG per metric family
│   ├── requirements.in            # direct Python deps
│   └── requirements.txt           # hashed, fully transitive lock (uv pip compile)
├── policies/capability.rego       # published Rego policy (same caveat semantics)
├── scripts/opa_e1.sh              # fetch pinned OPA/toxiproxy, serve policy, run local/5ms/20ms
├── workloads/                     # generated seeded fixtures (committed) + SHA256SUMS
├── results/                       # CSV per run (PCT_HOST+timestamp), verdict JSONs, MANIFEST.toml
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

Prereqs: Rust (via the pinned `rust-toolchain.toml`), Python 3.11 or newer,
`just`, `curl`. The official runs used CPython 3.11.15; the 2026-07-10 sandbox
rows (`sandbox=true`) record CPython 3.10.12. The `capability-grant@1` artifact
is imported from the sibling x402 checkout — point `PCT_X402_SRC` at it
(default `../presidio-hardened-x402/tools/src`).

```bash
pip install -r python/requirements.txt   # hashed, fully transitive lock
export PCT_X402_SRC=/path/to/presidio-hardened-x402/tools/src
export PCT_CPU="Apple M-series"        # recorded verbatim in every CSV row
export PCT_HOST=mac-mini               # row/file label; default "anon", never the hostname
export PCT_DELAY_METHOD=toxiproxy      # the official delay method (default: asyncio fallback)
# PCT_SANDBOX defaults to false under just -> rows stamped official.

just verify        # 3-way correctness gate (fail-closed); required before timing
just bench-e1      # gate, then Biscuit + grant@1 + OPA(local/5ms/20ms)
just plots         # PNGs of the reference platform's official files into plots/
```

`just verify` checks the committed fixtures against `workloads/SHA256SUMS` and
never regenerates them; `just gen` regenerates them explicitly (it overwrites
`workloads/`, and depends on `PCT_N_ALLOW`), after which `just verify-fixtures`
shows whether the output is byte-identical.

`scripts/opa_e1.sh` downloads **OPA 1.18.2** for the platform (darwin-arm64,
darwin-amd64, linux-arm64 or linux-amd64) into `bin/` by exact version and
checks its SHA-256 on every run; a mismatch aborts. OPA runs with
`--skip-version-check`, so it makes no outbound call at startup, and with its
default log level (`info`) unless `PCT_OPA_LOG_LEVEL` is set. The script waits
at most 15 s for port 8181 to be free and at most 15 s for OPA to become
healthy, and fails otherwise.

For the `+5ms`/`+20ms` configurations, `PCT_DELAY_METHOD` selects the method.
`toxiproxy` puts an upstream latency toxic in front of OPA: the script fetches
**toxiproxy 2.12.0** the same way (SHA-256 checked), starts it on 127.0.0.1
unless one already answers on :8474, and requires that it reports 2.12.0.
Unset or any other value uses the in-repo `python/delay_proxy.py` (asyncio,
one-way delay on the request path, applied to each relayed chunk in turn). Per commit
2b424a2, the official 2026-07-11 OPA run used toxiproxy. The CSV `config`
column records the target delay, not the method.

**Sandbox reduced-count invocation** (what produced the committed indicative
CSVs, when `verify` still ran `gen`; today `PCT_N_ALLOW` affects only `just gen`,
and `PCT_MAX_PER_CONFIG` caps the Biscuit and grant@1 streams):

```bash
PCT_SANDBOX=true PCT_N_ALLOW=3000 PCT_OPA_LOCAL=500 PCT_OPA_DELAY=120 just bench-e1
```

## Public verification (no private checkout)

`capability-grant@1` is imported from the non-public x402 checkout, so the
three-way gate (`just verify`) runs only on the owner's machine. Anyone can run
the two-way gate and the public part of the sweep:

```bash
just verify-public     # fixtures hash check, then biscuit == OPA == expected
just bench-e1-public   # verify-public, then Biscuit and OPA (local/5ms/20ms)
```

`verify-public` writes its verdict files to `target/gate/`, never over the
committed `results/*-verdicts.json`. CI (`.github/workflows/verify.yml`) runs it
and a short sweep on x86-64 and arm64 Linux for every push.

## Which results back which table

`results/MANIFEST.toml` lists every committed result file with its SHA-256,
platform, system and role (`official`, `superseded`, `sandbox`, `repetition`,
`gate-evidence`). The table generators read inputs through it and stop on any
ambiguity (a platform with zero or several official files for a system), a
changed file, or a file under `results/` the manifest does not list.
`python3 python/results_manifest.py check` verifies the whole manifest.

| generator | output | inputs (manifest) |
|---|---|---|
| `python/mkcrossplatform.py apple-m4 x86-cloud tables/crossplatform.tex` | cross-platform E1 table | official Biscuit and OPA files of both platforms |
| `python/mkvariability_table.py [--out tables/variability.tex]` | run-to-run variability table | the five `repetition` files per system on apple-m4 |
| `python/variability.py results/variability [out.csv]` | per-configuration variability CSV (default `tables/e1-variability.csv`) | `results/variability/rep*-*.csv` |
| `python/plot.py --platform apple-m4 [plots]` | PNGs | official E1 files of one platform |

The paper's main E1 table is generated in the paper repository from its own
copy of the three official apple-m4 files; the manifest names the same files.
`mkcrossplatform.py` takes its row labels and platform descriptions from the
manifest and the OPA version from the CSVs' `runtime` column; it also accepts
`--compare-dir DIR --compare-delay-method M` for a sweep that is not in the
manifest.

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

## Run-to-run variability sweep (added for the Future Internet revision, 2026-08-03)

Reviewers of the *Future Internet* submission asked whether the reported percentiles came from a
single execution per configuration. They did. Each experiment was therefore re-executed as **five
independent runs**, each in a fresh process, and for E1 with a fresh OPA server and freshly created
toxiproxy proxies, so that no thermal, page-cache, allocator, or connection state carries across
repetitions.

```bash
# E1: 5 repetitions, 10^4 exercises per config, 2x10^3 for the injected-delay configs.
# Writes results/variability/rep{1..5}-{biscuit,grant,opa}.csv
PCT_CPU="Apple M4 (4P+6E)" PCT_SANDBOX=false PCT_DELAY_METHOD=toxiproxy \
  ./scripts/repeat_e1.sh 5 10000 2000

# E3: 5 repetitions at the official iteration counts.
for i in 1 2 3 4 5; do ./target/release/e3-bench results/variability-e3/rep${i}-e3.csv; done

# E2: 5 repetitions of the full 2,000-triple corpus replay (run from the x402 tools tree).
# Writes results/variability-e2/rep{1..5}-e2-replay.csv

# Summaries (mean / SD / CV / Student-t 95% CI across repetitions):
python3 python/variability.py results/variability          # E1, all 30 configurations
python3 python/mkvariability_table.py                      # the paper's Table 8
```

`PCT_MAX_PER_CONFIG` (new) caps the timed exercise stream in the Biscuit and grant@1 benches so that
five full sweeps stay affordable; unset or `0` means "every allow exercise in the fixture", which is
what the official run uses. The headline tables in the paper remain the single full-scale official
run; the repetitions are an uncertainty statement about it, not a replacement for it.

**What the sweep showed.** Median latencies are stable: across all 30 E1 configurations the p50
coefficient of variation has median 1.9 % and never exceeds 5.0 %, and the repetition means agree
with the official single run to within 6.0 % everywhere. Tails are not: the p99 coefficient of
variation has median 4.6 % and a worst case of 49 % (Biscuit, depth 10), because the tail of a
microsecond-scale in-process operation is dominated by scheduling and allocator behaviour that
differs between executions. No claim in the paper rests on an E1 tail figure.
