"""Build-time check: the harness code the image runs imports only the stdlib.

Fails the build if python/common.py, opa_bench.py, verify_gate_2way.py,
mkcrossplatform.py or the lab-c helpers import anything outside the standard
library and each other, so the image needs no third-party Python packages.
"""

import ast
import sys
from pathlib import Path

FILES = [
    Path("/opt/harness/python/common.py"),
    Path("/opt/harness/python/opa_bench.py"),
    Path("/opt/harness/python/verify_gate_2way.py"),
    Path("/opt/harness/python/mkcrossplatform.py"),
    Path("/opt/lab-c/platform_info.py"),
    Path("/opt/lab-c/sanitize.py"),
    Path("/opt/harness/bin/curl"),
]
LOCAL = {p.stem for p in FILES}


bad = []
for path in FILES:
    for node in ast.walk(ast.parse(path.read_text(), str(path))):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names = [node.module or ""]
        else:
            continue
        for name in names:
            top = name.split(".")[0]
            if top not in sys.stdlib_module_names and top not in LOCAL and top != "__future__":
                bad.append(f"{path.name}: {name}")

if bad:
    sys.exit("non-stdlib imports: " + ", ".join(bad))
print(f"import audit: {len(FILES)} files, stdlib only")
