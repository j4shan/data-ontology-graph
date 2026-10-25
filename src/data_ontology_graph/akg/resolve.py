"""Resolve an AKG document against the graph it was built from.

The graph is either the running service, reached through its public JSON-RPC methods, or the
YAML intermediary the snapshot was built from, with relationships derived as the build derives
them. Both are compared through the same projection, each directed edge as its relationship
read from the dataset that holds it, so a document resolves the same way against either.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Protocol

from data_ontology_graph.akg.check import AkgFinding
from data_ontology_graph.akg.projection import endpoint_descriptions, project_dataset, project_edge
from data_ontology_graph.builder.intermediary import load_intermediary_yaml
from data_ontology_graph.model.derivation import derive_relationships
from data_ontology_graph.model.intermediary import IntermediaryDefinition
from data_ontology_graph.rpc import client
from data_ontology_graph.rpc.protocol import JsonRpcDispatcher


GraphCall = Callable[[str, dict[str, Any]], dict[str, Any]]
"""Send one JSON-RPC request and return the full response object."""

DATASET_FIELDS = ("name", "source", "grain", "description", "entity_definitions", "synonyms", "tags")
COLUMN_FIELDS = ("description", "value_description", "synonyms")
EDGE_FIELDS = (
    "identity_id", "to_node_id", "to_dataset_columns", "multiplicity", "match_existence",
    "reverse_multiplicity", "reverse_match_existence", "from_description", "to_description",
)


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
        runtime = {node.node_id: node.to_runtime() for node in definition.nodes}
        relationships = derive_relationships(runtime.values())
        self._edges = {relationship.edge_id: relationship for relationship in relationships}
        self._descriptions = {
            (node_id, tuple(item.dataset_columns)): effective[0]
            for node_id, node in runtime.items()
            for item in node.entity_definitions
            if (effective := item.effective_description(node.columns))
        }

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
        record["entity_definitions"] = [
            {**endpoint.model_dump(mode="json"),
             "effective_description": self._descriptions.get(
                 (endpoint.node_id, tuple(endpoint.dataset_columns)))}
            for endpoint in (edge.endpoint_a, edge.endpoint_b)
        ]
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
        for index, edge in enumerate(dataset.get("edges") or []):
            findings.extend(_compare_edge(f"{location}.edges[{index}]", node_id, edge, source))
    return findings


def _compare_edge(
    location: str, node_id: str, edge: dict[str, Any], source: GraphSource
) -> list[AkgFinding]:
    record, error = source.relationship(edge["edge_id"])
    if record is None:
        return [_finding(location, "unknown_element", error)]
    try:
        expected = project_edge(
            record, node_id, edge["from_dataset_columns"], endpoint_descriptions(record)
        )
    except ValueError as error:
        return [_finding(location, "unknown_element", str(error))]
    return [
        _mismatch(f"{location}.{field}", edge[field], expected.get(field))
        for field in EDGE_FIELDS
        if field in edge and edge[field] != expected.get(field)
    ]


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


def _mismatch(location: str, actual: Any, expected: Any) -> AkgFinding:
    return _finding(
        location, "graph_mismatch", f"document has {actual!r}, graph has {expected!r}"
    )


def _finding(location: str, rule: str, message: str) -> AkgFinding:
    return AkgFinding(location=location, rule=rule, severity="error", message=message)
