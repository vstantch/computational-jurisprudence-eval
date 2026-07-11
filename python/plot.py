"""Plot E1 results — one PNG per metric family, from the committed CSVs.

Reads every results/e1-*.csv (biscuit, grant@1, OPA at local/5ms/20ms), and
emits, per fanout:
  * latency_p50_vs_depth_f{N}.png   (log-y, all systems/configs)
  * latency_p99_vs_depth_f{N}.png
  * throughput_vs_depth_f{N}.png
  * token_size_vs_depth.png         (biscuit token vs grant@1 chain vs OPA input)

All axes label the platform + sandbox flag pulled from the CSV rows so a plot is
never mistaken for the official Mac-mini numbers.
"""

from __future__ import annotations

import csv
import glob
import os
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def load_rows(results_dir: str) -> list[dict]:
    rows = []
    for path in sorted(glob.glob(os.path.join(results_dir, "e1-*.csv"))):
        with open(path) as f:
            for r in csv.DictReader(f):
                rows.append(r)
    return rows


def series_label(r: dict) -> str:
    if r["system"] == "opa":
        return f"opa/{r['config']}"
    return r["system"]


def platform_caption(rows: list[dict]) -> str:
    if not rows:
        return ""
    r = rows[0]
    sb = "SANDBOX (indicative)" if r["sandbox"] == "true" else "official"
    return f"{r['os']}/{r['arch']} · {r['cpu']} · {r['runtime']} · {sb}"


def plot_metric(rows, fanout, ycol, title, fname, outdir, logy=True):
    by_series = defaultdict(list)
    for r in rows:
        if int(r["fanout"]) != fanout:
            continue
        by_series[series_label(r)].append((int(r["depth"]), float(r[ycol])))
    if not by_series:
        return
    plt.figure(figsize=(7, 4.5))
    for label in sorted(by_series):
        pts = sorted(by_series[label])
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        plt.plot(xs, ys, marker="o", label=label)
    if logy:
        plt.yscale("log")
    plt.xlabel("delegation-chain depth")
    plt.ylabel(ycol)
    plt.title(f"{title} (fanout={fanout})")
    plt.figtext(0.5, -0.02, platform_caption(rows), ha="center", fontsize=7)
    plt.legend()
    plt.grid(True, which="both", alpha=0.3)
    plt.tight_layout()
    path = os.path.join(outdir, fname)
    plt.savefig(path, dpi=130, bbox_inches="tight")
    plt.close()
    print(f"wrote {path}")


def plot_token(rows, outdir):
    by_series = defaultdict(dict)
    for r in rows:
        by_series[series_label(r)][int(r["depth"])] = int(r["token_bytes"])
    if not by_series:
        return
    plt.figure(figsize=(7, 4.5))
    for label in sorted(by_series):
        pts = sorted(by_series[label].items())
        plt.plot([p[0] for p in pts], [p[1] for p in pts], marker="s", label=label)
    plt.xlabel("delegation-chain depth")
    plt.ylabel("token / message bytes")
    plt.title("Token size vs depth")
    plt.figtext(0.5, -0.02, platform_caption(rows), ha="center", fontsize=7)
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    path = os.path.join(outdir, "token_size_vs_depth.png")
    plt.savefig(path, dpi=130, bbox_inches="tight")
    plt.close()
    print(f"wrote {path}")


def main():
    import sys
    results_dir = sys.argv[1] if len(sys.argv) > 1 else "results"
    outdir = sys.argv[2] if len(sys.argv) > 2 else "plots"
    os.makedirs(outdir, exist_ok=True)
    rows = load_rows(results_dir)
    if not rows:
        print("no results CSVs found — run the benches first")
        return
    fanouts = sorted({int(r["fanout"]) for r in rows})
    for fo in fanouts:
        plot_metric(rows, fo, "p50_ns", "Exercise latency p50",
                    f"latency_p50_vs_depth_f{fo}.png", outdir)
        plot_metric(rows, fo, "p99_ns", "Exercise latency p99",
                    f"latency_p99_vs_depth_f{fo}.png", outdir)
        plot_metric(rows, fo, "throughput_ops_s", "Single-core throughput",
                    f"throughput_vs_depth_f{fo}.png", outdir, logy=True)
    plot_token(rows, outdir)


if __name__ == "__main__":
    main()
