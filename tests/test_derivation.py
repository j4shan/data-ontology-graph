from itertools import combinations

import pytest
from pydantic import ValidationError

from data_ontology_graph.model.dataset import (
    DefinitionKey,
    ColumnMetadata,
    DatasetAccessor,
    DatasetDescriptor,
    DatasetNode,
    EntityDefinition,
)
from data_ontology_graph.model.derivation import (
    contained,
    derived_match_existence,
    derived_multiplicity,
    MembershipIndex,
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


def _index(nodes: list[DatasetNode]) -> MembershipIndex:
    return MembershipIndex({node.node_id: node for node in nodes})


def _node(name: str, definitions: list[EntityDefinition]) -> DatasetNode:
    columns = sorted({column for definition in definitions for column in definition.dataset_columns})
    return DatasetNode(
        node_id=f"dataset:{name}",
        descriptor=DatasetDescriptor(qualified_name=f"example.main.{name}", display_name=name),
        accessor=DatasetAccessor(
            kind="sqlite",
            endpoint="/srv/sqlite/example.sqlite",
            properties={"host": "localhost", "schema": "main", "object": name},
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

    index = _index(nodes)

    related = {
        identity: {index.pair(left, right).edge_id for left, right in combinations(keys, 2)}
        for identity, keys in index.by_identity.items()
    }
    assert {identity: len(edge_ids) for identity, edge_ids in related.items()} == {
        "device": 3,
        "group": 1,
    }


def test_two_definitions_on_one_dataset_are_related_as_a_self_join() -> None:
    link = _node(
        "device_link",
        [
            _definition(["device_a"], unique=False, conforms=True),
            _definition(["device_b"], universe="complete", unique=False),
        ],
    )

    relationship = _index([link]).pair(*_index([link]).by_identity["device"])

    assert relationship.endpoint_a.node_id == relationship.endpoint_b.node_id == link.node_id
    assert relationship.endpoint_a.dataset_columns == ["device_a"]
    assert relationship.a_to_b.multiplicity == Multiplicity.MANY_TO_MANY
    assert relationship.a_to_b.match_existence == MatchExistence.ALWAYS
    assert relationship.b_to_a.match_existence == MatchExistence.OPTIONAL


def test_a_definition_alone_yields_no_relationship() -> None:
    index = _index([_node("a", [_definition(unique=False)])])
    assert len(index.by_identity["device"]) == 1
    assert index.degree("dataset:a") == 0


def test_membership_construction_and_counts_do_not_construct_pairs(monkeypatch) -> None:
    from data_ontology_graph.model import derivation

    nodes = [_node(str(i), [_definition(unique=i == 0)]) for i in range(40)]

    def unexpected_pair(**kwargs):
        pytest.fail("membership construction must not derive relationship objects")

    monkeypatch.setattr(derivation, "JoinRelationship", unexpected_pair)
    index = _index(nodes)
    assert len(index.definitions) == 40
    assert not hasattr(index, "endpoints")
    assert len(index.by_identity["device"]) == 40
    assert index.entity_definition_count == 40
    assert index.degree(nodes[0].node_id) == 39


def test_selected_membership_pairs_preserve_claims_ids_and_self_join_degree() -> None:
    nodes = [
        _node("a", [_definition(["source"], unique=False), _definition(["target"], unique=True)]),
        _node("b", [_definition(unique=True, universe="complete")]),
        _node("c", [_definition(identity_id="unrelated")]),
    ]
    index = _index(nodes)
    assert index.entity_definition_count == 4
    assert index.degree(nodes[0].node_id) == 4
    assert index.degree(nodes[1].node_id) == 2
    assert index.degree(nodes[2].node_id) == 0
    keys = index.by_identity["device"]
    assert isinstance(keys, list) and keys == sorted(keys)
    assert all(isinstance(key, DefinitionKey) for key in keys)
    assert [key.node_id for key in keys] == ["dataset:a", "dataset:a", "dataset:b"]
    edge = index.pair(keys[2], keys[0])
    assert edge.a_to_b.multiplicity == Multiplicity.MANY_TO_ONE
    assert edge.a_to_b.match_existence == MatchExistence.UNKNOWN
    assert index.relationship(edge.edge_id) == index.pair(keys[0], keys[2])
    assert index.resolve(edge.edge_id) == (keys[0], keys[2])
    with pytest.raises(ValueError, match="two distinct definitions"):
        index.pair(keys[0], keys[0])
    with pytest.raises(ValueError, match="same logical entity"):
        index.pair(keys[0], index.by_identity["unrelated"][0])
    with pytest.raises(KeyError):
        index.relationship("missing")


def test_membership_id_resolution_handles_unescaped_delimiters() -> None:
    index = _index([
        _node("a__b:c", [_definition(["x+y__z"], identity_id="identity:__id")]),
        _node("d__e:f", [_definition(["r:s__t"], identity_id="identity:__id")]),
    ])
    left, right = index.by_identity["identity:__id"]
    edge = index.pair(left, right)
    assert index.resolve(edge.edge_id) == (left, right)
    assert index.relationship(edge.edge_id) == edge


def test_membership_id_resolution_rejects_ambiguous_legacy_tokens() -> None:
    index = _index([
        _node("a", [_definition(["x", "y"]), _definition(["x+y"])]),
        _node("b", [_definition()]),
    ])
    keys = index.by_identity["device"]
    # The existing ID format joins columns with '+', so these two distinct pairs collide.
    assert index.edge_id(keys[0], keys[2]) == index.edge_id(keys[1], keys[2])
    with pytest.raises(ValueError, match="ambiguous relationship ID"):
        index.relationship(index.edge_id(keys[0], keys[2]))
