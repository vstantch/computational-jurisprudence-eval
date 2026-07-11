"""Correctness gate — all three systems must agree, BEFORE any timing runs.

Reads the three verdict files produced by the systems over the shared gate
subset (first 50 allow + every crafted violation of every fixture):

  * results/biscuit-verdicts.json   (from `e1-biscuit verify`)
  * results/grant-verdicts.json     (from `grant_bench.py verdicts`)
  * results/opa-verdicts.json       (from `opa_bench.py verdicts`)

and the fixtures' expected verdicts. It asserts, per config and per exercise:

    biscuit == grant@1 == OPA == expected

For allow exercises expected is ALLOW; for the crafted violation set
(over_budget, out_of_prefix, expired, attenuated_depth) expected is DENY. Any
disagreement fails the gate (exit 1). Timing runs are wired to depend on this in
the justfile, so they refuse to start unless the three systems agree —
fail-closed (plan §1 E1 "correctness gate before timing").

jurisdiction is NOT in the violation set: grant@1's @1 fragment cannot check it,
so it is held constant and can never cause a disagreement (see README).
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
    grant = _load(os.path.join(results, "grant-verdicts.json"))
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
                g = grant[key][eid]
                o = opa[key][eid]
            except KeyError:
                disagreements.append((key, eid, e.get("violation"), "missing verdict"))
                continue
            checked += 1
            if not (b == g == o == expected):
                disagreements.append(
                    (key, eid, e.get("violation") or "allow",
                     f"expected={expected} biscuit={b} grant1={g} opa={o}")
                )

    print(f"correctness gate: checked {checked} exercises across "
          f"{len(common.fixture_paths(workloads))} configs")
    if disagreements:
        print(f"GATE FAILED — {len(disagreements)} disagreement(s):", file=sys.stderr)
        for key, eid, kind, detail in disagreements[:40]:
            print(f"  {key} id={eid} [{kind}] {detail}", file=sys.stderr)
        sys.exit(1)
    print("GATE PASSED — biscuit == grant@1 == OPA == expected on every gate "
          "exercise (allow + over_budget/out_of_prefix/expired/attenuated_depth).")


if __name__ == "__main__":
    main()
