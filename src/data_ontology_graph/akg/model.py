"""AKG document model.

An AKG holds the graph datasets that serve one objective, keyed by `node_id`, with trimmed graph
fields and the agent's reasoning beside them. A selected join is a directed edge stored in the
dataset traversal starts from, as navigation responses list it. Every model accepts unknown keys;
`check` reports them without rejecting the document.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from data_ontology_graph.model.enums import EntityUniverse, MatchExistence, Multiplicity


FORMAT_VERSION = 2
Status = Literal["draft", "final"]
Role = Literal["anchor", "grouping", "filter", "bridge"]
ColumnUse = Literal["measure", "count", "group", "filter", "time", "absence", "join_only", "output"]
ComparisonKind = Literal["coverage", "difference", "co_occurrence"]


class OpenModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class Snapshot(OpenModel):
    version: str = Field(min_length=1)
    schema_fingerprint: str = Field(min_length=1)


class GraphInfo(OpenModel):
    snapshot: Snapshot | None = Field(
        default=None, description="The served snapshot, recorded by `akg.py init`."
    )


class ColumnFacts(OpenModel):
    description: str | None = None
    value_description: str | None = None
    synonyms: list[str] | None = None


class EntityDefinitionFacts(OpenModel):
    identity_id: str = Field(min_length=1)
    dataset_columns: list[str] = Field(min_length=1)
    entity_universe: EntityUniverse
    description: str | None = Field(
        default=None,
        description="Effective description: the definition's own, or its single raw column's.",
    )
    description_source: Literal["entity", "column"] | None = None


class ColumnUsage(OpenModel):
    as_: ColumnUse = Field(alias="as")
    value: JsonValue = Field(default=None, description="Filter value or threshold.")
    note: str | None = None


class DatasetUsage(OpenModel):
    """Agent reasoning about one dataset."""

    role: Role | None = None
    columns: dict[str, ColumnUsage] | None = None
    note: str | None = None


class EdgeUsage(OpenModel):
    """Agent reasoning about one directed edge."""

    keep: list[str] | None = Field(
        default=None, description="Start or end node_id values whose unmatched rows must survive."
    )
    aggregate_before_join: bool | None = Field(
        default=None, description="Aggregate the end to the start's grain before combining."
    )
    note: str | None = None


class DirectedEdge(OpenModel):
    """One relationship read from the dataset that holds it, where traversal starts.

    A directed edge is identified by `edge_id` and `from_dataset_columns`: a relationship with
    both endpoints on one dataset gives that dataset two directed edges.
    """

    edge_id: str = Field(min_length=1)
    identity_id: str = Field(min_length=1)
    from_dataset_columns: list[str] = Field(min_length=1)
    to_node_id: str = Field(min_length=1)
    to_dataset_columns: list[str] = Field(min_length=1)
    multiplicity: Multiplicity
    match_existence: MatchExistence
    reverse_multiplicity: Multiplicity
    reverse_match_existence: MatchExistence
    from_description: str | None = None
    to_description: str | None = None
    stats: dict[str, JsonValue] | None = Field(
        default=None, description="Reserved for statistics once the graph serves them."
    )
    usage: EdgeUsage | None = None


class Dataset(OpenModel):
    """One graph dataset, keyed by `node_id` in the document."""

    name: str = Field(min_length=1, description="descriptor.qualified_name")
    source: str = Field(min_length=1, description="Accessor family, such as sqlite.")
    grain: list[str] | Literal["unknown"] | None = None
    columns: dict[str, ColumnFacts] | None = None
    description: str | None = None
    entity_definitions: list[EntityDefinitionFacts] | None = None
    synonyms: list[str] | None = None
    tags: list[str] | None = None
    stats: dict[str, JsonValue] | None = Field(
        default=None, description="Reserved for statistics once the graph serves them."
    )
    usage: DatasetUsage | None = None
    edges: list[DirectedEdge] | None = Field(
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

    format_version: Literal[2] = Field(description="AKG file format version.")
    status: Status
    question: str = Field(min_length=1)
    objective: str | None = None
    graph: GraphInfo | None = None
    datasets: dict[str, Dataset]
    comparisons: dict[str, Comparison] | None = None
    gaps: dict[str, Gap] | None = None
