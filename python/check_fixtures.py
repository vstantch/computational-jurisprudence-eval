"""Check the committed seeded fixtures against workloads/SHA256SUMS.

`just verify` and `just verify-public` run this instead of regenerating the
fixtures, so a gate always runs on exactly the committed workload. Fails if a
listed file is missing or differs, or if a fixture is present but unlisted.

Usage: python3 python/check_fixtures.py [workloads_dir]
"""

from __future__ import annotations

import glob
import hashlib
import os
import sys


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    wl = sys.argv[1] if len(sys.argv) > 1 else "workloads"
    listed = {}
    with open(os.path.join(wl, "SHA256SUMS")) as f:
        for line in f:
            digest, name = line.split()
            listed[name] = digest
    bad = []
    for name, digest in sorted(listed.items()):
        path = os.path.join(wl, name)
        if not os.path.exists(path):
            bad.append(f"missing {name}")
        elif sha256(path) != digest:
            bad.append(f"changed {name}")
    for path in glob.glob(os.path.join(wl, "graph_*.json")):
        if os.path.basename(path) not in listed:
            bad.append(f"unlisted {os.path.basename(path)}")
    if bad:
        print("FIXTURES DIFFER from workloads/SHA256SUMS:", file=sys.stderr)
        for b in bad:
            print(f"  {b}", file=sys.stderr)
        sys.exit(1)
    print(f"fixtures: {len(listed)} files match workloads/SHA256SUMS")


if __name__ == "__main__":
    main()
