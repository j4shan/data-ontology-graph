from pydantic import BaseModel, Field, model_validator

from data_ontology_graph.model.dataset import DatasetNode
from data_ontology_graph.model.enums import Cardinality, DatasetLayer, Participation, Precedence


class JoinEndpoint(BaseModel):
    node_id: str
    columns: list[str]
    is_unique: bool
    transform: str | None = None
    participation: Participation = Participation.UNKNOWN

    def identity_key(self) -> tuple[str, tuple[str, ...]]:
        return (self.node_id, tuple(sorted(self.columns)))


class JoinRelationship(BaseModel):
    edge_id: str
    endpoint_a: JoinEndpoint
    endpoint_b: JoinEndpoint
    precedence: Precedence = Precedence.DECLARED

    @model_validator(mode="after")
    def canonicalize(self) -> "JoinRelationship":
        left, right = canonical_endpoints(self.endpoint_a, self.endpoint_b)
        self.endpoint_a = left
        self.endpoint_b = right
        expected = edge_id_for(left, right)
        if self.edge_id != expected:
            raise ValueError(f"edge_id {self.edge_id!r} does not match canonical {expected!r}")
        return self

    def endpoint(self, node_id: str) -> JoinEndpoint:
        if self.endpoint_a.node_id == node_id:
            return self.endpoint_a
        if self.endpoint_b.node_id == node_id:
            return self.endpoint_b
        raise KeyError(node_id)

    def opposite(self, node_id: str) -> JoinEndpoint:
        if self.endpoint_a.node_id == node_id:
            return self.endpoint_b
        if self.endpoint_b.node_id == node_id:
            return self.endpoint_a
        raise KeyError(node_id)


class JoinAnnotation(BaseModel):
    edge_id: str
    weight: float = 1.0
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    notes: str = ""


class TraversalHop(BaseModel):
    relationship: JoinRelationship
    from_node_id: str
    to_node_id: str
    cardinality: Cardinality


def canonical_endpoints(
    endpoint_a: JoinEndpoint, endpoint_b: JoinEndpoint
) -> tuple[JoinEndpoint, JoinEndpoint]:
    if endpoint_a.identity_key() <= endpoint_b.identity_key():
        return endpoint_a, endpoint_b
    return endpoint_b, endpoint_a


def edge_id_for(endpoint_a: JoinEndpoint, endpoint_b: JoinEndpoint) -> str:
    left, right = canonical_endpoints(endpoint_a, endpoint_b)
    return f"{_side(left)}__{_side(right)}"


def _side(endpoint: JoinEndpoint) -> str:
    return f"{endpoint.node_id}:{'+'.join(sorted(endpoint.columns))}"


def cardinality_from(source_unique: bool, target_unique: bool) -> Cardinality:
    if source_unique and target_unique:
        return Cardinality.ONE_TO_ONE
    if not source_unique and target_unique:
        return Cardinality.N_TO_ONE
    if source_unique and not target_unique:
        return Cardinality.ONE_TO_N
    return Cardinality.M_TO_N


def derived_cardinality(relationship: JoinRelationship, from_node_id: str) -> Cardinality:
    source = relationship.endpoint(from_node_id)
    target = relationship.opposite(from_node_id)
    return cardinality_from(source.is_unique, target.is_unique)


def unique_side(relationship: JoinRelationship) -> str | None:
    a_unique = relationship.endpoint_a.is_unique
    b_unique = relationship.endpoint_b.is_unique
    if a_unique and not b_unique:
        return relationship.endpoint_a.node_id
    if b_unique and not a_unique:
        return relationship.endpoint_b.node_id
    return None


def entity_anchor(
    relationship: JoinRelationship, nodes: dict[str, DatasetNode]
) -> str | None:
    matches: list[str] = []
    for endpoint in (relationship.endpoint_a, relationship.endpoint_b):
        node = nodes.get(endpoint.node_id)
        if node is None or not node.primary_key:
            continue
        columns = node.column_map()
        pk_names = [columns[name].effective_logical_name() for name in node.primary_key if name in columns]
        ep_names = [
            columns[name].effective_logical_name() for name in endpoint.columns if name in columns
        ]
        if pk_names and set(pk_names) == set(ep_names) and len(pk_names) == len(node.primary_key):
            matches.append(node.node_id)
    if len(matches) == 1:
        return matches[0]
    return None


def recommended_join(from_participation: Participation) -> str:
    if from_participation == Participation.TOTAL:
        return "INNER"
    return "LEFT"


def make_relationship(
    endpoint_a: JoinEndpoint,
    endpoint_b: JoinEndpoint,
    precedence: Precedence = Precedence.DECLARED,
) -> JoinRelationship:
    left, right = canonical_endpoints(endpoint_a, endpoint_b)
    return JoinRelationship(
        edge_id=edge_id_for(left, right),
        endpoint_a=left,
        endpoint_b=right,
        precedence=precedence,
    )


def assert_primaries_own_edges(
    nodes: dict[str, DatasetNode], relationships: list[JoinRelationship]
) -> None:
    for relationship in relationships:
        for endpoint in (relationship.endpoint_a, relationship.endpoint_b):
            node = nodes.get(endpoint.node_id)
            if node is None:
                raise ValueError(f"edge {relationship.edge_id} references unknown node {endpoint.node_id}")
            if node.dataset_layer == DatasetLayer.SECONDARY:
                raise ValueError(
                    f"secondary node {node.node_id} must not own join relationships"
                )
