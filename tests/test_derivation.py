import pytest
from pydantic import ValidationError

from data_ontology_graph.model.dataset import (
    ColumnMetadata,
    DatasetAccessor,
    DatasetDescriptor,
    DatasetNode,
    EntityDefinition,
)
from data_ontology_graph.model.derivation import (
    contained,
    derive_relationships,
    derived_match_existence,
    derived_multiplicity,
)
from data_ontology_graph.model.enums import MatchExistence, Multiplicity


def _definition(
    columns: list[str] | None = None,
    *,
    universe: str = "partial",
    unique: bool | str = "unknown",
    total: bool | str = True,
    conforms: bool | str = "unknown",
    identity_id: str = "device",
) -> EntityDefinition:
    return EntityDefinition(
        identity_id=identity_id,
        dataset_columns=columns or ["id"],
        entity_universe=universe,
        unique=unique,
        total=total,
        conforms=conforms,
    )


def _node(name: str, definitions: list[EntityDefinition]) -> DatasetNode:
    columns = sorted({column for definition in definitions for column in definition.dataset_columns})
    return DatasetNode(
        node_id=f"dataset:{name}",
        descriptor=DatasetDescriptor(qualified_name=f"example.main.{name}", display_name=name),
        accessor=DatasetAccessor(
            schema_id="accessor.sqlite.v1",
            properties={
                "host": "localhost",
                "database_path": "/srv/sqlite/example.sqlite",
                "schema": "main",
                "object": name,
            },
        ),
        grain="unknown",
        columns=[ColumnMetadata(name=column) for column in columns],
        entity_definitions=definitions,
    )


@pytest.mark.parametrize(
    ("source", "target", "expected"),
    [
        (True, True, Multiplicity.ONE_TO_ONE),
        (False, True, Multiplicity.MANY_TO_ONE),
        (True, False, Multiplicity.ONE_TO_MANY),
        (False, False, Multiplicity.MANY_TO_MANY),
        ("unknown", True, Multiplicity.UNKNOWN),
        (True, "unknown", Multiplicity.UNKNOWN),
    ],
)
def test_multiplicity_derives_from_the_uniqueness_of_both_ends(source, target, expected) -> None:
    assert derived_multiplicity(_definition(unique=source), _definition(unique=target)) == expected


@pytest.mark.parametrize(
    ("source", "target", "expected"),
    [
        (_definition(conforms=True), _definition(universe="complete"), True),
        (_definition(universe="complete"), _definition(universe="complete"), True),
        (_definition(universe="complete"), _definition(universe="partial"), False),
        (_definition(conforms="unknown"), _definition(universe="complete"), None),
        (_definition(conforms=True), _definition(universe="partial"), None),
        (_definition(conforms=False), _definition(universe="complete"), None),
    ],
)
def test_containment_derives_from_conformance_and_universe(source, target, expected) -> None:
    assert contained(source, target) is expected


@pytest.mark.parametrize(
    ("source", "target", "expected"),
    [
        (_definition(conforms=True), _definition(universe="complete"), MatchExistence.ALWAYS),
        (
            _definition(total=False, conforms=True),
            _definition(universe="complete"),
            MatchExistence.OPTIONAL,
        ),
        (_definition(universe="complete"), _definition(universe="partial"), MatchExistence.OPTIONAL),
        (
            _definition(total="unknown", conforms=True),
            _definition(universe="complete"),
            MatchExistence.UNKNOWN,
        ),
        (_definition(conforms=True), _definition(universe="partial"), MatchExistence.UNKNOWN),
    ],
)
def test_match_existence_derives_from_totality_and_containment(source, target, expected) -> None:
    assert derived_match_existence(source, target) == expected


def test_a_complete_definition_cannot_be_declared_nonconforming() -> None:
    with pytest.raises(ValidationError, match="conforms by definition"):
        _definition(universe="complete", conforms=False)


def test_every_two_definitions_of_one_identity_are_related() -> None:
    nodes = [
        _node("a", [_definition(), _definition(["other"], identity_id="group")]),
        _node("b", [_definition()]),
        _node("c", [_definition()]),
        _node("d", [_definition(["other"], identity_id="group")]),
    ]

    relationships = derive_relationships(nodes)

    by_identity = {}
    for relationship in relationships:
        by_identity.setdefault(relationship.endpoint_a.identity_id, []).append(relationship)
    assert {identity: len(items) for identity, items in by_identity.items()} == {
        "device": 3,
        "group": 1,
    }
    assert [relationship.edge_id for relationship in relationships] == sorted(
        relationship.edge_id for relationship in relationships
    )


def test_two_definitions_on_one_dataset_are_related_as_a_self_join() -> None:
    link = _node(
        "device_link",
        [
            _definition(["device_a"], unique=False, conforms=True),
            _definition(["device_b"], universe="complete", unique=False),
        ],
    )

    [relationship] = derive_relationships([link])

    assert relationship.endpoint_a.node_id == relationship.endpoint_b.node_id == link.node_id
    assert relationship.endpoint_a.dataset_columns == ["device_a"]
    assert relationship.a_to_b.multiplicity == Multiplicity.MANY_TO_MANY
    assert relationship.a_to_b.match_existence == MatchExistence.ALWAYS
    assert relationship.b_to_a.match_existence == MatchExistence.OPTIONAL


def test_a_definition_alone_yields_no_relationship() -> None:
    assert derive_relationships([_node("a", [_definition(unique=False)])]) == []
