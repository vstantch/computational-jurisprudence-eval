"""Shared helpers for the E1 Python benches (grant@1 + OPA).

Keeps the CSV schema and platform stamp IDENTICAL to the Rust Biscuit bench so
all three systems land in one comparable table (plan §3: "every CSV row carries
platform metadata"). This sandbox is aarch64 Linux and produces INDICATIVE
shape-numbers only; the official numbers come from the owner's Apple-silicon Mac
mini. Nothing here fabricates a measurement — every value written is measured.
"""

from __future__ import annotations

import glob
import json
import os
import platform
import socket
import sys
from datetime import datetime, timezone

# Shared CSV schema — MUST match crates/e1-biscuit/src/main.rs::CSV_HEADER.
CSV_HEADER = (
    "schema,ts_utc,host,os,arch,cpu,runtime,sandbox,system,config,depth,fanout,"
    "n_exercises,p50_ns,p95_ns,p99_ns,mean_ns,throughput_ops_s,token_bytes"
)


def platform_stamp() -> dict:
    """Platform metadata for every CSV row. Reads the same PCT_* env vars the
    Rust bench reads so the three systems agree on host/cpu/sandbox labels."""
    return {
        "ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "host": os.environ.get("PCT_HOST", socket.gethostname()),
        "os": platform.system().lower(),
        "arch": platform.machine(),
        "cpu": os.environ.get("PCT_CPU", "unknown"),
        "runtime": os.environ.get(
            "PCT_RUNTIME", f"cpython-{platform.python_version()}"
        ),
        "sandbox": os.environ.get("PCT_SANDBOX", "true"),
    }


def csv_row(stamp: dict, system: str, config: str, depth: int, fanout: int,
            n: int, p50: int, p95: int, p99: int, mean: int,
            throughput: float, token_bytes: int) -> str:
    return (
        f"pct-eval/e1@1,{stamp['ts_utc']},{stamp['host']},{stamp['os']},"
        f"{stamp['arch']},{stamp['cpu']},{stamp['runtime']},{stamp['sandbox']},"
        f"{system},{config},{depth},{fanout},{n},{p50},{p95},{p99},{mean},"
        f"{throughput:.1f},{token_bytes}"
    )


def percentile_ns(sorted_ns: list[int], p: float) -> int:
    if not sorted_ns:
        return 0
    idx = round((p / 100.0) * (len(sorted_ns) - 1))
    return sorted_ns[min(idx, len(sorted_ns) - 1)]


def fixture_paths(workloads_dir: str) -> list[str]:
    return sorted(glob.glob(os.path.join(workloads_dir, "graph_d*_f*.json")))


def load_fixture(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def gate_exercises(fx: dict) -> list[dict]:
    """The fixed cross-system correctness-gate subset: first 50 allow exercises
    plus every crafted violation. MUST match the Rust bench's gate_ids()."""
    out, allow_taken = [], 0
    for e in fx["exercises"]:
        if e["expect"] == "allow":
            if allow_taken < 50:
                out.append(e)
                allow_taken += 1
        else:
            out.append(e)
    return out


def x402_src_on_path() -> str:
    """Put presidio_x402 on sys.path. Configurable via PCT_X402_SRC so the Mac
    run can point at its own checkout; defaults to the sibling repo layout."""
    default = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..", "..", "presidio-hardened-x402", "tools", "src",
        )
    )
    src = os.environ.get("PCT_X402_SRC", default)
    if src not in sys.path:
        sys.path.insert(0, src)
    return src
