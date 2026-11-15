"""Shared paths and catalog builds for the unit tests."""
from pathlib import Path

from data_ontology_graph.builder import build_snapshot_from_yaml
from data_ontology_graph.model.snapshot import GraphSnapshot
from data_ontology_graph.service.read import GraphReadService

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
LENDING = FIXTURES / "lending" / "catalog.yaml"
OPEN_ACCESSOR = FIXTURES / "open_accessor" / "catalog.yaml"
STATED = FIXTURES / "stated_relationships" / "catalog.yaml"
SCHEMAS = ROOT / "resources" / "schema"
VALID_EXAMPLE = SCHEMAS / "examples" / "intermediary-valid.yaml"
INVALID_EXAMPLE = SCHEMAS / "examples" / "intermediary-invalid.yaml"


def snapshot_of(catalog: Path = LENDING) -> GraphSnapshot:
    """A fresh snapshot built from a fixture catalog; callers may mutate it."""
    return build_snapshot_from_yaml(catalog)[0]


def service_of(catalog: Path = LENDING) -> GraphReadService:
    """A read service over a fresh build of a fixture catalog."""
    return GraphReadService(snapshot_of(catalog))
