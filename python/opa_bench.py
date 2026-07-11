"""E1 OPA centralized-PDP baseline bench.

Sends one policy-decision request per exercise to a running OPA server (native
binary serving policies/capability.rego over localhost HTTP), reusing a
keep-alive connection, and times the round trip. This is the "pays a round-trip
and an availability dependency" baseline from paper §3.3.

`config` column ∈ {local, 5ms, 20ms}: `local` hits OPA directly; the delay
configs hit it through the injected-latency proxy (toxiproxy on the Mac,
python/delay_proxy.py in the sandbox). The input document per exercise is the
SAME canonical chain + exercise the Biscuit and grant@1 paths consume, so the
decision is identical; only the transport differs.

Modes:
  bench    <workloads_dir> <out_csv> <config_label> [max_per_config]
  verdicts <workloads_dir> <out_json>

Env: OPA_HOST (default 127.0.0.1), OPA_PORT (default 8181).
INTEGRITY: only measured round trips are written.
"""

from __future__ import annotations

import http.client
import json
import os
import sys
import time

import common

OPA_HOST = os.environ.get("OPA_HOST", "127.0.0.1")
OPA_PORT = int(os.environ.get("OPA_PORT", "8181"))
DECISION_PATH = "/v1/data/pct/allow"


def _input_doc(fx: dict, e: dict) -> dict:
    return {
        "input": {
            "jurisdiction": fx["jurisdiction"],
            "chain": fx["chains"][0]["hops"],
            "exercise": {
                "resource_url": e["resource_url"],
                "amount_micro": e["amount_micro"],
                "at": e["at"],
                "jurisdiction": e["jurisdiction"],
            },
        }
    }


class OpaClient:
    """Keep-alive HTTP client for the OPA decision endpoint."""

    def __init__(self, host: str, port: int):
        self.host, self.port = host, port
        self.conn = http.client.HTTPConnection(host, port, timeout=30)

    def decide(self, doc: dict) -> bool:
        body = json.dumps(doc).encode()
        for attempt in range(2):
            try:
                self.conn.request(
                    "POST", DECISION_PATH, body,
                    {"Content-Type": "application/json", "Connection": "keep-alive"},
                )
                resp = self.conn.getresponse()
                data = resp.read()
                out = json.loads(data)
                return bool(out.get("result", False))
            except (http.client.HTTPException, ConnectionError, OSError):
                # Reconnect once (keep-alive can drop); fail closed after.
                self.conn.close()
                self.conn = http.client.HTTPConnection(self.host, self.port, timeout=30)
                if attempt == 1:
                    raise
        return False


def run_bench(workloads: str, out_csv: str, config_label: str,
              max_per_config: int | None) -> None:
    stamp = common.platform_stamp()
    client = OpaClient(OPA_HOST, OPA_PORT)
    rows = [common.CSV_HEADER]
    for path in common.fixture_paths(workloads):
        fx = common.load_fixture(path)
        allow = [e for e in fx["exercises"] if e["expect"] == "allow"]
        if max_per_config is not None:
            allow = allow[:max_per_config]

        # Representative input-doc size (message on the wire), vs depth.
        token_bytes = len(json.dumps(_input_doc(fx, allow[0])["input"]).encode())

        # Warmup (count configurable so high-delay configs stay affordable).
        warmup = int(os.environ.get("PCT_OPA_WARMUP", "50"))
        for e in allow[:warmup]:
            client.decide(_input_doc(fx, e))

        nanos: list[int] = []
        for e in allow:
            doc = _input_doc(fx, e)
            t0 = time.perf_counter_ns()
            client.decide(doc)
            nanos.append(time.perf_counter_ns() - t0)

        nanos.sort()
        n = len(nanos)
        total_s = sum(nanos) / 1e9
        mean = sum(nanos) // n if n else 0
        thr = n / total_s if total_s > 0 else 0.0
        rows.append(
            common.csv_row(
                stamp, "opa", config_label, fx["depth"], fx["fanout"], n,
                common.percentile_ns(nanos, 50),
                common.percentile_ns(nanos, 95),
                common.percentile_ns(nanos, 99),
                mean, thr, token_bytes,
            )
        )
        print(
            f"opa[{config_label}] d={fx['depth']} f={fx['fanout']} n={n} "
            f"p50={common.percentile_ns(nanos,50)}ns "
            f"p99={common.percentile_ns(nanos,99)}ns input={token_bytes}B"
        )

    os.makedirs(os.path.dirname(out_csv) or ".", exist_ok=True)
    # Append if the CSV already exists (so local/5ms/20ms accumulate into one file).
    header_needed = not os.path.exists(out_csv)
    with open(out_csv, "a") as f:
        if header_needed:
            f.write(rows[0] + "\n")
        f.write("\n".join(rows[1:]) + "\n")
    print(f"wrote {out_csv} (config={config_label})")


def run_verdicts(workloads: str, out_json: str) -> None:
    client = OpaClient(OPA_HOST, OPA_PORT)
    top = {}
    for path in common.fixture_paths(workloads):
        fx = common.load_fixture(path)
        per = {
            str(e["id"]): client.decide(_input_doc(fx, e))
            for e in common.gate_exercises(fx)
        }
        top[f"d{fx['depth']}_f{fx['fanout']}"] = per
    os.makedirs(os.path.dirname(out_json) or ".", exist_ok=True)
    with open(out_json, "w") as f:
        json.dump(top, f, indent=2)
    print(f"wrote OPA verdicts to {out_json}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "bench"
    wl = sys.argv[2] if len(sys.argv) > 2 else "workloads"
    if mode == "bench":
        out = sys.argv[3] if len(sys.argv) > 3 else "results/e1-opa.csv"
        label = sys.argv[4] if len(sys.argv) > 4 else "local"
        cap = int(sys.argv[5]) if len(sys.argv) > 5 else None
        run_bench(wl, out, label, cap)
    elif mode == "verdicts":
        out = sys.argv[3] if len(sys.argv) > 3 else "results/opa-verdicts.json"
        run_verdicts(wl, out)
    else:
        print(f"unknown mode {mode!r}", file=sys.stderr)
        sys.exit(2)
