from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from data_ontology_graph.model.dataset import (
    ColumnMetadata,
    DatasetAccessor,
    DatasetDescriptor,
    DatasetGrain,
    DatasetNode,
    EntityDefinition,
)
from data_ontology_graph.model.enums import MatchExistence, Multiplicity
from data_ontology_graph.model.relationship import JoinEndpoint, RelationshipDirection, edge_id_for


class LogicalIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    synonyms: list[str] = Field(default_factory=list)


class LogicalIdentityDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str = ""
    synonyms: list[str] = Field(default_factory=list)


class IntermediaryEntityDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_id: str = Field(min_length=1)
    dataset_columns: list[str] = Field(min_length=1)
    is_entity_universe: bool
    entity_expression: list[str] = Field(default_factory=list)
    entity_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("dataset_columns")
    @classmethod
    def dataset_columns_must_be_canonical(cls, value: list[str]) -> list[str]:
        return EntityDefinition.dataset_columns_must_be_canonical(value)

    @field_validator("identity_id")
    @classmethod
    def identity_id_must_be_nonempty(cls, value: str) -> str:
        return EntityDefinition.identity_id_must_be_nonempty(value)

    @field_validator("entity_expression")
    @classmethod
    def expressions_must_be_nonempty(cls, value: list[str]) -> list[str]:
        return EntityDefinition.expressions_must_be_nonempty(value)

    def key(self, node_id: str) -> tuple[str, str, tuple[str, ...]]:
        return (node_id, self.identity_id, tuple(self.dataset_columns))

    def to_runtime(self) -> EntityDefinition:
        return EntityDefinition.model_validate(self.model_dump())


class IntermediaryNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)
    descriptor: DatasetDescriptor
    accessor: DatasetAccessor
    grain: DatasetGrain | None = None
    columns: list[ColumnMetadata] = Field(min_length=1)
    entity_definitions: list[IntermediaryEntityDefinition] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_intermediary_properties(self) -> "IntermediaryNode":
        names = [column.name for column in self.columns]
        if len(names) != len(set(names)):
            raise ValueError("column names within a node must be unique")
        inventory = set(names)
        definition_keys: set[tuple[str, tuple[str, ...]]] = set()
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
        if self.grain is not None:
            for component in self.grain.components:
                missing = [
                    column for column in component.dataset_columns if column not in inventory
                ]
                if missing:
                    raise ValueError(f"grain uses missing columns: {missing}")
                if component.identity_id is not None:
                    key = (component.identity_id, tuple(component.dataset_columns))
                    if key not in definition_keys:
                        raise ValueError(
                            "grain component does not resolve to an entity definition: "
                            f"{component.identity_id!r}, {component.dataset_columns!r}"
                        )
        return self

    def to_runtime(self) -> DatasetNode:
        return DatasetNode(
            node_id=self.node_id,
            descriptor=self.descriptor,
            accessor=self.accessor,
            grain=self.grain,
            columns=self.columns,
            entity_definitions=[definition.to_runtime() for definition in self.entity_definitions],
        )


class EntityDefinitionReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)
    identity_id: str = Field(min_length=1)
    dataset_columns: list[str] = Field(min_length=1)

    @field_validator("dataset_columns")
    @classmethod
    def dataset_columns_must_be_canonical(cls, value: list[str]) -> list[str]:
        if not value or any(not column for column in value):
            raise ValueError("dataset_columns must contain at least one column")
        if len(value) != len(set(value)):
            raise ValueError("dataset_columns must not contain duplicate columns")
        if value != sorted(value):
            raise ValueError("dataset_columns must use ascending exact-name order")
        return value

    def key(self) -> tuple[str, str, tuple[str, ...]]:
        return (self.node_id, self.identity_id, tuple(self.dataset_columns))

    def to_endpoint(self) -> JoinEndpoint:
        return JoinEndpoint(
            node_id=self.node_id,
            identity_id=self.identity_id,
            dataset_columns=self.dataset_columns,
        )


class IntermediaryRelationshipDirection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    multiplicity: Multiplicity
    match_existence: MatchExistence

    def to_runtime(self) -> RelationshipDirection:
        return RelationshipDirection(
            multiplicity=self.multiplicity,
            match_existence=self.match_existence,
        )


class RelationshipDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint_a: EntityDefinitionReference
    endpoint_b: EntityDefinitionReference
    a_to_b: IntermediaryRelationshipDirection
    b_to_a: IntermediaryRelationshipDirection

    @model_validator(mode="after")
    def validate_relationship(self) -> "RelationshipDefinition":
        if self.endpoint_a.key() == self.endpoint_b.key():
            raise ValueError("relationship endpoints must be different entity definitions")
        if self.endpoint_a.identity_id != self.endpoint_b.identity_id:
            raise ValueError("relationship endpoints must use the same identity_id")
        return self

    def canonical_edge_id(self) -> str:
        return edge_id_for(self.endpoint_a.to_endpoint(), self.endpoint_b.to_endpoint())


class IntermediaryDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2"]
    logical_identities: dict[str, LogicalIdentityDefinition] = Field(min_length=1)
    nodes: list[IntermediaryNode] = Field(min_length=1)
    edges: list[RelationshipDefinition]

    @model_validator(mode="after")
    def validate_registry_and_references(self) -> "IntermediaryDefinition":
        empty_identity_ids = [key for key in self.logical_identities if not key.strip()]
        if empty_identity_ids:
            raise ValueError("logical identity registry keys must not be blank")
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("node_id values must be unique")

        registered: set[tuple[str, str, tuple[str, ...]]] = set()
        known_identities = set(self.logical_identities)
        for node in self.nodes:
            for definition in node.entity_definitions:
                if definition.identity_id not in known_identities:
                    raise ValueError(
                        f"node {node.node_id!r} references unknown logical identity "
                        f"{definition.identity_id!r}"
                    )
                registered.add(definition.key(node.node_id))

        edge_ids: set[str] = set()
        for edge in self.edges:
            for endpoint in (edge.endpoint_a, edge.endpoint_b):
                if endpoint.key() not in registered:
                    raise ValueError(
                        "edge endpoint does not resolve to a registered entity definition: "
                        f"{endpoint.key()!r}"
                    )
            edge_id = edge.canonical_edge_id()
            if edge_id in edge_ids:
                raise ValueError(f"duplicate relationship for canonical edge {edge_id!r}")
            edge_ids.add(edge_id)
        return self

    def runtime_identities(self) -> list[LogicalIdentity]:
        return [
            LogicalIdentity(identity_id=identity_id, **definition.model_dump())
            for identity_id, definition in sorted(self.logical_identities.items())
        ]
