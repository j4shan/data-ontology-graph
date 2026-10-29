"""Resolve an AKG document against the graph it was built from.

The graph is either the running service, reached through its public JSON-RPC methods, or the
YAML intermediary, built into a snapshot and served by the same read service in process, so
both sources answer in one shape. A dataset is compared with `graph.get_dataset`, and each
directed edge, position by position, with `graph.get_relationship` read from the dataset that
holds it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from data_ontology_graph.akg.check import AkgFinding, dataset_location, edge_location
from data_ontology_graph.builder import build_snapshot_from_yaml
from data_ontology_graph.rpc import client
from data_ontology_graph.rpc.protocol import JsonRpcDispatcher
from data_ontology_graph.service.read import GraphReadService


GraphCall = Callable[[str, dict[str, Any]], dict[str, Any]]
"""Send one JSON-RPC request and return the full response object."""

AGENT_FIELDS = ("node_id", "usage", "edge_groups", "stats")
"""Dataset keys that are not compared with the graph."""


class ServiceSource:
    """The graph read service, reached through one JSON-RPC call function."""

    def __init__(self, call: GraphCall) -> None:
        self._call = call

    def dataset(self, node_id: str) -> tuple[dict[str, Any] | None, str]:
        return self._result("graph.get_dataset", {"node_id": node_id})

    def edge(
        self, edge_id: str, node_id: str, columns: list[str]
    ) -> tuple[dict[str, Any] | None, str]:
        """The directed edge leaving (`node_id`, `columns`), as its named positions."""
        result, error = self._result("graph.get_relationship", {
            "edge_id": edge_id, "from_node_id": node_id, "from_dataset_columns": columns,
        })
        if result is None:
            return None, error
        return dict(zip(result["edge_fields"], result["edge"])), ""

    def snapshot(self) -> dict[str, Any] | None:
        return self._result("graph.snapshot_info", {})[0]

    def _result(self, method: str, params: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        response = self._call(method, params)
        if "error" in response:
            return None, response["error"]["message"]
        return response["result"], ""


GraphSource = ServiceSource


class YamlSource(ServiceSource):
    """The YAML intermediary, as one file or a directory manifest, served in process."""

    @classmethod
    def load(cls, path: Path | str) -> "YamlSource":
        snapshot, _, _ = build_snapshot_from_yaml(path)
        return cls(dispatcher_call(JsonRpcDispatcher(GraphReadService(snapshot))))

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
    """Return one finding per element or graph value that differs from the graph.

    `payload` must already pass the document checks. Only graph values present in the document
    are compared; agent fields and unknown keys are not.
    """
    findings: list[AkgFinding] = []
    recorded = (payload.get("graph") or {}).get("snapshot")
    served = source.snapshot()
    if recorded and served:
        # The snapshot version records which data the AKG was read from; a later refresh is
        # not a mismatch, so only the API version is compared.
        if recorded.get("api_version") != served.get("api_version"):
            findings.append(_mismatch(
                "$.graph.snapshot.api_version", recorded.get("api_version"), served.get("api_version")
            ))

    fields = payload["edge_fields"]
    for dataset in payload["datasets"]:
        node_id = dataset["node_id"]
        location = dataset_location(node_id)
        record, error = source.dataset(node_id)
        if record is None:
            findings.append(_finding(location, "unknown_element", error))
            continue
        findings.extend(_compare_dataset(location, dataset, record))
        for group in dataset.get("edge_groups") or []:
            for definition in group["entity_definitions"]:
                columns = definition["dataset_columns"]
                for array in definition["edges"]:
                    edge = dict(zip(fields, array))
                    where = edge_location(node_id, group["identity_id"], columns, edge["edge_id"])
                    expected, error = source.edge(edge["edge_id"], node_id, columns)
                    if expected is None:
                        findings.append(_finding(where, "unknown_element", error))
                        continue
                    findings.extend(
                        _mismatch(f"{where}.{field}", value, expected[field])
                        for field, value in edge.items()
                        if field in expected and value != expected[field]
                    )
    return findings


def _compare_dataset(
    location: str, dataset: dict[str, Any], record: dict[str, Any]
) -> list[AkgFinding]:
    findings: list[AkgFinding] = []
    for field, value in dataset.items():
        if field in AGENT_FIELDS or field not in record:
            continue
        served = record[field]
        if field == "columns":
            findings.extend(_compare_items(
                f"{location}.columns", value, served, lambda item: item["name"],
                lambda key: repr(key), "column",
            ))
        elif field == "entity_definitions":
            findings.extend(_compare_items(
                f"{location}.entity_definitions", value, served,
                lambda item: (item["identity_id"], tuple(item["dataset_columns"])),
                lambda key: f"{key[0]!r}, {list(key[1])!r}", "entity definition",
            ))
        elif field in ("accessor", "descriptor") and isinstance(value, dict):
            findings.extend(
                _mismatch(f"{location}.{field}.{key}", item, served.get(key))
                for key, item in value.items()
                if key in served and item != served[key]
            )
        elif value != served:
            findings.append(_mismatch(f"{location}.{field}", value, served))
    return findings


def _compare_items(location, items, served, key_of, label, kind) -> list[AkgFinding]:
    """Compare listed objects with the served ones of the same key, field by field."""
    findings: list[AkgFinding] = []
    by_key = {key_of(item): item for item in served}
    for item in items:
        key = key_of(item)
        where = f"{location}[{label(key)}]"
        if key not in by_key:
            findings.append(_finding(where, "unknown_element", f"no {kind} {label(key)}"))
            continue
        findings.extend(
            _mismatch(f"{where}.{field}", value, by_key[key].get(field))
            for field, value in item.items()
            if field in by_key[key] and value != by_key[key][field]
        )
    return findings


def _mismatch(location: str, actual: Any, expected: Any) -> AkgFinding:
    return _finding(
        location, "graph_mismatch", f"document has {actual!r}, graph has {expected!r}"
    )


def _finding(location: str, rule: str, message: str) -> AkgFinding:
    return AkgFinding(location=location, rule=rule, severity="error", message=message)
