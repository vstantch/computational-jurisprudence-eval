# ERRATA-DRAFT — for the owner's decision

Branch `harness-hygiene`, cut from tag `v2-fi-revision-2026-08-11` (06db5fc). Nothing
here has been applied to the paper or to `results/`, and no claim's status changes.
Each item gives what is written, what the evidence shows, and a proposed wording
for you to accept, change or reject. "Paper" means the published text,
`R5-correction/source/futureinternet-18-00437-corrected.tex` in the paper repository.

Every number in this file is a measurement on the machine named with it, or a
value read from a committed file; none is estimated.

---

## 1. Data Availability: tag `v0-official-run-2026-07-11` does not hold the files behind the OPA rows or Table E3

**Paper (Data Availability):** "Tag `v0-official-run-2026-07-11` pins the single
full-scale official run reported in Tables E1–E3."

**Evidence.** The tag points at 16bc75d. Its `results/` holds one official OPA
file, `e1-opa_pier39.local_20260710T233343Z.csv`, which reproduces none of the
paper's three OPA rows (0/6 cells each, p50 rounded to µs). The file that
reproduces all three OPA rows exactly, `e1-opa_pier39.local_20260711T135215Z.csv`,
was first committed in 2b424a2, and the E3 file in 3105560; neither commit is in
`v0`. Both are in `v1-fi-revision-2026-08-03` and `v2-fi-revision-2026-08-11`.
The Biscuit and capability-grant@1 rows do reproduce from files in `v0`.

**Proposed wording:** "Tag `v0-official-run-2026-07-11` pins the first official
run; the OPA rows of Table E1 and Table E3 come from the re-run committed after it
(commits 2b424a2 and 3105560), first pinned by tag `v1-fi-revision-2026-08-03`.
`results/MANIFEST.toml` names the file behind each table."

## 2. Which files the E1 table uses (no change to the paper; recorded for provenance)

Each row of the paper's E1 table reproduces exactly (p50, rounded to µs) from one
committed file and from no other:

| row | file |
|---|---|
| Biscuit | `results/e1-biscuit_pier39.local_20260710T230124Z.csv` |
| Python cap-grant | `results/e1-grant_pier39.local_20260710T230124Z.csv` |
| OPA localhost, +5 ms, +20 ms | `results/e1-opa_pier39.local_20260711T135215Z.csv` |

The earlier OPA sweep `results/e1-opa_pier39.local_20260710T233343Z.csv` matches no
row and is marked `superseded` in `results/MANIFEST.toml`. The old loaders took
"the last file by name" in `results/`, which happened to be the right OPA file;
they now resolve through the manifest and fail on ambiguity. The paper repository's
own copy (`pct-paper/data/e1/`) holds the same three files, with the 2026-07-10
OPA file under `_superseded/`.

## 3. Delay mechanism of the official +5/+20 ms rows

**Paper:** toxiproxy (Measurement conditions, Disclosed biases, Provenance).
**README at the tag:** "For the delay configs it uses the in-repo
`python/delay_proxy.py`; substitute toxiproxy … by pointing `OPA_PORT` at the
toxiproxy listener." **OFFICIAL-RUNS.md at the tag:** `./scripts/opa_e1.sh
bench-delayed toxiproxy`, a mode that has never existed.

**Evidence.**
* Commit 2b424a2 (2026-07-12 00:25 +02:00) adds the toxiproxy mode to
  `scripts/opa_e1.sh` and commits `e1-opa_pier39.local_20260711T135215Z.csv`, with
  the message "Commit the toxiproxy OPA CSV (sandbox=false) beside the earlier
  asyncio run". The run (2026-07-11 13:52 UTC) predates the commit, so the exact
  code that ran was not committed at the time.
* Tail shape. `delay_proxy.py` sleeps once per relayed chunk, in turn, so a request
  that arrives in two chunks pays the delay twice. The 2026-07-10 file shows that
  signature (fanout 1, depths 1–10): at +20 ms, p50 23.0–23.8 ms but p95
  44.2–45.9 ms and p99 44.9–46.6 ms (p95/p50 1.89–1.94); at +5 ms, p95/p50
  1.15–1.84. The 2026-07-11 file has p95/p50 1.03–1.05 at +20 ms and 1.09–1.13
  at +5 ms, the same tight shape as the five 2026-08-03 repetitions
  (`repeat_e1.sh` defaults to toxiproxy) and the 2026-08-11 x86 run
  (`run-cloud-x86.sh` sets toxiproxy).
* Limit of the second point: the sandbox run, which the README says used the
  asyncio proxy, has no doubled tail either (+20 ms: p50 24.4, p95 25.9 ms), so a
  tight tail alone does not prove toxiproxy.
* The CSVs have no column for the method.

**Conclusion.** The +5/+20 ms rows of the paper were produced with toxiproxy
according to the author's contemporaneous commit message. The data are consistent
with that and show the asyncio signature only in the superseded file. It is not
provable from the committed data alone. The paper's statement stands; README and
OFFICIAL-RUNS.md now describe the code (`PCT_DELAY_METHOD=toxiproxy`; asyncio is
the default fallback).

## 4. OPA decision logging: a bias against OPA (Measurement conditions / Disclosed biases)

**Paper:** "There are two disclosed biases" (Rego models no signature checks, in
OPA's favour; injected delay is a lower bound). **Harness:** `opa_e1.sh` starts
OPA at its default log level, `info`, at which OPA writes two log lines per
decision to `/tmp/opa-server.log`: about 400 B per decision, 241 MB for one
fanout-1 localhost sweep (6 × 10^5 decisions). That write is on the request path
of every timed decision in every committed OPA run.

**Measurement.** One machine (the build sandbox: Linux x86-64, Intel Xeon
@ 2.10 GHz, 4 vCPU, virtualised; not the Mac mini), OPA 1.18.2 native, CPython
3.11.15, harness `opa_bench.py` unchanged, fanout 1, harness defaults (10^5
decisions per depth, 50 warm-ups), log file on local disk as in `opa_e1.sh`.
Six sweeps in the order info, error, error, info, info, error (`--log-level
error` writes about 300 B per sweep). p50 in µs:

| run | level | d1 | d2 | d4 | d6 | d8 | d10 |
|---|---|---|---|---|---|---|---|
| 1 | info  | 429.5 | 482.5 | 565.2 | 640.7 | 765.6 | 829.4 |
| 2 | error | 382.5 | 436.4 | 491.7 | 556.2 | 669.0 | 770.0 |
| 3 | error | 392.0 | 446.0 | 506.7 | 562.7 | 649.0 | 758.8 |
| 4 | info  | 436.5 | 497.7 | 563.0 | 662.6 | 788.4 | 827.1 |
| 5 | info  | 420.6 | 491.1 | 564.3 | 645.7 | 751.7 | 837.8 |
| 6 | error | 400.4 | 423.6 | 479.1 | 571.9 | 679.4 | 824.4 |

p50(error) / p50(info), paired with the adjacent run (1-2, 4-3, 5-6), against the
run-to-run spread within each level (max/min − 1 of the three runs):

| depth | paired ratios | mean | range | info spread | error spread |
|---|---|---|---|---|---|
| 1  | 0.891 0.898 0.952 | 0.914 | 0.891–0.952 | 3.8 % | 4.7 % |
| 2  | 0.905 0.896 0.863 | 0.888 | 0.863–0.905 | 3.2 % | 5.3 % |
| 4  | 0.870 0.900 0.849 | 0.873 | 0.849–0.900 | 0.4 % | 5.8 % |
| 6  | 0.868 0.849 0.886 | 0.868 | 0.849–0.886 | 3.4 % | 2.8 % |
| 8  | 0.874 0.823 0.904 | 0.867 | 0.823–0.904 | 4.9 % | 4.7 % |
| 10 | 0.928 0.917 0.984 | 0.943 | 0.917–0.984 | 1.3 % | 8.6 % |

All 18 paired ratios are below 1. The effect (5.7–13.3 % of the info-level p50,
about 37–86 µs) exceeds the run-to-run spread at depths 1–8; at depth 10 it does
not (5.7 % against an 8.6 % spread among the error-level runs). On this machine,
the default log level therefore made local OPA slower: a bias **against** OPA,
opposite in direction to the disclosed Rego bias. The +5/+20 ms rows carry the
same absolute cost, which is under 1.5 % of their p50. The size on the Mac mini
(APFS, a different CPU) was not measured and may differ; n = 3 per level.

**Consequence for a stated result.** The paper reports that co-located OPA is the
faster of the two from depth 6 onward on the reference machine. A bias against
OPA can only move that crossover to the same or a shallower depth. On the Mac,
at depth 4, local OPA (152 µs) is 12.6 % slower than Biscuit (135 µs), so a
logging cost of about 11 % or more there would move the crossover from depth 6
to depth 4; at depth 2 (127 vs 74 µs) it would take 42 %. The cost on the Mac is
unmeasured, so whether the crossover depth holds is open; which way the bias
points is not.

**Proposed wording (Disclosed biases, as a third item):** "OPA ran at its default
log level, which writes a log record per decision. On a separate x86-64 machine,
running OPA with `--log-level error` lowered its local p50 by 6–13 % (depths 1–8;
three runs per level). This cost is included in the OPA rows and biases the
comparison against OPA; with it removed, the crossover reported above could
occur at a shallower depth." Before choosing, the cheapest check is to rerun the
localhost sweep on the Mac mini with `PCT_OPA_LOG_LEVEL=error` (about 10 min).
The harness default is unchanged.

## 5. OPA makes one outbound call at startup ("over localhost")

**Paper (E1):** OPA as "a centralized PDP evaluating an equivalent Rego policy over
localhost". **README:** OPA "over localhost HTTP". Neither is wrong about the
decision path, but `opa_e1.sh` at the tag started OPA without
`--skip-version-check`/`--disable-telemetry`.

**Capture.** OPA 1.18.2 (linux-amd64 static, SHA-256 9903e512…), started exactly
as `opa_e1.sh` did at the tag, under `strace -f -e trace=connect,sendto`, proxy
variables removed. Over 30 min: startup, 2,000 decisions in 68 s, then 29 min
idle. The only non-loopback system calls were, within 30 ms of startup: two DNS
queries (UDP 53 to the configured resolver) and one TCP connect to port 443 of
140.82.112.5, a GitHub address (api.github.com, OPA's version check). There
was no outbound call during or after the 2,000 decisions, and none periodically.
With `--skip-version-check`, and separately with `--disable-telemetry`, the same
capture (200 decisions, 20 s idle) recorded no `connect` or `sendto` at all.

**Proposed sentence:** "OPA was started without `--skip-version-check`, so at
startup it made one outbound HTTPS request to check for a newer version; it made
no network call per decision, and the timings are unaffected." The harness now
passes `--skip-version-check`.

## 6. Cross-platform: "the same harness at the same commit"

**Paper (§ cross-platform, and Table crossplatform's caption):** "The replication
uses the same harness at the same commit …"; "Both rows of each pair come from
the same harness at the same commit …".

**Evidence.** The reference E1 files were produced on 2026-07-10/11 (committed in
16bc75d and 2b424a2); the x86 run used b42ae1b (tag `v1-fi-revision-2026-08-03`).
Between 2b424a2 and b42ae1b the E1 code path differs only by `PCT_MAX_PER_CONFIG`,
an exercise cap added to the Biscuit and grant@1 benches that is unset (no cap)
in both runs; `scripts/opa_e1.sh`, `python/opa_bench.py`, `python/common.py` and
the policy are identical. So the runs used the same code path, not the same commit.

**Proposed wording:** "the same harness code path (commits 2b424a2 and b42ae1b,
which differ in E1 only by an exercise cap that neither run used)". The caption
of the generated table keeps its current text until you decide; the generator
reproduces it byte-for-byte.

## 7. Data Availability: "the table-generation scripts"

**Paper:** the harness repository comprises "… the committed result CSVs, and the
table-generation scripts".

**Evidence.** The generator of Tables E1–E3 (`pct-paper/mkresults.py`) lives in the
paper repository, not in the harness. The harness holds the generators of the
variability and cross-platform tables. At tags `v1` and `v2`,
`python/mkvariability_table.py` read hard-coded owner paths (`~/projects/pct-eval`
and a `/private/tmp/claude-501/…/scratchpad/e2-variability` directory), so it did
not run from a clone. Pointed at the committed `results/variability*`, it
reproduces the published variability table byte-for-byte, which confirms that the
committed E2 repetition files are the ones used. On this branch it reads the
manifest and runs from a clone.

**Proposed wording:** "… the committed result CSVs, and the scripts that generate
the variability and cross-platform tables; Tables E1–E3 are generated from the
same committed CSVs by the article's build (paper repository)." Or move
`mkresults.py` into the harness; your call.

## 8. README: "every row is stamped sandbox=true"; plots

**README (Integrity rule):** "The CSVs and PNGs currently in `results/` and
`plots/` were produced in a Linux aarch64 sandbox … every row is stamped
`sandbox=true`."

**Evidence.** Since 16bc75d, `results/` also holds the official Apple M4 files
(`sandbox=false`) and, since 8631061, the x86 files. The committed `plots/*.png`
were generated from all of `results/` at 16bc75d, so each series mixes sandbox and
official points (e.g. grant1 at depth 1 is plotted at both 65 µs and 167 µs),
under a caption that reads "SANDBOX (indicative)". The paper includes none of
these figures.

**Proposed wording:** "The PNGs in `plots/` mix the sandbox and official rows of
`results/` and are not results; `results/MANIFEST.toml` gives each file's role."
Regenerating the plots from the official files is a separate decision; nothing was
regenerated.

## 9. `runtime` column of Rust rows

The Biscuit and E3 benches wrote the literal string `rustc-1.96.1` into `runtime`
rather than the compiler's version. The toolchain was pinned to 1.96.1
(`rust-toolchain.toml`), so the value is plausible, but it is a label, not a
measurement. The paper's "Biscuit under rustc 1.96.1" rests on the toolchain pin.
On this branch `build.rs` records the compiler actually used; committed CSVs are
unchanged and keep the literal.

## 10. Host names in committed data (decision needed; nothing renamed)

`pier39.local` (the owner's machine) appears in the `host` column of 20 committed
files, in the `# host,` header of the five E2 repetition files, and in 5 file
names. `claude` (the sandbox) appears in 3 files and 3 names, `cj-cloud-x86` in
3 files and 2 names, `vm` in 1 name, and `unknown` in the 5 E3 repetition files.
No user name or home-directory path appears under `results/`.

---
