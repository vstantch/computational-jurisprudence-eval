#!/usr/bin/env python3
"""Build the cross-platform E1 table (LaTeX) from a reference and a second sweep.

Reviewers asked whether the latency results hold outside the single Apple M4 Mac
mini on which every number of the submitted version was produced. The harness
was re-run on x86-64 Linux inside a container against the same committed seeded
fixtures (docs/CROSS-PLATFORM.md). This script reduces the two sweeps to one
comparison table and emits the LaTeX.

Nothing is re-timed here; only measured CSV rows are summarized. Rows are keyed
by (system, config, depth) at fanout 1, the configuration the article reports.

Inputs are resolved through results/MANIFEST.toml, never by globbing: each
platform must have exactly one official Biscuit file and one official OPA file,
each with the SHA-256 the manifest records. Row labels and platform
descriptions come from the manifest; the OPA version comes from the CSVs'
`runtime` column and must agree between the two platforms, as must the delay
method the manifest records. Any disagreement stops the script.

A second sweep that is not in the manifest (for example a course run) can be
given as a directory; its row label and description then come from the CSVs'
cpu/os/arch columns, and its delay method, which the CSVs do not record, must
be stated with --compare-delay-method. A directory with two rows for the same
(system, config, depth) is an error, not "last file wins".

Usage:
  python3 python/mkcrossplatform.py [--manifest results/MANIFEST.toml] \\
      REFERENCE_PLATFORM COMPARE_PLATFORM OUT.tex
  python3 python/mkcrossplatform.py REFERENCE_PLATFORM \\
      --compare-dir DIR --compare-delay-method toxiproxy OUT.tex

The published table is: apple-m4 x86-cloud (tables/crossplatform.tex).
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import results_manifest  # noqa: E402

DEPTHS = [1, 2, 4, 6, 8, 10]

# (system, config) -> printed label, in table order.
ROWS = [
    (("biscuit", "na"), r"Biscuit (\texttt{biscuit-auth}, Rust)"),
    (("opa", "local"), r"OPA / local"),
    (("opa", "5ms"), r"OPA / $+5$\,ms"),
    (("opa", "20ms"), r"OPA / $+20$\,ms"),
]


class Sweep:
    """p50 values plus the metadata the caption is built from."""

    def __init__(self, paths: list[str], label: str, caption: str, delay_method: str):
        self.p50: dict = {}
        self.meta: dict[str, set] = {"cpu": set(), "os": set(), "arch": set(), "opa": set()}
        for path in paths:
            with open(path, newline="") as f:
                for row in csv.DictReader(f):
                    if row.get("schema") != "pct-eval/e1@1" or int(row["fanout"]) != 1:
                        continue
                    key = (row["system"], row["config"], int(row["depth"]))
                    if key in self.p50:
                        raise SystemExit(f"ambiguous input: {key} appears twice ({path})")
                    self.p50[key] = int(row["p50_ns"]) / 1000.0
                    for k in ("cpu", "os", "arch"):
                        self.meta[k].add(row[k])
                    if row["system"] == "opa":
                        self.meta["opa"].add(row["runtime"])
        self.label, self.caption, self.delay_method = label, caption, delay_method

    def single(self, key: str) -> str:
        vals = self.meta[key]
        if len(vals) != 1:
            raise SystemExit(f"{self.label}: expected one {key} value, found {sorted(vals)}")
        return next(iter(vals))


def from_manifest(m: results_manifest.Manifest, platform: str) -> Sweep:
    p = m.platforms[platform]
    paths = [m.one(platform, "biscuit"), m.one(platform, "opa")]
    sweep = Sweep(paths, p["row_label"], p["caption"], p["delay_method"])
    if sweep.single("cpu") != p["cpu"]:
        raise SystemExit(f"{platform}: CSV cpu {sweep.single('cpu')!r} != manifest {p['cpu']!r}")
    return sweep


TEX_SPECIALS = {"\\": r"\textbackslash{}", "_": r"\_", "%": r"\%", "&": r"\&",
                "#": r"\#", "$": r"\$", "{": r"\{", "}": r"\}"}


def tex_escape(s: str) -> str:
    """Escape CSV-derived text for LaTeX (manifest text is already LaTeX)."""
    return re.sub(r"[\\_%&#${}]", lambda m: TEX_SPECIALS[m.group()], s)


def from_dir(d: str, delay_method: str) -> Sweep:
    paths = sorted(glob.glob(os.path.join(d, "*.csv")))
    probe = Sweep(paths, d, "", delay_method)
    cpu, osname, arch = (tex_escape(probe.single(k)) for k in ("cpu", "os", "arch"))
    return Sweep(paths, f"{arch} ({cpu})", f"{cpu}, {osname}/{arch}", tex_escape(delay_method))


def fmt(v: float | None) -> str:
    if v is None:
        # The manuscript carries no em dashes; use an explicit marker instead.
        return r"n/a"
    if v >= 10000:
        thousands, rest = divmod(int(round(v)), 1000)
        return f"{thousands}{{,}}{rest:03d}"
    if v >= 100:
        return f"{int(round(v))}"
    return f"{v:.0f}"


def caption(ref: Sweep, cmp: Sweep) -> str:
    opa_ref, opa_cmp = ref.single("opa"), cmp.single("opa")
    if opa_ref != opa_cmp:
        raise SystemExit(f"OPA differs between platforms ({opa_ref} vs {opa_cmp}); "
                         "the caption would state 'the same OPA'")
    if ref.delay_method != cmp.delay_method:
        raise SystemExit(f"delay method differs ({ref.delay_method} vs {cmp.delay_method}); "
                         "the caption would state 'the same delay injection'")
    opa_version = opa_ref.removeprefix("opa-")
    return (
        r"\textbf{Measured (this work).} E1 replicated on a second platform: "
        r"exercise-time verification latency, p50 in microseconds, by "
        r"delegation-chain depth, at fanout~1. Both rows of each pair come from "
        r"the same harness at the same commit, the same committed seeded "
        f"fixtures, the same OPA {opa_version}, and the same "
        rf"\texttt{{{ref.delay_method}}} delay "
        r"injection; only the platform differs. "
        f"Reference: {ref.caption}. Cross-platform: {cmp.caption}. "
        r"\texttt{capability-grant@1} is absent because its artifact is not "
        r"public and could not be exercised off the reference machine."
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--manifest", default=results_manifest.DEFAULT)
    ap.add_argument("reference")
    ap.add_argument("compare", nargs="?")
    ap.add_argument("out")
    ap.add_argument("--compare-dir")
    ap.add_argument("--compare-delay-method")
    a = ap.parse_args()

    m = results_manifest.Manifest(a.manifest)
    ref = from_manifest(m, a.reference)
    if a.compare_dir:
        if a.compare or not a.compare_delay_method:
            ap.error("--compare-dir needs --compare-delay-method and no COMPARE_PLATFORM")
        cloud = from_dir(a.compare_dir, a.compare_delay_method)
    elif a.compare:
        cloud = from_manifest(m, a.compare)
    else:
        ap.error("give COMPARE_PLATFORM or --compare-dir")

    lines = []
    ratios = []
    for (system, config), label in ROWS:
        for platform, data in (("ref", ref), ("cloud", cloud)):
            cells = [fmt(data.p50.get((system, config, d))) for d in DEPTHS]
            lead = label if platform == "ref" else ""
            lines.append(f"{lead} & {data.label} & " + " & ".join(cells) + r" \\")
        for d in DEPTHS:
            x, y = ref.p50.get((system, config, d)), cloud.p50.get((system, config, d))
            if x and y:
                ratios.append(y / x)
        lines.append(r"\addlinespace")
    if lines and lines[-1] == r"\addlinespace":
        lines.pop()

    body = "\n".join(lines)
    tex = (
        # Kept verbatim: the published table carries this line.
        "% GENERATED by R2/harness/mkcrossplatform.py -- do not edit by hand.\n"
        "\\begin{table}[t]\n\\centering\n"
        f"\\caption{{{caption(ref, cloud)}}}\n"
        "\\label{tab:crossplatform}\n\\small\n"
        "\\begin{tabular}{@{}llrrrrrr@{}}\n\\toprule\n"
        "System / configuration & Platform & $d{=}1$ & $d{=}2$ & $d{=}4$ & "
        "$d{=}6$ & $d{=}8$ & $d{=}10$ \\\\\n\\midrule\n"
        f"{body}\n"
        "\\bottomrule\n\\end{tabular}\n\\end{table}\n"
    )

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(tex)

    print(f"wrote {a.out}")
    if ratios:
        print(f"cloud/reference p50 ratio: min {min(ratios):.2f} "
              f"max {max(ratios):.2f} over {len(ratios)} cells")
    for (system, config), _ in ROWS:
        rs = [cloud.p50[(system, config, d)] / ref.p50[(system, config, d)]
              for d in DEPTHS
              if (system, config, d) in ref.p50 and (system, config, d) in cloud.p50]
        if rs:
            print(f"  {system}/{config}: ratio min {min(rs):.2f} max {max(rs):.2f}")


if __name__ == "__main__":
    main()
