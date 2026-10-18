"""Resolve an AKG document against the graph it was built from.

The graph is either the running service, reached through its public JSON-RPC methods, or the
YAML intermediary the snapshot was built from. Both are compared through the same projection,
so a document resolves the same way against either.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Protocol

from data_ontology_graph.akg.check import AkgFinding
from data_ontology_graph.akg.projection import project_dataset, project_relationship
from data_ontology_graph.builder.intermediary import load_intermediary_yaml
from data_ontology_graph.model.intermediary import IntermediaryDefinition
from data_ontology_graph.rpc import client
from data_ontology_graph.rpc.protocol import JsonRpcDispatcher


GraphCall = Callable[[str, dict[str, Any]], dict[str, Any]]
"""Send one JSON-RPC request and return the full response object."""

DATASET_FIELDS = ("name", "source", "grain", "description", "entity_definitions", "synonyms", "tags")
COLUMN_FIELDS = ("description", "value_description", "synonyms")


class GraphSource(Protocol):
    def dataset(self, node_id: str) -> tuple[dict[str, Any] | None, str]: ...

    def relationship(self, edge_id: str) -> tuple[dict[str, Any] | None, str]: ...

    def snapshot(self) -> dict[str, Any] | None: ...


class ServiceSource:
    """The running graph service."""

    def __init__(self, call: GraphCall) -> None:
        self._call = call

    def dataset(self, node_id: str) -> tuple[dict[str, Any] | None, str]:
        return self._result("graph.get_dataset", {"node_id": node_id})

    def relationship(self, edge_id: str) -> tuple[dict[str, Any] | None, str]:
        return self._result(
            "graph.get_relationship", {"edge_id": edge_id, "response_format": "records"}
        )

    def snapshot(self) -> dict[str, Any] | None:
        return self._result("graph.snapshot_info", {})[0]

    def _result(self, method: str, params: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        response = self._call(method, params)
        if "error" in response:
            return None, response["error"]["message"]
        return response["result"], ""


class YamlSource:
    """The YAML intermediary, as one file or a directory manifest."""

    def __init__(self, definition: IntermediaryDefinition) -> None:
        self._nodes = {node.node_id: node.model_dump(mode="json") for node in definition.nodes}
        self._edges = {edge.canonical_edge_id(): edge for edge in definition.edges}

    @classmethod
    def load(cls, path: Path | str) -> "YamlSource":
        return cls(load_intermediary_yaml(path))

    def dataset(self, node_id: str) -> tuple[dict[str, Any] | None, str]:
        node = self._nodes.get(node_id)
        return (node, "") if node else (None, f"unknown dataset {node_id}")

    def relationship(self, edge_id: str) -> tuple[dict[str, Any] | None, str]:
        edge = self._edges.get(edge_id)
        if edge is None:
            return None, f"unknown relationship {edge_id}"
        record = edge.model_dump(mode="json")
        if not edge_id.startswith(_side(record["endpoint_a"]) + "__"):
            record = {
                "endpoint_a": record["endpoint_b"],
                "endpoint_b": record["endpoint_a"],
                "a_to_b": record["b_to_a"],
                "b_to_a": record["a_to_b"],
            }
        return record, ""

    def snapshot(self) -> dict[str, Any] | None:
        return None


def dispatcher_call(dispatcher: JsonRpcDispatcher) -> GraphCall:
    def call(method: str, params: dict[str, Any]) -> dict[str, Any]:
        return dispatcher.dispatch({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})

    return call


def socket_call(socket_path: Path) -> GraphCall:
    def call(method: str, params: dict[str, Any]) -> dict[str, Any]:
        return client.call(socket_path, method, params)

    return call


def resolve_document(payload: dict[str, Any], source: GraphSource) -> list[AkgFinding]:
    """Return one finding per element or graph field that differs from the graph.

    `payload` must already pass the document model. Only graph fields present in the document
    are compared; agent fields and unknown keys are not.
    """
    findings: list[AkgFinding] = []
    recorded = (payload.get("graph") or {}).get("snapshot")
    served = source.snapshot()
    if recorded and served:
        for field in ("version", "schema_fingerprint"):
            if recorded.get(field) != served.get(field):
                findings.append(
                    _mismatch(f"$.graph.snapshot.{field}", recorded.get(field), served.get(field))
                )

    for node_id, dataset in payload["datasets"].items():
        location = f"$.datasets[{node_id!r}]"
        node, error = source.dataset(node_id)
        if node is None:
            findings.append(_finding(location, "unknown_element", error))
            continue
        findings.extend(_compare_dataset(location, dataset, project_dataset(node, "full")))

    for edge_id, relationship in payload["relationships"].items():
        location = f"$.relationships[{edge_id!r}]"
        record, error = source.relationship(edge_id)
        if record is None:
            findings.append(_finding(location, "unknown_element", error))
            continue
        expected = project_relationship(record)
        for side, claims in expected.items():
            for key, value in claims.items():
                actual = relationship[side].get(key)
                if actual != value:
                    findings.append(_mismatch(f"{location}.{side}.{key}", actual, value))
    return findings


def _compare_dataset(
    location: str, dataset: dict[str, Any], expected: dict[str, Any]
) -> list[AkgFinding]:
    findings = [
        _mismatch(f"{location}.{field}", dataset[field], expected.get(field))
        for field in DATASET_FIELDS
        if field in dataset and dataset[field] != expected.get(field)
    ]
    served_columns = expected.get("columns", {})
    for name, column in (dataset.get("columns") or {}).items():
        if name not in served_columns:
            findings.append(
                _finding(f"{location}.columns[{name!r}]", "unknown_element", f"no column {name!r}")
            )
            continue
        for field in COLUMN_FIELDS:
            if field in column and column[field] != served_columns[name].get(field):
                findings.append(
                    _mismatch(
                        f"{location}.columns[{name!r}].{field}",
                        column[field],
                        served_columns[name].get(field),
                    )
                )
    return findings


def _side(endpoint: dict[str, Any]) -> str:
    return f"{endpoint['node_id']}:{endpoint['identity_id']}:{'+'.join(endpoint['dataset_columns'])}"


def _mismatch(location: str, actual: Any, expected: Any) -> AkgFinding:
    return _finding(
        location, "graph_mismatch", f"document has {actual!r}, graph has {expected!r}"
    )


def _finding(location: str, rule: str, message: str) -> AkgFinding:
    return AkgFinding(location=location, rule=rule, severity="error", message=message)
