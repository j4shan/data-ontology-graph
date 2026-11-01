import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Annotated, Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from data_ontology_graph.model.claims import ClaimModel
from data_ontology_graph.model.enums import EntityUniverse, Unknown


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetDescriptor(StrictModel):
    qualified_name: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str = ""
    synonyms: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


ACCESSOR_SOFT_LIMIT = 256
"""Characters of an accessor's canonical JSON above which the build warns (graph-model 2.8)."""


class DatasetAccessor(StrictModel):
    """A credential-free path of information to a dataset's data (`product/graph-model.md#2.6`).

    The graph never follows, resolves, or interprets an accessor. Keys and values of ``labels``
    and ``properties`` are the contributor's choice.
    """

    kind: str = Field(
        pattern=r"\S",
        description="Free-text name of the kind of system the endpoint belongs to.",
    )
    endpoint: str = Field(
        pattern=r"\S",
        description=(
            "Where the path of information starts, in any form: an address, URI, account "
            "identifier, connector-plugin connection name, or shared document."
        ),
    )
    labels: dict[Annotated[str, Field(min_length=1)], str] = Field(default_factory=dict)
    properties: dict[str, JsonValue] | None = Field(default=None, min_length=1)

    def canonical_json(self) -> str:
        """The accessor as written, without absent optional fields, in canonical JSON."""
        return json.dumps(
            self.model_dump(mode="json", exclude_defaults=True),
            ensure_ascii=False, separators=(",", ":"), sort_keys=True,
        )

    def identity(self) -> tuple[str, str, str]:
        """What makes two accessors the same access location; labels are not compared."""
        return (
            self.kind,
            self.endpoint,
            json.dumps(self.properties, separators=(",", ":"), sort_keys=True),
        )


def duplicate_accessor_messages(nodes: Iterable["DatasetNode"]) -> list[str]:
    """One message per dataset whose accessor equals an earlier dataset's (graph-model 2.7)."""
    owners: dict[tuple[str, str, str], str] = {}
    messages: list[str] = []
    for node in nodes:
        key = node.accessor.identity()
        if key in owners:
            messages.append(
                f"datasets {owners[key]!r} and {node.node_id!r} have the same accessor "
                "kind, endpoint, and properties"
            )
        else:
            owners[key] = node.node_id
    return messages


class ColumnMetadata(StrictModel):
    name: str = Field(min_length=1)
    description: str = ""
    value_description: str = ""
    synonyms: list[str] = Field(default_factory=list)


class GrainComponent(StrictModel):
    dataset_columns: list[str] = Field(min_length=1)
    identity_id: str | None = None
    description: str = ""

    @field_validator("dataset_columns")
    @classmethod
    def dataset_columns_must_be_canonical(cls, value: list[str]) -> list[str]:
        if any(not column for column in value):
            raise ValueError("grain dataset_columns must not contain empty names")
        if len(value) != len(set(value)):
            raise ValueError("grain dataset_columns must not contain duplicates")
        if value != sorted(value):
            raise ValueError("grain dataset_columns must use ascending exact-name order")
        return value


class DatasetGrain(StrictModel):
    components: list[GrainComponent] = Field(min_length=1)
    description: str = ""


class EntityDefinition(ClaimModel):
    claim_fields: ClassVar[tuple[str, ...]] = ("conforms", "entity_universe", "total", "unique")

    identity_id: str = Field(min_length=1)
    dataset_columns: list[str] = Field(min_length=1)
    entity_universe: EntityUniverse
    unique: bool | Unknown = Field(
        description="Whether an instance of the logical entity appears in at most one record."
    )
    total: bool | Unknown = Field(description="Whether every record has a non-null key.")
    conforms: bool | Unknown = Field(
        description="Whether every non-null key value belongs to the logical entity's population."
    )
    entity_expression: list[str] = Field(default_factory=list)
    entity_metadata: dict[str, Any] = Field(default_factory=dict)
    description: str = Field(
        default="",
        description=(
            "What this realization identifies in its dataset, such as the role it plays. "
            "Needed mainly for composite or transformed keys and generic column descriptions."
        ),
    )

    @field_validator("identity_id")
    @classmethod
    def identity_id_must_be_nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("identity_id must not be empty")
        return value

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

    @field_validator("entity_expression")
    @classmethod
    def expressions_must_be_nonempty(cls, value: list[str]) -> list[str]:
        if any(not expression.strip() for expression in value):
            raise ValueError("entity_expression labels must not be empty")
        return value

    @model_validator(mode="after")
    def complete_must_conform(self) -> "EntityDefinition":
        if self.entity_universe == EntityUniverse.COMPLETE and self.conforms is False:
            raise ValueError("a complete entity definition conforms by definition")
        return self

    def key(self, node_id: str) -> tuple[str, str, tuple[str, ...]]:
        return (node_id, self.identity_id, tuple(self.dataset_columns))

    def conforming(self) -> bool | None:
        """Whether every non-null key value belongs to the population; None when unknown."""
        if self.entity_universe == EntityUniverse.COMPLETE or self.conforms is True:
            return True
        return False if self.conforms is False else None

    def effective_description(self, columns: list[ColumnMetadata]) -> tuple[str, str] | None:
        return effective_description(
            self.description,
            self.dataset_columns,
            self.entity_expression,
            {column.name: column.description for column in columns},
        )


RAW_REFERENCE_WRAPPERS = ("", "[]", '""', "``")


def effective_description(
    description: str,
    dataset_columns: Sequence[str],
    entity_expression: Sequence[str],
    column_descriptions: Mapping[str, str],
) -> tuple[str, str] | None:
    """Return `(text, source)` describing an entity definition, or None.

    The definition's own description wins. Otherwise a definition realized through one
    unmodified column takes that column's description. A column is unmodified when every
    expression is the bare or bracket-, quote-, or backtick-wrapped column name.
    """
    if description.strip():
        return description, "entity"
    if len(dataset_columns) != 1:
        return None
    column = dataset_columns[0]
    references = {f"{pair[:1]}{column}{pair[1:]}" for pair in RAW_REFERENCE_WRAPPERS}
    if any(expression.strip() not in references for expression in entity_expression):
        return None
    text = column_descriptions.get(column, "")
    return (text, "column") if text.strip() else None


class DatasetNode(ClaimModel):
    claim_fields: ClassVar[tuple[str, ...]] = ("grain",)

    node_id: str = Field(min_length=1)
    descriptor: DatasetDescriptor
    accessor: DatasetAccessor
    grain: DatasetGrain | Unknown
    columns: list[ColumnMetadata] = Field(min_length=1)
    entity_definitions: list[EntityDefinition] = Field(default_factory=list)

    def column_names(self) -> set[str]:
        return {column.name for column in self.columns}

    def column_map(self) -> dict[str, ColumnMetadata]:
        return {column.name: column for column in self.columns}

    @model_validator(mode="after")
    def validate_invariants(self) -> "DatasetNode":
        names = [column.name for column in self.columns]
        if len(names) != len(set(names)):
            raise ValueError("column names within a dataset must be unique")
        inventory = set(names)

        definition_keys: set[tuple[str, tuple[str, ...]]] = set()
        definitions_by_identity: dict[str, list[EntityDefinition]] = {}
        for definition in self.entity_definitions:
            missing = [column for column in definition.dataset_columns if column not in inventory]
            if missing:
                raise ValueError(
                    f"entity definition {definition.identity_id!r} uses missing columns: {missing}"
                )
            key = (definition.identity_id, tuple(definition.dataset_columns))
            if key in definition_keys:
                raise ValueError(
                    "entity definitions must be unique by identity_id and dataset_columns"
                )
            definition_keys.add(key)
            definitions_by_identity.setdefault(definition.identity_id, []).append(definition)

        if isinstance(self.grain, DatasetGrain):
            for component in self.grain.components:
                missing = [column for column in component.dataset_columns if column not in inventory]
                if missing:
                    raise ValueError(f"grain uses missing columns: {missing}")
                if component.identity_id is not None:
                    candidates = definitions_by_identity.get(component.identity_id, [])
                    if not any(
                        definition.dataset_columns == component.dataset_columns
                        for definition in candidates
                    ):
                        raise ValueError(
                            "grain component does not resolve to an entity definition: "
                            f"{component.identity_id!r}, {component.dataset_columns!r}"
                        )
        return self

    def entity_definition_map(
        self,
    ) -> dict[tuple[str, str, tuple[str, ...]], EntityDefinition]:
        return {definition.key(self.node_id): definition for definition in self.entity_definitions}
