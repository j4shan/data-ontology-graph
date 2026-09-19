from pydantic import BaseModel, Field, field_validator, model_validator

from data_ontology_graph.model.enums import Additivity, DatasetLayer, GrainProvenance, KeyKind, TableRole
from data_ontology_graph.model.source import Source


class KeySpec(BaseModel):
    kind: KeyKind


class ColumnMetadata(BaseModel):
    name: str
    data_type: str = ""
    description: str = ""
    synonyms: list[str] = Field(default_factory=list)
    is_nullable: bool = True
    additivity: Additivity = Additivity.UNKNOWN
    key_spec: KeySpec | None = None
    logical_name: str | None = None
    logical_transform: str | None = None

    def effective_logical_name(self) -> str:
        return self.logical_name if self.logical_name else self.name


class GrainComponent(BaseModel):
    entity_name: str
    columns: list[str]
    provenance: GrainProvenance | None = None

    @field_validator("columns")
    @classmethod
    def columns_must_be_nonempty(cls, value: list[str]) -> list[str]:
        kept = [column for column in value if column]
        if not kept:
            raise ValueError("grain component columns must not be empty")
        return kept


class DeclaredForeignKey(BaseModel):
    local_columns: list[str]
    ref_table: str
    ref_columns: list[str]
    is_mandatory: bool = False


class FilteredUniqueKey(BaseModel):
    columns: list[str]
    filter_predicate: str


class PrimaryDatasetRef(BaseModel):
    qualified_name: str
    source_type: str
    node_id: str | None = None


class DatasetNode(BaseModel):
    node_id: str
    table_name: str
    table_role: TableRole = TableRole.UNKNOWN
    is_entity_universe: bool = False
    data_source: Source
    primary_key: list[str] = Field(default_factory=list)
    foreign_key_declarations: list[DeclaredForeignKey] = Field(default_factory=list)
    grain: list[GrainComponent] = Field(default_factory=list)
    unique_keys: list[list[str]] = Field(default_factory=list)
    filtered_unique_keys: list[FilteredUniqueKey] = Field(default_factory=list)
    columns: list[ColumnMetadata] = Field(default_factory=list)
    description: str = ""
    synonyms: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    dataset_layer: DatasetLayer = DatasetLayer.PRIMARY
    primary_ref: PrimaryDatasetRef | None = None
    replica_node_ids: list[str] = Field(default_factory=list)
    pk_child_entity: dict[str, list[str]] = Field(default_factory=dict)
    logical_entity_key: dict[str, list[str]] = Field(default_factory=dict)

    def column_names(self) -> set[str]:
        return {column.name for column in self.columns}

    def column_map(self) -> dict[str, ColumnMetadata]:
        return {column.name: column for column in self.columns}

    def covers_unconditional_unique(self, columns: list[str]) -> bool:
        covered = set(columns)
        if self.primary_key and set(self.primary_key) <= covered:
            return True
        return any(set(unique) <= covered for unique in self.unique_keys)

    @model_validator(mode="after")
    def validate_invariants(self) -> "DatasetNode":
        names = [column.name for column in self.columns]
        if len(names) != len(set(names)):
            raise ValueError("column names within a node must be unique")
        inventory = set(names)

        self.grain = [component for component in self.grain if component.columns]

        if self.dataset_layer == DatasetLayer.PRIMARY:
            for column in self.primary_key:
                if column not in inventory:
                    raise ValueError(f"primary-key column {column!r} is not in the column inventory")
            for declaration in self.foreign_key_declarations:
                for column in declaration.local_columns:
                    if column not in inventory:
                        raise ValueError(
                            f"foreign-key column {column!r} is not in the column inventory"
                        )

        for unique in self.unique_keys:
            missing = [column for column in unique if column not in inventory]
            if missing:
                raise ValueError(f"unique-key columns missing from inventory: {missing}")
        for filtered in self.filtered_unique_keys:
            missing = [column for column in filtered.columns if column not in inventory]
            if missing:
                raise ValueError(f"filtered unique-key columns missing from inventory: {missing}")

        for entity, columns in self.logical_entity_key.items():
            missing = [column for column in columns if column not in inventory]
            if missing:
                raise ValueError(f"logical entity key {entity!r} uses missing columns: {missing}")
            if self.primary_key and not set(columns) <= set(self.primary_key):
                raise ValueError(
                    f"logical entity key {entity!r} must be a subset of the primary key"
                )
        return self
