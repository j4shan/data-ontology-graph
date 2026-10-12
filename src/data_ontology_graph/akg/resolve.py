"""Resolve an AKG document against a served graph snapshot.

The resolver speaks only the public JSON-RPC methods, so it checks a document the same way
whether the service is in process or behind the socket.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from data_ontology_graph.akg.model import AkgDocument, GraphCut
from data_ontology_graph.builder.intermediary import ValidationFinding
from data_ontology_graph.model.intermediary import (
    IntermediaryNode,
    LogicalIdentityDefinition,
    RelationshipDefinition,
)
from data_ontology_graph.rpc import client
from data_ontology_graph.rpc.protocol import JsonRpcDispatcher


GraphCall = Callable[[str, dict[str, Any]], dict[str, Any]]
"""Send one JSON-RPC request and return the full response object."""


def dispatcher_call(dispatcher: JsonRpcDispatcher) -> GraphCall:
    def call(method: str, params: dict[str, Any]) -> dict[str, Any]:
        return dispatcher.dispatch({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})

    return call


def socket_call(socket_path: Path) -> GraphCall:
    def call(method: str, params: dict[str, Any]) -> dict[str, Any]:
        return client.call(socket_path, method, params)

    return call


def resolve_akg(document: AkgDocument, call: GraphCall) -> list[ValidationFinding]:
    """Return one finding per document value that differs from the served snapshot."""
    findings: list[ValidationFinding] = []
    info = call("graph.snapshot_info", {})
    if "error" in info:
        return [_finding("$.snapshot", "service_error", info["error"]["message"])]
    for field in ("version", "schema_fingerprint"):
        expected = info["result"][field]
        actual = getattr(document.snapshot, field)
        if actual != expected:
            findings.append(
                _mismatch(f"$.snapshot.{field}", "the served snapshot", actual, expected)
            )

    for akg_index, akg in enumerate(document.akgs):
        for cut_index, cut in enumerate(akg.cuts):
            prefix = f"$.akgs[{akg_index}].cuts[{cut_index}]"
            findings.extend(_resolve_cut(cut, prefix, call))
    return findings


def _resolve_cut(cut: GraphCut, prefix: str, call: GraphCall) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    for identity_id, identity in cut.logical_identities.items():
        location = f"{prefix}.logical_identities.{identity_id}"
        response = call("graph.get_identity", {"identity_id": identity_id, "limit": 1})
        if "error" in response:
            findings.append(_finding(location, "unknown_element", response["error"]["message"]))
            continue
        served = LogicalIdentityDefinition.model_validate(
            {key: response["result"][key] for key in ("name", "description", "synonyms")}
        )
        findings.extend(_compare(location, f"identity {identity_id!r}", identity, served))

    for index, node in enumerate(cut.nodes):
        location = f"{prefix}.nodes[{index}]"
        response = call("graph.get_dataset", {"node_id": node.node_id})
        if "error" in response:
            findings.append(_finding(location, "unknown_element", response["error"]["message"]))
            continue
        served = IntermediaryNode.model_validate(_without_unknown_fields(response["result"]))
        findings.extend(_compare(location, f"node {node.node_id!r}", node, served))

    for index, edge in enumerate(cut.edges):
        location = f"{prefix}.edges[{index}]"
        edge_id = edge.canonical_edge_id()
        response = call(
            "graph.get_relationship", {"edge_id": edge_id, "response_format": "records"}
        )
        if "error" in response:
            findings.append(_finding(location, "unknown_element", response["error"]["message"]))
            continue
        findings.extend(_compare_edge(location, edge_id, edge, response["result"]))
    return findings


def _compare_edge(
    location: str, edge_id: str, edge: RelationshipDefinition, served: dict[str, Any]
) -> list[ValidationFinding]:
    # The canonical edge ID matched, so the endpoints agree; only the authored order may differ.
    same_order = (
        edge.endpoint_a.node_id == served["endpoint_a"]["node_id"]
        and edge.endpoint_a.dataset_columns == served["endpoint_a"]["dataset_columns"]
    )
    served_claims = {
        "a_to_b": served["a_to_b" if same_order else "b_to_a"],
        "b_to_a": served["b_to_a" if same_order else "a_to_b"],
    }
    findings = []
    for direction, claims in served_claims.items():
        document_claims = getattr(edge, direction).model_dump(mode="json")
        for claim, expected in claims.items():
            if document_claims[claim] != expected:
                findings.append(
                    _mismatch(
                        f"{location}.{direction}.{claim}",
                        f"edge {edge_id!r}",
                        document_claims[claim],
                        expected,
                    )
                )
    return findings


def _compare(location: str, element: str, document: Any, served: Any) -> list[ValidationFinding]:
    actual = document.model_dump(mode="json")
    expected = served.model_dump(mode="json")
    return [
        _mismatch(f"{location}.{field}", element, actual[field], expected[field])
        for field in actual
        if actual[field] != expected[field]
    ]


def _without_unknown_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_unknown_fields(item)
            for key, item in value.items()
            if key != "unknown_fields"
        }
    if isinstance(value, list):
        return [_without_unknown_fields(item) for item in value]
    return value


def _mismatch(location: str, element: str, actual: Any, expected: Any) -> ValidationFinding:
    return _finding(
        location,
        "snapshot_mismatch",
        f"{element}: document has {_short(actual)}, snapshot has {_short(expected)}",
    )


def _finding(location: str, rule: str, message: str) -> ValidationFinding:
    return ValidationFinding(location=location, rule=rule, message=message)


def _short(value: Any, limit: int = 160) -> str:
    text = json.dumps(value, sort_keys=True)
    return text if len(text) <= limit else text[: limit - 3] + "..."
