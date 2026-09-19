from itertools import combinations

from data_ontology_graph.model.dataset import DatasetNode, GrainComponent
from data_ontology_graph.model.enums import DatasetLayer, GrainProvenance


def apply_overlay(node: DatasetNode, overlay: dict) -> DatasetNode:
    payload = node.model_dump(mode="python")
    for field in (
        "table_role",
        "is_entity_universe",
        "description",
        "synonyms",
        "tags",
        "dataset_layer",
        "primary_key",
        "unique_keys",
        "filtered_unique_keys",
        "grain",
        "logical_entity_key",
        "primary_ref",
        "replica_node_ids",
    ):
        if field in overlay:
            payload[field] = overlay[field]
    column_overlays = {item["name"]: item for item in overlay.get("columns", [])}
    merged_columns = []
    for column in payload["columns"]:
        extra = column_overlays.get(column["name"], {})
        column.update({key: value for key, value in extra.items() if key != "name"})
        merged_columns.append(column)
    payload["columns"] = merged_columns
    if "data_source" in overlay:
        payload["data_source"] = overlay["data_source"]
    return DatasetNode.model_validate(payload)


def synthesize_grain(node: DatasetNode) -> DatasetNode:
    if node.grain or not node.primary_key:
        return node
    updated = node.model_copy(deep=True)
    updated.grain = [
        GrainComponent(
            entity_name=column,
            columns=[column],
            provenance=GrainProvenance.INFERRED_FROM_PRIMARY_KEY,
        )
        for column in node.primary_key
    ]
    return updated


def decompose_composite_primary_key(node: DatasetNode) -> DatasetNode:
    if len(node.primary_key) < 2:
        return node
    updated = node.model_copy(deep=True)
    children: dict[str, list[str]] = {}
    columns = node.primary_key
    for size in range(1, len(columns)):
        for subset in combinations(columns, size):
            key = "+".join(subset)
            children[key] = list(subset)
    updated.pk_child_entity = children
    return updated


def resolve_replicas(nodes: list[DatasetNode]) -> list[DatasetNode]:
    by_id = {node.node_id: node.model_copy(deep=True) for node in nodes}
    by_table = {}
    for node in by_id.values():
        if node.dataset_layer == DatasetLayer.PRIMARY:
            by_table.setdefault(node.table_name.lower(), []).append(node)
    for node in list(by_id.values()):
        if node.dataset_layer != DatasetLayer.SECONDARY or node.primary_ref is None:
            continue
        ref = node.primary_ref
        if ref.node_id and ref.node_id in by_id:
            primary = by_id[ref.node_id]
        else:
            matches = by_table.get(ref.qualified_name.lower(), [])
            if len(matches) != 1:
                continue
            primary = matches[0]
            ref.node_id = primary.node_id
        if node.node_id not in primary.replica_node_ids:
            primary.replica_node_ids = [*primary.replica_node_ids, node.node_id]
        by_id[primary.node_id] = primary
        by_id[node.node_id] = node
    return list(by_id.values())


def enrich_nodes(nodes: list[DatasetNode], overlays: dict[str, dict] | None = None) -> list[DatasetNode]:
    overlays = overlays or {}
    enriched = []
    for node in nodes:
        overlay = overlays.get(node.node_id) or overlays.get(node.table_name)
        if overlay:
            node = apply_overlay(node, overlay)
        node = synthesize_grain(node)
        node = decompose_composite_primary_key(node)
        enriched.append(node)
    return resolve_replicas(enriched)
