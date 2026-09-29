#!/bin/bash
# Lab C entrypoint: correctness gate, then the E1 depth sweep, then the
# harness's table generator. Harness scratch output stays on the /tmp tmpfs;
# only lab-c/sanitize.py writes to /out, by whitelist.
#
# Exit codes: 0 ok, 2 usage or /out not mounted, 3 GATE FAIL,
#             4 not native (no timings), anything else: harness error.
set -euo pipefail

H=/opt/harness
L=/opt/lab-c
CMD="${1:-help}"

say() { printf 'lab-c: %s\n' "$*"; }

usage() {
  cat <<'EOF'
Lab C: E1 harness (Biscuit vs OPA) at v2-fi-revision-2026-08-11.

Subcommands (each writes to /out/<subcommand>/):
  gate    correctness gate only: Biscuit and OPA give identical ALLOW/DENY
          on every seeded fixture
  smoke   gate, then one depth (d4, fanout 1) with reduced counts; < 2 min
  sweep   gate, then the E1 depth sweep: Biscuit, OPA local, OPA +5 ms and
          +20 ms through toxiproxy (harness defaults: depths 1-10, fanout 1)
  all     sweep, then the harness's table generator (crossplatform.tex)

Mount a writable directory at /out; see the handout for the full command.
EOF
}

case "$CMD" in
  gate|smoke|sweep|all) ;;
  help|-h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

# Every run uses the harness defaults: drop any PCT_* / port override passed in.
while read -r v; do unset "$v"; done < <(compgen -e | grep -E '^(PCT_|OPA_|PROXY|TOXIPROXY_URL$)' || true)

# /out must be a bind mount or volume, writable by this user.
if ! awk '$5 == "/out" { found = 1 } END { exit !found }' /proc/self/mountinfo; then
  say "/out is not mounted; add -v \"\$PWD/lab-c-out:/out\"" >&2
  exit 2
fi
if ! ( : > /out/.lab-c-write-test ) 2>/dev/null; then
  say "/out is not writable by uid $(id -u); add --user \"\$(id -u):\$(id -g)\"" >&2
  exit 2
fi
rm -f /out/.lab-c-write-test
# Harness scratch (CSVs, OPA's per-request log: ~300 MB for a full sweep).
if ! RAW="$(mktemp -d /tmp/lab-c.XXXXXX 2>/dev/null)"; then
  say "/tmp is not writable; add --tmpfs /tmp:rw,nosuid,nodev,size=1g" >&2
  exit 2
fi
export PCT_HOST=lab-c
export PCT_SANDBOX=true
export PCT_DELAY_METHOD=toxiproxy
PCT_CPU="$(python3 "$L/platform_info.py" cpu)"
export PCT_CPU

say "image cj-lab-c:ws2026, harness v2-fi-revision-2026-08-11 (06db5fc)"
say "uname -m: $(uname -m)"
say "image arch: $(cat "$L/image-arch")"
say "subcommand: $CMD"

run_gate() {
  mkdir -p "$RAW/gate"
  say "gate: Biscuit and OPA verdicts on all seeded fixtures"
  if e1-biscuit verify "$H/workloads" "$RAW/gate/biscuit-verdicts.json" \
     && PCT_WORKLOADS="$H/workloads" PCT_RESULTS="$RAW/gate" "$H/scripts/opa_e1.sh" verdicts \
     && python3 "$H/python/verify_gate_2way.py" "$H/workloads" "$RAW/gate"; then
    say "GATE PASS"
  else
    echo "GATE FAIL"
    say "no timings written"
    exit 3
  fi
}

require_native() {
  if ! python3 "$L/platform_info.py" check-native; then
    say "no timings written"
    exit 4
  fi
}

run_sweep() { # workloads_dir
  mkdir -p "$RAW/sweep"
  e1-biscuit bench "$1" "$RAW/sweep/e1-biscuit.csv"
  PCT_WORKLOADS="$1" PCT_RESULTS="$RAW/sweep" "$H/scripts/opa_e1.sh" bench
}

finish() {
  local dest="/out/$CMD"
  mkdir -p "$dest"
  rm -f "$dest"/{platform.json,biscuit-verdicts.json,opa-verdicts.json,e1-biscuit.csv,e1-opa.csv,crossplatform.tex}
  python3 "$L/platform_info.py" json "$RAW/platform.json"
  python3 "$L/sanitize.py" "$RAW" "$dest" "$RAW/platform.json"
  say "wrote $(cd "$dest" && ls | sort | tr '\n' ' ')to $dest"
}

run_gate

case "$CMD" in
  gate)
    ;;
  smoke)
    require_native
    say "smoke: depth 4, fanout 1, reduced counts (not comparable to a sweep)"
    PCT_MAX_PER_CONFIG=10000 PCT_OPA_LOCAL=2000 PCT_OPA_DELAY=100 run_sweep "$H/workloads-smoke"
    ;;
  sweep|all)
    require_native
    say "sweep: depths 1 2 4 6 8 10, fanout 1, harness default counts"
    run_sweep "$H/workloads-f1"
    if [[ "$CMD" == all ]]; then
      python3 "$H/python/mkcrossplatform.py" "$H/reference" "$RAW/sweep" "$RAW/crossplatform.tex"
    fi
    ;;
esac

finish
say "scratch used: $(du -sm /tmp | cut -f1) MB of tmpfs"
say "elapsed ${SECONDS}s"
[[ "$CMD" == smoke ]] && say "SMOKE OK"
exit 0
