from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from data_ontology_graph.model.enums import EntityUniverse, Multiplicity, Unknown
from data_ontology_graph.service.tables import ResponseFormat, Table
from data_ontology_graph.service.views import Detail, FieldObject


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


Collection = Table | list[dict[str, Any]]
"""A graph-object collection: a table by default, or records with ``response_format="records"``."""


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


SearchKind = Literal["identity", "dataset", "entity_definition", "column"]


SearchCell = str | list[str] | None


class SearchGroup(ContractModel):
    """Search results for one kind as two header-keyed row tables joined by ``key``.

    ``subject_row_header`` names the position of each value in a ``subject_rows`` row, and
    ``match_row_header`` does the same for ``match_rows``. A subject has one match row for each
    field value that matched.
    """

    kind: SearchKind
    truncated: bool
    subject_row_header: list[str]
    subject_rows: list[list[SearchCell]]
    match_row_header: list[str]
    match_rows: list[list[str]]


class SearchRequest(ContractModel):
    query: str = Field(min_length=1)
    kind: list[SearchKind] | None = Field(default=None, min_length=1)
    limit: int = Field(default=50, ge=1, le=1000)


class SearchResponse(ContractModel):
    snapshot: SnapshotInfo
    query: str
    normalized_query: str
    groups: list[SearchGroup]
    truncated: bool


class IdentityRequest(ContractModel):
    identity_id: str = Field(min_length=1)
    entity_universe: list[EntityUniverse] | None = Field(default=None, min_length=1)
    limit: int = Field(default=100, ge=1, le=1000)
    response_format: ResponseFormat = "table"


class DatasetRequest(ContractModel):
    node_id: str = Field(min_length=1)


class RelationshipRequest(ContractModel):
    edge_id: str = Field(min_length=1)
    from_node_id: str | None = Field(default=None, min_length=1)
    from_dataset_columns: list[str] | None = Field(default=None, min_length=1)
    response_format: ResponseFormat = "table"

    @model_validator(mode="after")
    def columns_need_a_dataset(self) -> "RelationshipRequest":
        if self.from_dataset_columns is not None and self.from_node_id is None:
            raise ValueError("from_dataset_columns requires from_node_id")
        return self


class NavigationRequest(ContractModel):
    response_format: ResponseFormat = "table"
    detail: Detail = "standard"
    fields: dict[FieldObject, list[str]] = Field(default_factory=dict)


class EdgesRequest(NavigationRequest):
    node_id: str = Field(min_length=1)
    limit: int = Field(default=200, ge=1, le=1000)
    """Directed edges listed per entity definition."""
    identity_id: str | None = Field(default=None, min_length=1)
    from_dataset_columns: list[str] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def columns_need_a_logical_entity(self) -> "EdgesRequest":
        if self.from_dataset_columns is not None and self.identity_id is None:
            raise ValueError("from_dataset_columns requires identity_id")
        return self


class SubgraphRequest(NavigationRequest):
    seed_node_ids: list[str] = Field(min_length=1)
    max_depth: int = Field(default=1, ge=0, le=10)
    max_nodes: int = Field(default=1000, ge=1, le=10_000)
    limit: int = Field(default=200, ge=1, le=1000)
    """Directed edges listed per entity definition."""


class PathsRequest(NavigationRequest):
    from_node_id: str = Field(min_length=1)
    to_node_id: str = Field(min_length=1)
    max_edges: int = Field(default=4, ge=1, le=10)
    limit: int = Field(default=6, ge=1, le=100)
    allowed_multiplicities: list[Multiplicity] | None = Field(
        default=None, min_length=1, max_length=5,
    )


class ConnectingSubgraphRequest(NavigationRequest):
    node_ids: list[str] = Field(min_length=2)

    @model_validator(mode="after")
    def distinct_endpoints(self) -> "ConnectingSubgraphRequest":
        if any(not node_id for node_id in self.node_ids):
            raise ValueError("node_ids must contain non-empty dataset IDs")
        if len(set(self.node_ids)) != len(self.node_ids):
            raise ValueError("node_ids must contain distinct datasets")
        return self


class IdentityDetail(ContractModel):
    identity_id: str
    name: str
    description: str
    synonyms: list[str]
    entity_definitions: Collection
    datasets: Collection
    truncated: bool


class DatasetDetail(ContractModel):
    node_id: str
    descriptor: dict[str, Any]
    accessor: dict[str, Any]
    grain: dict[str, Any] | Unknown
    columns: list[dict[str, Any]]
    entity_definitions: list[dict[str, Any]]
    unknown_fields: list[str]


class RelationshipDetail(ContractModel):
    edge_id: str
    identity_id: str
    endpoint_a: dict[str, Any]
    endpoint_b: dict[str, Any]
    a_to_b: dict[str, Any]
    b_to_a: dict[str, Any]
    unknown_fields: list[str]
    annotation: dict[str, Any] | None
    from_node_id: str | None = None
    from_dataset_columns: list[str] | None = None
    edge_fields: list[str] | None = None
    edge: list[Any] | None = None
    datasets: Collection
    entity_definitions: Collection


class NavigationResponse(ContractModel):
    """Datasets with their edge groups nested in records, or split out keyed by ``node_id``.

    An edge group holds one logical entity's directed edges leaving a dataset, by entity
    definition. Each directed edge is an array whose positions ``edge_fields`` names, the same in
    both formats. In records format, edge groups, columns, and entity definitions are nested in
    their datasets and the table-only collections are omitted.
    """

    detail: Detail
    fields: dict[str, list[str]]
    edge_fields: list[str]
    datasets: Collection
    edge_groups: list[dict[str, Any]] | None = None
    columns: Table | None = None
    entity_definitions: Table | None = None
    truncated: bool

    @model_serializer(mode="wrap")
    def omit_absent_tables(self, handler):
        data = handler(self)
        for key in ("edge_groups", "columns", "entity_definitions"):
            if key in data and data[key] is None:
                del data[key]
        return data


class EdgesResponse(NavigationResponse):
    node_id: str
    limit: int


class SubgraphResponse(NavigationResponse):
    snapshot: SnapshotInfo
    seed_node_ids: list[str]
    max_depth: int
    max_nodes: int
    limit: int


class PathsResponse(NavigationResponse):
    snapshot: SnapshotInfo
    from_node_id: str
    to_node_id: str
    path_count: int
    routes: list[list[list[Any]]]
    """Routes in rank order, each its directed edges in travel order."""


class ConnectingSubgraphResponse(NavigationResponse):
    snapshot: SnapshotInfo
    node_ids: list[str]
    status: Literal["completed", "disconnected"]
    algorithm: Literal["mehlhorn_unweighted"] = "mehlhorn_unweighted"
