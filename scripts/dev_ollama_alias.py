"""Tiny TCP forwarder so a single-daemon Ollama dev box can satisfy both
`ollama_drone_endpoint` (11434) and `ollama_egs_endpoint` (11435) from
`shared/config.yaml` without spinning up a second `ollama serve`.

Why this exists. The integration contracts pin two endpoints, modeling the
real-world deployment where the per-drone agent and the EGS coordinator each
own their own daemon (potentially on different hardware). On a single-laptop
dev box (Hazim's WSL2 setup, May 2026) running two Ollama daemons against the
same blob store is awkward: the system-managed daemon at /usr/share/ollama
runs as the `ollama` user with 0700-mode model dirs, so a second user-mode
daemon has nothing to read. Rather than mutate `shared/config.yaml` away from
the contract or copy 17 GB of blobs around, we just listen on 11435 and
splice every byte to 127.0.0.1:11434.

Usage:
    python3 scripts/dev_ollama_alias.py &
    # then run the resilience scenario as documented in
    # docs/sim-resilience-run-notes.md.

Limitations. Pure TCP-level forwarder — no HTTP awareness, no load balancing,
no TLS. This is a Phase D / demo-time helper, not a production component.
Tests don't cover it; the resilience-run notes document its role.
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading


def _splice(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(8192)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def _handle_client(client: socket.socket, upstream_host: str, upstream_port: int) -> None:
    try:
        upstream = socket.create_connection((upstream_host, upstream_port))
    except OSError as exc:
        print(f"[ollama-alias] upstream connect failed: {exc}", flush=True)
        client.close()
        return
    threading.Thread(target=_splice, args=(client, upstream), daemon=True).start()
    threading.Thread(target=_splice, args=(upstream, client), daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--listen-host", default="127.0.0.1")
    p.add_argument("--listen-port", type=int, default=11435)
    p.add_argument("--upstream-host", default="127.0.0.1")
    p.add_argument("--upstream-port", type=int, default=11434)
    args = p.parse_args(argv)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.listen_host, args.listen_port))
    server.listen(16)
    print(
        f"[ollama-alias] listening on {args.listen_host}:{args.listen_port} -> "
        f"{args.upstream_host}:{args.upstream_port}",
        flush=True,
    )
    try:
        while True:
            client, _ = server.accept()
            threading.Thread(
                target=_handle_client,
                args=(client, args.upstream_host, args.upstream_port),
                daemon=True,
            ).start()
    except KeyboardInterrupt:
        print("[ollama-alias] stopped via SIGINT", flush=True)
        return 0


if __name__ == "__main__":
    sys.exit(main())
