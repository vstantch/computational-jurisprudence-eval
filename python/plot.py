"""Plot E1 results — one PNG per metric family, from the committed CSVs.

Reads one platform's official E1 CSVs via results/MANIFEST.toml (--platform),
or a directory holding one e1-*.csv per system (--dir), and emits, per fanout:
  * latency_p50_vs_depth_f{N}.png   (log-y, all systems/configs)
  * latency_p99_vs_depth_f{N}.png
  * throughput_vs_depth_f{N}.png
  * token_size_vs_depth.png         (biscuit token vs grant@1 chain vs OPA input)

All axes label the platform + sandbox flag pulled from the CSV rows so a plot is
never mistaken for the official Mac-mini numbers.

Usage: python3 python/plot.py (--platform apple-m4 | --dir DIR) [outdir]
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
import sys
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import results_manifest  # noqa: E402


def load_rows(paths: list[str]) -> list[dict]:
    """Rows from these CSVs; two rows for the same (system, config, depth,
    fanout) are an error, not a zig-zag line or a silent last-file-wins."""
    rows, seen = [], {}
    for path in paths:
        with open(path) as f:
            for r in csv.DictReader(f):
                key = (r["system"], r["config"], r["depth"], r["fanout"])
                if key in seen:
                    raise SystemExit(f"ambiguous input: {key} in {seen[key]} and {path}")
                seen[key] = path
                rows.append(r)
    return rows


def input_paths(args) -> list[str]:
    if args.platform:
        m = results_manifest.Manifest(args.manifest)
        return [m.one(args.platform, s) for s in ("biscuit", "grant1", "opa")
                if m.select(args.platform, s)]
    return sorted(glob.glob(os.path.join(args.dir, "e1-*.csv")))


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
    ap = argparse.ArgumentParser(description="Plot E1 results, one PNG per metric.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--platform", help="manifest platform, e.g. apple-m4")
    src.add_argument("--dir", help="a directory with one e1-*.csv per system")
    ap.add_argument("--manifest", default=results_manifest.DEFAULT)
    ap.add_argument("outdir", nargs="?", default="plots")
    args = ap.parse_args()
    outdir = args.outdir
    os.makedirs(outdir, exist_ok=True)
    rows = load_rows(input_paths(args))
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
