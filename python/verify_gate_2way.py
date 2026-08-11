"""Cross-platform correctness gate — Biscuit and OPA must agree, BEFORE timing.

This is the two-way variant of the upstream three-way gate
(``python/verify_gate.py`` in computational-jurisprudence-eval, commit b42ae1b,
tag ``v1-fi-revision-2026-08-03``). The logic below is that gate with the
``grant@1`` term removed and nothing else changed.

Why two-way. The third system in E1, ``capability-grant@1``, is imported from
the ``presidio-hardened-x402`` checkout via ``PCT_X402_SRC``; that artifact is
not public, so it cannot be exercised on a machine other than the author's. The
cross-platform replication of Section 7.5 therefore covers the two systems whose
sources are public, and asserts

    biscuit == OPA == expected

on the same gate subset the upstream gate uses (first 50 allow exercises plus
every crafted violation of every fixture). A disagreement fails the gate and the
timing runs do not proceed.

This file adds a gate; it does not relax one. Every exercise checked here is
checked against the same expected verdict the three-way gate uses, and the
crafted violation classes (over_budget, out_of_prefix, expired,
attenuated_depth) are unchanged. jurisdiction is not in the violation set, for
the reason the upstream gate states: grant@1's fragment cannot check it, so the
workload holds it constant.

Usage: python3 verify_gate_2way.py <workloads_dir> <results_dir>
"""

from __future__ import annotations

import json
import os
import sys

import common


def _load(path: str) -> dict:
    if not os.path.exists(path):
        print(f"MISSING verdict file: {path}", file=sys.stderr)
        sys.exit(2)
    with open(path) as f:
        return json.load(f)


def main() -> None:
    workloads = sys.argv[1] if len(sys.argv) > 1 else "workloads"
    results = sys.argv[2] if len(sys.argv) > 2 else "results"

    biscuit = _load(os.path.join(results, "biscuit-verdicts.json"))
    opa = _load(os.path.join(results, "opa-verdicts.json"))

    disagreements = []
    checked = 0
    for path in common.fixture_paths(workloads):
        fx = common.load_fixture(path)
        key = f"d{fx['depth']}_f{fx['fanout']}"
        for e in common.gate_exercises(fx):
            eid = str(e["id"])
            expected = e["expect"] == "allow"
            try:
                b = biscuit[key][eid]
                o = opa[key][eid]
            except KeyError:
                disagreements.append((key, eid, e.get("violation"), "missing verdict"))
                continue
            checked += 1
            if not (b == o == expected):
                disagreements.append(
                    (key, eid, e.get("violation") or "allow",
                     f"expected={expected} biscuit={b} opa={o}")
                )

    print(f"correctness gate (2-way): checked {checked} exercises across "
          f"{len(common.fixture_paths(workloads))} configs")
    if disagreements:
        print(f"GATE FAILED — {len(disagreements)} disagreement(s):", file=sys.stderr)
        for key, eid, kind, detail in disagreements[:40]:
            print(f"  {key} id={eid} [{kind}] {detail}", file=sys.stderr)
        sys.exit(1)
    print("GATE PASSED — biscuit == OPA == expected on every gate exercise "
          "(allow + over_budget/out_of_prefix/expired/attenuated_depth).")


if __name__ == "__main__":
    main()
