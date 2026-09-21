from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from data_ontology_graph.model.enums import Cardinality, MatchExistence, Multiplicity


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JoinEndpoint(StrictModel):
    node_id: str = Field(min_length=1)
    identity_id: str = Field(min_length=1)
    dataset_columns: list[str] = Field(min_length=1)

    @field_validator("dataset_columns")
    @classmethod
    def dataset_columns_must_be_canonical(cls, value: list[str]) -> list[str]:
        if any(not column for column in value):
            raise ValueError("dataset_columns must not contain empty names")
        if len(value) != len(set(value)):
            raise ValueError("dataset_columns must not contain duplicate columns")
        if value != sorted(value):
            raise ValueError("dataset_columns must use ascending exact-name order")
        return value

    def identity_key(self) -> tuple[str, str, tuple[str, ...]]:
        return (self.node_id, self.identity_id, tuple(self.dataset_columns))


class RelationshipDirection(StrictModel):
    multiplicity: Multiplicity
    match_existence: MatchExistence


class JoinRelationship(StrictModel):
    edge_id: str = Field(min_length=1)
    endpoint_a: JoinEndpoint
    endpoint_b: JoinEndpoint
    a_to_b: RelationshipDirection
    b_to_a: RelationshipDirection

    @model_validator(mode="after")
    def canonicalize(self) -> "JoinRelationship":
        original_a = self.endpoint_a.identity_key()
        left, right = canonical_endpoints(self.endpoint_a, self.endpoint_b)
        if left.identity_key() != original_a:
            self.a_to_b, self.b_to_a = self.b_to_a, self.a_to_b
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

    def direction_from(self, node_id: str) -> RelationshipDirection:
        if self.endpoint_a.node_id == node_id:
            return self.a_to_b
        if self.endpoint_b.node_id == node_id:
            return self.b_to_a
        raise KeyError(node_id)


class JoinAnnotation(StrictModel):
    edge_id: str
    weight: float = 1.0
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    notes: str = ""


class TraversalHop(StrictModel):
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
    return (
        f"{endpoint.node_id}:{endpoint.identity_id}:"
        f"{'+'.join(endpoint.dataset_columns)}"
    )


def derived_cardinality(relationship: JoinRelationship, from_node_id: str) -> Cardinality:
    explicit = relationship.direction_from(from_node_id).multiplicity
    return {
        Multiplicity.ONE_TO_ONE: Cardinality.ONE_TO_ONE,
        Multiplicity.MANY_TO_ONE: Cardinality.N_TO_ONE,
        Multiplicity.ONE_TO_MANY: Cardinality.ONE_TO_N,
        Multiplicity.MANY_TO_MANY: Cardinality.M_TO_N,
        Multiplicity.UNKNOWN: Cardinality.UNKNOWN,
    }[explicit]
