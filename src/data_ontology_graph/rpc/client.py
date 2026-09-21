from __future__ import annotations

import argparse
import json
import socket
from pathlib import Path
from typing import Any


def call(socket_path: Path, method: str, params: dict[str, Any], request_id: object = 1) -> Any:
    request = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    }
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(str(socket_path))
        connection.sendall(json.dumps(request, separators=(",", ":")).encode("utf-8") + b"\n")
        response = _receive_line(connection)
    return json.loads(response)


def _receive_line(connection: socket.socket) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = connection.recv(64 * 1024)
        if not chunk:
            raise ConnectionError("graph service closed before returning a response")
        chunks.append(chunk)
        combined = b"".join(chunks)
        if b"\n" in combined:
            return combined.split(b"\n", 1)[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Call the local ontology graph service")
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("method")
    parser.add_argument("--params", default="{}", help="JSON object of method parameters")
    args = parser.parse_args()
    params = json.loads(args.params)
    if not isinstance(params, dict):
        parser.error("--params must decode to a JSON object")
    response = call(args.socket, args.method, params)
    print(json.dumps(response, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
