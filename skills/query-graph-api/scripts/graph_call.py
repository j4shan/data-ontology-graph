#!/usr/bin/env python3
"""Call the Data Ontology Graph service over its JSON-RPC 2.0 Unix-domain socket.

Standard library only; imports no graph-core code.

    graph_call.py METHOD [PARAMS_JSON] [--socket PATH] [--full [--records]] [--detail]

The socket comes from --socket or $DOG_SOCKET. The client changes into the socket's directory and
connects by basename, so socket paths longer than the platform sun_path limit still work.

By default a result is printed as a compact projection:

- search: per kind, one line per subject with each matching field value.
- get_dataset: names first, then grain, columns, and entity definitions; no accessor.
- get_identity: the datasets that realize the identity, with their entity universe.
- get_hops: one {edge_id, step} entry per hop; the step shows both directions.
- get_relationship: canonical claims, plus `direction` and `reverse_direction` when the params
  name `from_node_id`.
- find_paths: one line per path (default limit 10), fan-out-free paths first; --detail adds each
  path's {edge_id, step} hops. `fan_out` counts steps that multiply rows (1:many, many:many) and
  `unknown` counts steps with an unknown claim.
- expand_subgraph: one line per node and per edge.

`cut` is a client-side method. Given {"node_ids": [...], "edge_ids": [...]}, it fetches each node
and edge and prints one graph cut in the AKG contract's node and edge model, ready to paste into
an AKG document. --full prints the raw result; --full --records converts each table to records.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path

DEFAULT_PATH_LIMIT = 10
FAN_OUT = ("1:many", "many:many")


class ServiceError(RuntimeError):
    def __init__(self, error: dict) -> None:
        super().__init__(error.get("message", "graph service error"))
        self.error = error


def call(socket_path: Path, method: str, params: dict) -> dict:
    request = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    cwd = os.getcwd()
    os.chdir(socket_path.parent)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.connect(socket_path.name)
            conn.sendall(json.dumps(request).encode() + b"\n")
            buf = b""
            while b"\n" not in buf:
                chunk = conn.recv(65536)
                if not chunk:
                    raise ConnectionError("service closed the connection")
                buf += chunk
    finally:
        os.chdir(cwd)
    return json.loads(buf.split(b"\n", 1)[0])


def result_of(socket_path: Path, method: str, params: dict):
    response = call(socket_path, method, params)
    if "error" in response:
        raise ServiceError(response["error"])
    return response["result"]


def to_records(table: dict) -> list[dict]:
    """Convert one {"header", "rows"} table to records, nesting dotted column names."""
    records = []
    for row in table["rows"]:
        if len(row) != len(table["header"]):
            raise ValueError(f"row has {len(row)} values for {len(table['header'])} columns")
        record: dict = {}
        for column, value in zip(table["header"], row):
            *parents, leaf = column.split(".")
            target = record
            for parent in parents:
                target = target.setdefault(parent, {})
            target[leaf] = value
        records.append(record)
    return records


def expand_tables(result):
    """Replace every table in a result with its records; other values are unchanged."""
    if isinstance(result, dict):
        if set(result) == {"header", "rows"}:
            return to_records(result)
        return {key: expand_tables(value) for key, value in result.items()}
    if isinstance(result, list):
        return [expand_tables(value) for value in result]
    return result


def _claims(direction: dict | None) -> str:
    if direction is None:
        return "-"
    return f'{direction["multiplicity"]}/{direction["match_existence"]}'


def _side(endpoint: dict) -> str:
    return f'{endpoint["node_id"]}[{",".join(endpoint["dataset_columns"])}]'


def _columns(relationship: dict, node_id: str) -> list[str]:
    for side in ("endpoint_a", "endpoint_b"):
        if relationship[side]["node_id"] == node_id:
            return relationship[side]["dataset_columns"]
    raise KeyError(node_id)


def _step(relationships: dict, step: dict) -> str:
    """One hop as `from[cols] -> to[cols] identity direction | reverse`."""
    relationship = relationships[step["edge_id"]]
    origin = f'{step["from_node_id"]}[{",".join(_columns(relationship, step["from_node_id"]))}]'
    target = f'{step["to_node_id"]}[{",".join(_columns(relationship, step["to_node_id"]))}]'
    unknown = f' unknown={",".join(step["unknown_fields"])}' if step["unknown_fields"] else ""
    return (
        f'{origin} -> {target} {relationship["identity_id"]} '
        f'{_claims(step["direction"])} | reverse {_claims(step["reverse_direction"])}{unknown}'
    )


def _subject(kind: str, subject: dict) -> str:
    if kind == "column":
        label = f'{subject["node_id"]}.{subject["column_name"]}'
    elif kind == "dataset":
        label = f'{subject["key"]} ({subject["display_name"]})'
    elif kind == "entity_definition":
        label = (
            f'{subject["node_id"]}[{",".join(subject["dataset_columns"])}] '
            f'{subject["identity_id"]}'
        )
    else:
        label = f'{subject["key"]} ({subject["name"]})'
    unknown = subject.get("unknown_fields")
    return f'{label} unknown={",".join(unknown)}' if unknown else label


def _search(result: dict) -> dict:
    groups = []
    for group in result["groups"]:
        matches: dict[str, list[str]] = {}
        for row in group["match_rows"]:
            match = dict(zip(group["match_row_header"], row))
            value = str(match["matched_value"])
            value = value if len(value) <= 60 else value[:57] + "..."
            matches.setdefault(match["key"], []).append(
                f'{match["match_type"]}:{match["match_field"]}={value!r}'
            )
        hits = []
        for row in group["subject_rows"]:
            subject = dict(zip(group["subject_row_header"], row))
            hits.append(f'{_subject(group["kind"], subject)} <- {"; ".join(matches[subject["key"]])}')
        groups.append({"kind": group["kind"], "truncated": group["truncated"], "hits": hits})
    return {"normalized_query": result["normalized_query"], "truncated": result["truncated"],
            "groups": groups}


def _hop(relationships: dict, step: dict) -> dict:
    return {"edge_id": step["edge_id"], "step": _step(relationships, step)}


def compact(method: str, result, *, detail: bool = False):
    if method == "graph.search":
        return _search(result)
    if method == "graph.get_dataset":
        return {
            "node_id": result["node_id"],
            "qualified_name": result["descriptor"]["qualified_name"],
            "display_name": result["descriptor"]["display_name"],
            "description": result["descriptor"]["description"],
            "tags": result["descriptor"]["tags"],
            "grain": result["grain"],
            "columns": [
                {key: value for key, value in column.items() if value not in ("", [])}
                for column in result["columns"]
            ],
            "entity_definitions": [
                {
                    "identity_id": definition["identity_id"],
                    "dataset_columns": definition["dataset_columns"],
                    "entity_universe": definition["entity_universe"],
                }
                for definition in result["entity_definitions"]
            ],
            "unknown_fields": result["unknown_fields"],
        }
    result = expand_tables(result)
    relationships = {r["edge_id"]: r for r in result.get("relationships", [])}
    if method == "graph.get_hops":
        return {
            "truncated": result["truncated"],
            "hops": [_hop(relationships, step) for step in result["hops"]],
        }
    if method == "graph.get_relationship":
        return {
            "edge_id": result["edge_id"],
            "identity_id": result["identity_id"],
            "endpoint_a": _side(result["endpoint_a"]),
            "endpoint_b": _side(result["endpoint_b"]),
            "a_to_b": _claims(result["a_to_b"]),
            "b_to_a": _claims(result["b_to_a"]),
            "from_node_id": result["from_node_id"],
            "direction": _claims(result["direction"]),
            "reverse_direction": _claims(result["reverse_direction"]),
            "unknown_fields": result["unknown_fields"],
        }
    if method == "graph.find_paths":
        grouped: list[list[dict]] = []
        for step in result["hops"]:
            if step["path"] == len(grouped):
                grouped.append([])
            grouped[step["path"]].append(step)
        paths = []
        for rank, steps in enumerate(grouped):
            shape = " > ".join(step["direction"]["multiplicity"] for step in steps)
            fan_out = sum(step["direction"]["multiplicity"] in FAN_OUT for step in steps)
            unknown = sum(bool(step["unknown_fields"]) for step in steps)
            route = " -> ".join(
                [steps[0]["from_node_id"]] + [step["to_node_id"] for step in steps]
            )
            paths.append({
                "rank": rank,
                "fan_out": fan_out,
                "unknown": unknown,
                "line": f"#{rank} [{shape}] fan_out={fan_out} unknown={unknown}: {route}",
                "hops": [_hop(relationships, step) for step in steps],
            })
        # Fan-out-free chains first, then fewer unknown hops; service rank breaks ties.
        paths.sort(key=lambda path: (path["fan_out"], path["unknown"], path["rank"]))
        if detail:
            listed = [{"line": path["line"], "hops": path["hops"]} for path in paths]
        else:
            listed = [path["line"] for path in paths]
        return {"truncated": result["truncated"], "path_count": len(paths), "paths": listed}
    if method == "graph.expand_subgraph":
        return {
            "truncated": result["truncated"],
            "nodes": [
                f'{d["distance"]} {d["node_id"]} ({d["descriptor"]["qualified_name"]})'
                for d in result["datasets"]
            ],
            "edges": [
                f'{edge_id}: {_side(e["endpoint_a"])} <-> {_side(e["endpoint_b"])} '
                f'{e["identity_id"]} a_to_b {_claims(e["a_to_b"])} | b_to_a {_claims(e["b_to_a"])}'
                for edge_id, e in relationships.items()
            ],
        }
    if method == "graph.get_identity":
        names = {d["node_id"]: d["descriptor"]["qualified_name"] for d in result["datasets"]}
        return {
            **{k: v for k, v in result.items() if k not in ("datasets", "entity_definitions")},
            "definitions": [
                f'{d["node_id"]}[{",".join(d["dataset_columns"])}] '
                f'({names[d["node_id"]]}) universe={d["entity_universe"]}'
                for d in result["entity_definitions"]
            ],
        }
    return result


def _without_unknown_fields(value):
    if isinstance(value, dict):
        return {k: _without_unknown_fields(v) for k, v in value.items() if k != "unknown_fields"}
    if isinstance(value, list):
        return [_without_unknown_fields(item) for item in value]
    return value


def build_cut(socket_path: Path, node_ids: list[str], edge_ids: list[str]) -> dict:
    """Fetch nodes and edges and return one cut in the AKG contract's graph model."""
    nodes = [
        _without_unknown_fields(result_of(socket_path, "graph.get_dataset", {"node_id": node_id}))
        for node_id in node_ids
    ]
    edges = []
    for edge_id in edge_ids:
        relationship = result_of(
            socket_path,
            "graph.get_relationship",
            {"edge_id": edge_id, "response_format": "records"},
        )
        identity_id = relationship["identity_id"]
        edges.append({
            side: {
                "node_id": relationship[side]["node_id"],
                "identity_id": identity_id,
                "dataset_columns": relationship[side]["dataset_columns"],
            }
            for side in ("endpoint_a", "endpoint_b")
        } | {"a_to_b": relationship["a_to_b"], "b_to_a": relationship["b_to_a"]})
    identities = {}
    for identity_id in sorted({edge["endpoint_a"]["identity_id"] for edge in edges}):
        detail = result_of(socket_path, "graph.get_identity", {"identity_id": identity_id, "limit": 1})
        identities[identity_id] = {
            "name": detail["name"],
            "description": detail["description"],
            "synonyms": detail["synonyms"],
        }
    return {"logical_identities": identities, "nodes": nodes, "edges": edges}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("method")
    parser.add_argument("params", nargs="?", default="{}")
    parser.add_argument("--socket", default=os.environ.get("DOG_SOCKET"))
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--records", action="store_true",
                        help="with --full, convert each table to a list of records")
    parser.add_argument("--detail", action="store_true",
                        help="with find_paths, list each path's hops")
    args = parser.parse_args(argv)
    if not args.socket:
        parser.error("set --socket or DOG_SOCKET")
    socket_path = Path(args.socket).expanduser().resolve()
    params = json.loads(args.params)
    try:
        if args.method == "cut":
            output = build_cut(
                socket_path, params.get("node_ids", []), params.get("edge_ids", [])
            )
        else:
            method = args.method if args.method.startswith("graph.") else f"graph.{args.method}"
            if method == "graph.find_paths":
                params.setdefault("limit", DEFAULT_PATH_LIMIT)
            result = result_of(socket_path, method, params)
            if args.full:
                output = expand_tables(result) if args.records else result
            else:
                output = compact(method, result, detail=args.detail)
    except ServiceError as error:
        print(json.dumps(error.error, indent=1))
        return 1
    print(json.dumps(output, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
