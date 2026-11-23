
import pytest

from data_ontology_graph.model.snapshot import GraphSnapshot
from data_ontology_graph.service.read import GraphReadService
from data_ontology_graph.service.tables import to_records
from testkit.builders import EMPLOYEE, SEED, TENANT, WAREHOUSE, fanout_service, role
from testkit.records import dataset_edges


def call(s, **params):
    return s.get_dataset_edges(SEED, identity_id=TENANT, **params).model_dump(mode="json")


def test_auto_histogram_covers_all_targets_before_detail_limits():
    s = fanout_service()
    result = call(s, limit=1)
    assert result["view"] == "aggregated"
    assert result["fan_out_count"] == 210
    assert result["logical_entity_count"] == 33
    assert result["truncated"]
    assert "datasets" not in result and "edge_fields" not in result
    rows = to_records(result["histogram"])
    assert len(rows) == 20
    assert rows[:3] == [
        {"identity_id": TENANT, "name": TENANT, "entity_definition_count": 210, "dataset_count": 210},
        {"identity_id": EMPLOYEE, "name": EMPLOYEE, "entity_definition_count": 106, "dataset_count": 105},
        {"identity_id": WAREHOUSE, "name": WAREHOUSE, "entity_definition_count": 70, "dataset_count": 70},
    ]
    assert [row["identity_id"] for row in rows[3:]] == [f"kind_{i:02}" for i in range(17)]
    assert all(row["identity_id"] != "source_only" for row in rows)


def test_auto_switches_only_above_threshold_and_explicit_views_override_it():
    s = fanout_service(4)
    assert call(s, fan_out_threshold=4)["view"] == "detailed"
    assert call(s, fan_out_threshold=3)["view"] == "aggregated"
    assert call(s, view="aggregated")["view"] == "aggregated"
    assert call(s, view="detailed", fan_out_threshold=1)["view"] == "detailed"


def test_refinement_preserves_source_scope_and_uses_and_semantics():
    s = fanout_service()
    one = call(s, target_identity_ids=[EMPLOYEE], view="aggregated")
    both = call(s, target_identity_ids=[WAREHOUSE, EMPLOYEE, EMPLOYEE], view="aggregated")
    assert one["fan_out_count"] == 105
    assert call(s, target_identity_ids=[EMPLOYEE])["view"] == "detailed"
    assert both["fan_out_count"] == 35
    assert both["target_identity_ids"] == sorted([EMPLOYEE, WAREHOUSE])
    assert both["identity_id"] == TENANT
    employee = next(row for row in to_records(both["histogram"]) if row["identity_id"] == EMPLOYEE)
    assert (employee["entity_definition_count"], employee["dataset_count"]) == (36, 35)
    # Targets can be selected even when their identity is absent from the seed and top 20.
    outside = call(s, target_identity_ids=["kind_29"])
    assert outside["view"] == "detailed" and outside["fan_out_count"] == 1
    assert [d["node_id"] for d in to_records(outside["datasets"])] == [SEED, "fanout:n0029"]


def test_repeated_source_roles_do_not_double_count_targets_and_self_joins_can_be_paged():
    from data_ontology_graph.model.dataset import ColumnMetadata

    snapshot = fanout_service(3).index.snapshot
    seed = next(node for node in snapshot.nodes if node.node_id == SEED)
    seed.columns.append(ColumnMetadata(name="tenant_alias"))
    seed.entity_definitions.append(role(TENANT, "tenant_alias"))
    s = GraphReadService(GraphSnapshot.model_validate(snapshot.model_dump()))
    summary = call(s, view="aggregated", response_format="records")
    assert summary["fan_out_count"] == 3
    tenant = next(row for row in summary["histogram"] if row["identity_id"] == TENANT)
    assert tenant["entity_definition_count"] == tenant["dataset_count"] == 3
    seen = []
    cursor = None
    for i in range(4):
        page = call(s, view="detailed", response_format="records", limit=1, cursor=cursor)
        seen.extend(dataset_edges(page["datasets"][0], page["edge_fields"]))
        cursor = page["next_cursor"]
        assert bool(cursor) == (i < 3)
    assert len(seen) == 8
    assert len({(edge["edge_id"], tuple(edge["from_dataset_columns"])) for edge in seen}) == 8
    assert len([edge for edge in seen if edge["to_node_id"] == SEED]) == 2
    assert {tuple(edge["from_dataset_columns"]) for edge in seen} == {(TENANT,), ("tenant_alias",)}
    # A target filter absent from the seed also removes same-dataset relationships.
    filtered = call(s, view="detailed", response_format="records", target_identity_ids=[EMPLOYEE])
    assert filtered["fan_out_count"] == 2
    assert all(edge["to_node_id"] != SEED for edge in dataset_edges(filtered["datasets"][0], filtered["edge_fields"]))


@pytest.mark.parametrize("target", ["unused", "source_only"])
def test_empty_results_are_not_confused_with_unknown_identities(target):
    s = fanout_service()
    detailed = call(s, target_identity_ids=[target])
    assert detailed["fan_out_count"] == 0 and detailed["next_cursor"] is None
    assert [d["node_id"] for d in to_records(detailed["datasets"])] == [SEED]
    summary = call(s, target_identity_ids=[target], view="aggregated")
    assert summary["fan_out_count"] == summary["logical_entity_count"] == 0
    assert to_records(summary["histogram"]) == []


def test_detailed_continuation_returns_each_match_once_and_bounds_pair_derivation(monkeypatch):
    s = fanout_service(9)
    original = s.index.memberships.pair
    derived = []

    def pair(left, right):
        derived.append((left, right))
        return original(left, right)

    monkeypatch.setattr(s.index.memberships, "pair", pair)
    cursor = None
    found = []
    for page_number in range(3):
        # Auto continues detailed pages even though the selection stays above the threshold.
        page = call(s, view="auto" if cursor else "detailed", fan_out_threshold=1,
                    response_format="records", limit=3, cursor=cursor)
        assert page["view"] == "detailed"
        edges = dataset_edges(page["datasets"][0], page["edge_fields"])
        assert len(edges) == 3 and page["fan_out_count"] == 9
        assert page["datasets"][0]["edge_groups"][0]["entity_definitions"][0]["edge_count"] == 9
        assert len(derived) == 3 * (page_number + 1)
        found.extend(edge["to_node_id"] for edge in edges)
        cursor = page["next_cursor"]
        assert bool(cursor) == (page_number < 2)
    assert found == [f"fanout:n{i:04}" for i in range(9)]
