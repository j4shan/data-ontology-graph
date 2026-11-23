"""Path search between logical entities (system design 2.3.6).

``topology_service`` gives each link its own logical entity, defined on the link's two datasets,
so two links meeting at a dataset are a step between their logical entities.
"""
from threading import Event

from data_ontology_graph.model.enums import Multiplicity
from data_ontology_graph.service.contracts import PathsRequest
from testkit.builders import HUB, PLANT, same_dataset_service, topology_service



def find(service, source, target, **kwargs):
    return service.find_paths(PathsRequest(source_identity_id=source, target_identity_id=target, **kwargs))


def chains(response):
    return [[e.identity_id for e in result.entities] for result in response.results]


def test_steps_read_claims_in_the_direction_of_travel():
    service = topology_service(*PLANT)
    forward = find(service, "confirmation~operation", "order~plant", max_links=3)
    assert chains(forward) == [["confirmation~operation", "operation~order", "order~plant"]]
    step = forward.results[0].links[0]
    assert (step.from_identity_id, step.to_identity_id) == ("confirmation~operation", "operation~order")
    assert step.multiplicities == [Multiplicity.MANY_TO_ONE] and step.common_dataset_count == 1
    assert step.stated is None
    backward = find(service, "order~plant", "confirmation~operation", max_links=3)
    assert [s.multiplicities for s in backward.results[0].links] == [[Multiplicity.ONE_TO_MANY]] * 2


def test_multiplicity_filter_applies_in_the_direction_of_travel():
    service = topology_service(*PLANT)
    to_one = ["many:1", "1:1"]
    assert find(service, "confirmation~operation", "order~plant", max_links=3, multiplicity=to_one).total == 1
    assert find(service, "order~plant", "confirmation~operation", max_links=3, multiplicity=to_one).total == 0
    assert find(service, "order~plant", "confirmation~operation", max_links=3, multiplicity=["1:many"]).total == 1
    # The calendar route has a many:many step, so a to-one filter removes it.
    assert find(service, "confirmation~day", "fact~plant", max_links=3).total == 1
    assert find(service, "confirmation~day", "fact~plant", max_links=3, multiplicity=to_one).total == 0


def test_an_empty_result_names_the_single_filter_changes_that_yield_results():
    service = topology_service(*PLANT)
    response = find(service, "order~plant", "confirmation~operation", max_links=3, multiplicity=["many:1", "1:1"])
    assert [(r.change, r.total) for r in response.relaxations] == [
        ({"multiplicity": ["1:1", "1:many", "many:1"], "order": "converging"}, 1),
        ({"multiplicity": None, "order": "any"}, 1),
    ]


def test_a_non_empty_result_also_names_the_changes_that_widen_it():
    service = topology_service(*PLANT)
    response = find(service, "confirmation~operation", "order~plant", max_links=3)
    assert response.total == 1
    assert [(r.change, r.total) for r in response.relaxations] == [({"max_links": 4}, 2)]
    widened = find(service, "confirmation~operation", "order~plant", max_links=4)
    assert widened.total == 2 and widened.relaxations == []


def test_the_filter_report_counts_what_each_claim_filter_keeps():
    service = topology_service(*PLANT)
    report = find(service, "order~plant", "confirmation~operation", max_links=3,
                  multiplicity=["many:1", "1:1"]).filter_report
    assert (report.unfiltered_total, report.to_one_total, report.from_one_total,
            report.converging_total, report.unknown_multiplicity_total) == (1, 0, 1, 1, 0)
    assert report.by_links == {"2": 1} and report.fewer_links_total == 1
    assert [(t.identity_id, t.path_count) for t in report.through_entities] == [("operation~order", 1)]


def test_a_path_that_meets_on_one_definition_restates_the_shorter_path():
    service = topology_service(*HUB)
    # hub~a, hub~b and hub~c are all defined on the hub dataset; through hub~b both entity links meet on
    # its one definition there, which only restates the direct step.
    assert chains(find(service, "hub~a", "hub~c")) == [["hub~a", "hub~c"]]
    kept = find(service, "hub~a", "hub~c", exclude_restatements=False)
    assert chains(kept) == [["hub~a", "hub~c"], ["hub~a", "hub~b", "hub~c"]]
    assert [r.tie_group for r in kept.results] == [0, 1]


def test_participants_in_legs_and_closed_participation():
    service = topology_service(*HUB)
    legs = find(service, "hub~a", "hub~c", participant_identity_ids=["hub~b"])
    assert legs.total == 0 and legs.leg_counts == {"hub~b": 0}
    assert legs.filter_report.leg_counts == {"hub~b": 0}
    assert [(r.change.get("participation"), r.change.get("k_unnamed"), r.total) for r in legs.relaxations] == [
        ("closed", 0, 1), ("closed", 1, 1), (None, None, 1),
    ]
    assert legs.relaxations[-1].change == {"exclude_restatements": False}
    closed = find(service, "hub~a", "hub~c", participant_identity_ids=["hub~b"], participation="closed")
    [result] = closed.results
    assert result.shape == "closed" and result.unnamed_identity_ids == []
    assert len(result.links) == 3 and result.links[0].from_identity_id == "hub~a"


def test_legs_put_each_participant_on_a_path_within_the_whole_bound():
    service = topology_service(*PLANT)
    response = find(service, "confirmation~operation", "order~plant", max_links=3,
                    participant_identity_ids=["operation~order"])
    [result] = response.results
    assert result.shape == "shared_chain" and response.leg_counts == {"operation~order": 1}
    assert result.legs == {"operation~order": ["confirmation~operation", "operation~order", "order~plant"]}
    assert find(service, "confirmation~operation", "order~plant", max_links=1,
                participant_identity_ids=["operation~order"]).total == 0


def test_stated_relationships_are_steps_with_their_claims(stated_service):
    stated = find(stated_service, "campaign_identity", "conversion_identity", max_links=4, link_kinds="stated")
    assert chains(stated) == [["campaign_identity", "impression_identity", "click_identity",
                               "hashed_id_identity", "conversion_identity"]]
    first = stated.results[0].links[0]
    assert first.stated.multiplicity == "1:many" and first.common_dataset_count == 0
    assert first.stated.descriptions == ["A campaign owns the impressions it serves."]
    second = stated.results[0].links[1]
    assert second.stated.descriptions[0].startswith("An impression conditionally causes a click.")
    assert find(stated_service, "campaign_identity", "conversion_identity", max_links=3,
                link_kinds="stated").total == 0
    # All edge kinds also join through shared datasets, so a shorter path exists.
    assert find(stated_service, "campaign_identity", "conversion_identity", max_links=3).total == 1


def test_a_self_relationship_needs_two_definitions_on_one_dataset(tmp_path):
    service = same_dataset_service(tmp_path)
    [result] = find(service, "device", "device", max_links=1).results
    assert [e.identity_id for e in result.entities] == ["device", "device"]


def test_a_self_step_inside_a_path_is_a_caller_option(tmp_path):
    service = same_dataset_service(tmp_path, site=True)
    assert chains(find(service, "device", "site")) == [["device", "site"]]
    with_self = find(service, "device", "site", self_links=True)
    assert chains(with_self) == [["device", "site"], ["device", "device", "site"]]
    assert {"self_links": True} in [r.change for r in find(service, "device", "site").relaxations]
    # A logical entity takes at most one self step, and never leaves the path to return.
    assert find(service, "device", "site", self_links=True, max_links=3).total == 2


def test_pages_continue_and_cursors_belong_to_their_request():
    service = topology_service(*HUB)
    first = find(service, "hub~a", "hub~c", exclude_restatements=False, limit=1)
    assert first.total == 2 and [r.rank for r in first.results] == [1] and first.next_cursor
    second = find(service, "hub~a", "hub~c", exclude_restatements=False, limit=1, cursor=first.next_cursor)
    assert [r.rank for r in second.results] == [2] and second.next_cursor is None


def test_cancellation_reports_a_lower_bound():
    service = topology_service(*PLANT)
    cancelled = Event()
    cancelled.set()
    response = service.find_paths(PathsRequest(source_identity_id="confirmation~operation",
                                               target_identity_id="order~plant", max_links=3), cancelled)
    assert response.total_is_lower_bound

