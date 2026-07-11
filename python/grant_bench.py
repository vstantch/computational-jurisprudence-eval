"""E1 capability-grant@1 bench (the artifact under test, benched AS-IS).

Imports `presidio_x402.capability` from the shipped x402 tools tree and measures
the exercise-time cost of `verify_chain()` (Ed25519 per hop + hash-link +
attenuation) followed by `VerifiedGrantChain.check_payment()` (per-call cap,
endpoint prefix, validity window) — the same (url, amount, time) decision the
Biscuit and OPA paths make. grant@1 is a *Python* artifact and the paper says so;
we do not reimplement it, we time it.

Methodology (plan §1 E1 metrics; plan §4 "GC pinned off during timing windows"):
  * micro-USD integer amounts everywhere (grant@1 accepts int micro-USD natively)
    — no float enters the wire form or the comparison;
  * per-exercise timing with `perf_counter_ns`, a warmup pass, and `gc.disable()`
    across the measured window;
  * token size = canonical JSON bytes of the full signed chain, vs depth.

Two modes:
  bench    <workloads_dir> <out_csv>   -> latency/throughput/token CSV
  verdicts <workloads_dir> <out_json>  -> ALLOW/DENY over the gate subset

INTEGRITY: only measured values are written; a run reports exactly what it timed.
"""

from __future__ import annotations

import gc
import json
import sys
import time
from datetime import datetime, timezone

import common

common.x402_src_on_path()
from presidio_x402.capability import (  # noqa: E402
    CapabilityError,
    delegate_grant,
    issue_grant,
    verify_chain,
)
from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: E402

OPERATOR_ID = "acme-operator"


def _keypair() -> tuple[str, str]:
    sk = ed25519.Ed25519PrivateKey.generate()
    return sk.private_bytes_raw().hex(), sk.public_key().public_bytes_raw().hex()


def _parse_at(rfc: str) -> datetime:
    return datetime.fromisoformat(rfc.replace("Z", "+00:00")).astimezone(timezone.utc)


def _caveats(hop: dict) -> dict:
    # micro-USD integers -> grant@1 interprets int as micro-USD; timestamps and
    # prefixes pass through verbatim. Semantics identical to the Biscuit checks
    # and the Rego input document.
    return {
        "max_per_call_usd": hop["max_per_call_micro"],
        "daily_limit_usd": hop["daily_limit_micro"],
        "window_seconds": hop["window_seconds"],
        "valid_from": hop["valid_from"],
        "valid_until": hop["valid_until"],
        "endpoint_prefixes": hop["endpoint_prefixes"],
    }


def build_chain(fx: dict) -> tuple[list[dict], dict]:
    """Build one signed, attenuating chain from a fixture's hop schedule. All
    fanout leaves are structurally identical (same narrowing), so one
    representative chain gives the correct per-exercise verify cost; fanout
    shapes throughput, not per-op latency."""
    hops = fx["chains"][0]["hops"]
    issued_at = _parse_at(fx["now_rfc3339"])
    op_priv, op_pub = _keypair()
    trust = {OPERATOR_ID: {"alg": "ed25519", "public_key": op_pub}}
    hop_keys = [_keypair() for _ in hops]

    root = issue_grant(
        subject="agent-0",
        issuer=OPERATOR_ID,
        issuer_private_key=op_priv,
        subject_public_key=hop_keys[0][1],
        caveats=_caveats(hops[0]),
        issued_at=issued_at,
    )
    chain = [root]
    prev_priv = hop_keys[0][0]
    for i in range(1, len(hops)):
        child = delegate_grant(
            chain[-1],
            parent_private_key=prev_priv,
            caveats=_caveats(hops[i]),
            subject=f"agent-{i}",
            subject_public_key=hop_keys[i][1],
            issued_at=issued_at,
        )
        chain.append(child)
        prev_priv = hop_keys[i][0]
    return chain, trust


def verdict(chain: list[dict], trust: dict, e: dict) -> bool:
    """True iff grant@1 ALLOWS this exercise (verify_chain + check_payment)."""
    at = _parse_at(e["at"])
    try:
        vc = verify_chain(chain, trust, at=at)
        vc.check_payment(
            resource_url=e["resource_url"],
            amount_usd=e["amount_micro"],  # int micro-USD
            at=at,
        )
        return True
    except CapabilityError:
        return False


def run_bench(workloads: str, out_csv: str) -> None:
    stamp = common.platform_stamp()
    rows = [common.CSV_HEADER]
    for path in common.fixture_paths(workloads):
        fx = common.load_fixture(path)
        chain, trust = build_chain(fx)
        token_bytes = len(
            json.dumps(chain, separators=(",", ":"), ensure_ascii=False).encode()
        )
        allow = [e for e in fx["exercises"] if e["expect"] == "allow"]

        # Warmup (also asserts the happy path really allows).
        for e in allow[:200]:
            if not verdict(chain, trust, e):
                print(
                    f"WARNING: allow exercise {e['id']} denied in {path} (bug!)",
                    file=sys.stderr,
                )

        nanos: list[int] = []
        gc.disable()
        try:
            for e in allow:
                at = _parse_at(e["at"])
                url = e["resource_url"]
                amt = e["amount_micro"]
                t0 = time.perf_counter_ns()
                try:
                    vc = verify_chain(chain, trust, at=at)
                    vc.check_payment(resource_url=url, amount_usd=amt, at=at)
                except CapabilityError:
                    pass
                nanos.append(time.perf_counter_ns() - t0)
        finally:
            gc.enable()

        nanos.sort()
        n = len(nanos)
        total_s = sum(nanos) / 1e9
        mean = sum(nanos) // n if n else 0
        thr = n / total_s if total_s > 0 else 0.0
        rows.append(
            common.csv_row(
                stamp, "grant1", "na", fx["depth"], fx["fanout"], n,
                common.percentile_ns(nanos, 50),
                common.percentile_ns(nanos, 95),
                common.percentile_ns(nanos, 99),
                mean, thr, token_bytes,
            )
        )
        print(
            f"grant1 d={fx['depth']} f={fx['fanout']} n={n} "
            f"p50={common.percentile_ns(nanos,50)}ns "
            f"p99={common.percentile_ns(nanos,99)}ns token={token_bytes}B"
        )

    import os
    os.makedirs(os.path.dirname(out_csv) or ".", exist_ok=True)
    with open(out_csv, "w") as f:
        f.write("\n".join(rows) + "\n")
    print(f"wrote {out_csv}")


def run_verdicts(workloads: str, out_json: str) -> None:
    top = {}
    for path in common.fixture_paths(workloads):
        fx = common.load_fixture(path)
        chain, trust = build_chain(fx)
        per = {str(e["id"]): verdict(chain, trust, e) for e in common.gate_exercises(fx)}
        top[f"d{fx['depth']}_f{fx['fanout']}"] = per
    import os
    os.makedirs(os.path.dirname(out_json) or ".", exist_ok=True)
    with open(out_json, "w") as f:
        json.dump(top, f, indent=2)
    print(f"wrote grant@1 verdicts to {out_json}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "bench"
    wl = sys.argv[2] if len(sys.argv) > 2 else "workloads"
    if mode == "bench":
        out = sys.argv[3] if len(sys.argv) > 3 else "results/e1-grant.csv"
        run_bench(wl, out)
    elif mode == "verdicts":
        out = sys.argv[3] if len(sys.argv) > 3 else "results/grant-verdicts.json"
        run_verdicts(wl, out)
    else:
        print(f"unknown mode {mode!r}", file=sys.stderr)
        sys.exit(2)
