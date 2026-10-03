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
from data_ontology_graph.model.enums import (
    Cardinality,
    EntityUniverse,
    MatchExistence,
    Multiplicity,
)
from data_ontology_graph.model.intermediary import LogicalIdentity
from data_ontology_graph.model.relationship import (
    JoinEndpoint,
    JoinRelationship,
    RelationshipDirection,
    derived_cardinality,
    edge_id_for,
)
from data_ontology_graph.model.snapshot import GraphSnapshot, now_utc


def _node(name: str, *, universe: EntityUniverse = EntityUniverse.PARTIAL) -> DatasetNode:
    return DatasetNode(
        node_id=f"dataset:{name}",
        descriptor=DatasetDescriptor(
            qualified_name=f"example.main.{name}",
            display_name=name,
        ),
        accessor=DatasetAccessor(
            schema_id="accessor.sqlite.v1",
            properties={
                "host": "localhost",
                "database_path": "/srv/sqlite/example.sqlite",
                "schema": "main",
                "object": name,
            },
        ),
        grain=DatasetGrain(
            components=[GrainComponent(identity_id="customer", dataset_columns=["id"])]
        ),
        columns=[ColumnMetadata(name="id")],
        entity_definitions=[
            EntityDefinition(
                identity_id="customer",
                dataset_columns=["id"],
                entity_universe=universe,
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
    subset = _node("events", universe=EntityUniverse.PARTIAL)
    universe = _node("customers", universe=EntityUniverse.COMPLETE)
    unassessed = _node("orders", universe=EntityUniverse.UNKNOWN)
    assert subset.entity_definitions[0].entity_universe == EntityUniverse.PARTIAL
    assert universe.entity_definitions[0].entity_universe == EntityUniverse.COMPLETE
    assert unassessed.entity_definitions[0].unknown_fields() == ["entity_universe"]
    assert subset.entity_definitions[0].unknown_fields() == []
    assert "entity_universe" not in DatasetNode.model_fields


def test_edge_identity_and_directional_cardinality() -> None:
    left = _node("events")
    right = _node("customers", universe=EntityUniverse.COMPLETE)
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


def test_grain_is_required_and_may_be_explicitly_unknown() -> None:
    payload = _node("customer").model_dump(mode="python")
    payload.pop("grain")
    with pytest.raises(ValidationError, match="grain"):
        DatasetNode.model_validate(payload)

    payload["grain"] = "unknown"
    node = DatasetNode.model_validate(payload)
    assert node.unknown_fields() == ["grain"]
    assert node.model_dump(mode="json")["grain"] == "unknown"


def test_descriptive_text_is_free_text_including_unknown_placeholders() -> None:
    column = ColumnMetadata(name="code", description=" Unknown ", value_description="N/A")
    assert column.description == " Unknown "
    assert column.value_description == "N/A"
    assert not hasattr(column, "unknown_fields")


def test_unknown_fields_cover_typed_claims_only() -> None:
    definition = EntityDefinition(
        identity_id="customer",
        dataset_columns=["id"],
        entity_universe=EntityUniverse.UNKNOWN,
    )
    assert definition.unknown_fields() == ["entity_universe"]
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ColumnMetadata.model_validate({"name": "code", "notes": "unresolved"})


def test_canonical_edge_order_swaps_directions_and_relative_unknowns() -> None:
    later = JoinEndpoint(node_id="dataset:z", identity_id="customer", dataset_columns=["id"])
    earlier = JoinEndpoint(node_id="dataset:a", identity_id="customer", dataset_columns=["id"])
    relationship = JoinRelationship(
        edge_id=edge_id_for(later, earlier),
        endpoint_a=later,
        endpoint_b=earlier,
        a_to_b=RelationshipDirection(
            multiplicity=Multiplicity.MANY_TO_ONE,
            match_existence=MatchExistence.UNKNOWN,
        ),
        b_to_a=RelationshipDirection(
            multiplicity=Multiplicity.ONE_TO_MANY,
            match_existence=MatchExistence.OPTIONAL,
        ),
    )

    assert relationship.endpoint_a.node_id == "dataset:a"
    assert relationship.unknown_fields() == ["b_to_a.match_existence"]
    assert relationship.unknown_fields_from("dataset:z") == ["direction.match_existence"]
    assert relationship.unknown_fields_from("dataset:a") == [
        "reverse_direction.match_existence"
    ]
