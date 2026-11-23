"""Entity links at one logical entity through the read service and JSON-RPC (system design 2.3.12).

An entity link joins two logical entities with entity definitions on a common dataset or a stated
cross-entity relationship; ``link_kinds: "stated"`` lists the stated cross-entity relationships.
"""

import pytest

from data_ontology_graph.model.entity_relationship import EntityRelationship
from data_ontology_graph.model.enums import Multiplicity
from data_ontology_graph.service.contracts import EntityLinksRequest
from data_ontology_graph.service.read import GraphReadService
from testkit import STATED, snapshot_of
from testkit.builders import PLANT, topology_service
from testkit.rpc import dispatch



def links(service, identity_id, **kwargs):
    return service.get_entity_links(EntityLinksRequest(identity_id=identity_id, **kwargs))


def others(response):
    return [item.identity_id for item in response.links]


def test_snapshot_info_counts_cross_entity_relationships(stated_service) -> None:
    assert stated_service.snapshot_info().entity_relationship_count == 6


def test_stated_links_are_ordered_by_the_other_entity(stated_service) -> None:
    response = links(stated_service, "impression_identity", link_kinds="stated")
    assert response.name == "Impression" and response.link_count == 2
    assert [(item.identity_id, item.name) for item in response.links] == [
        ("campaign_identity", "Campaign"), ("click_identity", "Click"),
    ]
    assert response.links[0].stated.descriptions == ["A campaign owns the impressions it serves."]
    assert response.links[0].stated.id
    assert response.truncated is False and response.next_cursor is None


def test_all_link_kinds_add_the_entities_on_common_datasets(stated_service) -> None:
    stated = others(links(stated_service, "impression_identity", link_kinds="stated"))
    every = links(stated_service, "impression_identity")
    assert set(stated) < set(others(every))
    on_dataset = [item for item in every.links if item.stated is None]
    assert on_dataset and all(item.common_dataset_count >= 1 for item in on_dataset)
    stated_only = next(item for item in every.links if item.identity_id == "campaign_identity")
    assert stated_only.common_dataset_count == 0 and stated_only.multiplicities == []


def test_a_self_pair_appears_once(stated_service) -> None:
    assert others(links(stated_service, "employee_identity")) == ["employee_identity"]


def test_link_pages_continue_until_the_list_ends(stated_service) -> None:
    first = links(stated_service, "hashed_id_identity", link_kinds="stated", limit=1)
    assert others(first) == ["click_identity"] and first.link_count == 2 and first.truncated is True
    second = links(stated_service, "hashed_id_identity", link_kinds="stated", limit=1, cursor=first.next_cursor)
    assert others(second) == ["conversion_identity"] and second.next_cursor is None


def test_a_logical_entity_without_relationships_has_no_stated_links() -> None:
    snapshot = snapshot_of(STATED)
    without = snapshot.model_copy(update={"entity_relationships": []})
    empty = GraphReadService(type(snapshot).model_validate(without.model_dump()))
    response = links(empty, "order_identity", link_kinds="stated")
    assert response.link_count == 0 and response.links == []


def test_claim_filters_read_from_the_requested_entity() -> None:
    service = topology_service(*PLANT)
    [forward] = links(service, "confirmation~operation", multiplicity=["many:1"]).links
    assert forward.identity_id == "operation~order" and forward.multiplicities == [Multiplicity.MANY_TO_ONE]
    assert others(links(service, "operation~order", multiplicity=["many:1"])) == ["order~plant"]
    assert others(links(service, "operation~order", multiplicity=["1:many"])) == ["confirmation~operation"]
    assert others(links(service, "confirmation~operation")) == ["confirmation~day", "operation~order"]
    assert others(links(service, "confirmation~operation", avoid_identity_ids=["confirmation~day"])) == [
        "operation~order"]


def test_links_are_served_over_json_rpc(stated_service) -> None:
    listed = dispatch(stated_service, "graph.get_entity_links",
                   {"identity_id": "click_identity", "link_kinds": "stated", "limit": 5})
    assert [item["identity_id"] for item in listed["result"]["links"]] == ["hashed_id_identity", "impression_identity"]
    assert listed["result"]["links"][1]["stated"]["multiplicity"] == "many:1"


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


def test_stated_claims_are_read_from_the_requested_logical_entity(stated_service) -> None:
    def item(identity_id: str, other: str):
        response = links(stated_service, identity_id, link_kinds="stated")
        return next(entry for entry in response.links if entry.identity_id == other).stated

    from_impression = item("impression_identity", "click_identity")
    assert (from_impression.multiplicity, from_impression.match_existence,
            from_impression.reverse_match_existence) == ("1:many", "optional", "always")
    from_click = item("click_identity", "impression_identity")
    assert (from_click.multiplicity, from_click.match_existence,
            from_click.reverse_match_existence) == ("many:1", "always", "optional")
    assert item("employee_identity", "employee_identity").unknown_fields == ["match_existence"]
