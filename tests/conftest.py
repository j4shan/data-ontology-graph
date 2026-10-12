import asyncio
import hashlib
import shutil
import sqlite3
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from data_ontology_graph.builder import build_snapshot_from_yaml
from data_ontology_graph.rpc.server import GraphUnixServer
from data_ontology_graph.service.read import GraphReadService


MINIBANK = Path(__file__).parent / "fixtures" / "minibank"
LENDING = Path(__file__).parent / "fixtures" / "lending" / "catalog.yaml"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_critic_tree(root: Path, catalog: str = "minibank") -> Path:
    """Build a Critic-style source tree for the minibank fixture under ``root``."""
    data = root / "resources" / "data"
    catalog_dir = data / "dev_databases" / catalog
    (catalog_dir / "database_description").mkdir(parents=True)
    with sqlite3.connect(catalog_dir / f"{catalog}.sqlite") as connection:
        connection.executescript((MINIBANK / "schema.sql").read_text(encoding="utf-8"))
    connection.close()
    for csv_file in sorted((MINIBANK / "database_description").glob("*.csv")):
        shutil.copy(csv_file, catalog_dir / "database_description" / csv_file.name)
    lines = [
        f"{_sha256(path)}  {path.relative_to(data).as_posix()}"
        for path in sorted(catalog_dir.rglob("*"))
        if path.is_file()
    ]
    (data / "SOURCES.md").write_text(
        "# Test data sources\n\n### `" + catalog + "` hashes\n\n```\n" + "\n".join(lines) + "\n```\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def critic_root(tmp_path: Path) -> Path:
    return build_critic_tree(tmp_path / "critic")


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
