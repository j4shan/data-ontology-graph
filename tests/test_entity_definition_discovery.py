import base64
import json
from threading import Event

import pytest

from data_ontology_graph.model.dataset import ColumnMetadata
from data_ontology_graph.model.snapshot import GraphSnapshot
from data_ontology_graph.query.entity_definitions import EntityDefinitionDiscovery
from data_ontology_graph.rpc.protocol import INVALID_PARAMS, METHOD_NOT_FOUND, RESOURCE_NOT_FOUND, JsonRpcDispatcher
from data_ontology_graph.service.contracts import EntityDefinitionsRequest
from data_ontology_graph.service.read import GraphReadService
from data_ontology_graph.service.tables import to_records
from test_edge_discovery import EMPLOYEE, SEED, TENANT, WAREHOUSE, definition, service


def call(s, **params):
    return s.get_entity_definitions(TENANT, **params).model_dump(mode="json")


def with_roles(size=5):
    snapshot = service(size).index.snapshot
    node = next(node for node in snapshot.nodes if node.node_id == "fanout:n0000")
    node.columns.extend([ColumnMetadata(name="tenant_alias"), ColumnMetadata(name="channel_id")])
    node.entity_definitions.extend([
        definition(TENANT, "tenant_alias", unique=True), definition("channel", "channel_id"),
    ])
    payload = snapshot.model_dump()
    payload["logical_identities"].append({"identity_id": "channel", "name": "Channel"})
    return GraphReadService(GraphSnapshot.model_validate(payload))


def test_discovery_histogram_and_detail_never_construct_relationship_pairs(monkeypatch):
    s = with_roles(210)

    def unexpected(*args, **kwargs):
        pytest.fail("entity-definition discovery must use memberships without relationship pairs")

    monkeypatch.setattr(type(s.index.memberships), "pair", unexpected)
    result = call(s, limit=1)
    assert result["view"] == "aggregated"
    assert result["snapshot"]["api_version"] == "4"
    assert result["dataset_count"] == 211
    assert result["primary_definition_count"] == 212
    assert result["logical_entity_count"] == 34
    assert result["truncated"] is True
    assert "datasets" not in result and "entity_definitions" not in result and "next_cursor" not in result
    rows = to_records(result["histogram"])
    assert len(rows) == 20
    assert rows[:2] == [
        {"identity_id": EMPLOYEE, "name": EMPLOYEE, "entity_definition_count": 106, "dataset_count": 105},
        {"identity_id": WAREHOUSE, "name": WAREHOUSE, "entity_definition_count": 70, "dataset_count": 70},
    ]
    assert TENANT not in {row["identity_id"] for row in rows}
    assert [row["identity_id"] for row in rows[2:]] == ["channel", *[f"kind_{i:02}" for i in range(17)]]
    page = call(s, view="detailed", response_format="records", limit=1)
    assert page["view"] == "detailed" and len(page["datasets"]) == 1
    assert len(page["entity_definitions"]) == 2
    assert call(s, cursor=page["next_cursor"], response_format="records", limit=1)["view"] == "detailed"


def test_auto_uses_filtered_distinct_datasets_and_explicit_views_override_it():
    s = with_roles(3)
    assert call(s, dataset_threshold=4)["view"] == "detailed"
    assert call(s, dataset_threshold=3)["view"] == "aggregated"
    assert call(s, target_identity_ids=[EMPLOYEE], dataset_threshold=3)["view"] == "detailed"
    assert call(s, view="aggregated")["view"] == "aggregated"
    assert call(s, view="detailed", dataset_threshold=1)["view"] == "detailed"


def test_and_filters_recount_all_matching_datasets_and_keep_selected_histogram_entities():
    s = service()
    one = call(s, target_identity_ids=[EMPLOYEE], view="aggregated", limit=1)
    both = call(s, target_identity_ids=[WAREHOUSE, EMPLOYEE, EMPLOYEE], view="aggregated", limit=1)
    assert one["dataset_count"] == one["primary_definition_count"] == 105
    assert both["dataset_count"] == both["primary_definition_count"] == 35
    assert both["target_identity_ids"] == sorted([EMPLOYEE, WAREHOUSE])
    histogram = {row["identity_id"]: row for row in to_records(both["histogram"])}
    assert histogram[EMPLOYEE]["entity_definition_count"] == 36
    assert histogram[EMPLOYEE]["dataset_count"] == 35
    outside = call(s, target_identity_ids=["kind_29"], response_format="records")
    assert outside["view"] == "detailed" and outside["dataset_count"] == 1
    assert [node["node_id"] for node in outside["datasets"]] == ["fanout:n0029"]
    assert {item["identity_id"] for item in outside["entity_definitions"]} == {TENANT, "kind_29"}


def test_four_additional_targets_are_allowed_and_duplicates_do_not_consume_slots():
    s = with_roles()
    targets = [EMPLOYEE, WAREHOUSE, "kind_00", "channel"]
    result = call(s, target_identity_ids=targets + [EMPLOYEE], response_format="records")
    assert result["target_identity_ids"] == sorted(targets)
    assert result["dataset_count"] == 1 and result["primary_definition_count"] == 2
    assert {item["identity_id"] for item in result["entity_definitions"]} == {TENANT, *targets}
    assert len(result["entity_definitions"]) == 7


def test_universe_filter_applies_only_to_primary_definitions_before_counts_and_paging():
    s = with_roles()
    result = call(s, entity_universe=["complete"], target_identity_ids=[EMPLOYEE], response_format="records")
    assert result["dataset_count"] == result["primary_definition_count"] == 1
    assert [(d["identity_id"], d["dataset_columns"]) for d in result["entity_definitions"]] == [
        (EMPLOYEE, [EMPLOYEE]), (EMPLOYEE, ["manager_id"]), (TENANT, ["tenant_alias"]),
    ]
    # Asking for the primary again as a target must not reintroduce disqualified primary roles.
    repeated = call(s, entity_universe=["complete"], target_identity_ids=[TENANT, EMPLOYEE],
                    response_format="records")
    assert repeated["entity_definitions"] == result["entity_definitions"]
    summary = call(s, entity_universe=["complete"], target_identity_ids=[EMPLOYEE], view="aggregated")
    assert summary["dataset_count"] == summary["primary_definition_count"] == 1
    assert TENANT not in {row["identity_id"] for row in to_records(summary["histogram"])}


def test_detailed_pages_keep_roles_together_and_enumerate_each_dataset_once(monkeypatch):
    s = with_roles()

    def unexpected(*args, **kwargs):
        pytest.fail("detailed pages must not compute a histogram")

    monkeypatch.setattr(EntityDefinitionDiscovery, "histogram", unexpected)
    cursor = None
    found = []
    while True:
        result = call(s, view="auto" if cursor else "detailed", response_format="records",
                      limit=2, cursor=cursor, dataset_threshold=1)
        nodes = [node["node_id"] for node in result["datasets"]]
        assert len(nodes) == 2
        assert result["dataset_count"] == 6 and result["primary_definition_count"] == 7
        assert {d["node_id"] for d in result["entity_definitions"]} == set(nodes)
        if not found:
            assert len([d for d in result["entity_definitions"] if d["node_id"] == "fanout:n0000"]) == 2
        found.extend(nodes)
        cursor = result["next_cursor"]
        assert result["truncated"] is True
        if cursor is None:
            break
    assert found == sorted(s.index.nodes)
    assert len(set(found)) == 6
    assert call(s, limit=100)["truncated"] is False


@pytest.mark.parametrize("target", ["unused", "source_only"])
def test_known_empty_intersections_have_zero_counts_and_no_detail_or_histogram(target):
    s = service()
    for view in ("auto", "aggregated"):
        result = call(s, target_identity_ids=[EMPLOYEE, target], view=view)
        assert result["dataset_count"] == result["primary_definition_count"] == 0
        assert result["truncated"] is False
        if view == "aggregated":
            assert result["logical_entity_count"] == 0 and to_records(result["histogram"]) == []
        else:
            assert result["next_cursor"] is None
            assert to_records(result["datasets"]) == to_records(result["entity_definitions"]) == []
    empty = s.get_entity_definitions("unused")
    assert empty.dataset_count == empty.primary_definition_count == 0


def test_table_and_records_carry_identical_selected_metadata_and_counts():
    s = with_roles()
    for view in ("aggregated", "detailed"):
        params = dict(view=view, target_identity_ids=[EMPLOYEE, WAREHOUSE], limit=100)
        table = call(s, **params)
        records = call(s, **params, response_format="records")
        for field in (("histogram",) if view == "aggregated" else ("datasets", "entity_definitions")):
            assert to_records(table.pop(field)) == records.pop(field)
        assert table == records


def test_cursor_binds_full_scope_and_accepts_equivalent_filter_orders():
    s = with_roles(30)
    base = dict(limit=1, target_identity_ids=[EMPLOYEE, WAREHOUSE],
                entity_universe=["partial", "complete"])
    cursor = call(s, view="detailed", **base)["next_cursor"]
    page = call(s, cursor=cursor, limit=1, target_identity_ids=[WAREHOUSE, EMPLOYEE, EMPLOYEE],
                entity_universe=["complete", "partial", "complete"])
    assert page["view"] == "detailed" and page["next_cursor"] != cursor
    for change in [
        {"limit": 2}, {"target_identity_ids": [EMPLOYEE]}, {"entity_universe": ["complete"]},
        {"dataset_threshold": 1}, {"response_format": "records"},
    ]:
        with pytest.raises(ValueError, match="does not match"):
            call(s, cursor=cursor, **(base | change))
    with pytest.raises(ValueError, match="different snapshot"):
        call(with_roles(31), cursor=cursor, **base)
    with pytest.raises(ValueError, match="does not match"):
        s.get_entity_definitions(EMPLOYEE, cursor=cursor, **base)
    with pytest.raises(ValueError, match="cursor requires"):
        call(s, cursor=cursor, view="aggregated", **base)
    edge_cursor = s.get_edges(SEED, view="detailed", limit=1).next_cursor
    with pytest.raises(ValueError, match="does not match"):
        call(s, cursor=edge_cursor, limit=1)


@pytest.mark.parametrize("cursor", ["!bad", "bm90LWpzb24", "e30", "W10", "bnVsbA", "x" * 4097])
def test_invalid_cursors_are_reported_as_invalid_params(cursor):
    result = JsonRpcDispatcher(service()).dispatch({
        "jsonrpc": "2.0", "id": 1, "method": "graph.get_entity_definitions",
        "params": {"identity_id": TENANT, "cursor": cursor},
    })
    assert result["error"]["code"] == INVALID_PARAMS


def test_cursor_offsets_and_api_version_are_validated(monkeypatch):
    s = service(5)
    cursor = call(s, view="detailed", limit=2)["next_cursor"]
    payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    for offset in [True, -1, 0, "2", 100]:
        changed = base64.urlsafe_b64encode(json.dumps(payload | {"offset": offset}).encode()).decode()
        with pytest.raises(ValueError, match="offset|outside"):
            call(s, cursor=changed, limit=2)
    import data_ontology_graph.service.read as read
    monkeypatch.setattr(read, "API_VERSION", "future")
    with pytest.raises(ValueError, match="does not match"):
        call(s, cursor=cursor, limit=2)


@pytest.mark.parametrize("params", [
    {"identity_id": ""}, {"target_identity_ids": [""]}, {"target_identity_ids": TENANT},
    {"target_identity_ids": ["a", "b", "c", "d", "e"]}, {"target_identity_ids": None},
    {"entity_universe": []}, {"entity_universe": ["invalid"]}, {"view": "invalid"},
    {"limit": 0}, {"limit": 1001}, {"dataset_threshold": 0}, {"dataset_threshold": 10001},
    {"response_format": "invalid"}, {"unexpected": True},
])
def test_rpc_validates_filters_bounds_and_presentation(params):
    result = JsonRpcDispatcher(service()).dispatch({
        "jsonrpc": "2.0", "id": 1, "method": "graph.get_entity_definitions",
        "params": {"identity_id": TENANT, **params},
    })
    assert result["error"]["code"] == INVALID_PARAMS


def test_rpc_replaces_old_method_and_reports_unknown_entities():
    dispatcher = JsonRpcDispatcher(service())
    old = dispatcher.dispatch({"jsonrpc": "2.0", "id": 1, "method": "graph.get_identity", "params": {}})
    assert old["error"]["code"] == METHOD_NOT_FOUND
    for params in [{"identity_id": "missing"}, {"identity_id": TENANT, "target_identity_ids": ["missing"]}]:
        result = dispatcher.dispatch({"jsonrpc": "2.0", "id": 1,
                                      "method": "graph.get_entity_definitions", "params": params})
        assert result["error"]["code"] == RESOURCE_NOT_FOUND
    assert EntityDefinitionsRequest(identity_id=TENANT).target_identity_ids == []


def test_entity_discovery_honors_cancellation():
    event = Event()
    event.set()
    with pytest.raises(InterruptedError, match="cancelled"):
        service().get_entity_definitions(TENANT, cancel_event=event)


@pytest.mark.parametrize("stage,view", [("histogram", "aggregated"), ("page_definitions", "detailed")])
def test_cancellation_during_discovery_never_returns_partial_counts_or_definitions(monkeypatch, stage, view):
    event = Event()
    original = getattr(EntityDefinitionDiscovery, stage)

    def cancel(self, *args):
        event.set()
        return original(self, *args)

    monkeypatch.setattr(EntityDefinitionDiscovery, stage, cancel)
    with pytest.raises(InterruptedError, match="cancelled"):
        service().get_entity_definitions(TENANT, view=view, cancel_event=event)


def test_rpc_workflow_refines_a_histogram_and_exhausts_filtered_datasets():
    dispatcher = JsonRpcDispatcher(service())
    base = {"identity_id": TENANT, "dataset_threshold": 10, "limit": 7, "response_format": "records"}

    def rpc(**params):
        response = dispatcher.dispatch({
            "jsonrpc": "2.0", "id": 1, "method": "graph.get_entity_definitions", "params": base | params,
        })
        assert "error" not in response
        return response["result"]

    assert rpc()["dataset_count"] == 211
    filters = {"target_identity_ids": [EMPLOYEE, WAREHOUSE]}
    refined = rpc(**filters)
    assert refined["view"] == "aggregated" and refined["dataset_count"] == 35
    found = []
    page = rpc(**filters, view="detailed")
    while True:
        assert page["view"] == "detailed" and page["dataset_count"] == 35
        assert {definition["identity_id"] for definition in page["entity_definitions"]} == {
            TENANT, EMPLOYEE, WAREHOUSE,
        }
        found.extend(node["node_id"] for node in page["datasets"])
        if page["next_cursor"] is None:
            break
        page = rpc(**filters, cursor=page["next_cursor"])
    assert found == [f"fanout:n{i:04}" for i in range(0, 210, 6)]
