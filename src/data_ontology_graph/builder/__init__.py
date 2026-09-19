from data_ontology_graph.builder.ingest import apply_overlay, enrich_nodes
from data_ontology_graph.builder.infer import infer_relationships
from data_ontology_graph.builder.report import InferenceReport
from data_ontology_graph.builder.sqlite_catalog import ingest_sqlite, require_sqlite_version
from data_ontology_graph.builder.validate import Contradiction, detect_contradictions
from data_ontology_graph.model.relationship import JoinAnnotation
from data_ontology_graph.model.snapshot import GraphSnapshot, now_utc, schema_fingerprint


def build_snapshot(
    nodes,
    overlays=None,
    annotations: list[JoinAnnotation] | None = None,
) -> tuple[GraphSnapshot, InferenceReport, list[Contradiction]]:
    enriched = enrich_nodes(list(nodes), overlays)
    edges, report = infer_relationships(enriched)
    known = {edge.edge_id for edge in edges}
    kept = [item for item in (annotations or []) if item.edge_id in known]
    snapshot = GraphSnapshot(
        built_at=now_utc(),
        schema_fingerprint=schema_fingerprint(),
        nodes=enriched,
        edges=edges,
        annotations=kept,
    )
    return snapshot, report, detect_contradictions(edges)


__all__ = [
    "Contradiction",
    "InferenceReport",
    "apply_overlay",
    "build_snapshot",
    "detect_contradictions",
    "enrich_nodes",
    "infer_relationships",
    "ingest_sqlite",
    "require_sqlite_version",
]
