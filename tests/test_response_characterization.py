"""Graph API responses for every fixture catalog, pinned against expected JSON Lines.

Each line of ``tests/fixtures/<catalog>/responses.jsonl`` holds one request and its response.
Regenerate with ``REGENERATE_RESPONSES=1 uv run pytest tests/test_response_characterization.py``
only when a response change is intended.
"""

import json
import os
import re
from itertools import combinations

import pytest

from data_ontology_graph.model import derivation, ids
from data_ontology_graph.rpc.protocol import JsonRpcDispatcher
from data_ontology_graph.service.read import GraphReadService
from testkit import FIXTURES, snapshot_of
from testkit.builders import SEED, TENANT, fanout_service, with_roles
from testkit.rpc import dispatch

CATALOGS = ("lending", "open_accessor", "stated_relationships")
FORMATS = ("table", "records")
DETAILS = ("essential", "standard", "full")
# Build-time values: the snapshot version carries the build time, and cursors its fingerprint.
UNPINNED = {"version", "built_at", "next_cursor"}
# Methods whose responses name no relationship, so they add no ``get_relationship`` requests.
UNLISTED = {"graph.search", "graph.get_entity_links", "graph.find_paths"}


def _normalized(value):
    if isinstance(value, dict):
        return {
            key: ("<unpinned>" if key in UNPINNED and value[key] is not None else _normalized(item))
            for key, item in value.items()
            if key != "snapshot"
        }
    if isinstance(value, list):
        return [_normalized(item) for item in value]
    return value


def _edge_ids(value, found: set[str]) -> None:
    """Collect edge IDs, which responses carry as dictionary values or directed-edge array items."""
    if isinstance(value, dict):
        for item in value.values():
            _edge_ids(item, found)
    elif isinstance(value, list):
        for item in value:
            _edge_ids(item, found)
    elif isinstance(value, str) and ids.edge_ordinals(value) is not None:
        found.add(value)


def _requests(snapshot) -> list[tuple[str, dict]]:
    node_ids = sorted(node.node_id for node in snapshot.nodes)
    identity_ids = sorted(identity.identity_id for identity in snapshot.logical_identities)
    requests: list[tuple[str, dict]] = [("graph.snapshot_info", {})]
    for node_id in node_ids:
        requests.append(("graph.get_dataset", {"node_id": node_id}))
    for identity_id in identity_ids:
        for view in ("aggregated", "detailed"):
            requests.append(("graph.get_entity_definitions",
                             {"identity_id": identity_id, "view": view}))
        requests.append(("graph.get_entity_definitions",
                         {"identity_id": identity_id, "view": "detailed", "limit": 1}))
    for response_format in FORMATS:
        for detail in DETAILS:
            common = {"response_format": response_format, "detail": detail}
            for node_id in node_ids:
                for view in ("aggregated", "detailed"):
                    requests.append(("graph.get_dataset_edges", {**common, "node_id": node_id, "view": view}))
                requests.append(("graph.get_dataset_edges",
                                 {**common, "node_id": node_id, "view": "detailed", "limit": 1}))
    names = {identity.name for identity in snapshot.logical_identities}
    names |= {node.descriptor.display_name for node in snapshot.nodes if node.descriptor.display_name}
    for query in sorted(names):
        requests.append(("graph.search", {"query": query, "limit": 1000}))
    for identity_id in identity_ids:
        requests.append(("graph.get_entity_links", {"identity_id": identity_id}))
        requests.append(("graph.get_entity_links", {"identity_id": identity_id, "link_kinds": "stated"}))
        requests.append(("graph.get_entity_links", {"identity_id": identity_id, "multiplicity": ["many:1", "1:1"]}))
    for left, right in combinations(identity_ids, 2):
        ends = {"source_identity_id": left, "target_identity_id": right}
        requests.append(("graph.find_paths", ends))
        requests.append(("graph.find_paths", {**ends, "max_links": 3, "multiplicity": ["many:1", "1:1"]}))
        requests.append(("graph.find_paths", {**ends, "link_kinds": "stated", "max_links": 4}))
    return requests


def _responses(catalog: str) -> list[dict]:
    snapshot = snapshot_of(FIXTURES / catalog / "catalog.yaml")
    dispatcher = JsonRpcDispatcher(GraphReadService(snapshot))
    calls = _requests(snapshot)
    raw = [dispatch(dispatcher, m, p) for m, p in calls]
    found: set[str] = set()
    _edge_ids([r for (m, _), r in zip(calls, raw) if m not in UNLISTED], found)
    for edge_id in sorted(found):
        calls.append(("graph.get_relationship", {"edge_id": edge_id}))
        raw.append(dispatch(dispatcher, "graph.get_relationship", {"edge_id": edge_id}))
        relationship = raw[-1].get("result") or {}
        for side in ("endpoint_a", "endpoint_b"):
            endpoint = relationship.get(side)
            if endpoint:
                params = {"edge_id": edge_id, "from_node_id": endpoint["node_id"],
                          "from_dataset_columns": endpoint["dataset_columns"]}
                calls.append(("graph.get_relationship", params))
                raw.append(dispatch(dispatcher, "graph.get_relationship", params))
    return [{"method": m, "params": p, "response": _normalized(r)} for (m, p), r in zip(calls, raw)]


@pytest.mark.parametrize("catalog", CATALOGS)
def test_responses_match_pinned_expectations(catalog: str) -> None:
    expected_path = FIXTURES / catalog / "responses.jsonl"
    actual = _responses(catalog)
    if os.environ.get("REGENERATE_RESPONSES"):
        expected_path.write_text(
            "".join(json.dumps(entry, separators=(",", ":"), sort_keys=True) + "\n" for entry in actual),
            encoding="utf-8",
        )
    lines = expected_path.read_text(encoding="utf-8").splitlines()
    expected = [json.loads(line) for line in lines]
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected):
        assert got == want, (got["method"], got["params"])


@pytest.mark.parametrize("catalog", CATALOGS)
def test_requests_derive_no_more_relationships_than_they_list(catalog: str, monkeypatch) -> None:
    snapshot = snapshot_of(FIXTURES / catalog / "catalog.yaml")
    dispatcher = JsonRpcDispatcher(GraphReadService(snapshot))
    calls = {"count": 0}
    original = derivation.JoinRelationship

    def counted(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(derivation, "JoinRelationship", counted)
    for method, params in _requests(snapshot):
        calls["count"] = 0
        response = dispatch(dispatcher, method, params)
        # Every listed relationship or directed edge names its edge_id, `D<i>-D<j>`.
        listed = len(re.findall(r'"D[1-9][0-9]*-D[1-9][0-9]*"', json.dumps(response)))
        assert calls["count"] <= listed, (method, params, calls["count"], listed)


@pytest.mark.parametrize(("build", "method", "params"), [
    (fanout_service, "graph.get_dataset_edges", {"node_id": SEED, "identity_id": TENANT}),
    (lambda: with_roles(210), "graph.get_entity_definitions", {"identity_id": TENANT}),
    (lambda: with_roles(210), "graph.get_entity_definitions", {"identity_id": TENANT, "view": "detailed", "limit": 1}),
], ids=["edges-auto-aggregated", "definitions-auto-aggregated", "definitions-detailed"])
def test_discovery_above_the_threshold_derives_no_relationships(build, method, params, monkeypatch) -> None:
    """The committed catalogs stay below the 200-dataset threshold, so automatic aggregation is
    reached only by the synthetic fan-out catalog: it must derive no relationship either."""
    service = build()
    derived = []
    original = type(service.index.memberships).pair

    def counted(self, *args, **kwargs):
        derived.append(args)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(type(service.index.memberships), "pair", counted)
    response = dispatch(service, method, params)
    assert "result" in response, response
    if "view" not in params:
        assert response["result"]["view"] == "aggregated"
    assert derived == []
