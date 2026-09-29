"""Aggregate the repeated-execution E1 sweep into run-to-run variability stats.

Reviewers of the Future Internet submission asked whether the reported
percentiles came from a single execution per configuration (they did) and for
a quantification of run-to-run uncertainty. scripts/repeat_e1.sh produces R
independent executions; this script reduces them to, per (system, config,
depth): the number of repetitions, the mean of the per-run p50, the sample
standard deviation, the coefficient of variation, and a 95 % confidence
interval on the mean using the Student-t critical value for R-1 degrees of
freedom.

Nothing here re-times anything: it only summarizes measured CSV rows.

Usage: python3 python/variability.py results/variability [out.csv] [fanout]

The default out.csv is tables/e1-variability.csv, never a file under results/.
"""

from __future__ import annotations

import csv
import glob
import os
import statistics
import sys

# Student-t two-sided 95 % critical values, df = 1..15 (beyond that, 1.96).
_T95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160,
    14: 2.145, 15: 2.131,
}


def t95(df: int) -> float:
    return _T95.get(df, 1.96)


def load(indir: str, fanout: str) -> dict:
    """Group per-run p50/p99 (in microseconds) by (system, config, depth)."""
    runs: dict[tuple[str, str, int], dict[str, list[float]]] = {}
    for path in sorted(glob.glob(os.path.join(indir, "rep*-*.csv"))):
        with open(path) as f:
            for row in csv.DictReader(f):
                if row["fanout"] != fanout:
                    continue
                key = (row["system"], row["config"], int(row["depth"]))
                slot = runs.setdefault(key, {"p50": [], "p99": [], "n": []})
                slot["p50"].append(int(row["p50_ns"]) / 1000.0)
                slot["p99"].append(int(row["p99_ns"]) / 1000.0)
                slot["n"].append(int(row["n_exercises"]))
    return runs


def main() -> None:
    indir = sys.argv[1] if len(sys.argv) > 1 else "results/variability"
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "tables", "e1-variability.csv")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    fanout = sys.argv[3] if len(sys.argv) > 3 else "1"

    runs = load(indir, fanout)
    if not runs:
        raise SystemExit(f"no repetition CSVs under {indir}")

    header = [
        "system", "config", "depth", "runs", "n_exercises_per_run",
        "p50_mean_us", "p50_sd_us", "p50_cv_pct", "p50_ci95_halfwidth_us",
        "p99_mean_us", "p99_sd_us", "p99_cv_pct",
    ]
    rows = []
    for (system, config, depth) in sorted(runs, key=lambda k: (k[0], k[1], k[2])):
        s = runs[(system, config, depth)]
        r = len(s["p50"])
        if r < 2:
            continue
        m50, sd50 = statistics.mean(s["p50"]), statistics.stdev(s["p50"])
        m99, sd99 = statistics.mean(s["p99"]), statistics.stdev(s["p99"])
        half = t95(r - 1) * sd50 / (r ** 0.5)
        rows.append([
            system, config, depth, r, s["n"][0],
            f"{m50:.2f}", f"{sd50:.2f}", f"{100 * sd50 / m50:.2f}", f"{half:.2f}",
            f"{m99:.2f}", f"{sd99:.2f}", f"{100 * sd99 / m99:.2f}",
        ])

    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"wrote {out} ({len(rows)} configurations)")
    for row in rows:
        print("  ".join(str(c) for c in row))


if __name__ == "__main__":
    main()
