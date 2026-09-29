"""Copy harness output from the tmpfs scratch directory to /out, by whitelist.

The harness writes CSV rows with ts_utc and host columns, and names the OPA CSV
after `hostname`. None of that reaches /out: every file is re-written here from
parsed values, keeping only the columns below, and validated on the way.

Files written to the destination directory:
  platform.json          arch, cpu_model, cores, os, kernel, virtualised
  biscuit-verdicts.json  gate verdicts: {"d<depth>_f<fanout>": {"<id>": bool}}
  opa-verdicts.json      same shape
  e1-biscuit.csv         COLUMNS below, system=biscuit
  e1-opa.csv             COLUMNS below, system=opa, config local/5ms/20ms
  crossplatform.tex      the harness's table generator output, unchanged

Usage: sanitize.py <raw_dir> <dest_dir> <platform.json>
"""

from __future__ import annotations

import csv
import glob
import json
import os
import re
import sys

SCHEMA = "lab-c/e1@1"
COLUMNS = [
    "schema", "os", "arch", "cpu", "runtime", "sandbox", "system", "config",
    "depth", "fanout", "n_exercises", "p50_ns", "p95_ns", "p99_ns", "mean_ns",
    "throughput_ops_s", "token_bytes",
]
INT_COLS = ["depth", "fanout", "n_exercises", "p50_ns", "p95_ns", "p99_ns",
            "mean_ns", "token_bytes"]
SYSTEM_CONFIGS = {"biscuit": {"na"}, "opa": {"local", "5ms", "20ms"}}
RUNTIME = re.compile(r"^(rustc|opa|cpython)-[0-9][0-9.]*$")
VERDICT_KEY = re.compile(r"^d[0-9]+_f[0-9]+$")


def fail(msg: str) -> None:
    sys.exit(f"lab-c: sanitize: {msg}")


def rows_from(raw: str, pattern: str, system: str, plat: dict) -> list[dict]:
    paths = sorted(glob.glob(os.path.join(raw, pattern)))
    if len(paths) != 1:
        fail(f"expected one {pattern} in scratch, found {len(paths)}")
    out = []
    with open(paths[0], newline="") as f:
        for r in csv.DictReader(f):
            if r.get("schema") != "pct-eval/e1@1":
                fail(f"unexpected schema {r.get('schema')!r}")
            if r["system"] != system or r["config"] not in SYSTEM_CONFIGS[system]:
                fail(f"unexpected system/config {r['system']}/{r['config']}")
            # platform columns must be exactly the whitelisted platform facts
            if (r["os"], r["arch"], r["cpu"]) != (plat["os"], plat["arch"], plat["cpu_model"]):
                fail("platform columns differ from platform.json")
            if r["sandbox"] != "true" or not RUNTIME.match(r["runtime"]):
                fail("unexpected sandbox/runtime value")
            row = {c: r[c] for c in COLUMNS if c != "schema"}
            for c in INT_COLS:
                row[c] = str(int(row[c]))
            row["throughput_ops_s"] = f"{float(row['throughput_ops_s']):.1f}"
            row["schema"] = SCHEMA
            out.append(row)
    if not out:
        fail(f"{pattern} has no rows")
    return out


def write_csv(path: str, rows: list[dict]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def copy_verdicts(src: str, dst: str) -> None:
    with open(src) as f:
        data = json.load(f)
    clean = {}
    for key, per in data.items():
        if not VERDICT_KEY.match(key):
            fail(f"bad verdict key {key!r}")
        clean[key] = {}
        for eid, v in per.items():
            if not eid.isdigit() or not isinstance(v, bool):
                fail("bad verdict entry")
            clean[key][eid] = v
    with open(dst, "w") as f:
        json.dump(clean, f, indent=2)
        f.write("\n")


def main() -> None:
    raw, dest, plat_path = sys.argv[1], sys.argv[2], sys.argv[3]
    with open(plat_path) as f:
        plat = json.load(f)
    if set(plat) != {"arch", "cpu_model", "cores", "os", "kernel", "virtualised"}:
        fail("platform.json has unexpected fields")
    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, "platform.json"), "w") as f:
        json.dump(plat, f, indent=2, sort_keys=True)
        f.write("\n")

    for name in ("biscuit-verdicts.json", "opa-verdicts.json"):
        src = os.path.join(raw, "gate", name)
        if os.path.exists(src):
            copy_verdicts(src, os.path.join(dest, name))

    sweep = os.path.join(raw, "sweep")
    if os.path.isdir(sweep):
        write_csv(os.path.join(dest, "e1-biscuit.csv"),
                  rows_from(sweep, "e1-biscuit*.csv", "biscuit", plat))
        write_csv(os.path.join(dest, "e1-opa.csv"),
                  rows_from(sweep, "e1-opa_*.csv", "opa", plat))

    tex = os.path.join(raw, "crossplatform.tex")
    if os.path.exists(tex):
        with open(tex) as f:
            body = f.read()
        with open(os.path.join(dest, "crossplatform.tex"), "w") as f:
            f.write(body)


if __name__ == "__main__":
    main()
