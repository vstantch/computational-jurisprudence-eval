"""Explicit provenance for results/: which committed file backs which table.

Replaces "glob a directory and let the last file by name win". Every loader
that feeds a published table resolves its inputs through results/MANIFEST.toml
and fails on any ambiguity: a SHA-256 that differs from the manifest, a file
under results/ that the manifest does not list, or a (platform, system) with
zero or several files of the requested role.

Usage:
  python3 python/results_manifest.py check          verify the whole manifest
  python3 python/results_manifest.py show PLATFORM  list its official files
"""

from __future__ import annotations

import hashlib
import os
import sys
import tomllib

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT = os.path.join(ROOT, "results", "MANIFEST.toml")


class ManifestError(SystemExit):
    def __init__(self, msg: str):
        super().__init__(f"results manifest: {msg}")


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Manifest:
    def __init__(self, path: str = DEFAULT):
        self.path = path
        self.results_dir = os.path.dirname(os.path.abspath(path))
        with open(path, "rb") as f:
            data = tomllib.load(f)
        if data.get("schema") != "pct-eval/results-manifest@1":
            raise ManifestError(f"unknown schema {data.get('schema')!r}")
        self.platforms: dict = data["platforms"]
        self.files: list[dict] = data["file"]
        seen = set()
        for e in self.files:
            if e["path"] in seen:
                raise ManifestError(f"{e['path']} listed twice")
            seen.add(e["path"])
            if e["platform"] not in self.platforms:
                raise ManifestError(f"{e['path']}: unknown platform {e['platform']!r}")

    def abspath(self, entry: dict) -> str:
        return os.path.join(self.results_dir, entry["path"])

    def verified(self, entry: dict) -> str:
        """Absolute path of an entry, after checking its SHA-256."""
        path = self.abspath(entry)
        if not os.path.exists(path):
            raise ManifestError(f"{entry['path']} is listed but missing")
        got = _sha256(path)
        if got != entry["sha256"]:
            raise ManifestError(f"{entry['path']}: sha256 {got}, manifest says {entry['sha256']}")
        return path

    def check(self) -> int:
        for e in self.files:
            self.verified(e)
        listed = {e["path"] for e in self.files}
        for dirpath, _, names in os.walk(self.results_dir):
            for n in names:
                rel = os.path.relpath(os.path.join(dirpath, n), self.results_dir)
                if rel != "MANIFEST.toml" and rel not in listed:
                    raise ManifestError(f"{rel} is under results/ but not in the manifest")
        return len(self.files)

    def select(self, platform: str, system: str, role: str = "official") -> list[dict]:
        if platform not in self.platforms:
            raise ManifestError(f"unknown platform {platform!r}")
        return [e for e in self.files
                if e["platform"] == platform and e["system"] == system and e["role"] == role]

    def one(self, platform: str, system: str, role: str = "official") -> str:
        """The single verified file for (platform, system, role); else fail."""
        hits = self.select(platform, system, role)
        if len(hits) != 1:
            names = ", ".join(e["path"] for e in hits) or "none"
            raise ManifestError(
                f"expected exactly one {role} file for {platform}/{system}, found {len(hits)}: {names}")
        return self.verified(hits[0])


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    m = Manifest(os.environ.get("PCT_RESULTS_MANIFEST", DEFAULT))
    if cmd == "check":
        n = m.check()
        print(f"results manifest: {n} files, all SHA-256 match, nothing unlisted")
    elif cmd == "show" and len(sys.argv) == 3:
        for e in m.files:
            if e["platform"] == sys.argv[2] and e["role"] == "official":
                print(f"{e['system']:8} {e['path']}")
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
