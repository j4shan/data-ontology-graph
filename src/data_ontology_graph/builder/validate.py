from collections import defaultdict

from pydantic import BaseModel

from data_ontology_graph.model.relationship import JoinRelationship


class Contradiction(BaseModel):
    source_node_id: str
    source_columns: tuple[str, ...]
    target_node_id: str
    target_column_sets: list[tuple[str, ...]]
    edge_ids: list[str]


def detect_contradictions(edges: list[JoinRelationship]) -> list[Contradiction]:
    groups: dict[tuple[str, tuple[str, ...], str], list[JoinRelationship]] = defaultdict(list)
    for edge in edges:
        for source, target in (
            (edge.endpoint_a, edge.endpoint_b),
            (edge.endpoint_b, edge.endpoint_a),
        ):
            key = (source.node_id, tuple(source.dataset_columns), target.node_id)
            groups[key].append(edge)
    findings: list[Contradiction] = []
    for (source_id, source_cols, target_id), group in groups.items():
        targets = {tuple(edge.opposite(source_id).dataset_columns) for edge in group}
        if len(targets) > 1:
            findings.append(
                Contradiction(
                    source_node_id=source_id,
                    source_columns=source_cols,
                    target_node_id=target_id,
                    target_column_sets=sorted(targets),
                    edge_ids=sorted({edge.edge_id for edge in group}),
                )
            )
    return findings
