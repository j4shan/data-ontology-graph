from pathlib import Path

from data_ontology_graph.builder.intermediary import (
    IntermediaryValidationError,
    IntermediaryValidationReport,
    load_intermediary_directory,
    load_intermediary_yaml,
    validate_intermediary_yaml,
)
from data_ontology_graph.builder.report import ExplicitBuildReport
from data_ontology_graph.builder.validate import Contradiction, detect_contradictions
from data_ontology_graph.model.intermediary import IntermediaryDefinition
from data_ontology_graph.model.relationship import JoinRelationship
from data_ontology_graph.model.snapshot import GraphSnapshot, now_utc, schema_fingerprint


def build_snapshot_from_definition(
    definition: IntermediaryDefinition,
) -> tuple[GraphSnapshot, ExplicitBuildReport, list[Contradiction]]:
    """Build only the explicit graph contained in a validated intermediary."""
    edges = [
        JoinRelationship(
            edge_id=edge.canonical_edge_id(),
            endpoint_a=edge.endpoint_a.to_endpoint(),
            endpoint_b=edge.endpoint_b.to_endpoint(),
            a_to_b=edge.a_to_b.to_runtime(),
            b_to_a=edge.b_to_a.to_runtime(),
        )
        for edge in definition.edges
    ]
    snapshot = GraphSnapshot(
        built_at=now_utc(),
        schema_fingerprint=schema_fingerprint(),
        logical_identities=definition.runtime_identities(),
        nodes=[node.to_runtime() for node in definition.nodes],
        edges=edges,
    )
    report = ExplicitBuildReport(
        node_count=len(snapshot.nodes),
        edge_count=len(snapshot.edges),
    )
    return snapshot, report, []


def build_snapshot_from_yaml(
    path: Path | str,
) -> tuple[GraphSnapshot, ExplicitBuildReport, list[Contradiction]]:
    """Validate a complete YAML intermediary before building its explicit graph."""
    return build_snapshot_from_definition(load_intermediary_yaml(path))


__all__ = [
    "Contradiction",
    "ExplicitBuildReport",
    "IntermediaryValidationError",
    "IntermediaryValidationReport",
    "build_snapshot_from_definition",
    "build_snapshot_from_yaml",
    "detect_contradictions",
    "load_intermediary_yaml",
    "load_intermediary_directory",
    "validate_intermediary_yaml",
]
