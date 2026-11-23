from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

from data_ontology_graph.model.enums import EntityUniverse, MatchExistence, Multiplicity, Unknown
from data_ontology_graph.service.tables import ResponseFormat, Table
from data_ontology_graph.service.views import Detail, FieldObject


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


Collection = Table | list[dict[str, Any]]
"""A graph-object collection: a table by default, or records with ``response_format="records"``."""


API_VERSION = "6"
"""The graph API contract: methods, parameters, and response shapes. Raise it on a breaking change."""


class SnapshotInfo(ContractModel):
    api_version: str = API_VERSION
    version: str
    node_count: int
    entity_definition_count: int
    identity_count: int
    entity_relationship_count: int


class EntityDefinitionRef(ContractModel):
    node_id: str
    identity_id: str
    dataset_columns: list[str]


SearchKind = Literal["identity", "dataset", "entity_definition", "entity_relationship", "column"]


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


class EntityDefinitionsRequest(ContractModel):
    identity_id: str = Field(min_length=1)
    entity_universe: list[EntityUniverse] | None = Field(default=None, min_length=1)
    limit: int = Field(default=100, ge=1, le=1000)
    response_format: ResponseFormat = "table"
    target_identity_ids: list[Annotated[str, Field(min_length=1)]] = Field(default_factory=list)
    view: Literal["auto", "aggregated", "detailed"] = "auto"
    dataset_threshold: int = Field(default=200, ge=1, le=10_000)
    cursor: str | None = Field(default=None, min_length=1, max_length=4096)

    @field_validator("target_identity_ids")
    @classmethod
    def canonical_targets(cls, values: list[str]) -> list[str]:
        selected = sorted(set(values))
        if len(selected) > 4:
            raise ValueError("target_identity_ids allows at most four distinct logical entities")
        return selected

    @field_validator("entity_universe")
    @classmethod
    def canonical_universes(cls, values: list[EntityUniverse] | None) -> list[EntityUniverse] | None:
        return sorted(set(values)) if values is not None else None

    @model_validator(mode="after")
    def cursor_needs_detail(self) -> "EntityDefinitionsRequest":
        if self.cursor is not None and self.view == "aggregated":
            raise ValueError("cursor requires an auto or detailed view")
        return self


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


class DatasetEdgesRequest(NavigationRequest):
    node_id: str = Field(min_length=1)
    limit: int = Field(default=200, ge=1, le=1000)
    """Directed edges listed per entity definition."""
    identity_id: str | None = Field(default=None, min_length=1)
    from_dataset_columns: list[str] | None = Field(default=None, min_length=1)
    view: Literal["auto", "aggregated", "detailed"] = "auto"
    fan_out_threshold: int = Field(default=200, ge=1, le=10_000)
    target_identity_ids: list[Annotated[str, Field(min_length=1)]] = Field(default_factory=list)
    cursor: str | None = Field(default=None, min_length=1, max_length=4096)

    @field_validator("target_identity_ids")
    @classmethod
    def canonical_targets(cls, values: list[str]) -> list[str]:
        return sorted(set(values))

    @model_validator(mode="after")
    def columns_need_a_logical_entity(self) -> "DatasetEdgesRequest":
        if self.from_dataset_columns is not None and self.identity_id is None:
            raise ValueError("from_dataset_columns requires identity_id")
        if self.cursor is not None and self.view == "aggregated":
            raise ValueError("cursor requires an auto or detailed view")
        return self


MAX_PATH_LINKS = 6
"""Upper bound of ``PathsRequest.max_links``."""


class PathsRequest(ContractModel):
    """Path search between two logical entities under the caller's filters (system design 2.3.6)."""

    source_identity_id: str = Field(min_length=1)
    target_identity_id: str = Field(min_length=1)
    max_links: int = Field(default=2, ge=1, le=MAX_PATH_LINKS)
    link_kinds: Literal["all", "stated"] = "all"
    multiplicity: list[Multiplicity] | None = Field(default=None, min_length=1, max_length=5)
    order: Literal["any", "converging"] = "any"
    match_existence: list[MatchExistence] | None = Field(default=None, min_length=1, max_length=3)
    avoid_identity_ids: list[str] = Field(default_factory=list, max_length=50)
    participant_identity_ids: list[str] = Field(default_factory=list, max_length=3)
    participation: Literal["legs", "closed"] = "legs"
    shape: Literal["both", "independent", "shared_chain"] = "both"
    k_unnamed: int = Field(default=0, ge=0, le=2)
    exclude_restatements: bool = True
    self_links: bool = False
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = None

    @model_validator(mode="after")
    def consistent_filters(self) -> "PathsRequest":
        ends = {self.source_identity_id, self.target_identity_id}
        parts = self.participant_identity_ids
        if len(set(parts)) != len(parts):
            raise ValueError("participant_identity_ids must be distinct")
        if ends & set(parts):
            raise ValueError("participant_identity_ids must not contain the source or target")
        if (ends | set(parts)) & set(self.avoid_identity_ids):
            raise ValueError("avoid_identity_ids must not contain the source, target or a participant")
        if self.participation == "closed":
            if not parts:
                raise ValueError("participation closed requires participant_identity_ids")
            if self.multiplicity is not None or self.match_existence is not None or self.order != "any":
                raise ValueError("multiplicity, match_existence and order apply to paths and legs, not closed participation")
        elif self.k_unnamed:
            raise ValueError("k_unnamed applies to closed participation")
        return self


class EntityLinksRequest(ContractModel):
    """The entity links at one logical entity under the caller's filters (system design 2.3.12)."""

    identity_id: str = Field(min_length=1)
    link_kinds: Literal["all", "stated"] = "all"
    multiplicity: list[Multiplicity] | None = Field(default=None, min_length=1, max_length=5)
    match_existence: list[MatchExistence] | None = Field(default=None, min_length=1, max_length=3)
    avoid_identity_ids: list[str] = Field(default_factory=list, max_length=50)
    limit: int = Field(default=200, ge=1, le=1000)
    cursor: str | None = None

    @model_validator(mode="after")
    def requested_entity_is_not_avoided(self) -> "EntityLinksRequest":
        if self.identity_id in self.avoid_identity_ids:
            raise ValueError("avoid_identity_ids must not contain identity_id")
        return self


class EntityDefinitionsSelection(ContractModel):
    snapshot: SnapshotInfo
    identity_id: str
    name: str
    description: str
    synonyms: list[str]
    entity_universe: list[EntityUniverse] | None
    target_identity_ids: list[str]
    limit: int
    dataset_threshold: int
    dataset_count: int
    primary_definition_count: int


class EntityDefinitionsResponse(EntityDefinitionsSelection):
    view: Literal["detailed"] = "detailed"
    entity_definitions: Collection
    datasets: Collection
    truncated: bool
    next_cursor: str | None = None


class AggregatedEntityDefinitionsResponse(EntityDefinitionsSelection):
    view: Literal["aggregated"] = "aggregated"
    histogram: Collection
    logical_entity_count: int
    truncated: bool


class DatasetDetail(ContractModel):
    """The navigation dataset record with every field (system design 2.4.4)."""

    snapshot: SnapshotInfo
    node_id: str
    qualified_name: str
    accessor: dict[str, Any]
    grain: dict[str, Any] | Unknown
    descriptor: dict[str, Any]
    unknown_fields: list[str]
    columns: list[dict[str, Any]]
    entity_definitions: list[dict[str, Any]]


class RelationshipDetail(ContractModel):
    snapshot: SnapshotInfo
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


class DatasetEdgesSelection(ContractModel):
    snapshot: SnapshotInfo
    node_id: str
    limit: int
    identity_id: str | None
    from_dataset_columns: list[str] | None
    target_identity_ids: list[str]
    fan_out_count: int
    fan_out_threshold: int


class DatasetEdgesResponse(NavigationResponse, DatasetEdgesSelection):
    view: Literal["detailed"] = "detailed"
    next_cursor: str | None = None


class AggregatedDatasetEdgesResponse(DatasetEdgesSelection):
    view: Literal["aggregated"] = "aggregated"
    detail: Detail
    fields: dict[str, list[str]]
    histogram: Collection
    logical_entity_count: int
    truncated: bool


class PathEntity(ContractModel):
    identity_id: str
    name: str
    dataset_count: int


class StatedClaims(ContractModel):
    """The entity link's cross-entity relationship, its claims read in the direction of travel."""

    id: str
    descriptions: list[str]
    multiplicity: Multiplicity
    match_existence: MatchExistence
    reverse_match_existence: MatchExistence
    unknown_fields: list[str]


class EntityLink(ContractModel):
    """An entity link on a path, read from ``from_identity_id`` (system design 2.3.6)."""

    from_identity_id: str
    to_identity_id: str
    multiplicities: list[Multiplicity]
    match_existences: list[MatchExistence]
    common_dataset_count: int
    stated: StatedClaims | None


class LinkedEntity(ContractModel):
    """The other logical entity of an entity link and the link's claims, read from the requested
    logical entity (system design 2.3.12)."""

    identity_id: str
    name: str
    dataset_count: int
    multiplicities: list[Multiplicity]
    match_existences: list[MatchExistence]
    common_dataset_count: int
    stated: StatedClaims | None


class EntityLinksResponse(ContractModel):
    snapshot: SnapshotInfo
    identity_id: str
    name: str
    limit: int
    link_count: int
    links: list[LinkedEntity]
    truncated: bool
    next_cursor: str | None = None


class PathResult(ContractModel):
    rank: int
    tie_group: int
    shape: Literal["path", "shared_chain", "independent", "closed"]
    entities: list[PathEntity]
    links: list[EntityLink]
    legs: dict[str, list[str]] | None = None
    unnamed_identity_ids: list[str] | None = None


class ThroughEntity(ContractModel):
    identity_id: str
    name: str
    path_count: int
    dataset_count: int


class PathFilterReport(ContractModel):
    """Paths between the two logical entities with the claim filters removed, and what each claim
    setting would keep (system design 2.3.6)."""

    unfiltered_total: int
    unfiltered_is_lower_bound: bool
    by_links: dict[str, int]
    fewer_links_total: int
    unknown_multiplicity_total: int
    to_one_total: int
    to_one_is_lower_bound: bool
    from_one_total: int
    from_one_is_lower_bound: bool
    converging_total: int
    converging_is_lower_bound: bool
    through_entities: list[ThroughEntity]
    leg_counts: dict[str, int] | None = None


class PathRelaxation(ContractModel):
    """One filter change that widens the result, and the result count it gives."""

    change: dict[str, Any]
    total: int
    total_is_lower_bound: bool


class PathsResponse(ContractModel):
    snapshot: SnapshotInfo
    source_identity_id: str
    target_identity_id: str
    total: int
    total_is_lower_bound: bool
    tie_group_count: int
    results: list[PathResult]
    filter_report: PathFilterReport
    relaxations: list[PathRelaxation]
    leg_counts: dict[str, int] | None = None
    next_cursor: str | None = None
