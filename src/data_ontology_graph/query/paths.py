from collections import defaultdict, deque

from data_ontology_graph.model.enums import DatasetLayer
from data_ontology_graph.model.relationship import (
    JoinRelationship,
    TraversalHop,
    derived_cardinality,
)
from data_ontology_graph.model.snapshot import GraphSnapshot


def primary_adjacency(snapshot: GraphSnapshot) -> dict[str, list[JoinRelationship]]:
    primaries = {
        node.node_id
        for node in snapshot.nodes
        if node.dataset_layer == DatasetLayer.PRIMARY
    }
    adj: dict[str, list[JoinRelationship]] = defaultdict(list)
    for edge in snapshot.edges:
        if edge.endpoint_a.node_id in primaries and edge.endpoint_b.node_id in primaries:
            adj[edge.endpoint_a.node_id].append(edge)
            adj[edge.endpoint_b.node_id].append(edge)
    return adj


def find_paths(
    snapshot: GraphSnapshot,
    from_node_id: str,
    to_node_id: str,
    max_hops: int = 4,
) -> list[list[TraversalHop]]:
    adj = primary_adjacency(snapshot)
    weights = {
        annotation.edge_id: annotation.weight for annotation in snapshot.annotations
    }
    found: list[list[TraversalHop]] = []
    queue: deque[tuple[str, list[TraversalHop], set[str]]] = deque(
        [(from_node_id, [], {from_node_id})]
    )
    while queue:
        current, hops, seen = queue.popleft()
        if len(hops) >= max_hops:
            continue
        for edge in adj.get(current, []):
            nxt = edge.opposite(current).node_id
            if nxt in seen:
                continue
            hop = TraversalHop(
                relationship=edge,
                from_node_id=current,
                to_node_id=nxt,
                cardinality=derived_cardinality(edge, current),
            )
            path = [*hops, hop]
            if nxt == to_node_id:
                found.append(path)
            else:
                queue.append((nxt, path, seen | {nxt}))
    found.sort(
        key=lambda path: (
            len(path),
            -sum(weights.get(hop.relationship.edge_id, 1.0) for hop in path),
        )
    )
    return found
