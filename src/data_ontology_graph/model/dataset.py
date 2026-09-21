from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetDescriptor(StrictModel):
    qualified_name: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str = ""
    synonyms: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class S3AccessorProperties(StrictModel):
    bucket: str = Field(min_length=1)
    prefix: str
    format: str = Field(min_length=1)


class DatabricksUnityAccessorProperties(StrictModel):
    workspace_host: str = Field(min_length=1)
    catalog: str = Field(min_length=1)
    schema_name: str = Field(alias="schema", min_length=1)
    object: str = Field(min_length=1)
    format: str | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SqlDatabaseAccessorProperties(StrictModel):
    host: str = Field(min_length=1)
    database: str = Field(min_length=1)
    schema_name: str = Field(alias="schema", min_length=1)
    object: str = Field(min_length=1)
    dialect: str = Field(min_length=1)
    format: str | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SnowflakeAccessorProperties(StrictModel):
    account: str = Field(min_length=1)
    database: str = Field(min_length=1)
    schema_name: str = Field(alias="schema", min_length=1)
    object: str = Field(min_length=1)
    format: str | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SqliteAccessorProperties(StrictModel):
    path: str = Field(min_length=1)
    object: str = Field(min_length=1)
    format: str = "sqlite"


ACCESSOR_PROPERTY_SCHEMAS: dict[str, type[BaseModel]] = {
    "accessor.s3.v1": S3AccessorProperties,
    "accessor.databricks-unity.v1": DatabricksUnityAccessorProperties,
    "accessor.sql-database.v1": SqlDatabaseAccessorProperties,
    "accessor.snowflake.v1": SnowflakeAccessorProperties,
    "accessor.sqlite.v1": SqliteAccessorProperties,
}


class DatasetAccessor(StrictModel):
    schema_id: str = Field(min_length=1)
    properties: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_known_schema(self) -> "DatasetAccessor":
        schema = ACCESSOR_PROPERTY_SCHEMAS.get(self.schema_id)
        if schema is None:
            raise ValueError(f"unknown accessor schema_id {self.schema_id!r}")
        schema.model_validate(self.properties)
        return self


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


class EntityDefinition(StrictModel):
    identity_id: str = Field(min_length=1)
    dataset_columns: list[str] = Field(min_length=1)
    is_entity_universe: bool
    entity_expression: list[str] = Field(default_factory=list)
    entity_metadata: dict[str, Any] = Field(default_factory=dict)

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

    def key(self, node_id: str) -> tuple[str, str, tuple[str, ...]]:
        return (node_id, self.identity_id, tuple(self.dataset_columns))


class DatasetNode(StrictModel):
    node_id: str = Field(min_length=1)
    descriptor: DatasetDescriptor
    accessor: DatasetAccessor
    grain: DatasetGrain | None = None
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

        if self.grain is not None:
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
