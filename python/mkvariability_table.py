#!/usr/bin/env python3
"""Build tables/variability.tex from the repeated-execution sweeps.

Reviewers asked whether the reported percentiles came from a single execution
per configuration and for a quantification of run-to-run uncertainty. Five
independent executions of each experiment were run (fresh process each time,
fresh OPA server and toxiproxy proxies for E1). This script reduces them to
mean / SD / CV / 95 % CI per quantity and emits the LaTeX table.

Nothing is re-timed here; only measured CSV rows are summarized. The
repetition files are resolved through results/MANIFEST.toml (role
"repetition", platform apple-m4), which also checks their SHA-256.

Usage: python3 python/mkvariability_table.py [--manifest M] [--out tables/variability.tex]
"""

from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import results_manifest  # noqa: E402

PLATFORM = "apple-m4"
OUT = Path(__file__).resolve().parent.parent / "tables" / "variability.tex"


def rep_files(m: results_manifest.Manifest, systems: tuple[str, ...]) -> list[str]:
    """Verified repetition files for these systems, in path order."""
    entries = [e for s in systems for e in m.select(PLATFORM, s, "repetition")]
    reps = sorted(e["rep"] for e in entries if e["system"] == systems[0])
    if reps != [1, 2, 3, 4, 5]:
        raise SystemExit(f"expected repetitions 1..5 for {systems[0]}, found {reps}")
    return [m.verified(e) for e in sorted(entries, key=lambda e: e["path"])]

_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
        7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228}


def stats(xs: list[float]) -> tuple[int, float, float, float, float]:
    """(n, mean, sd, cv_pct, ci95_halfwidth)."""
    n = len(xs)
    m = statistics.mean(xs)
    sd = statistics.stdev(xs) if n > 1 else 0.0
    cv = 100.0 * sd / m if m else 0.0
    half = _T95.get(n - 1, 1.96) * sd / (n ** 0.5) if n > 1 else 0.0
    return n, m, sd, cv, half


def fmt(xs: list[float], unit_scale: float = 1.0, prec: int = 2) -> str:
    n, m, sd, cv, half = stats([x * unit_scale for x in xs])
    return (f"{n} & {m:.{prec}f} & {sd:.{prec}f} & {cv:.1f} & "
            f"$\\pm${half:.{prec}f}")


# ---------------------------------------------------------------- E1
def load_e1(paths: list[str], fanout: str = "1") -> dict:
    runs: dict[tuple[str, str, int], list[float]] = {}
    for path in paths:
        with open(path) as f:
            for row in csv.DictReader(f):
                if row.get("fanout") != fanout:
                    continue
                key = (row["system"], row["config"], int(row["depth"]))
                runs.setdefault(key, []).append(int(row["p50_ns"]) / 1000.0)
    return runs


E1_ROWS = [
    ("biscuit", "na", "Biscuit (Rust), p50"),
    ("grant1", "na", "capability-grant@1 (Python), p50"),
    ("opa", "local", "OPA / local, p50"),
    ("opa", "5ms", "OPA / $+5$\\,ms, p50"),
    ("opa", "20ms", "OPA / $+20$\\,ms, p50"),
]


def e1_block(runs: dict) -> list[str]:
    out = []
    for system, config, label in E1_ROWS:
        for depth in (1, 10):
            xs = runs.get((system, config, depth))
            if not xs:
                continue
            out.append(f"{label}, $d{{=}}{depth}$ & " + fmt(xs) + r" \\")
    return out


# ---------------------------------------------------------------- E2
def load_e2(paths: list[str]) -> dict:
    runs: dict[tuple[int, str], list[float]] = {}
    for path in paths:
        with open(path) as f:
            rows = [r for r in f if not r.startswith("#")]
        for row in csv.DictReader(rows):
            key = (int(row["depth"]), row["stage"])
            runs.setdefault(key, []).append(float(row["p99_ms"]))
    return runs


def e2_block(runs: dict) -> list[str]:
    out = []
    for depth in (1, 2, 4, 6):
        xs = runs.get((depth, "added_total"))
        if xs:
            out.append(f"Added latency p99, depth {depth} & " + fmt(xs, prec=3) + r" \\")
    xs = runs.get((1, "redaction"))
    if xs:
        out.append(r"Redaction stage p99, depth 1 & " + fmt(xs, prec=3) + r" \\")
    return out


# ---------------------------------------------------------------- E3
E3_ROWS = [
    ("non_membership_verify", "0", "Non-membership verify (verifier)"),
    ("witness_update", "10000", "Witness update, $B{=}10^4$ (holder)"),
    ("omega_publish", "10000", "$\\Omega$ publication, $B{=}10^4$ (manager)"),
]


def load_e3(paths: list[str]) -> dict:
    runs: dict[tuple[str, str], list[float]] = {}
    for path in paths:
        with open(path) as f:
            for row in csv.DictReader(f):
                key = (row["operation"], row["batch_size"])
                runs.setdefault(key, []).append(int(row["p50_ns"]) / 1e6)
    return runs


def e3_block(runs: dict) -> list[str]:
    out = []
    for op, batch, label in E3_ROWS:
        xs = runs.get((op, batch))
        if xs:
            out.append(f"{label} & " + fmt(xs, prec=2) + r" \\")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the variability table (LaTeX).")
    ap.add_argument("--manifest", default=results_manifest.DEFAULT)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    m = results_manifest.Manifest(a.manifest)
    e1 = load_e1(rep_files(m, ("biscuit", "grant1", "opa")))
    e2 = load_e2(rep_files(m, ("e2",)))
    e3 = load_e3(rep_files(m, ("e3",)))
    b1, b2, b3 = e1_block(e1), e2_block(e2), e3_block(e3)
    if not (b1 and b2 and b3):
        print(f"WARNING: incomplete blocks (E1 {len(b1)}, E2 {len(b2)}, E3 {len(b3)})")

    lines = [
        r"\begin{table}[t]",
        r"\centering",
        r"\caption{\textbf{Measured (this work).} Run-to-run variability across "
        r"five independent executions of each experiment, each in a fresh process "
        r"(and, for E1, a fresh OPA server and freshly created \texttt{toxiproxy} "
        r"proxies). Reported per quantity: number of executions, mean across "
        r"executions, sample standard deviation, coefficient of variation, and the "
        r"half-width of a 95\,\% confidence interval on the mean (Student-$t$, "
        r"$R-1$ degrees of freedom). E1 repetitions use $10^4$ exercises per "
        r"configuration and $2\times10^3$ for the injected-delay configurations; "
        r"E2 repetitions replay the full 2{,}000-triple corpus; E3 repetitions use "
        r"the same iteration counts as the official run. Units: microseconds for "
        r"E1, milliseconds for E2 and E3.}",
        r"\label{tab:variability}",
        r"\small",
        r"\begin{tabular}{@{}lrrrrr@{}}",
        r"\toprule",
        r"Quantity & $R$ & Mean & SD & CV (\%) & 95\,\% CI \\",
        r"\midrule",
        r"\multicolumn{6}{@{}l}{\emph{E1: exercise-time verification latency ($\mu$s)}}\\",
        *b1,
        r"\midrule",
        r"\multicolumn{6}{@{}l}{\emph{E2: x402 payment path, per-stage latency (ms)}}\\",
        *b2,
        r"\midrule",
        r"\multicolumn{6}{@{}l}{\emph{E3: accumulator revocation (ms)}}\\",
        *b3,
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    print(f"wrote {out}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
