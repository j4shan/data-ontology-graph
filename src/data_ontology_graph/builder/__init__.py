from pathlib import Path

from data_ontology_graph.builder.intermediary import (
    IntermediaryValidationError,
    IntermediaryValidationReport,
    intermediary_directory_json_schema,
    load_intermediary_directory,
    load_intermediary_yaml,
    validate_intermediary_yaml,
    write_intermediary_directory_json_schema,
)
from data_ontology_graph.builder.report import (
    ExplicitBuildReport,
    accessor_warnings,
    unknown_field_locations,
)
from data_ontology_graph.model.intermediary import IntermediaryDefinition
from data_ontology_graph.model.snapshot import GraphSnapshot, snapshot_version


def build_snapshot_from_definition(
    definition: IntermediaryDefinition,
) -> tuple[GraphSnapshot, ExplicitBuildReport]:
    """Build the graph of a validated intermediary, deriving its relationships."""
    nodes = [node.to_runtime() for node in definition.nodes]
    snapshot = GraphSnapshot(
        version=snapshot_version(),
        logical_identities=definition.runtime_identities(),
        nodes=nodes,
    )
    report = ExplicitBuildReport(
        node_count=len(snapshot.nodes),
        entity_definition_count=snapshot.memberships.entity_definition_count,
        unknown_fields=unknown_field_locations(definition),
        warnings=accessor_warnings(snapshot.nodes),
    )
    return snapshot, report


def build_snapshot_from_yaml(
    path: Path | str,
) -> tuple[GraphSnapshot, ExplicitBuildReport]:
    """Validate a complete YAML intermediary before building its explicit graph."""
    return build_snapshot_from_definition(load_intermediary_yaml(path))


__all__ = [
    "ExplicitBuildReport",
    "IntermediaryValidationError",
    "IntermediaryValidationReport",
    "accessor_warnings",
    "build_snapshot_from_definition",
    "build_snapshot_from_yaml",
    "intermediary_directory_json_schema",
    "load_intermediary_yaml",
    "load_intermediary_directory",
    "unknown_field_locations",
    "validate_intermediary_yaml",
    "write_intermediary_directory_json_schema",
]
