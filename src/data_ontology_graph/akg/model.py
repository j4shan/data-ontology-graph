"""AKG document model.

An AKG is a forest of graph cuts. A cut reuses the intermediary node, relationship, and
logical-identity models unchanged; this module adds only the document envelope, the cut
container, and the query reasoning that accompanies an AKG.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from data_ontology_graph.model.intermediary import (
    EntityDefinitionReference,
    IntermediaryNode,
    LogicalIdentityDefinition,
    RelationshipDefinition,
)


AKG_VERSION = "1.0"

Usage = Literal["measure", "count", "group", "filter", "time", "absence", "join_only", "output"]
Comparison = Literal["coverage", "difference", "co_occurrence"]


class SnapshotReference(BaseModel):
    """The served snapshot the AKG was selected from, as reported by `graph.snapshot_info`."""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1)
    schema_fingerprint: str = Field(min_length=1)


class GraphCut(BaseModel):
    """One connected component of an AKG, in the graph's own node and edge model."""

    model_config = ConfigDict(extra="forbid")

    logical_identities: dict[str, LogicalIdentityDefinition] = Field(
        default_factory=dict,
        description=(
            "Registry entries keyed by identity_id. Every identity an edge uses is required; "
            "other identities of the cut's entity definitions may be listed."
        ),
    )
    nodes: list[IntermediaryNode] = Field(min_length=1)
    edges: list[RelationshipDefinition] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_cut(self) -> "GraphCut":
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("node_id values must be unique within a cut")

        registered: set[tuple[str, str, tuple[str, ...]]] = set()
        node_identities: set[str] = set()
        for node in self.nodes:
            for definition in node.entity_definitions:
                registered.add(definition.key(node.node_id))
                node_identities.add(definition.identity_id)
        extraneous = sorted(set(self.logical_identities) - node_identities)
        if extraneous:
            raise ValueError(
                f"logical identities are not used by any node in the cut: {extraneous}"
            )

        edge_ids: set[str] = set()
        for index, edge in enumerate(self.edges):
            for endpoint in (edge.endpoint_a, edge.endpoint_b):
                if endpoint.key() not in registered:
                    raise ValueError(
                        f"edges[{index}] endpoint does not resolve to an entity definition of a "
                        f"node in this cut: {endpoint.key()!r}"
                    )
            if edge.endpoint_a.identity_id not in self.logical_identities:
                raise ValueError(
                    f"edges[{index}] uses logical identity {edge.endpoint_a.identity_id!r}, "
                    "which the cut does not list"
                )
            edge_id = edge.canonical_edge_id()
            if edge_id in edge_ids:
                raise ValueError(f"duplicate edge in cut: {edge_id!r}")
            edge_ids.add(edge_id)

        disconnected = _unreached(node_ids, self.edges)
        if disconnected:
            raise ValueError(
                "a cut must be connected through its own edges; split unreached nodes "
                f"into separate cuts: {disconnected}"
            )
        return self

    def node(self, node_id: str) -> IntermediaryNode | None:
        return next((node for node in self.nodes if node.node_id == node_id), None)


class ColumnReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)
    column: str = Field(min_length=1)


class Attribute(ColumnReference):
    """How the answer uses one column of a selected node."""

    usage: Usage
    value: JsonValue = Field(
        default=None, description="Filter value or threshold, when the question states one."
    )
    note: str = ""


class Traversal(BaseModel):
    """The anchor-side orientation of one selected edge."""

    model_config = ConfigDict(extra="forbid")

    origin: EntityDefinitionReference
    target: EntityDefinitionReference
    aggregate_before_join: bool = Field(
        default=False,
        description="Aggregate the target side to the origin's grain before combining.",
    )
    note: str = ""


class DrillAcross(BaseModel):
    """Two or more anchors compared on shared cut columns rather than joined to each other."""

    model_config = ConfigDict(extra="forbid")

    anchors: list[str] = Field(min_length=2)
    shared_columns: list[ColumnReference] = Field(min_length=1)
    comparison: Comparison


class DataGap(BaseModel):
    """Knowledge the answer needs that the graph could not connect or supply."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1)
    cuts: list[int] = Field(
        default_factory=list, description="Zero-based indices of the cuts involved."
    )
    node_ids: list[str] = Field(default_factory=list)


class Reasoning(BaseModel):
    """Query reasoning that accompanies an AKG. It never adds a node or edge."""

    model_config = ConfigDict(extra="forbid")

    anchors: list[str] = Field(
        default_factory=list, description="Nodes whose grain carries a measure."
    )
    attributes: list[Attribute] = Field(default_factory=list)
    traversals: list[Traversal] = Field(default_factory=list)
    drill_across: list[DrillAcross] = Field(default_factory=list)
    data_gaps: list[DataGap] = Field(default_factory=list)


class AbstractKnowledgeGraph(BaseModel):
    """One reading of a question: a forest of graph cuts plus its reasoning."""

    model_config = ConfigDict(extra="forbid")

    interpretation: str = Field(min_length=1)
    cuts: list[GraphCut] = Field(min_length=1)
    reasoning: Reasoning = Field(default_factory=Reasoning)

    @model_validator(mode="after")
    def validate_forest(self) -> "AbstractKnowledgeGraph":
        owner: dict[str, int] = {}
        for index, cut in enumerate(self.cuts):
            for node in cut.nodes:
                if node.node_id in owner:
                    raise ValueError(
                        f"node {node.node_id!r} appears in cuts[{owner[node.node_id]}] and "
                        f"cuts[{index}]; cuts of one AKG must be disjoint"
                    )
                owner[node.node_id] = index

        reasoning = self.reasoning
        for node_id in reasoning.anchors:
            self._require_node(node_id, "reasoning.anchors")
        for index, attribute in enumerate(reasoning.attributes):
            self._require_column(attribute, f"reasoning.attributes[{index}]")
        edges = {
            frozenset((edge.endpoint_a.key(), edge.endpoint_b.key()))
            for cut in self.cuts
            for edge in cut.edges
        }
        for index, traversal in enumerate(reasoning.traversals):
            if frozenset((traversal.origin.key(), traversal.target.key())) not in edges:
                raise ValueError(
                    f"reasoning.traversals[{index}] does not match an edge in any cut"
                )
        for index, drill in enumerate(reasoning.drill_across):
            for node_id in drill.anchors:
                self._require_node(node_id, f"reasoning.drill_across[{index}].anchors")
            for column in drill.shared_columns:
                self._require_column(column, f"reasoning.drill_across[{index}].shared_columns")
        for index, gap in enumerate(reasoning.data_gaps):
            for cut_index in gap.cuts:
                if not 0 <= cut_index < len(self.cuts):
                    raise ValueError(
                        f"reasoning.data_gaps[{index}] names cut {cut_index}, which does not exist"
                    )
            for node_id in gap.node_ids:
                self._require_node(node_id, f"reasoning.data_gaps[{index}].node_ids")
        return self

    def _node(self, node_id: str) -> IntermediaryNode | None:
        for cut in self.cuts:
            node = cut.node(node_id)
            if node is not None:
                return node
        return None

    def _require_node(self, node_id: str, location: str) -> IntermediaryNode:
        node = self._node(node_id)
        if node is None:
            raise ValueError(f"{location} names node {node_id!r}, which is in no cut")
        return node

    def _require_column(self, reference: ColumnReference, location: str) -> None:
        node = self._require_node(reference.node_id, location)
        if reference.column not in {column.name for column in node.columns}:
            raise ValueError(
                f"{location} names column {reference.column!r}, which node "
                f"{reference.node_id!r} does not have"
            )


class AkgDocument(BaseModel):
    """The AKGs that resolve one question, one per reading, the preferred reading first."""

    model_config = ConfigDict(extra="forbid")

    akg_version: Literal["1.0"]
    question: str = Field(min_length=1)
    snapshot: SnapshotReference
    akgs: list[AbstractKnowledgeGraph] = Field(min_length=1)


def _unreached(node_ids: list[str], edges: list[RelationshipDefinition]) -> list[str]:
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for edge in edges:
        adjacency[edge.endpoint_a.node_id].add(edge.endpoint_b.node_id)
        adjacency[edge.endpoint_b.node_id].add(edge.endpoint_a.node_id)
    reached = {node_ids[0]}
    frontier = [node_ids[0]]
    while frontier:
        for neighbour in adjacency[frontier.pop()]:
            if neighbour not in reached:
                reached.add(neighbour)
                frontier.append(neighbour)
    return [node_id for node_id in node_ids if node_id not in reached]
