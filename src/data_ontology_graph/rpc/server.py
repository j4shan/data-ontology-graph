from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import stat
from pathlib import Path
from typing import Any

from data_ontology_graph.rpc.protocol import (
    INVALID_REQUEST,
    PARSE_ERROR,
    JsonRpcDispatcher,
    error_response,
)
from data_ontology_graph.service.read import GraphReadService
from data_ontology_graph.store.snapshot_store import SnapshotStore


MAX_MESSAGE_BYTES = 16 * 1024 * 1024


class GraphUnixServer:
    def __init__(self, service: GraphReadService, socket_path: Path) -> None:
        self.dispatcher = JsonRpcDispatcher(service)
        self.socket_path = Path(socket_path)
        self._server: asyncio.Server | None = None
        self._socket_identity: tuple[int, int] | None = None

    async def start(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if len(os.fsencode(self.socket_path)) > 100:
            raise ValueError(
                "Unix-domain socket path must be at most 100 encoded bytes "
                f"for portable local use: {self.socket_path}"
            )
        _prepare_socket_path(self.socket_path)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.setblocking(False)
            listener.bind(str(self.socket_path))
            listener.listen(socket.SOMAXCONN)
            self._server = await asyncio.start_unix_server(
                self._handle_client,
                sock=listener,
                limit=MAX_MESSAGE_BYTES,
            )
        except Exception:
            listener.close()
            raise
        self.socket_path.chmod(0o600)
        details = self.socket_path.stat()
        self._socket_identity = (details.st_dev, details.st_ino)

    async def serve_forever(self) -> None:
        if self._server is None:
            await self.start()
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self.socket_path.exists():
            details = self.socket_path.stat()
            identity = (details.st_dev, details.st_ino)
            if stat.S_ISSOCK(details.st_mode) and identity == self._socket_identity:
                self.socket_path.unlink()
        self._socket_identity = None

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            while True:
                try:
                    line = await reader.readline()
                except ValueError:
                    writer.write(
                        json.dumps(
                            error_response(None, INVALID_REQUEST, "Message too large"),
                            separators=(",", ":"),
                        ).encode("utf-8")
                        + b"\n"
                    )
                    await writer.drain()
                    break
                if not line:
                    break
                try:
                    payload = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    response: object = error_response(None, PARSE_ERROR, "Parse error")
                else:
                    response = self._dispatch_payload(payload)
                if response is not None:
                    writer.write(
                        json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n"
                    )
                    await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    def _dispatch_payload(self, payload: object) -> object | None:
        if not isinstance(payload, list):
            return self.dispatcher.dispatch(payload)
        if not payload:
            return error_response(None, INVALID_REQUEST, "Invalid Request")
        return [self.dispatcher.dispatch(item) for item in payload]


def _prepare_socket_path(path: Path) -> None:
    if not path.exists():
        return
    details = path.stat()
    if not stat.S_ISSOCK(details.st_mode):
        raise RuntimeError(f"refusing to replace non-socket path: {path}")
    if details.st_uid != os.getuid():
        raise PermissionError(f"socket is not owned by the current user: {path}")

    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(0.2)
        probe.connect(str(path))
    except (ConnectionRefusedError, FileNotFoundError, TimeoutError):
        path.unlink()
    else:
        raise RuntimeError(f"graph service is already listening on {path}")
    finally:
        probe.close()


def load_service(snapshot_directory: Path) -> GraphReadService:
    snapshot = SnapshotStore(snapshot_directory.parent).load(snapshot_directory)
    return GraphReadService(snapshot)


async def _run(snapshot_directory: Path, socket_path: Path) -> None:
    server = GraphUnixServer(load_service(snapshot_directory), socket_path)
    await server.start()
    try:
        await server.serve_forever()
    finally:
        await server.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local ontology graph service")
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--socket", type=Path, required=True)
    args = parser.parse_args()
    try:
        asyncio.run(_run(args.snapshot_dir, args.socket))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
