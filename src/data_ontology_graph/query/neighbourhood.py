"""Directed edges and bounded neighbourhood expansion, shared by every navigation method.

A directed edge is a relationship traversed from one of its endpoints. Neighbour listing is the
only place a relationship becomes a directed edge: each endpoint lying on a dataset gives one
directed edge leaving it, so a relationship with both endpoints on one dataset gives that dataset
two directed edges. A dataset's directed edges are grouped by the entity definition they leave
from, and limits apply per group, so every entity definition stays visible.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from data_ontology_graph.model.relationship import (
    JoinEndpoint,
    JoinRelationship,
    RelationshipDirection,
)


@dataclass(frozen=True)
class DirectedEdge:
    relationship: JoinRelationship
    source: JoinEndpoint
    target: JoinEndpoint

    @property
    def edge_id(self) -> str:
        return self.relationship.edge_id

    @property
    def _from_a(self) -> bool:
        return self.source.identity_key() == self.relationship.endpoint_a.identity_key()

    @property
    def outgoing(self) -> RelationshipDirection:
        return self.relationship.a_to_b if self._from_a else self.relationship.b_to_a

    @property
    def reverse(self) -> RelationshipDirection:
        return self.relationship.b_to_a if self._from_a else self.relationship.a_to_b

    def sort_key(self) -> tuple:
        """Logical entity ID, start columns, end node_id, then end columns."""
        return (
            self.source.identity_id, tuple(self.source.dataset_columns),
            self.target.node_id, tuple(self.target.dataset_columns),
        )


def directed_edge_from(relationship: JoinRelationship, source_key: tuple) -> DirectedEdge:
    """The directed edge of ``relationship`` leaving the endpoint keyed ``source_key``."""
    a, b = relationship.endpoint_a, relationship.endpoint_b
    if a.identity_key() == source_key:
        return DirectedEdge(relationship, a, b)
    if b.identity_key() == source_key:
        return DirectedEdge(relationship, b, a)
    raise KeyError(source_key)


def directed_edges_by_dataset(relationships: Iterable[JoinRelationship]) -> dict[str, tuple[DirectedEdge, ...]]:
    """Every dataset's directed edges in ``DirectedEdge.sort_key`` order."""
    listed: dict[str, list[DirectedEdge]] = defaultdict(list)
    for relationship in relationships:
        a, b = relationship.endpoint_a, relationship.endpoint_b
        listed[a.node_id].append(DirectedEdge(relationship, a, b))
        listed[b.node_id].append(DirectedEdge(relationship, b, a))
    return {node_id: tuple(sorted(edges, key=DirectedEdge.sort_key)) for node_id, edges in listed.items()}


@dataclass
class EdgeGroup:
    """The directed edges leaving one entity definition, of ``edge_count`` in all."""

    source: JoinEndpoint
    edge_count: int
    edges: list[DirectedEdge]

    @property
    def truncated(self) -> bool:
        return len(self.edges) < self.edge_count


def group_edges(
    edges: Iterable[DirectedEdge],
    *,
    limit: int | None = None,
    listed: Callable[[DirectedEdge], bool] | None = None,
) -> list[EdgeGroup]:
    """Group ``edges``, given in sort-key order, by the entity definition they leave from.

    Each group lists at most ``limit`` directed edges, and only those ``listed`` accepts.
    """
    groups: list[EdgeGroup] = []
    for edge in edges:
        if not groups or groups[-1].source.identity_key() != edge.source.identity_key():
            groups.append(EdgeGroup(edge.source, 0, []))
        group = groups[-1]
        group.edge_count += 1
        if (limit is None or len(group.edges) < limit) and (listed is None or listed(edge)):
            group.edges.append(edge)
    return groups


@dataclass
class Neighbourhood:
    datasets: list[tuple[str, int]]
    """Returned datasets with their distance from the nearest seed, in (distance, node_id) order."""
    groups: dict[str, list[EdgeGroup]]
    """Edge groups of each expanded dataset; boundary datasets have no entry."""
    truncated: bool


def expand(
    edges: dict[str, tuple[DirectedEdge, ...]],
    seeds: list[str],
    depth: int,
    *,
    max_nodes: int | None = None,
    limit: int | None = None,
    edge_filter: Callable[[DirectedEdge], bool] | None = None,
    referenced_only: bool = False,
) -> Neighbourhood:
    """Expand breadth-first from ``seeds`` to ``depth``.

    A dataset closer than ``depth`` is expanded and lists the directed edges leaving it, grouped by
    entity definition; a dataset at ``depth`` is a boundary dataset and lists none. ``max_nodes``
    caps datasets in order, ``limit`` caps each group's listed directed edges, and a directed edge
    whose target is omitted is not listed. ``edge_filter`` drops directed edges from traversal and
    from the groups. With ``referenced_only``, only seeds and the targets of listed directed edges
    are returned.
    """
    allowed = edge_filter or (lambda edge: True)
    distance = {seed: 0 for seed in seeds}
    frontier = list(dict.fromkeys(seeds))
    for level in range(depth):
        following = []
        for node_id in frontier:
            for edge in edges.get(node_id, ()):
                target = edge.target.node_id
                if allowed(edge) and target not in distance:
                    distance[target] = level + 1
                    following.append(target)
        frontier = following

    ordered = sorted(distance.items(), key=lambda item: (item[1], item[0]))
    selected = ordered if max_nodes is None else ordered[:max_nodes]
    truncated = len(selected) < len(ordered)
    kept = {node_id for node_id, _ in selected}
    groups: dict[str, list[EdgeGroup]] = {}
    for node_id, node_distance in selected:
        if node_distance >= depth:
            continue
        groups[node_id] = group_edges(
            (edge for edge in edges.get(node_id, ()) if allowed(edge)),
            limit=limit, listed=lambda edge: edge.target.node_id in kept,
        )
        truncated = truncated or any(group.truncated for group in groups[node_id])
    if referenced_only:
        referenced = set(seeds) | {
            edge.target.node_id
            for node_groups in groups.values() for group in node_groups for edge in group.edges
        }
        selected = [item for item in selected if item[0] in referenced]
    return Neighbourhood(datasets=selected, groups=groups, truncated=truncated)
