"""Cross-entity relationships through the read service and JSON-RPC (system design 2.3.12-2.3.13)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from data_ontology_graph.builder import build_snapshot_from_yaml
from data_ontology_graph.model.entity_relationship import EntityRelationship, EntityRelationshipIndex
from data_ontology_graph.query.entity_relationship_paths import ranked_paths
from data_ontology_graph.rpc.protocol import INVALID_PARAMS, RESOURCE_NOT_FOUND, JsonRpcDispatcher
from data_ontology_graph.service.contracts import (
    EntityRelationshipPathsRequest,
    EntityRelationshipsRequest,
    SearchRequest,
)
from data_ontology_graph.service.read import GraphReadService


STATED = Path(__file__).parent / "fixtures" / "stated_relationships" / "catalog.yaml"


@pytest.fixture(scope="module")
def service() -> GraphReadService:
    snapshot, _ = build_snapshot_from_yaml(STATED)
    return GraphReadService(snapshot)


def _call(service: GraphReadService, method: str, params: dict) -> dict:
    return JsonRpcDispatcher(service).dispatch({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})


def test_snapshot_info_counts_cross_entity_relationships(service) -> None:
    assert service.snapshot_info().entity_relationship_count == 6


def test_relationships_at_a_logical_entity_are_ordered_by_the_other_entity(service) -> None:
    response = service.get_entity_relationships(EntityRelationshipsRequest(identity_id="impression_identity"))
    assert response.name == "Impression"
    assert response.relationship_count == 2
    assert [(item.identity_id, item.name) for item in response.entity_relationships] == [
        ("campaign_identity", "Campaign"),
        ("click_identity", "Click"),
    ]
    assert response.entity_relationships[0].descriptions == ["A campaign owns the impressions it serves."]
    assert response.truncated is False and response.next_cursor is None


def test_a_self_pair_appears_once(service) -> None:
    response = service.get_entity_relationships(EntityRelationshipsRequest(identity_id="employee_identity"))
    assert [item.identity_id for item in response.entity_relationships] == ["employee_identity"]


def test_relationship_pages_continue_until_the_list_ends(service) -> None:
    first = service.get_entity_relationships(EntityRelationshipsRequest(identity_id="hashed_id_identity", limit=1))
    assert [item.identity_id for item in first.entity_relationships] == ["click_identity"]
    assert first.relationship_count == 2 and first.truncated is True
    second = service.get_entity_relationships(
        EntityRelationshipsRequest(identity_id="hashed_id_identity", limit=1, cursor=first.next_cursor)
    )
    assert [item.identity_id for item in second.entity_relationships] == ["conversion_identity"]
    assert second.next_cursor is None


def test_a_cursor_is_bound_to_its_request(service) -> None:
    first = service.get_entity_relationships(EntityRelationshipsRequest(identity_id="hashed_id_identity", limit=1))
    with pytest.raises(ValueError, match="does not match"):
        service.get_entity_relationships(
            EntityRelationshipsRequest(identity_id="impression_identity", limit=1, cursor=first.next_cursor)
        )


def test_a_logical_entity_without_relationships_has_an_empty_list(service) -> None:
    response = service.get_entity_relationships(EntityRelationshipsRequest(identity_id="order_identity"))
    assert [item.identity_id for item in response.entity_relationships] == ["calendar_day_identity"]
    snapshot, _ = build_snapshot_from_yaml(STATED)
    snapshot_without = snapshot.model_copy(update={"entity_relationships": []})
    empty = GraphReadService(type(snapshot).model_validate(snapshot_without.model_dump()))
    response = empty.get_entity_relationships(EntityRelationshipsRequest(identity_id="order_identity"))
    assert response.relationship_count == 0 and response.entity_relationships == []


def test_stated_path_reads_each_step_in_path_direction(service) -> None:
    response = service.find_entity_relationship_paths(
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


def test_paths_longer_than_max_steps_are_not_returned(service) -> None:
    response = service.find_entity_relationship_paths(
        EntityRelationshipPathsRequest(
            from_identity_id="campaign_identity", to_identity_id="conversion_identity", max_steps=3,
        )
    )
    assert response.path_count == 0 and response.paths == []


def test_logical_entities_with_no_stated_path_return_no_paths(service) -> None:
    response = service.find_entity_relationship_paths(
        EntityRelationshipPathsRequest(from_identity_id="order_identity", to_identity_id="click_identity")
    )
    assert response.path_count == 0 and response.truncated is False


def _index(pairs: list[tuple[str, str]]) -> EntityRelationshipIndex:
    return EntityRelationshipIndex(
        EntityRelationship(endpoints=tuple(sorted(pair)), descriptions=[f"{pair[0]} relates to {pair[1]}."])
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


def test_equal_endpoints_are_invalid_params(service) -> None:
    with pytest.raises(ValidationError, match="must differ"):
        EntityRelationshipPathsRequest(from_identity_id="click_identity", to_identity_id="click_identity")
    response = _call(service, "graph.find_entity_relationship_paths",
                     {"from_identity_id": "click_identity", "to_identity_id": "click_identity"})
    assert response["error"]["code"] == INVALID_PARAMS


@pytest.mark.parametrize(
    ("method", "params"),
    [
        ("graph.get_entity_relationships", {"identity_id": "missing_identity"}),
        ("graph.find_entity_relationship_paths",
         {"from_identity_id": "click_identity", "to_identity_id": "missing_identity"}),
    ],
)
def test_unknown_logical_entities_are_resource_not_found(service, method, params) -> None:
    response = _call(service, method, params)
    assert response["error"]["code"] == RESOURCE_NOT_FOUND
    assert "unknown identity missing_identity" in response["error"]["message"]


def test_methods_are_served_over_json_rpc(service) -> None:
    listed = _call(service, "graph.get_entity_relationships", {"identity_id": "click_identity", "limit": 5})
    assert [item["identity_id"] for item in listed["result"]["entity_relationships"]] == [
        "hashed_id_identity", "impression_identity",
    ]
    paths = _call(service, "graph.find_entity_relationship_paths",
                  {"from_identity_id": "click_identity", "to_identity_id": "campaign_identity", "k": 1})
    assert paths["result"]["path_count"] == 1
    assert paths["result"]["paths"][0][0] == {
        "from_identity_id": "click_identity",
        "to_identity_id": "impression_identity",
        "descriptions": [
            "An impression conditionally causes a click. A click is recorded only when the viewer clicks the "
            "served impression."
        ],
    }


def test_search_matches_cross_entity_relationship_descriptions(service) -> None:
    response = service.search(SearchRequest(query="shipped", kind=["entity_relationship"]))
    (group,) = response.groups
    assert group.kind == "entity_relationship"
    assert group.subject_row_header == ["key", "endpoints"]
    key = '["calendar_day_identity","order_identity"]'
    assert group.subject_rows == [[key, ["calendar_day_identity", "order_identity"]]]
    assert group.match_rows == [[
        key, "exact", "description", "shipped",
        "An order is shipped on one calendar day once it ships.",
    ]]


def test_search_without_kind_includes_cross_entity_relationships_in_group_order(service) -> None:
    response = service.search(SearchRequest(query="click"))
    assert [group.kind for group in response.groups] == [
        "column", "dataset", "entity_definition", "entity_relationship", "identity",
    ]


def test_search_keys_stay_distinct_when_logical_entity_ids_contain_delimiters() -> None:
    from data_ontology_graph.model.intermediary import LogicalIdentity
    from data_ontology_graph.model.snapshot import GraphSnapshot

    snapshot, _ = build_snapshot_from_yaml(STATED)
    identities = [LogicalIdentity(identity_id=value, name=value) for value in ("a", "a|b", "b|c", "c")]
    colliding = GraphSnapshot(
        version=snapshot.version,
        logical_identities=[*snapshot.logical_identities, *identities],
        nodes=snapshot.nodes,
        entity_relationships=[
            {"endpoints": ["a", "b|c"], "descriptions": ["alpha link"]},
            {"endpoints": ["a|b", "c"], "descriptions": ["alpha other"]},
        ],
    )
    (group,) = GraphReadService(colliding).search(SearchRequest(query="alpha", kind=["entity_relationship"])).groups
    keys = [row[0] for row in group.subject_rows]
    assert keys == ['["a","b|c"]', '["a|b","c"]']
    assert {row[0]: row[4] for row in group.match_rows} == {
        '["a","b|c"]': "alpha link", '["a|b","c"]': "alpha other",
    }
