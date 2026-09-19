from data_ontology_graph.model.enums import DatasetLayer
from data_ontology_graph.model.relationship import derived_cardinality
from data_ontology_graph.model.snapshot import GraphSnapshot
from data_ontology_graph.query.paths import find_paths
from data_ontology_graph.query.sql_fragments import hop_join_type, join_on_sql


def search_nodes(snapshot: GraphSnapshot, query: str) -> list[dict]:
    needle = query.lower()
    hits = []
    for node in snapshot.nodes:
        if node.dataset_layer != DatasetLayer.PRIMARY:
            continue
        haystack = " ".join(
            [node.table_name, node.node_id, node.table_role.value, *node.synonyms, *node.tags]
        ).lower()
        if needle in haystack:
            hits.append(_node_summary(node))
    return hits


def node_detail(snapshot: GraphSnapshot, node_id: str) -> dict:
    node = snapshot.node_map()[node_id]
    return {
        "node_id": node.node_id,
        "table_name": node.table_name,
        "table_role": node.table_role.value,
        "dataset_layer": node.dataset_layer.value,
        "grain": [item.model_dump(mode="json") for item in node.grain],
        "primary_key": node.primary_key,
        "unique_keys": node.unique_keys,
        "columns": [column.model_dump(mode="json") for column in node.columns],
        "data_source": node.data_source.model_dump(mode="json", by_alias=True),
        "synonyms": node.synonyms,
        "tags": node.tags,
        "is_entity_universe": node.is_entity_universe,
    }


def hops_from(snapshot: GraphSnapshot, node_id: str) -> list[dict]:
    hops = []
    for edge in snapshot.edges:
        if node_id not in {edge.endpoint_a.node_id, edge.endpoint_b.node_id}:
            continue
        other = edge.opposite(node_id)
        hops.append(
            {
                "edge_id": edge.edge_id,
                "from_node_id": node_id,
                "to_node_id": other.node_id,
                "cardinality": derived_cardinality(edge, node_id).value,
                "from_participation": edge.endpoint(node_id).participation.value,
                "to_participation": other.participation.value,
                "transform": edge.endpoint(node_id).transform,
                "precedence": edge.precedence.value,
            }
        )
    return hops


def path_payloads(snapshot: GraphSnapshot, from_node_id: str, to_node_id: str, max_hops: int) -> list[dict]:
    nodes = snapshot.node_map()
    paths = []
    for path in find_paths(snapshot, from_node_id, to_node_id, max_hops=max_hops):
        hops = []
        for hop in path:
            source = hop.relationship.endpoint(hop.from_node_id)
            hops.append(
                {
                    "edge_id": hop.relationship.edge_id,
                    "from_node_id": hop.from_node_id,
                    "to_node_id": hop.to_node_id,
                    "cardinality": hop.cardinality.value,
                    "participation": source.participation.value,
                    "recommended_join": hop_join_type(source),
                    "transform": source.transform,
                    "sql_on": join_on_sql(hop.relationship, nodes[hop.from_node_id], nodes[hop.to_node_id]),
                }
            )
        paths.append({"hops": hops, "length": len(hops)})
    return paths


def column_guidance(snapshot: GraphSnapshot, node_id: str) -> list[dict]:
    node = snapshot.node_map()[node_id]
    return [
        {
            "name": column.name,
            "additivity": column.additivity.value,
            "grouping_safe": column.additivity.value in {"dimension", "unknown"},
            "unknown": column.additivity.value == "unknown",
        }
        for column in node.columns
    ]


def _node_summary(node) -> dict:
    return {
        "node_id": node.node_id,
        "table_name": node.table_name,
        "table_role": node.table_role.value,
        "synonyms": node.synonyms,
        "tags": node.tags,
    }
