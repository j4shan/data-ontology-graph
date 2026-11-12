"""Graph API responses for every fixture catalog, pinned against expected JSON.

Regenerate with ``REGENERATE_RESPONSES=1 uv run pytest tests/test_response_characterization.py``
only when a response change is intended.
"""

import json
import os
from itertools import combinations
from pathlib import Path

import pytest

from data_ontology_graph.builder import build_snapshot_from_yaml
from data_ontology_graph.model import derivation
from data_ontology_graph.rpc.protocol import JsonRpcDispatcher
from data_ontology_graph.service.read import GraphReadService

FIXTURES = Path(__file__).parent / "fixtures"
CATALOGS = ("lending", "open_accessor")
FORMATS = ("table", "records")
DETAILS = ("essential", "full")
UNPINNED = {"version", "built_at", "next_cursor"}
"""Build-time values: the snapshot version carries the build time, and cursors its fingerprint."""


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
    elif isinstance(value, str) and "__" in value and " -> " not in value:
        found.add(value)


def _requests(snapshot) -> list[tuple[str, dict]]:
    node_ids = sorted(node.node_id for node in snapshot.nodes)
    identity_ids = sorted(identity.identity_id for identity in snapshot.logical_identities)
    requests: list[tuple[str, dict]] = []
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
                    requests.append(("graph.get_edges", {**common, "node_id": node_id, "view": view}))
                requests.append(("graph.get_edges",
                                 {**common, "node_id": node_id, "view": "detailed", "limit": 1}))
                requests.append(("graph.expand_subgraph",
                                 {**common, "seed_node_ids": [node_id], "max_depth": 2}))
                requests.append(("graph.expand_subgraph",
                                 {**common, "seed_node_ids": [node_id], "max_depth": 3,
                                  "max_nodes": 3, "limit": 1}))
    for response_format in FORMATS:
        common = {"response_format": response_format, "detail": "full"}
        for left, right in combinations(node_ids, 2):
            requests.append(("graph.find_paths",
                             {**common, "from_node_id": left, "to_node_id": right}))
            requests.append(("graph.find_paths",
                             {**common, "from_node_id": left, "to_node_id": right,
                              "allowed_multiplicities": ["many:1", "1:1"]}))
            requests.append(("graph.find_connecting_subgraph",
                             {**common, "node_ids": [left, right]}))
        requests.append(("graph.find_connecting_subgraph", {**common, "node_ids": node_ids[:16]}))
    return requests


def _responses(catalog: str) -> list[dict]:
    snapshot, _, _ = build_snapshot_from_yaml(FIXTURES / catalog / "catalog.yaml")
    dispatcher = JsonRpcDispatcher(GraphReadService(snapshot))
    calls = _requests(snapshot)
    raw = [dispatcher.dispatch({"jsonrpc": "2.0", "id": 1, "method": m, "params": p}) for m, p in calls]
    found: set[str] = set()
    _edge_ids(raw, found)
    for edge_id in sorted(found):
        calls.append(("graph.get_relationship", {"edge_id": edge_id}))
        raw.append(dispatcher.dispatch({"jsonrpc": "2.0", "id": 1, "method": "graph.get_relationship",
                                        "params": {"edge_id": edge_id}}))
        relationship = raw[-1].get("result") or {}
        for side in ("endpoint_a", "endpoint_b"):
            endpoint = relationship.get(side)
            if endpoint:
                params = {"edge_id": edge_id, "from_node_id": endpoint["node_id"],
                          "from_dataset_columns": endpoint["dataset_columns"]}
                calls.append(("graph.get_relationship", params))
                raw.append(dispatcher.dispatch({"jsonrpc": "2.0", "id": 1,
                                                "method": "graph.get_relationship", "params": params}))
    return [{"method": m, "params": p, "response": _normalized(r)} for (m, p), r in zip(calls, raw)]


@pytest.mark.parametrize("catalog", CATALOGS)
def test_responses_match_pinned_expectations(catalog: str) -> None:
    expected_path = FIXTURES / catalog / "responses.json"
    actual = _responses(catalog)
    if os.environ.get("REGENERATE_RESPONSES"):
        expected_path.write_text(json.dumps(actual, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected):
        assert got == want, (got["method"], got["params"])


@pytest.mark.parametrize("catalog", CATALOGS)
def test_requests_derive_no_more_relationships_than_they_list(catalog: str, monkeypatch) -> None:
    snapshot, _, _ = build_snapshot_from_yaml(FIXTURES / catalog / "catalog.yaml")
    dispatcher = JsonRpcDispatcher(GraphReadService(snapshot))
    calls = {"count": 0}
    original = derivation.JoinRelationship

    def counted(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(derivation, "JoinRelationship", counted)
    for method, params in _requests(snapshot):
        if method in ("graph.expand_subgraph", "graph.find_connecting_subgraph"):
            continue  # breadth-first traversal derives beyond what it lists (assessment E1)
        calls["count"] = 0
        response = dispatcher.dispatch({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        # Every listed relationship or directed edge names its edge_id, which holds "__".
        listed = json.dumps(response).count("__")
        assert calls["count"] <= listed, (method, params, calls["count"], listed)
