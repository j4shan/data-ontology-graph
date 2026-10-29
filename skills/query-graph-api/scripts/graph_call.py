#!/usr/bin/env python3
"""Send one JSON-RPC 2.0 request to the Data Ontology Graph service over its Unix-domain socket.

Standard library only. `query.py` and `service.py` use this module; it has no command line.

The socket comes from $DOG_SOCKET, else the service home's `graph.sock`; the home is $DOG_HOME
or ~/.data-ontology-graph. The client changes into the socket's directory and connects by
basename, so socket paths longer than the platform sun_path limit still work.
"""
from __future__ import annotations

import json
import os
import socket
from pathlib import Path

DEFAULT_HOME = "~/.data-ontology-graph"


def service_home() -> Path:
    """The private per-user service home, shared with the graph service."""
    return Path(os.environ.get("DOG_HOME") or DEFAULT_HOME).expanduser()


def default_socket() -> Path:
    override = os.environ.get("DOG_SOCKET")
    return Path(override).expanduser() if override else service_home() / "graph.sock"


def call(socket_path: Path, method: str, params: dict) -> dict:
    request = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    cwd = os.getcwd()
    os.chdir(socket_path.parent)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.connect(socket_path.name)
            conn.sendall(json.dumps(request).encode() + b"\n")
            buf = b""
            while b"\n" not in buf:
                chunk = conn.recv(65536)
                if not chunk:
                    raise ConnectionError("service closed the connection")
                buf += chunk
    finally:
        os.chdir(cwd)
    return json.loads(buf.split(b"\n", 1)[0])
