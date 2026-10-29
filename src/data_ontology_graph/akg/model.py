"""AKG document model, format 3.

An AKG holds the graph datasets that serve one objective, each in the shape of the graph service
response it was concluded from: the dataset record without the fields that describe only a
response, with the selected columns, and with the selected directed edges in `edge_groups` as
directed-edge arrays named by the document's `edge_fields`. The agent's reasoning sits beside
them in `usage`, `comparisons`, and `gaps`. Every model accepts unknown keys; `check` reports
them without rejecting the document.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from data_ontology_graph.model.enums import EntityUniverse


EDGE_FIELDS = (
    "edge", "multiplicity", "match_existence", "reverse_multiplicity", "reverse_match_existence",
    "from_description", "to_description", "edge_id",
)
"""The `standard` directed-edge positions an AKG records (system design 2.4.1)."""
Status = Literal["draft", "final"]
Role = Literal["anchor", "grouping", "filter", "bridge"]
ColumnUse = Literal["measure", "count", "group", "filter", "time", "absence", "join_only", "output"]
ComparisonKind = Literal["coverage", "difference", "co_occurrence"]


class OpenModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class Snapshot(OpenModel):
    api_version: str = Field(min_length=1, description="The graph API version the AKG follows.")
    version: str = Field(min_length=1, description="The snapshot version the AKG was read from.")


class GraphInfo(OpenModel):
    snapshot: Snapshot | None = Field(
        default=None, description="The served snapshot, as `graph.snapshot_info` returns it."
    )


class Accessor(OpenModel):
    schema_id: str = Field(min_length=1)
    properties: dict[str, JsonValue] | None = None


class Descriptor(OpenModel):
    display_name: str | None = None
    description: str | None = None
    synonyms: list[str] | None = None
    tags: list[str] | None = None


class Column(OpenModel):
    name: str = Field(min_length=1)
    description: str | None = None
    value_description: str | None = None
    synonyms: list[str] | None = None


class EntityDefinition(OpenModel):
    identity_id: str = Field(min_length=1)
    dataset_columns: list[str] = Field(min_length=1)
    entity_universe: EntityUniverse | None = None
    unique: bool | Literal["unknown"] | None = None
    total: bool | Literal["unknown"] | None = None
    conforms: bool | Literal["unknown"] | None = None
    entity_expression: list[str] | None = None
    entity_metadata: dict[str, JsonValue] | None = None
    description: str | None = None
    effective_description: str | None = None
    description_source: Literal["entity", "column"] | None = None
    unknown_fields: list[str] | None = None


class EdgeUsage(OpenModel):
    """Agent reasoning about one directed edge."""

    keep: list[str] | None = Field(
        default=None, description="Start or end node_id values whose unmatched rows must survive."
    )
    aggregate_before_join: bool | None = Field(
        default=None, description="Aggregate the end to the start's grain before combining."
    )
    note: str | None = None


class GroupDefinition(OpenModel):
    """One entity definition of an edge group, with its selected directed edges."""

    dataset_columns: list[str] = Field(min_length=1)
    edges: list[list[JsonValue]] = Field(
        description="Directed-edge arrays at the positions the document's `edge_fields` names."
    )
    usage: dict[str, EdgeUsage] | None = Field(
        default=None, description="Agent reasoning per directed edge, keyed by `edge_id`."
    )


class EdgeGroup(OpenModel):
    identity_id: str = Field(min_length=1)
    entity_definitions: list[GroupDefinition] = Field(min_length=1)


class ColumnUsage(OpenModel):
    as_: ColumnUse = Field(alias="as")
    value: JsonValue = Field(default=None, description="Filter value or threshold.")
    note: str | None = None


class DatasetUsage(OpenModel):
    """Agent reasoning about one dataset."""

    role: Role | None = None
    columns: dict[str, ColumnUsage] | None = None
    note: str | None = None


class Dataset(OpenModel):
    """One graph dataset record, as a graph service response presents it."""

    node_id: str = Field(min_length=1)
    qualified_name: str = Field(min_length=1)
    accessor: Accessor
    grain: dict[str, JsonValue] | Literal["unknown"] | None = None
    descriptor: Descriptor | None = None
    unknown_fields: list[str] | None = None
    columns: list[Column] | None = None
    entity_definitions: list[EntityDefinition] | None = None
    stats: dict[str, JsonValue] | None = Field(
        default=None, description="Reserved for statistics once the graph serves them."
    )
    usage: DatasetUsage | None = None
    edge_groups: list[EdgeGroup] | None = Field(
        default=None, description="Selected directed edges leaving this dataset."
    )


class EdgeReference(OpenModel):
    node_id: str = Field(min_length=1, description="The dataset that holds the directed edge.")
    edge_id: str = Field(min_length=1)


class ColumnReference(OpenModel):
    node_id: str = Field(min_length=1)
    column: str = Field(min_length=1)


class Comparison(OpenModel):
    """Two or more anchors compared on shared columns rather than joined to each other."""

    anchors: list[str] = Field(min_length=2)
    shared_columns: list[ColumnReference] = Field(min_length=1)
    comparison: ComparisonKind


class Gap(OpenModel):
    """Knowledge the objective needs that the graph cannot connect or supply."""

    description: str = Field(min_length=1)
    datasets: list[str] | None = None
    edges: list[EdgeReference] | None = None


class AkgDocument(OpenModel):
    """The graph datasets and directed edges that serve one objective."""

    status: Status
    question: str = Field(min_length=1)
    objective: str | None = None
    graph: GraphInfo | None = None
    edge_fields: list[str] = Field(
        min_length=2, description="Names of the directed-edge array positions."
    )
    datasets: list[Dataset]
    comparisons: dict[str, Comparison] | None = None
    gaps: dict[str, Gap] | None = None
