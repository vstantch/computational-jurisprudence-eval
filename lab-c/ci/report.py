"""CI-only reporting for the Lab C image (not shipped in the image).

  report.py smoke <log> <arch>          assert the canary lines, in order
  report.py out <out_dir>               assert /out holds only whitelisted files/fields
  report.py sweep <out_dir>             p50 table + runner-observed crossover depth
  report.py overhead <native> <cont>    per-depth container/native ratio of p50

Every number is one run on one CI runner (n = 1 per platform).
"""

from __future__ import annotations

import csv
import glob
import json
import os
import sys

DEPTHS = [1, 2, 4, 6, 8, 10]
SERIES = [("biscuit", "na"), ("opa", "local"), ("opa", "5ms"), ("opa", "20ms")]
OUT_FILES = {
    "platform.json", "biscuit-verdicts.json", "opa-verdicts.json",
    "e1-biscuit.csv", "e1-opa.csv", "crossplatform.tex",
}
PLATFORM_KEYS = {"arch", "cpu_model", "cores", "os", "kernel", "virtualised"}
CSV_COLUMNS = (
    "schema,os,arch,cpu,runtime,sandbox,system,config,depth,fanout,n_exercises,"
    "p50_ns,p95_ns,p99_ns,mean_ns,throughput_ops_s,token_bytes"
)
HERE = os.path.dirname(os.path.abspath(__file__))


def p50s(d: str) -> dict:
    """(system, config, depth) -> p50 in microseconds, fanout 1, any CSV schema."""
    out = {}
    for path in sorted(glob.glob(os.path.join(d, "*.csv"))):
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                if r.get("fanout") == "1":
                    out[(r["system"], r["config"], int(r["depth"]))] = int(r["p50_ns"]) / 1000
    return out


def smoke(log: str, arch: str) -> None:
    want = open(os.path.join(HERE, "..", "smoke-expected.txt")).read().replace("@ARCH@", arch)
    want = want.splitlines()
    got = open(log).read().splitlines()
    i = 0
    for line in got:
        if i < len(want) and line == want[i]:
            i += 1
    if i != len(want):
        sys.exit(f"canary line missing or out of order: {want[i]!r}")
    for bad in ("fetching", "GATE FAIL", "REFUSING"):
        if any(bad in line for line in got):
            sys.exit(f"unexpected output containing {bad!r}")
    print(f"smoke canary: all {len(want)} lines present, in order")


def out(d: str) -> None:
    files = set()
    for root, _, names in os.walk(d):
        for n in names:
            files.add(n)
            if n not in OUT_FILES:
                sys.exit(f"unexpected file in /out: {os.path.join(root, n)}")
    for path in glob.glob(os.path.join(d, "**", "platform.json"), recursive=True):
        keys = set(json.load(open(path)))
        if keys != PLATFORM_KEYS:
            sys.exit(f"{path}: fields {sorted(keys)}")
    for path in glob.glob(os.path.join(d, "**", "e1-*.csv"), recursive=True):
        if open(path).readline().strip() != CSV_COLUMNS:
            sys.exit(f"{path}: unexpected columns")
    print(f"/out whitelist ok: {sorted(files)}")


def sweep(d: str) -> None:
    v = p50s(d)
    print("p50 microseconds, fanout 1 (one run, this runner)")
    print("series        " + "".join(f"{'d' + str(x):>10}" for x in DEPTHS))
    for s, c in SERIES:
        label = s if s == "biscuit" else f"opa/{c}"
        print(f"{label:<14}" + "".join(f"{v.get((s, c, x), float('nan')):>10.0f}" for x in DEPTHS))
    faster = [x for x in DEPTHS
              if ("opa", "local", x) in v and ("biscuit", "na", x) in v
              and v[("opa", "local", x)] < v[("biscuit", "na", x)]]
    if faster:
        print(f"runner-observed crossover: local OPA p50 below Biscuit p50 at depths {faster}; "
              f"first at d={faster[0]}")
    else:
        print("runner-observed crossover: none in the measured range")


def overhead(native: str, cont: str) -> None:
    a, b = p50s(native), p50s(cont)
    flagged = []
    print("container p50 / native p50, fanout 1 (one run each, same runner)")
    print("series        " + "".join(f"{'d' + str(x):>9}" for x in DEPTHS))
    for s, c in SERIES:
        label = s if s == "biscuit" else f"opa/{c}"
        cells = []
        for x in DEPTHS:
            k = (s, c, x)
            if k in a and k in b:
                r = b[k] / a[k]
                cells.append(f"{r:>9.3f}")
                if abs(r - 1) > 0.10:
                    flagged.append(f"{label} d={x}: {r:.3f}")
            else:
                cells.append(f"{'n/a':>9}")
        print(f"{label:<14}" + "".join(cells))
    print("native p50 us / container p50 us:")
    for s, c in SERIES:
        label = s if s == "biscuit" else f"opa/{c}"
        print(f"  {label:<12}" + "  ".join(
            f"d{x} {a.get((s, c, x), 0):.0f}/{b.get((s, c, x), 0):.0f}" for x in DEPTHS))
    if flagged:
        print("MEDIAN SHIFT > 10 %: " + "; ".join(flagged))
    else:
        print("no median shifted by more than 10 %")


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    {"smoke": smoke, "out": out, "sweep": sweep, "overhead": overhead}[cmd](*args)
