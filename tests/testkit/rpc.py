"""JSON-RPC helpers: in-process dispatch and Unix-socket servers for tests."""
import asyncio
import json
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from data_ontology_graph.rpc.protocol import JsonRpcDispatcher
from data_ontology_graph.rpc.server import GraphUnixServer
from data_ontology_graph.service.read import GraphReadService


def dispatch(target: GraphReadService | JsonRpcDispatcher, method: str, params: dict | None = None,
             request_id: int = 1) -> dict:
    """One JSON-RPC request through the dispatcher, as the server would hand it over."""
    dispatcher = target if isinstance(target, JsonRpcDispatcher) else JsonRpcDispatcher(target)
    return dispatcher.dispatch(
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
    )


@contextmanager
def temporary_socket_path() -> Iterator[Path]:
    """A socket path under /tmp: macOS limits AF_UNIX paths to roughly 104 bytes."""
    with tempfile.TemporaryDirectory(prefix="dog-", dir="/tmp") as directory:
        yield Path(directory) / "graph.sock"


@contextmanager
def serve_unix(service: GraphReadService, **server_options) -> Iterator[Path]:
    """Serve ``service`` on a Unix socket from a background event loop."""
    with temporary_socket_path() as path:
        server = GraphUnixServer(service, path, **server_options)
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            asyncio.run_coroutine_threadsafe(server.start(), loop).result(timeout=10)
            yield path
        finally:
            asyncio.run_coroutine_threadsafe(server.close(), loop).result(timeout=10)
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=10)
            loop.close()


async def rpc_call(path: Path, request_id: int, method: str, params: dict) -> dict:
    """One newline-delimited JSON-RPC exchange over a fresh connection."""
    reader, writer = await asyncio.open_unix_connection(path)
    request = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    writer.write(json.dumps(request).encode("utf-8") + b"\n")
    await writer.drain()
    response = json.loads(await reader.readline())
    writer.close()
    await writer.wait_closed()
    return response
