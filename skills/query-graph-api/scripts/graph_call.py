#!/usr/bin/env python3
"""Call the Data Ontology Graph service over its JSON-RPC 2.0 Unix-domain socket.

Standard library only; imports no graph-core code.

    graph_call.py METHOD [PARAMS_JSON] [--socket PATH] [--full [--records]] [--detail]

The socket comes from --socket, then $DOG_SOCKET, then the service home's `graph.sock`; the home
is $DOG_HOME or ~/.data-ontology-graph. The client changes into the socket's directory and
connects by basename, so socket paths longer than the platform sun_path limit still work.

By default a result is printed as a compact projection:

- search: per kind, one line per subject with each matching field value.
- get_dataset: names first, then grain, columns, and entity definitions; no accessor.
- get_identity: the datasets that realize the logical entity, with their entity universe.
- get_edges: one line per entity definition with its listed and total directed edges, then one
  {edge_id, step} entry per listed directed edge leaving the dataset; the step names the columns
  it leaves from and arrives at, each endpoint's effective description, the logical entity ID, and
  the outgoing claims, then the reverse claims at `standard` detail and above.
- get_relationship: canonical claims, plus the directed edge leaving the endpoint the params name
  with `from_node_id` (and `from_dataset_columns` when both endpoints lie on that dataset).
- find_paths: one line per route, fan-out-free routes first; --detail adds each route's
  {edge_id, step} directed edges. `fan_out` counts directed edges that multiply rows (1:many,
  many:many) and `unknown` counts directed edges with an unknown claim.
- expand_subgraph: one line per dataset with its edge count, and one step per listed directed edge.

--full prints the raw result; --full --records converts each table to records. To build an AKG,
use the sibling `akg.py`, which writes graph objects into the AKG file directly.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path

DEFAULT_HOME = "~/.data-ontology-graph"
FAN_OUT = ("1:many", "many:many")


class ServiceError(RuntimeError):
    def __init__(self, error: dict) -> None:
        super().__init__(error.get("message", "graph service error"))
        self.error = error


def service_home() -> Path:
    """The private per-user service home; keep equal to data_ontology_graph.home."""
    return Path(os.environ.get("DOG_HOME") or DEFAULT_HOME).expanduser()


def default_socket() -> Path:
    override = os.environ.get("DOG_SOCKET")
    return Path(override).expanduser() if override else service_home() / "graph.sock"


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


def _end(label: str, description: str | None) -> str:
    """`node[cols]`, followed by the endpoint's effective description, if any."""
    return f'{label} "{description}"' if description else label


def _ends(label: str) -> tuple[str, str]:
    """Split `start[cols] -> end[cols]` at the arrow outside quoted column names."""
    quoted = False
    index = 0
    while index < len(label):
        char = label[index]
        if quoted:
            if char == "\\":
                index += 1
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif label.startswith(" -> ", index):
            return label[:index], label[index + 4:]
        index += 1
    raise ValueError(f"not a directed edge: {label!r}")


def _step(edge: dict, identity_id: str | None = None) -> str:
    """One directed edge as `from[cols] "desc" -> to[cols] "desc" logical-entity-ID claims | reverse claims`."""
    start, end = _ends(edge["edge"])
    text = f'{_end(start, edge.get("from_description"))} -> {_end(end, edge.get("to_description"))}'
    if identity_id:
        text += f" {identity_id}"
    text += f' {edge["multiplicity"]}/{edge["match_existence"]}'
    if "reverse_multiplicity" in edge:
        text += f' | reverse {edge["reverse_multiplicity"]}/{edge["reverse_match_existence"]}'
    return text


def _named(result: dict, edge: list) -> dict:
    """A directed-edge array keyed by the response's `edge_fields`."""
    return dict(zip(result["edge_fields"], edge))


def _groups(result: dict) -> list[tuple[str, dict]]:
    """Every edge group with the dataset it belongs to, from either response format."""
    if "edge_groups" in result:
        return [(group["node_id"], group) for group in result["edge_groups"]]
    return [(d["node_id"], group) for d in result["datasets"] for group in d.get("edge_groups", ())]


def _edges(result: dict) -> list[tuple[str, dict]]:
    """Every listed directed edge with its group's logical entity ID."""
    return [
        (group["identity_id"], _named(result, edge))
        for _, group in _groups(result)
        for definition in group["entity_definitions"]
        for edge in definition["edges"]
    ]


def _group_lines(result: dict) -> list[str]:
    """One line per entity definition: `node[cols] logical-entity-ID listed/total`."""
    return [
        f'{node_id}[{",".join(definition["dataset_columns"])}] {group["identity_id"]} '
        f'{len(definition["edges"])}/{definition["edge_count"]}'
        + (" truncated" if definition["truncated"] else "")
        for node_id, group in _groups(result)
        for definition in group["entity_definitions"]
    ]


def _definitions(result: dict) -> dict:
    return {
        (d["node_id"], d["identity_id"], tuple(d["dataset_columns"])): d
        for d in result.get("entity_definitions", [])
    }


def _endpoint(definitions: dict, identity_id: str, endpoint: dict) -> str:
    definition = definitions.get(
        (endpoint["node_id"], identity_id, tuple(endpoint["dataset_columns"]))
    ) or {}
    return _end(f'{endpoint["node_id"]}[{",".join(endpoint["dataset_columns"])}]',
                definition.get("effective_description"))


def _subject(kind: str, subject: dict) -> str:
    if kind == "column":
        label = f'{subject["node_id"]}.{subject["column_name"]}'
    elif kind == "dataset":
        label = f'{subject["key"]} ({subject["qualified_name"]})'
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


def _edge(edge: dict, identity_id: str | None = None) -> dict:
    return {"edge_id": edge["edge_id"], "step": _step(edge, identity_id)}


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
                    **({"description": definition["effective_description"],
                        "description_source": definition["description_source"]}
                       if definition.get("effective_description") else {}),
                }
                for definition in result["entity_definitions"]
            ],
            "unknown_fields": result["unknown_fields"],
        }
    result = expand_tables(result)
    if method == "graph.get_edges":
        return {
            "truncated": result["truncated"],
            "groups": _group_lines(result),
            "edges": [_edge(edge, identity_id) for identity_id, edge in _edges(result)],
        }
    if method == "graph.get_relationship":
        definitions = _definitions(result)
        return {
            "edge_id": result["edge_id"],
            "identity_id": result["identity_id"],
            "endpoint_a": _endpoint(definitions, result["identity_id"], result["endpoint_a"]),
            "endpoint_b": _endpoint(definitions, result["identity_id"], result["endpoint_b"]),
            "a_to_b": _claims(result["a_to_b"]),
            "b_to_a": _claims(result["b_to_a"]),
            "edge": (_step(_named(result, result["edge"]), result["identity_id"])
                     if result["edge"] else None),
            "unknown_fields": result["unknown_fields"],
        }
    if method == "graph.find_paths":
        paths = []
        for rank, route in enumerate(result["routes"]):
            steps = [_named(result, edge) for edge in route]
            shape = " > ".join(edge["multiplicity"] for edge in steps)
            fan_out = sum(edge["multiplicity"] in FAN_OUT for edge in steps)
            unknown = sum(
                "unknown" in (edge["multiplicity"], edge["match_existence"]) for edge in steps
            )
            ends = [_ends(edge["edge"]) for edge in steps]
            line = " -> ".join([start for start, _ in ends] + [ends[-1][1]])
            paths.append({
                "rank": rank,
                "fan_out": fan_out,
                "unknown": unknown,
                "line": f"#{rank} [{shape}] fan_out={fan_out} unknown={unknown}: {line}",
                "edges": [_edge(edge) for edge in steps],
            })
        # Fan-out-free chains first, then fewer unknown edges; service rank breaks ties.
        paths.sort(key=lambda path: (path["fan_out"], path["unknown"], path["rank"]))
        if detail:
            listed = [{"line": path["line"], "edges": path["edges"]} for path in paths]
        else:
            listed = [path["line"] for path in paths]
        return {"truncated": result["truncated"], "path_count": len(paths), "paths": listed}
    if method == "graph.expand_subgraph":
        return {
            "truncated": result["truncated"],
            "nodes": [
                f'{d["distance"]} {d["node_id"]} ({d["qualified_name"]}) edges={d["edge_count"]}'
                for d in result["datasets"]
            ],
            "groups": _group_lines(result),
            "edges": [_step(edge, identity_id) for identity_id, edge in _edges(result)],
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("method")
    parser.add_argument("params", nargs="?", default="{}")
    parser.add_argument("--socket", help="default: $DOG_SOCKET or the service home's socket")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--records", action="store_true",
                        help="with --full, convert each table to a list of records")
    parser.add_argument("--detail", action="store_true",
                        help="with find_paths, list each path's edges")
    args = parser.parse_args(argv)
    socket_path = (Path(args.socket).expanduser() if args.socket else default_socket()).resolve()
    params = json.loads(args.params)
    try:
        method = args.method if args.method.startswith("graph.") else f"graph.{args.method}"
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
