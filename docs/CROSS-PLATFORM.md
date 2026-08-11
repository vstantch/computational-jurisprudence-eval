# Cross-platform replication of E1 and E3 (x86-64 Linux, container)

Produced for the second revision of *Computational Jurisprudence* (Future Internet,
futureinternet-4477444), in response to a reviewer asking whether the latency results hold outside
the single Apple M4 Mac mini that produced every number in the submitted version.

## What was run

The harness at this commit, unmodified, against the committed seeded fixtures.

**Held identical to the official Mac-mini run:**

* the committed workload fixtures (same generator, same seed, same corpus). That they are
  byte-identical is confirmed independently by the `token_bytes` column, which is a property of the
  fixture rather than of the machine and agrees exactly across the two runs;
* OPA **1.18.2**, the version the official run used;
* `toxiproxy` latency toxics for the `+5ms` and `+20ms` configurations, not the in-repo asyncio
  fallback;
* exercise counts: 10^5 for the three local configurations, 10^4 for the two delay configurations;
* warm-up, keep-alive, and token pre-materialization (harness defaults, untouched).

**Differs, and recorded in the data:**

* platform: Intel Xeon @ 2.10 GHz, 4 vCPU, Linux/x86-64, in a container under a hypervisor;
* fanout 1 only, the configuration the article reports (`workloads-f1/` is a symlink view of the
  committed fixtures; nothing under `workloads/` is modified);
* the correctness gate is **two-way** rather than three-way. `capability-grant@1` is imported from
  the `presidio-hardened-x402` checkout via `PCT_X402_SRC`, which is not public, so it cannot be
  exercised off the author's machine. `python/verify_gate_2way.py` is the upstream three-way gate
  with that term removed and nothing else changed. It passed on all 323 gate exercises before any
  timing.

## On the `sandbox` flag

These rows are stamped `sandbox=false`, and the reasoning should be explicit because the README uses
that flag to mean something specific.

In this repository `sandbox=true` marks *reduced exercise counts and the in-repo asyncio delay
proxy*, i.e. indicative shape-numbers that must not be cited. This run used the full counts and real
toxiproxy, so it is not a sandbox run in that sense. It is also not the official Mac-mini run. The
`host`, `os`, `arch`, and `cpu` columns distinguish the two unambiguously (`cj-cloud-x86`, `linux`,
`x86_64`, `Intel Xeon @ 2.10GHz (4 vCPU)` versus `pier39.local`, `macos`/`darwin`, `aarch64`/`arm64`,
`Apple M4 (4P+6E)`), and the paper's Table 9 labels every row by platform.

The integrity rule is unchanged and was not bent: every value here is measured, nothing is estimated
or extrapolated, and no existing result file was touched.

## Results

`results/cloud-x86/`:

| file | contents |
|---|---|
| `e1-biscuit_cj-cloud-x86_*.csv` | Biscuit, 6 depths, fanout 1, 10^5 exercises each |
| `e1-opa_vm_*.csv` | OPA local / +5ms / +20ms, 6 depths each |
| `e3-accum_cj-cloud-x86_*.csv` | accumulator: non-membership gen/verify, and epoch-root / Ω-publish / witness-update at B ∈ {10^2, 10^3, 10^4} |
| `biscuit-verdicts.json`, `opa-verdicts.json` | gate evidence |

Note the OPA CSV is named from `hostname` (`vm`) rather than `PCT_HOST`, because `scripts/opa_e1.sh`
builds its filename from `$(hostname)`. The **rows** carry `host=cj-cloud-x86` correctly; only the
filename differs. Left as-is rather than renamed, so the file is exactly what the harness emitted.

### Headline: p50 microseconds, fanout 1

| system / config | d1 | d2 | d4 | d6 | d8 | d10 |
|---|---|---|---|---|---|---|
| biscuit | 81 | 145 | 271 | 384 | 508 | 632 |
| opa / local | 592 | 652 | 703 | 816 | 884 | 961 |
| opa / +5ms | 6386 | 6419 | 6495 | 6566 | 6611 | 6710 |
| opa / +20ms | 21,896 | 21,940 | 22,026 | 22,073 | 22,082 | 22,193 |

Against the Mac-mini reference: Biscuit is 1.86–2.01× slower, local OPA 4.17–5.30× slower, and both
delay configurations are *marginally faster* here (0.92–0.99×) because the injected delay dominates.

Two consequences the paper reports:

1. **The remote-PDP gap is platform-independent**, since its dominant term is the network rather
   than the CPU. This is the comparison the architecture rests on.
2. **The co-located crossover does not replicate.** On the Mac mini local OPA becomes the faster of
   the two from depth 6 onward; here it is slower at every depth, because an out-of-process decision
   point pays serialization, a loopback round trip, and a scheduler wakeup per decision, and all
   three degrade more than in-process cryptography on fewer, shared cores.

### E3, p50 milliseconds

| operation | B | Mac mini | x86-64 | ratio |
|---|---|---|---|---|
| non-membership verify | — | 1.03 | 2.48 | 2.42 |
| witness update (holder) | 10^4 | 82.27 | 177.46 | 2.16 |
| Ω publication (manager) | 10^4 | 2564.60 | 10099.49 | 3.94 |

The verifier's check stays flat in revocation volume on both machines, which is the property the
paper's Pillar III depends on; only the constant moves.

## Re-running

```bash
bash scripts/run-cloud-x86.sh .
```

The script creates the fanout-1 symlink view, fetches `toxiproxy-server` if absent (`opa_e1.sh`
fetches OPA itself), builds both Rust binaries, runs the two-way gate, and then E1 and E3. Expect
roughly 50 minutes on a 4-vCPU box, dominated by the `+20ms` sweep.

## What this does not establish

Neither machine is a distributed deployment, so both delay results remain injected-delay laboratory
numbers. Neither ran under concurrent load; both boxes were effectively idle apart from the
benchmark, which is the condition under which a co-located decision point looks best. And no
server-class bare-metal machine was measured on either architecture.
