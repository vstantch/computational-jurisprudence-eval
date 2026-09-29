#!/usr/local/bin/python3
"""Loopback-only stand-in for the curl calls scripts/opa_e1.sh makes.

opa_e1.sh uses curl for OPA health checks and the toxiproxy REST API, all on
127.0.0.1. This covers exactly those flags (-s -S -f -L -o -X -d) with the
standard library, so the image installs no packages beyond its base, and it
refuses any host other than loopback. It is never on a timed path.
"""

import http.client
import sys
from urllib.parse import urlsplit

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def main(argv: list[str]) -> int:
    method, data, out, fail, url = None, None, None, False, None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("-X"):
            method = a[2:] or argv[i + 1]
            i += 1 if a[2:] else 2
            continue
        if a in ("-d", "--data"):
            data, i = argv[i + 1].encode(), i + 2
            continue
        if a == "-o":
            out, i = argv[i + 1], i + 2
            continue
        if a.startswith("-") and not a.startswith("--") and set(a[1:]) <= set("sSfL"):
            fail = fail or "f" in a
            i += 1
            continue
        if a.startswith("-"):
            print(f"curl (lab-c shim): unsupported option {a}", file=sys.stderr)
            return 2
        url, i = a, i + 1
    parts = urlsplit(url or "")
    if parts.scheme != "http" or parts.hostname not in LOOPBACK:
        print(f"curl (lab-c shim): refusing non-loopback URL {url!r}", file=sys.stderr)
        return 7
    method = method or ("POST" if data is not None else "GET")
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    headers = {"Content-Type": "application/x-www-form-urlencoded"} if data is not None else {}
    try:
        conn = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=10)
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        body = resp.read()
    except OSError:
        return 7
    if fail and resp.status >= 400:
        return 22
    if out:
        with open(out, "wb") as f:
            f.write(body)
    else:
        sys.stdout.buffer.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
