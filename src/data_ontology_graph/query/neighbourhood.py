"""Directed edges at a dataset, listed by `get_dataset_edges` and `get_relationship`.

A directed edge is a relationship traversed from one of its endpoints. Neighbour listing is the
only place a relationship becomes a directed edge: each endpoint lying on a dataset gives one
directed edge leaving it, so a relationship with both endpoints on one dataset gives that dataset
two directed edges. A dataset's directed edges are grouped by the entity definition they leave
from, and limits apply per group, so every entity definition stays visible.
"""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass

from data_ontology_graph.model.derivation import MembershipIndex
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


class _DatasetEdges(Sequence[DirectedEdge]):
    """A re-iterable outgoing-edge view; creating it does not derive a relationship."""

    def __init__(self, memberships: MembershipIndex, node_id: str) -> None:
        self.memberships = memberships
        self.node_id = node_id

    def __len__(self) -> int:
        return self.memberships.degree(self.node_id)

    def __iter__(self) -> Iterator[DirectedEdge]:
        index = self.memberships
        for source in index.definition_keys(self.node_id):
            for target in index.by_identity[source.identity_id]:
                if target != source:
                    yield DirectedEdge(index.pair(source, target), index.endpoint(source), index.endpoint(target))

    def __getitem__(self, position: int | slice) -> DirectedEdge | list[DirectedEdge]:
        return list(self)[position]


class MembershipDirectedEdges(Mapping[str, Sequence[DirectedEdge]]):
    """Dataset adjacency backed by memberships, with no stored pairwise edge collection."""

    def __init__(self, memberships: MembershipIndex) -> None:
        self.memberships = memberships

    def __len__(self) -> int:
        return len(self.memberships.nodes)

    def __iter__(self) -> Iterator[str]:
        return iter(self.memberships.nodes)

    def __getitem__(self, node_id: str) -> Sequence[DirectedEdge]:
        if node_id not in self.memberships.nodes:
            raise KeyError(node_id)
        return _DatasetEdges(self.memberships, node_id)


@dataclass
class EdgeGroup:
    """The directed edges leaving one entity definition, of ``edge_count`` in all."""

    source: JoinEndpoint
    edge_count: int
    edges: list[DirectedEdge]

    @property
    def truncated(self) -> bool:
        return len(self.edges) < self.edge_count
