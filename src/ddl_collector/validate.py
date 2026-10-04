"""Validate collector output through the graph builder's own gate."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from data_ontology_graph.builder import build_snapshot_from_definition
from data_ontology_graph.builder.intermediary import (
    ValidationFinding,
    load_intermediary_yaml,
    validate_intermediary_yaml,
)
from ddl_collector.draft import DraftFinding
from ddl_collector.survey import UNRESOLVED, Decision


class CollectorReport(BaseModel):
    valid: bool
    findings: list[ValidationFinding] = Field(default_factory=list)
    draft_findings: list[DraftFinding] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)
    node_count: int = 0
    edge_count: int = 0
    identity_count: int = 0
    decisions: dict[str, int] = Field(default_factory=dict)
    unresolved: list[str] = Field(default_factory=list)

    @property
    def publishable(self) -> bool:
        return self.valid and not self.draft_findings and not self.unresolved


def validate_catalog_directory(
    yaml_dir: Path,
    decisions: list[Decision] | None = None,
    draft_findings: list[DraftFinding] | None = None,
) -> CollectorReport:
    """Validate a ``yaml/`` directory whose manifest sits beside it, as the builder would."""
    decisions = decisions or []
    counts: dict[str, int] = {}
    for decision in decisions:
        counts[decision.status] = counts.get(decision.status, 0) + 1
    unresolved = sorted(d.decision_id for d in decisions if d.status in UNRESOLVED)
    common = {
        "draft_findings": draft_findings or [],
        "decisions": dict(sorted(counts.items())),
        "unresolved": unresolved,
    }
    validation = validate_intermediary_yaml(yaml_dir)
    if not validation.valid:
        return CollectorReport(valid=False, findings=validation.findings, **common)
    definition = load_intermediary_yaml(yaml_dir)
    snapshot, build_report, _ = build_snapshot_from_definition(definition)
    return CollectorReport(
        valid=True,
        unknown_fields=build_report.unknown_fields,
        node_count=build_report.node_count,
        edge_count=build_report.edge_count,
        identity_count=len(snapshot.logical_identities),
        **common,
    )
