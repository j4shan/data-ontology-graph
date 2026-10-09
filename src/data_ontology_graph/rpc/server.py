from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import stat
from pathlib import Path
from threading import Event
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
    def __init__(
        self, service: GraphReadService, socket_path: Path,
        *, max_concurrent_navigation: int = 2,
    ) -> None:
        if max_concurrent_navigation < 1:
            raise ValueError("max_concurrent_navigation must be positive")
        self.dispatcher = JsonRpcDispatcher(service)
        self.socket_path = Path(socket_path)
        self._server: asyncio.Server | None = None
        self._socket_identity: tuple[int, int] | None = None
        self._navigation_slots = asyncio.Semaphore(max_concurrent_navigation)
        self._clients: set[asyncio.Task] = set()

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
        server, self._server = self._server, None
        if server is not None:
            server.close()
        clients = tuple(self._clients)
        for task in clients:
            task.cancel()
        if clients:
            await asyncio.gather(*clients, return_exceptions=True)
        if server is not None:
            await server.wait_closed()
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
        task = asyncio.current_task()
        assert task is not None
        self._clients.add(task)
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
                    response = await self._dispatch_payload(payload)
                if response is not None:
                    writer.write(
                        json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n"
                    )
                    await writer.drain()
        finally:
            self._clients.discard(task)
            writer.close()
            await writer.wait_closed()

    async def _dispatch_payload(self, payload: object) -> object | None:
        if not isinstance(payload, list):
            return await self._dispatch_one(payload)
        if not payload:
            return error_response(None, INVALID_REQUEST, "Invalid Request")
        # Process batch elements sequentially to avoid an unbounded task fan-out.
        return [await self._dispatch_one(item) for item in payload]

    async def _dispatch_one(self, payload: object) -> object:
        navigation = isinstance(payload, dict) and payload.get("method") in {
            "graph.find_paths", "graph.expand_subgraph", "graph.find_connecting_subgraph",
        }
        if navigation:
            async with self._navigation_slots:
                return await self._dispatch_worker(payload)
        return await self._dispatch_worker(payload)

    async def _dispatch_worker(self, payload: object) -> object:
        cancel_event = Event()
        worker = asyncio.create_task(
            asyncio.to_thread(self.dispatcher.dispatch, payload, cancel_event)
        )
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancel_event.set()
            # Retain the concurrency slot until the worker actually stops.
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue
            raise


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


def load_service(
    snapshot_directory: Path, *, max_connecting_datasets: int = 16,
) -> GraphReadService:
    snapshot = SnapshotStore(snapshot_directory.parent).load(snapshot_directory)
    return GraphReadService(snapshot, max_connecting_datasets=max_connecting_datasets)


async def _run(
    snapshot_directory: Path, socket_path: Path,
    max_connecting_datasets: int = 16, max_concurrent_navigation: int = 2,
) -> None:
    server = GraphUnixServer(
        load_service(snapshot_directory, max_connecting_datasets=max_connecting_datasets),
        socket_path, max_concurrent_navigation=max_concurrent_navigation,
    )
    await server.start()
    try:
        await server.serve_forever()
    finally:
        await server.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local ontology graph service")
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--max-connecting-datasets", type=int, default=16)
    parser.add_argument("--max-concurrent-navigation", type=int, default=2)
    args = parser.parse_args()
    try:
        asyncio.run(_run(args.snapshot_dir, args.socket, args.max_connecting_datasets,
                         args.max_concurrent_navigation))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
