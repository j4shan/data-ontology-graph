import pytest
from pydantic import ValidationError

from data_ontology_graph.model.dataset import (
    ColumnMetadata,
    DatasetAccessor,
    DatasetDescriptor,
    DatasetGrain,
    DatasetNode,
    EntityDefinition,
    GrainComponent,
)
from data_ontology_graph.model.enums import Cardinality, MatchExistence, Multiplicity
from data_ontology_graph.model.intermediary import LogicalIdentity
from data_ontology_graph.model.relationship import (
    JoinEndpoint,
    JoinRelationship,
    RelationshipDirection,
    derived_cardinality,
    edge_id_for,
)
from data_ontology_graph.model.snapshot import GraphSnapshot, now_utc


def _node(name: str, *, universe: bool = False) -> DatasetNode:
    return DatasetNode(
        node_id=f"dataset:{name}",
        descriptor=DatasetDescriptor(
            qualified_name=f"example.main.{name}",
            display_name=name,
        ),
        accessor=DatasetAccessor(
            schema_id="accessor.sqlite.v1",
            properties={"path": "example.sqlite", "object": name, "format": "sqlite"},
        ),
        grain=DatasetGrain(
            components=[GrainComponent(identity_id="customer", dataset_columns=["id"])]
        ),
        columns=[ColumnMetadata(name="id")],
        entity_definitions=[
            EntityDefinition(
                identity_id="customer",
                dataset_columns=["id"],
                is_entity_universe=universe,
            )
        ],
    )


def _relationship(left: DatasetNode, right: DatasetNode) -> JoinRelationship:
    endpoint_a = JoinEndpoint(
        node_id=left.node_id,
        identity_id="customer",
        dataset_columns=["id"],
    )
    endpoint_b = JoinEndpoint(
        node_id=right.node_id,
        identity_id="customer",
        dataset_columns=["id"],
    )
    return JoinRelationship(
        edge_id=edge_id_for(endpoint_a, endpoint_b),
        endpoint_a=endpoint_a,
        endpoint_b=endpoint_b,
        a_to_b=RelationshipDirection(
            multiplicity=Multiplicity.MANY_TO_ONE,
            match_existence=MatchExistence.ALWAYS,
        ),
        b_to_a=RelationshipDirection(
            multiplicity=Multiplicity.ONE_TO_MANY,
            match_existence=MatchExistence.OPTIONAL,
        ),
    )


def test_accessor_schema_dispatch_validates_provider_properties() -> None:
    with pytest.raises(ValidationError, match="unknown accessor schema_id"):
        DatasetAccessor(schema_id="accessor.unknown.v1", properties={})

    with pytest.raises(ValidationError, match="bucket"):
        DatasetAccessor(
            schema_id="accessor.s3.v1",
            properties={"prefix": "events/", "format": "parquet"},
        )


def test_duplicate_column_names_are_rejected() -> None:
    payload = _node("customer").model_dump(mode="python")
    payload["columns"].append({"name": "id"})
    with pytest.raises(ValidationError, match="column names within a dataset must be unique"):
        DatasetNode.model_validate(payload)


def test_entity_definition_columns_must_exist() -> None:
    payload = _node("customer").model_dump(mode="python")
    payload["entity_definitions"][0]["dataset_columns"] = ["missing"]
    with pytest.raises(ValidationError, match="uses missing columns"):
        DatasetNode.model_validate(payload)


def test_grain_is_singular_and_identity_components_resolve() -> None:
    node = _node("customer")
    assert node.grain is not None
    assert len(node.grain.components) == 1

    payload = node.model_dump(mode="python")
    payload["grain"]["components"][0]["identity_id"] = "missing"
    with pytest.raises(ValidationError, match="does not resolve to an entity definition"):
        DatasetNode.model_validate(payload)


def test_entity_universe_is_scoped_to_each_definition() -> None:
    subset = _node("events", universe=False)
    universe = _node("customers", universe=True)
    assert subset.entity_definitions[0].is_entity_universe is False
    assert universe.entity_definitions[0].is_entity_universe is True
    assert "is_entity_universe" not in DatasetNode.model_fields


def test_edge_identity_and_directional_cardinality() -> None:
    left = _node("events")
    right = _node("customers", universe=True)
    relationship = _relationship(left, right)

    assert edge_id_for(relationship.endpoint_a, relationship.endpoint_b) == edge_id_for(
        relationship.endpoint_b, relationship.endpoint_a
    )
    assert derived_cardinality(relationship, left.node_id) == Cardinality.N_TO_ONE
    assert derived_cardinality(relationship, right.node_id) == Cardinality.ONE_TO_N


def test_snapshot_requires_registered_endpoint_definitions() -> None:
    left = _node("events")
    right = _node("customers")
    relationship = _relationship(left, right)
    relationship.endpoint_b.node_id = "dataset:missing"
    relationship.edge_id = edge_id_for(relationship.endpoint_a, relationship.endpoint_b)

    with pytest.raises(ValidationError, match="unknown dataset"):
        GraphSnapshot(
            built_at=now_utc(),
            logical_identities=[LogicalIdentity(identity_id="customer", name="Customer")],
            nodes=[left, right],
            edges=[relationship],
        )
