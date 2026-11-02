import base64
import json

import pytest

from data_ontology_graph.model.dataset import DatasetNode, EntityDefinition
from data_ontology_graph.model.snapshot import GraphSnapshot
from data_ontology_graph.rpc.protocol import INVALID_PARAMS, RESOURCE_NOT_FOUND, JsonRpcDispatcher
from data_ontology_graph.service.read import GraphReadService
from data_ontology_graph.service.tables import to_records
from graph_records import dataset_edges


SEED = "fanout:seed"
TENANT, EMPLOYEE, WAREHOUSE = "tenant_identity", "employee_identity", "warehouse_identity"


def definition(identity, column=None, unique=False):
    return EntityDefinition(
        identity_id=identity, dataset_columns=[column or identity], unique=unique,
        total=True, conforms=True, entity_universe="complete" if unique else "partial",
    )


def service(size=210):
    """One synthetic catalog, including repeated roles and histogram groups beyond the top 20."""
    specs = [(SEED, [definition(TENANT, unique=True), definition("source_only")])]
    for i in range(size):
        definitions = [definition(TENANT)]
        if i % 2 == 0:
            definitions.append(definition(EMPLOYEE))
        if i == 0:
            definitions.append(definition(EMPLOYEE, "manager_id"))
        if i % 3 == 0:
            definitions.append(definition(WAREHOUSE))
        if i < 30:
            definitions.append(definition(f"kind_{i:02}"))
        specs.append((f"fanout:n{i:04}", definitions))
    nodes = [DatasetNode(
        node_id=name, descriptor={"qualified_name": name, "display_name": name},
        accessor={"kind": "fixture", "endpoint": "fanout", "properties": {"object": name}},
        grain="unknown", entity_definitions=definitions,
        columns=[{"name": column} for column in sorted({c for d in definitions for c in d.dataset_columns})],
    ) for name, definitions in specs]
    identities = sorted({d.identity_id for node in nodes for d in node.entity_definitions} | {"unused"})
    return GraphReadService(GraphSnapshot(
        version="2026-11-01T00:00:00Z", nodes=nodes,
        logical_identities=[{"identity_id": identity, "name": identity} for identity in identities],
    ))


def call(s, **params):
    return s.get_edges(SEED, identity_id=TENANT, **params).model_dump(mode="json")


def test_auto_histogram_covers_all_targets_before_detail_limits_and_derives_no_pairs(monkeypatch):
    s = service()

    def unexpected(*args, **kwargs):
        pytest.fail("aggregated discovery must not derive or enumerate pairwise relationships")

    monkeypatch.setattr(type(s.index.memberships), "pair", unexpected)
    monkeypatch.setattr(type(s.index.memberships), "__iter__", unexpected)
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
    s = service(4)
    assert call(s, fan_out_threshold=4)["view"] == "detailed"
    assert call(s, fan_out_threshold=3)["view"] == "aggregated"
    assert call(s, view="aggregated")["view"] == "aggregated"
    assert call(s, view="detailed", fan_out_threshold=1)["view"] == "detailed"


def test_refinement_preserves_source_scope_and_uses_and_semantics():
    s = service()
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

    snapshot = service(3).index.snapshot
    seed = next(node for node in snapshot.nodes if node.node_id == SEED)
    seed.columns.append(ColumnMetadata(name="tenant_alias"))
    seed.entity_definitions.append(definition(TENANT, "tenant_alias"))
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


def test_cursor_uses_canonical_and_filters_in_any_order():
    s = service(30)
    first = call(s, view="detailed", limit=1, target_identity_ids=[WAREHOUSE, EMPLOYEE])
    second = call(s, limit=1, target_identity_ids=[EMPLOYEE, WAREHOUSE, EMPLOYEE], cursor=first["next_cursor"])
    assert second["fan_out_count"] == first["fan_out_count"] == 5
    assert second["next_cursor"] != first["next_cursor"]


@pytest.mark.parametrize("target", ["unused", "source_only"])
def test_empty_results_are_not_confused_with_unknown_identities(target):
    s = service()
    detailed = call(s, target_identity_ids=[target])
    assert detailed["fan_out_count"] == 0 and detailed["next_cursor"] is None
    assert [d["node_id"] for d in to_records(detailed["datasets"])] == [SEED]
    summary = call(s, target_identity_ids=[target], view="aggregated")
    assert summary["fan_out_count"] == summary["logical_entity_count"] == 0
    assert to_records(summary["histogram"]) == []


def test_detailed_continuation_returns_each_match_once_and_bounds_pair_derivation(monkeypatch):
    s = service(9)
    original = s.index.memberships.pair
    derived = []

    def pair(left, right):
        derived.append((left, right))
        return original(left, right)

    monkeypatch.setattr(s.index.memberships, "pair", pair)
    cursor = None
    found = []
    for page_number in range(3):
        page = call(s, view="detailed", response_format="records", limit=3, cursor=cursor)
        edges = dataset_edges(page["datasets"][0], page["edge_fields"])
        assert len(edges) == 3 and page["fan_out_count"] == 9
        assert page["datasets"][0]["edge_groups"][0]["entity_definitions"][0]["edge_count"] == 9
        assert len(derived) == 3 * (page_number + 1)
        found.extend(edge["to_node_id"] for edge in edges)
        cursor = page["next_cursor"]
        assert bool(cursor) == (page_number < 2)
    assert found == [f"fanout:n{i:04}" for i in range(9)]


def test_cursor_binds_filters_presentation_page_size_and_snapshot():
    s = service(8)
    cursor = call(s, view="detailed", limit=2)["next_cursor"]
    assert call(s, cursor=cursor, limit=2)["view"] == "detailed"
    for change in [
        {"limit": 3}, {"target_identity_ids": [EMPLOYEE]}, {"detail": "full"},
        {"response_format": "records"}, {"fan_out_threshold": 1},
        {"fields": {"dataset": ["columns"]}},
    ]:
        with pytest.raises(ValueError, match="does not match"):
            call(s, cursor=cursor, **({"limit": 2} | change))
    # A different graph built in the same UTC second must also reject the continuation.
    with pytest.raises(ValueError, match="different snapshot"):
        call(service(9), cursor=cursor, limit=2)
    with pytest.raises(ValueError, match="cursor requires"):
        call(s, cursor=cursor, limit=2, view="aggregated")


@pytest.mark.parametrize("cursor", ["!bad", "bm90LWpzb24", "e30", "W10", "bnVsbA"])
def test_malformed_cursors_are_invalid_params(cursor):
    result = JsonRpcDispatcher(service()).dispatch({
        "jsonrpc": "2.0", "id": 1, "method": "graph.get_edges", "params": {"node_id": SEED, "cursor": cursor},
    })
    assert result["error"]["code"] == INVALID_PARAMS


def test_invalid_cursor_offsets_and_exhausted_tokens_are_rejected():
    s = service(8)
    cursor = call(s, view="detailed", limit=2)["next_cursor"]
    payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    for offset in [True, -1, 0, "2", 100]:
        changed = base64.urlsafe_b64encode(json.dumps({**payload, "offset": offset}).encode()).decode()
        with pytest.raises(ValueError, match="offset|outside"):
            call(s, cursor=changed, limit=2)


def test_rpc_validates_unknown_targets_and_new_controls_and_serializes_histograms():
    dispatcher = JsonRpcDispatcher(service())

    def rpc(**params):
        return dispatcher.dispatch({"jsonrpc": "2.0", "id": 1, "method": "graph.get_edges",
                                    "params": {"node_id": SEED, **params}})

    assert rpc(target_identity_ids=["missing"])["error"]["code"] == RESOURCE_NOT_FOUND
    for params in [
        {"target_identity_ids": [""]}, {"target_identity_ids": "tenant_identity"},
        {"view": "unknown"}, {"fan_out_threshold": 0}, {"fan_out_threshold": 10_001},
    ]:
        assert rpc(**params)["error"]["code"] == INVALID_PARAMS
    table = rpc()["result"]
    records = rpc(response_format="records")["result"]
    assert table["view"] == records["view"] == "aggregated"
    assert to_records(table["histogram"]) == records["histogram"]
    assert table["snapshot"]["api_version"] == "4"


def test_public_rpc_workflow_can_drill_down_then_exhaust_a_still_large_selection():
    dispatcher = JsonRpcDispatcher(service())
    base = {"node_id": SEED, "identity_id": TENANT, "detail": "essential",
            "response_format": "records", "fan_out_threshold": 10, "limit": 7}

    def rpc(**params):
        response = dispatcher.dispatch({
            "jsonrpc": "2.0", "id": 1, "method": "graph.get_edges", "params": base | params,
        })
        assert "error" not in response
        return response["result"]

    assert rpc()["fan_out_count"] == 210
    filters = {"target_identity_ids": [EMPLOYEE, WAREHOUSE]}
    refined = rpc(**filters)
    assert refined["view"] == "aggregated" and refined["fan_out_count"] == 35
    page = rpc(**filters, view="detailed")
    targets = []
    while True:
        assert page["view"] == "detailed" and page["fan_out_count"] == 35
        targets.extend(edge["to_node_id"] for edge in dataset_edges(page["datasets"][0], page["edge_fields"]))
        groups = page["datasets"][0]["edge_groups"]
        assert {group["identity_id"] for group in groups} == {TENANT}
        if page["next_cursor"] is None:
            break
        # Auto continues detailed pages even though this selection remains above the threshold.
        page = rpc(**filters, cursor=page["next_cursor"])
    assert targets == [f"fanout:n{i:04}" for i in range(0, 210, 6)]
