"""Cross-entity relationships through the read stated_service and JSON-RPC (system design 2.3.12-2.3.13)."""

import pytest
from pydantic import ValidationError

from data_ontology_graph.model.entity_relationship import EntityRelationship, EntityRelationshipIndex
from data_ontology_graph.query.entity_relationship_paths import ranked_paths
from data_ontology_graph.rpc.protocol import JsonRpcDispatcher
from data_ontology_graph.service.contracts import (
    EntityRelationshipPathsRequest,
    EntityRelationshipsRequest,
)
from data_ontology_graph.service.read import GraphReadService
from testkit import STATED, snapshot_of


def _call(stated_service: GraphReadService, method: str, params: dict) -> dict:
    return JsonRpcDispatcher(stated_service).dispatch({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})


def test_snapshot_info_counts_cross_entity_relationships(stated_service) -> None:
    assert stated_service.snapshot_info().entity_relationship_count == 6


def test_relationships_at_a_logical_entity_are_ordered_by_the_other_entity(stated_service) -> None:
    response = stated_service.get_entity_relationships(EntityRelationshipsRequest(identity_id="impression_identity"))
    assert response.name == "Impression"
    assert response.relationship_count == 2
    assert [(item.identity_id, item.name) for item in response.entity_relationships] == [
        ("campaign_identity", "Campaign"),
        ("click_identity", "Click"),
    ]
    assert response.entity_relationships[0].descriptions == ["A campaign owns the impressions it serves."]
    assert response.truncated is False and response.next_cursor is None


def test_a_self_pair_appears_once(stated_service) -> None:
    response = stated_service.get_entity_relationships(EntityRelationshipsRequest(identity_id="employee_identity"))
    assert [item.identity_id for item in response.entity_relationships] == ["employee_identity"]


def test_relationship_pages_continue_until_the_list_ends(stated_service) -> None:
    first = stated_service.get_entity_relationships(EntityRelationshipsRequest(identity_id="hashed_id_identity", limit=1))
    assert [item.identity_id for item in first.entity_relationships] == ["click_identity"]
    assert first.relationship_count == 2 and first.truncated is True
    second = stated_service.get_entity_relationships(
        EntityRelationshipsRequest(identity_id="hashed_id_identity", limit=1, cursor=first.next_cursor)
    )
    assert [item.identity_id for item in second.entity_relationships] == ["conversion_identity"]
    assert second.next_cursor is None


def test_a_logical_entity_without_relationships_has_an_empty_list(stated_service) -> None:
    response = stated_service.get_entity_relationships(EntityRelationshipsRequest(identity_id="order_identity"))
    assert [item.identity_id for item in response.entity_relationships] == ["calendar_day_identity"]
    snapshot = snapshot_of(STATED)
    snapshot_without = snapshot.model_copy(update={"entity_relationships": []})
    empty = GraphReadService(type(snapshot).model_validate(snapshot_without.model_dump()))
    response = empty.get_entity_relationships(EntityRelationshipsRequest(identity_id="order_identity"))
    assert response.relationship_count == 0 and response.entity_relationships == []


def test_stated_path_reads_each_step_in_path_direction(stated_service) -> None:
    response = stated_service.find_entity_relationship_paths(
        EntityRelationshipPathsRequest(from_identity_id="campaign_identity", to_identity_id="conversion_identity")
    )
    assert response.path_count == 1 and response.truncated is False
    assert [(step.from_identity_id, step.to_identity_id) for step in response.paths[0]] == [
        ("campaign_identity", "impression_identity"),
        ("impression_identity", "click_identity"),
        ("click_identity", "hashed_id_identity"),
        ("hashed_id_identity", "conversion_identity"),
    ]
    assert response.paths[0][1].descriptions[0].startswith("An impression conditionally causes a click.")


def test_paths_longer_than_max_steps_are_not_returned(stated_service) -> None:
    response = stated_service.find_entity_relationship_paths(
        EntityRelationshipPathsRequest(
            from_identity_id="campaign_identity", to_identity_id="conversion_identity", max_steps=3,
        )
    )
    assert response.path_count == 0 and response.paths == []


def test_logical_entities_with_no_stated_path_return_no_paths(stated_service) -> None:
    response = stated_service.find_entity_relationship_paths(
        EntityRelationshipPathsRequest(from_identity_id="order_identity", to_identity_id="click_identity")
    )
    assert response.path_count == 0 and response.truncated is False


def _index(pairs: list[tuple[str, str]]) -> EntityRelationshipIndex:
    return EntityRelationshipIndex(
        EntityRelationship(
            endpoints=tuple(sorted(pair)), multiplicity="unknown", match_existence=("unknown", "unknown"),
            descriptions=[f"{pair[0]} relates to {pair[1]}."])
        for pair in pairs
    )


def test_paths_rank_by_step_count_then_logical_entity_ids() -> None:
    index = _index([("a", "z"), ("a", "c"), ("c", "z"), ("a", "b"), ("b", "z"), ("b", "c")])
    paths, truncated = ranked_paths(index, "a", "z", limit=10, max_steps=3)
    assert paths == [
        ["a", "z"],
        ["a", "b", "z"],
        ["a", "c", "z"],
        ["a", "b", "c", "z"],
        ["a", "c", "b", "z"],
    ]
    assert truncated is False
    limited, truncated = ranked_paths(index, "a", "z", limit=2, max_steps=3)
    assert limited == paths[:2] and truncated is True


def test_paths_never_repeat_a_logical_entity_or_use_a_self_pair() -> None:
    index = _index([("a", "a"), ("a", "b"), ("b", "b"), ("b", "c")])
    paths, _ = ranked_paths(index, "a", "c", limit=10, max_steps=6)
    assert paths == [["a", "b", "c"]]


def test_equal_endpoints_are_rejected() -> None:
    with pytest.raises(ValidationError, match="must differ"):
        EntityRelationshipPathsRequest(from_identity_id="click_identity", to_identity_id="click_identity")


def test_methods_are_served_over_json_rpc(stated_service) -> None:
    listed = _call(stated_service, "graph.get_entity_relationships", {"identity_id": "click_identity", "limit": 5})
    assert [item["identity_id"] for item in listed["result"]["entity_relationships"]] == [
        "hashed_id_identity", "impression_identity",
    ]
    paths = _call(stated_service, "graph.find_entity_relationship_paths",
                  {"from_identity_id": "click_identity", "to_identity_id": "campaign_identity", "k": 1})
    assert paths["result"]["path_count"] == 1
    assert paths["result"]["paths"][0][0] == {
        "from_identity_id": "click_identity",
        "to_identity_id": "impression_identity",
        "descriptions": [
            "An impression conditionally causes a click. A click is recorded only when the viewer clicks the "
            "served impression."
        ],
        "multiplicity": "many:1",
        "match_existence": "always",
        "reverse_match_existence": "optional",
        "unknown_fields": [],
    }


def test_claims_read_from_each_endpoint() -> None:
    relationship = EntityRelationship(
        endpoints=("click_identity", "impression_identity"), multiplicity="many:1",
        match_existence=("always", "optional"), descriptions=["An impression conditionally causes a click."],
    )
    assert tuple(relationship.read_from("click_identity")) == ("many:1", "always", "optional")
    assert tuple(relationship.read_from("impression_identity")) == ("1:many", "optional", "always")
    with pytest.raises(ValueError):
        relationship.read_from("campaign_identity")


def test_self_pair_claims_read_as_stated() -> None:
    relationship = EntityRelationship(
        endpoints=("employee_identity", "employee_identity"), multiplicity="many:1",
        match_existence=("unknown", "optional"),
        descriptions=["An employee reports to one manager, who is also an employee."],
    )
    claims = relationship.read_from("employee_identity")
    assert tuple(claims) == ("many:1", "unknown", "optional")
    assert claims.unknown_fields() == ["match_existence"]
    assert relationship.unknown_fields() == ["match_existence.0"]


def test_listed_claims_are_read_from_the_requested_logical_entity(stated_service) -> None:
    def item(identity_id: str, other: str):
        response = stated_service.get_entity_relationships(EntityRelationshipsRequest(identity_id=identity_id))
        return next(entry for entry in response.entity_relationships if entry.identity_id == other)

    from_impression = item("impression_identity", "click_identity")
    assert (from_impression.multiplicity, from_impression.match_existence,
            from_impression.reverse_match_existence) == ("1:many", "optional", "always")
    from_click = item("click_identity", "impression_identity")
    assert (from_click.multiplicity, from_click.match_existence,
            from_click.reverse_match_existence) == ("many:1", "always", "optional")
    self_pair = item("employee_identity", "employee_identity")
    assert self_pair.unknown_fields == ["match_existence"]


def test_path_steps_read_claims_in_the_direction_of_travel(stated_service) -> None:
    response = stated_service.find_entity_relationship_paths(
        EntityRelationshipPathsRequest(from_identity_id="campaign_identity", to_identity_id="click_identity"),
    )
    first, second = response.paths[0]
    assert (first.from_identity_id, first.to_identity_id, first.multiplicity) == (
        "campaign_identity", "impression_identity", "1:many",
    )
    assert (second.from_identity_id, second.to_identity_id, second.multiplicity,
            second.match_existence, second.reverse_match_existence) == (
        "impression_identity", "click_identity", "1:many", "optional", "always",
    )
