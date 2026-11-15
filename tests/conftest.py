from collections.abc import Iterator
from pathlib import Path

import pytest

from data_ontology_graph.model.snapshot import GraphSnapshot
from data_ontology_graph.service.read import GraphReadService
from testkit import OPEN_ACCESSOR, STATED, VALID_EXAMPLE, service_of, snapshot_of
from testkit.rpc import serve_unix


@pytest.fixture
def lending_snapshot() -> GraphSnapshot:
    """A fresh lending snapshot; tests may mutate it."""
    return snapshot_of()


@pytest.fixture
def lending_service() -> GraphReadService:
    return service_of()


@pytest.fixture
def example_service() -> GraphReadService:
    """The schema's valid example catalog, which holds unknown claims and placeholders."""
    return service_of(VALID_EXAMPLE)


@pytest.fixture
def open_accessor_service() -> GraphReadService:
    return service_of(OPEN_ACCESSOR)


@pytest.fixture(scope="module")
def stated_service() -> GraphReadService:
    """The stated-relationships catalog; read-only, so one build serves a module."""
    return service_of(STATED)


@pytest.fixture
def lending_socket() -> Iterator[Path]:
    """Serve the lending snapshot on a Unix socket from a background event loop."""
    with serve_unix(service_of()) as path:
        yield path
