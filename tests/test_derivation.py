from itertools import combinations

import pytest
from pydantic import ValidationError

from data_ontology_graph.model.dataset import DatasetNode, DefinitionKey
from data_ontology_graph.model.derivation import (
    contained,
    derived_match_existence,
    derived_multiplicity,
    MembershipIndex,
)
from data_ontology_graph.model.enums import MatchExistence, Multiplicity
from testkit.builders import dataset_node, definition


def _index(nodes: list[DatasetNode]) -> MembershipIndex:
    return MembershipIndex({node.node_id: node for node in nodes})


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
    assert derived_multiplicity(definition(unique=source), definition(unique=target)) == expected


@pytest.mark.parametrize(
    ("source", "target", "expected"),
    [
        (definition(conforms=True), definition(universe="complete"), True),
        (definition(universe="complete"), definition(universe="complete"), True),
        (definition(universe="complete"), definition(universe="partial"), False),
        (definition(conforms="unknown"), definition(universe="complete"), None),
        (definition(conforms=True), definition(universe="partial"), None),
        (definition(conforms=False), definition(universe="complete"), None),
    ],
)
def test_containment_derives_from_conformance_and_universe(source, target, expected) -> None:
    assert contained(source, target) is expected


@pytest.mark.parametrize(
    ("source", "target", "expected"),
    [
        (definition(conforms=True), definition(universe="complete"), MatchExistence.ALWAYS),
        (
            definition(total=False, conforms=True),
            definition(universe="complete"),
            MatchExistence.OPTIONAL,
        ),
        (definition(universe="complete"), definition(universe="partial"), MatchExistence.OPTIONAL),
        (
            definition(total="unknown", conforms=True),
            definition(universe="complete"),
            MatchExistence.UNKNOWN,
        ),
        (definition(conforms=True), definition(universe="partial"), MatchExistence.UNKNOWN),
    ],
)
def test_match_existence_derives_from_totality_and_containment(source, target, expected) -> None:
    assert derived_match_existence(source, target) == expected


def test_a_complete_definition_cannot_be_declared_nonconforming() -> None:
    with pytest.raises(ValidationError, match="conforms by definition"):
        definition(universe="complete", conforms=False)


def test_every_two_definitions_of_one_identity_are_related() -> None:
    nodes = [
        dataset_node("a", [definition(), definition(["other"], identity_id="group")]),
        dataset_node("b", [definition()]),
        dataset_node("c", [definition()]),
        dataset_node("d", [definition(["other"], identity_id="group")]),
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
    link = dataset_node(
        "device_link",
        [
            definition(["device_a"], unique=False, conforms=True),
            definition(["device_b"], universe="complete", unique=False),
        ],
    )

    relationship = _index([link]).pair(*_index([link]).by_identity["device"])

    assert relationship.endpoint_a.node_id == relationship.endpoint_b.node_id == link.node_id
    assert relationship.endpoint_a.dataset_columns == ["device_a"]
    assert relationship.a_to_b.multiplicity == Multiplicity.MANY_TO_MANY
    assert relationship.a_to_b.match_existence == MatchExistence.ALWAYS
    assert relationship.b_to_a.match_existence == MatchExistence.OPTIONAL


def test_a_definition_alone_yields_no_relationship() -> None:
    index = _index([dataset_node("a", [definition(unique=False)])])
    assert len(index.by_identity["device"]) == 1
    assert index.degree("dataset:a") == 0


def test_membership_construction_and_counts_do_not_construct_pairs(monkeypatch) -> None:
    from data_ontology_graph.model import derivation

    nodes = [dataset_node(str(i), [definition(unique=i == 0)]) for i in range(40)]

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
        dataset_node("a", [definition(["source"], unique=False), definition(["target"], unique=True)]),
        dataset_node("b", [definition(unique=True, universe="complete")]),
        dataset_node("c", [definition(identity_id="unrelated")]),
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
        dataset_node("a__b:c", [definition(["x+y__z"], identity_id="identity:__id")]),
        dataset_node("d__e:f", [definition(["r:s__t"], identity_id="identity:__id")]),
    ])
    left, right = index.by_identity["identity:__id"]
    edge = index.pair(left, right)
    assert index.resolve(edge.edge_id) == (left, right)
    assert index.relationship(edge.edge_id) == edge


@pytest.mark.parametrize("nodes", [
    # columns ["x", "y"] and ["x+y"], each paired with b
    [dataset_node("a", [definition(["x", "y"]), definition(["x+y"])]), dataset_node("b", [definition()])],
    # (a, x:y)-(b, x:y) and (a:x, y)-(b:x, y), each on ["id"]
    [
        dataset_node("a", [definition(identity_id="x:y")]), dataset_node("b", [definition(identity_id="x:y")]),
        dataset_node("a:x", [definition(identity_id="y")]), dataset_node("b:x", [definition(identity_id="y")]),
    ],
    # a column holding the old pair separator and a dataset prefix
    [
        dataset_node("p", [definition(["id"]), definition(["id__dataset:q:device:k"])]),
        dataset_node("q", [definition(["k__dataset:r:device:id"])]),
        dataset_node("r", [definition(["id"])]),
    ],
], ids=["plus-in-column", "colon-in-ids", "separator-in-column"])
def test_free_text_names_never_make_two_relationships_share_an_id(nodes) -> None:
    """IDs compose definition ordinals, so no name can make two pairs collide (system design 3.6)."""
    index = _index(nodes)
    pairs = [pair for keys in index.by_identity.values() for pair in combinations(keys, 2)]
    edge_ids = [index.edge_id(*pair) for pair in pairs]
    assert len(set(edge_ids)) == len(pairs)
    assert [index.resolve(edge_id) for edge_id in edge_ids] == pairs


def test_definition_ids_follow_ascending_key_order() -> None:
    index = _index([
        dataset_node("b", [definition(["k"])]),
        dataset_node("a", [definition(["z"]), definition(["y"], identity_id="account")]),
    ])
    assert [index.definition_id(key) for key in sorted(index.definitions)] == ["D1", "D2", "D3"]
    assert index.edge_id(*index.by_identity["device"]) == "D2-D3"


@pytest.mark.parametrize("edge_id", [
    "D3-D2", "D2-D2", "D02-D3", "D0-D2", "D2-D9", "D1-D2", "d2-d3", "D2_D3", "", "C2-C3",
])
def test_ids_that_name_no_canonical_pair_resolve_to_nothing(edge_id: str) -> None:
    # D1 is the account definition on a; D2 and D3 are device definitions.
    index = _index([
        dataset_node("b", [definition(["k"])]),
        dataset_node("a", [definition(["z"]), definition(["y"], identity_id="account")]),
    ])
    with pytest.raises(KeyError):
        index.resolve(edge_id)
