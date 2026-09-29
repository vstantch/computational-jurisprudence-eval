#!/bin/sh
# scripts/opa_e1.sh at the tag starts "$ROOT/bin/opa run --server ..." without
# --disable-telemetry, and OPA otherwise contacts its update-check server at
# startup. This shim sits at that path and adds the flag to `opa run`; every
# other invocation (e.g. `opa version`) passes through unchanged.
set -eu
real=/usr/local/libexec/lab-c/opa
if [ "${1:-}" = "run" ]; then
  shift
  exec "$real" run --disable-telemetry "$@"
fi
exec "$real" "$@"
