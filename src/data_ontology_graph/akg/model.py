"""AKG document model.

An AKG holds the graph datasets and relationships that serve one objective, keyed by their
canonical graph identifiers, with trimmed graph fields and the agent's reasoning beside them.
Every model accepts unknown keys; `check` reports them without rejecting the document.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from data_ontology_graph.model.enums import EntityUniverse, MatchExistence, Multiplicity


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


class Endpoint(OpenModel):
    node_id: str = Field(min_length=1)
    identity_id: str = Field(min_length=1)
    dataset_columns: list[str] = Field(min_length=1)


class Direction(OpenModel):
    multiplicity: Multiplicity
    match_existence: MatchExistence


class RelationshipUsage(OpenModel):
    """Agent reasoning about one relationship."""

    from_: str | None = Field(
        default=None, alias="from", description="The endpoint node_id traversal starts from."
    )
    keep: list[str] | None = Field(
        default=None, description="Endpoint node_id values whose unmatched rows must survive."
    )
    aggregate_before_join: bool | None = None
    note: str | None = None


class Relationship(OpenModel):
    """One graph relationship, keyed by its canonical edge ID in the document."""

    endpoint_a: Endpoint
    endpoint_b: Endpoint
    a_to_b: Direction
    b_to_a: Direction
    stats: dict[str, JsonValue] | None = Field(
        default=None, description="Reserved for statistics once the graph serves them."
    )
    usage: RelationshipUsage | None = None


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
    relationships: list[str] | None = None


class AkgDocument(OpenModel):
    """The graph datasets and relationships that serve one objective."""

    status: Status
    question: str = Field(min_length=1)
    objective: str | None = None
    graph: GraphInfo | None = None
    datasets: dict[str, Dataset]
    relationships: dict[str, Relationship]
    comparisons: dict[str, Comparison] | None = None
    gaps: dict[str, Gap] | None = None
