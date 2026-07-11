"""Tiny asyncio TCP delay proxy — the sandbox fallback for toxiproxy.

The plan asks for +5 ms / +20 ms injected network delay in front of the OPA PDP
via a toxiproxy sidecar, with the explicit instruction: "if toxiproxy download
fails in the sandbox, implement a tiny asyncio TCP delay proxy in python/ as
fallback and note it." This is that fallback.

It forwards TCP between a listen port and the upstream OPA port, sleeping
`delay_ms` on the REQUEST path (client -> upstream) of every relayed chunk. With
HTTP keep-alive each exercise is a fresh request chunk on the persistent
connection, so each decision pays ~+delay_ms — modelling a remote PDP honestly.
The response path is not delayed (one-way injection); the CSV `config` column
records which delay was in force. On the Mac mini the justfile uses toxiproxy
instead (documented in README); the measured shape is what matters here.

Usage: python delay_proxy.py <listen_port> <upstream_host> <upstream_port> <delay_ms>
"""

from __future__ import annotations

import asyncio
import sys


async def _pump(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                delay_s: float) -> None:
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            if delay_s > 0:
                await asyncio.sleep(delay_s)
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


def _make_handler(upstream_host: str, upstream_port: int, delay_s: float):
    async def handle(client_reader, client_writer):
        try:
            up_reader, up_writer = await asyncio.open_connection(
                upstream_host, upstream_port
            )
        except OSError:
            client_writer.close()
            return
        await asyncio.gather(
            _pump(client_reader, up_writer, delay_s),      # request path: +delay
            _pump(up_reader, client_writer, 0.0),          # response path: none
            return_exceptions=True,
        )
    return handle


async def _main() -> None:
    listen_port = int(sys.argv[1])
    upstream_host = sys.argv[2]
    upstream_port = int(sys.argv[3])
    delay_ms = float(sys.argv[4])
    server = await asyncio.start_server(
        _make_handler(upstream_host, upstream_port, delay_ms / 1000.0),
        "127.0.0.1",
        listen_port,
    )
    print(
        f"delay-proxy 127.0.0.1:{listen_port} -> "
        f"{upstream_host}:{upstream_port} (+{delay_ms}ms request path)",
        flush=True,
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(_main())
