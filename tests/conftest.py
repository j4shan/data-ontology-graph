import asyncio
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from data_ontology_graph.builder import build_snapshot_from_yaml
from data_ontology_graph.rpc.server import GraphUnixServer
from data_ontology_graph.service.read import GraphReadService


LENDING = Path(__file__).parent / "fixtures" / "lending" / "catalog.yaml"


@pytest.fixture
def lending_socket() -> Iterator[Path]:
    """Serve the lending snapshot on a Unix socket from a background event loop."""
    snapshot, _, _ = build_snapshot_from_yaml(LENDING)
    # macOS limits AF_UNIX paths to roughly 104 bytes, so the socket lives under /tmp.
    with tempfile.TemporaryDirectory(prefix="dog-", dir="/tmp") as directory:
        socket_path = Path(directory) / "graph.sock"
        server = GraphUnixServer(GraphReadService(snapshot), socket_path)
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            asyncio.run_coroutine_threadsafe(server.start(), loop).result(timeout=10)
            yield socket_path
        finally:
            asyncio.run_coroutine_threadsafe(server.close(), loop).result(timeout=10)
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=10)
            loop.close()
