from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SnapshotInfo(ContractModel):
    version: str
    schema_fingerprint: str | None
    built_at: str
    node_count: int
    edge_count: int
    identity_count: int


class EntityDefinitionRef(ContractModel):
    node_id: str
    identity_id: str
    dataset_columns: list[str]


class SearchSubject(ContractModel):
    kind: Literal["identity", "dataset", "entity_definition", "column"]
    key: str
    label: str
    node_id: str | None = None
    identity_id: str | None = None
    dataset_columns: list[str] = Field(default_factory=list)
    column_name: str | None = None


class SearchHit(ContractModel):
    subject: SearchSubject
    match_kind: Literal["exact", "prefix"]
    matched_term: str
    matched_field: str


class SearchRequest(ContractModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=50, ge=1, le=1000)


class SearchResponse(ContractModel):
    snapshot: SnapshotInfo
    query: str
    normalized_query: str
    hits: list[SearchHit]
    truncated: bool


class IdentityRequest(ContractModel):
    identity_id: str = Field(min_length=1)


class DatasetRequest(ContractModel):
    node_id: str = Field(min_length=1)


class RelationshipRequest(ContractModel):
    edge_id: str = Field(min_length=1)


class HopsRequest(ContractModel):
    node_id: str = Field(min_length=1)


class SubgraphRequest(ContractModel):
    seed_node_ids: list[str] = Field(min_length=1)
    max_depth: int = Field(default=1, ge=0, le=10)
    max_nodes: int = Field(default=1000, ge=1, le=10_000)
    max_edges: int = Field(default=1000, ge=1, le=10_000)

    @model_validator(mode="after")
    def seeds_must_fit_node_limit(self) -> "SubgraphRequest":
        if len(set(self.seed_node_ids)) > self.max_nodes:
            raise ValueError("max_nodes must be at least the number of unique seed nodes")
        return self


class PathsRequest(ContractModel):
    from_node_id: str = Field(min_length=1)
    to_node_id: str = Field(min_length=1)
    max_hops: int = Field(default=4, ge=1, le=10)
    limit: int = Field(default=50, ge=1, le=1000)


class IdentityDetail(ContractModel):
    identity_id: str
    name: str
    description: str
    synonyms: list[str]
    definitions: list[dict[str, Any]]


class DatasetDetail(ContractModel):
    node_id: str
    descriptor: dict[str, Any]
    accessor: dict[str, Any]
    grain: dict[str, Any] | None
    columns: list[dict[str, Any]]
    entity_definitions: list[dict[str, Any]]


class RelationshipDetail(ContractModel):
    edge_id: str
    identity_id: str
    endpoint_a: dict[str, Any]
    endpoint_b: dict[str, Any]
    a_to_b: dict[str, Any]
    b_to_a: dict[str, Any]
    annotation: dict[str, Any] | None


class HopDetail(ContractModel):
    edge_id: str
    from_node_id: str
    to_node_id: str
    identity_id: str
    from_endpoint: dict[str, Any]
    to_endpoint: dict[str, Any]
    direction: dict[str, Any]
    reverse_direction: dict[str, Any]


class SubgraphResponse(ContractModel):
    snapshot: SnapshotInfo
    seed_node_ids: list[str]
    max_depth: int
    max_nodes: int
    max_edges: int
    nodes: list[dict[str, Any]]
    edges: list[RelationshipDetail]
    truncated: bool


class PathsResponse(ContractModel):
    snapshot: SnapshotInfo
    from_node_id: str
    to_node_id: str
    paths: list[dict[str, Any]]
    truncated: bool
