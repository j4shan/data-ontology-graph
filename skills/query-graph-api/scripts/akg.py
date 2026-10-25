#!/usr/bin/env python3
"""Build an AKG file incrementally from the Data Ontology Graph service.

Standard library only; imports no graph-core code. Graph objects go from the service into the
file without being retyped: `add-*` fetches them and writes their trimmed fields, and never
changes a graph field already present. A selected join is a directed edge stored in the dataset
traversal starts from. Agent reasoning changes only through `annotate`, `gap`, and
`comparison`, which apply RFC 7396 merge-patches given as JSON text, `-` (standard input), or
`@path`. Every write is atomic and resets `status` to `draft`; `data-ontology-graph-akg
finalize` sets `final`.

    akg.py init FILE --question Q [--objective O]
    akg.py add-dataset FILE NODE_ID... [--detail essential|standard|full] [--columns c1,c2]
    akg.py add-edge FILE NODE_ID EDGE_ID... [--from-columns c1,c2] [--no-endpoints]
    akg.py remove FILE KEY... [--cascade]
    akg.py exists FILE KEY...
    akg.py show FILE [--full]
    akg.py annotate FILE KEY PATCH_JSON [--from NODE_ID] [--from-columns c1,c2]
    akg.py gap FILE ID PATCH_JSON
    akg.py comparison FILE ID PATCH_JSON
    akg.py migrate FILE

A KEY is a dataset `node_id` or an `edge_id`. `migrate` converts a file written with the earlier
`relationships` map.

The socket comes from --socket, then $DOG_SOCKET, then the service home's socket. Each command
prints one JSON line.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from graph_call import ServiceError, default_socket, result_of  # noqa: E402

FORMAT_VERSION = 2
DETAIL_LEVELS = ("essential", "standard", "full")
UNKNOWN = "unknown"
DATASET_ORDER = (
    "name", "source", "grain", "description", "columns", "entity_definitions", "synonyms", "tags",
    "stats", "usage", "edges",
)


class AkgError(RuntimeError):
    pass


# Projection: keep these rules equal to data_ontology_graph.akg.projection.

def source_of(schema_id: str) -> str:
    parts = schema_id.split(".")
    return parts[1] if len(parts) >= 3 else schema_id


def project_dataset(node: dict, detail: str = "essential", columns=None) -> dict:
    if detail not in DETAIL_LEVELS:
        raise ValueError(f"unknown detail level {detail!r}; use one of {DETAIL_LEVELS}")
    full = detail == "full"
    descriptor = node["descriptor"]
    inventory = {column["name"]: column for column in node["columns"]}
    selected = list(dict.fromkeys(columns or [])) if detail == "essential" else list(inventory)
    missing = [name for name in selected if name not in inventory]
    if missing:
        raise ValueError(f"{node['node_id']} has no columns {missing}")

    dataset = {
        "name": descriptor["qualified_name"],
        "source": source_of(node["accessor"]["schema_id"]),
        "grain": _grain(node["grain"]),
    }
    if detail != "essential" and descriptor.get("description"):
        dataset["description"] = descriptor["description"]
    if selected:
        fields = ("description", "value_description", "synonyms") if full else (
            "description", "value_description",
        )
        dataset["columns"] = {
            name: {field: inventory[name][field] for field in fields if inventory[name].get(field)}
            for name in selected
        }
    if detail != "essential":
        descriptions = {name: column.get("description", "") for name, column in inventory.items()}
        dataset["entity_definitions"] = [
            _definition(definition, descriptions)
            for definition in node.get("entity_definitions", [])
        ]
    if full:
        for field in ("synonyms", "tags"):
            if descriptor.get(field):
                dataset[field] = descriptor[field]
    return dataset


def project_edge(relationship: dict, from_node_id: str, from_dataset_columns: list,
                 descriptions: dict | None = None) -> dict:
    sides = [(relationship[side], forward, reverse) for side, forward, reverse in (
        ("endpoint_a", "a_to_b", "b_to_a"), ("endpoint_b", "b_to_a", "a_to_b"),
    )]
    for start, forward, reverse in sides:
        if start["node_id"] == from_node_id and start["dataset_columns"] == from_dataset_columns:
            end = relationship["endpoint_b" if forward == "a_to_b" else "endpoint_a"]
            break
    else:
        raise ValueError(
            f"{from_node_id}{from_dataset_columns} is not an endpoint of {relationship['edge_id']}"
        )
    edge = {
        "edge_id": relationship["edge_id"],
        "identity_id": start.get("identity_id", relationship.get("identity_id")),
        "from_dataset_columns": start["dataset_columns"],
        "to_node_id": end["node_id"],
        "to_dataset_columns": end["dataset_columns"],
        "multiplicity": relationship[forward]["multiplicity"],
        "match_existence": relationship[forward]["match_existence"],
        "reverse_multiplicity": relationship[reverse]["multiplicity"],
        "reverse_match_existence": relationship[reverse]["match_existence"],
    }
    for field, endpoint in (("from_description", start), ("to_description", end)):
        text = (descriptions or {}).get((endpoint["node_id"], tuple(endpoint["dataset_columns"])))
        if text:
            edge[field] = text
    return edge


def endpoint_descriptions(record: dict) -> dict:
    return {
        (definition["node_id"], tuple(definition["dataset_columns"])):
            definition["effective_description"]
        for definition in record.get("entity_definitions", [])
        if definition.get("effective_description")
    }


RAW_REFERENCE_WRAPPERS = ("", "[]", '""', "``")


def effective_description(description, dataset_columns, entity_expression, column_descriptions):
    """Keep equal to data_ontology_graph.model.dataset.effective_description."""
    if description.strip():
        return description, "entity"
    if len(dataset_columns) != 1:
        return None
    column = dataset_columns[0]
    references = {f"{pair[:1]}{column}{pair[1:]}" for pair in RAW_REFERENCE_WRAPPERS}
    if any(expression.strip() not in references for expression in entity_expression):
        return None
    text = column_descriptions.get(column, "")
    return (text, "column") if text.strip() else None


def _definition(definition: dict, descriptions: dict) -> dict:
    projected = {
        "identity_id": definition["identity_id"],
        "dataset_columns": definition["dataset_columns"],
        "entity_universe": definition["entity_universe"],
    }
    effective = effective_description(
        definition.get("description", ""),
        definition["dataset_columns"],
        definition.get("entity_expression", []),
        descriptions,
    )
    if effective:
        projected["description"], projected["description_source"] = effective
    return projected


def _grain(grain) -> list | str:
    if grain == UNKNOWN:
        return UNKNOWN
    columns: list[str] = []
    for component in grain["components"]:
        columns.extend(column for column in component["dataset_columns"] if column not in columns)
    return columns


# File access.

def load(path: Path, converted: bool = True) -> dict:
    """Read the file; with `converted`, refuse one that still holds a `relationships` map."""
    if not path.exists():
        raise AkgError(f"{path} does not exist; run `akg.py init` first")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise AkgError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise AkgError(f"{path} does not hold a JSON object")
    if converted and "relationships" in document:
        raise AkgError(f"{path} uses the earlier relationships map; run `akg.py migrate` first")
    document.setdefault("datasets", {})
    return document


def save(path: Path, document: dict) -> None:
    document["status"] = "draft"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def merge_patch(target, patch):
    """RFC 7396: objects merge recursively, `null` deletes, anything else replaces."""
    if not isinstance(patch, dict):
        return patch
    result = dict(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = merge_patch(result.get(key), value)
    return result


# Commands.

def init(path: Path, socket_path: Path | None, question: str, objective: str | None) -> dict:
    if path.exists():
        raise AkgError(f"{path} already exists")
    document = {"status": "draft", "question": question}
    if objective:
        document["objective"] = objective
    snapshot = None
    if socket_path is not None:
        try:
            info = result_of(socket_path, "graph.snapshot_info", {})
            snapshot = {"version": info["version"], "schema_fingerprint": info["schema_fingerprint"]}
            document["graph"] = {"snapshot": snapshot}
        except (OSError, ServiceError):
            snapshot = None
    document = {"format_version": FORMAT_VERSION, **document, "datasets": {}}
    path.parent.mkdir(parents=True, exist_ok=True)
    save(path, document)
    return {"created": str(path), "snapshot": snapshot}


def add_datasets(
    document: dict, socket_path: Path, node_ids: list[str], detail: str, columns: list[str]
) -> dict:
    report: dict[str, list[str]] = {"added": [], "extended": [], "unchanged": []}
    for node_id in node_ids:
        node = result_of(socket_path, "graph.get_dataset", {"node_id": node_id})
        outcome = _merge_dataset(document, node_id, project_dataset(node, detail, columns))
        report[outcome].append(node_id)
    return report


def add_edges(
    document: dict, socket_path: Path, node_id: str, edge_ids: list[str],
    from_columns: list[str], endpoints: bool,
) -> dict:
    report: dict[str, list[str]] = {"added": [], "unchanged": [], "datasets_added": [],
                                    "datasets_extended": []}
    for edge_id in edge_ids:
        params = {"edge_id": edge_id, "from_node_id": node_id, "response_format": "records"}
        if from_columns:
            params["from_dataset_columns"] = from_columns
        record = result_of(socket_path, "graph.get_relationship", params)
        edge = project_edge(
            record, node_id, record["from_dataset_columns"], endpoint_descriptions(record)
        )
        if endpoints:
            for end, columns in ((node_id, edge["from_dataset_columns"]),
                                 (edge["to_node_id"], edge["to_dataset_columns"])):
                node = result_of(socket_path, "graph.get_dataset", {"node_id": end})
                outcome = _merge_dataset(document, end, project_dataset(node, "essential", columns))
                if outcome != "unchanged":
                    report[f"datasets_{outcome}"].append(end)
        if node_id not in document["datasets"]:
            raise AkgError(f"{node_id} is not in the document; add it first or drop --no-endpoints")
        held = document["datasets"][node_id].setdefault("edges", [])
        if _find(held, edge_id, edge["from_dataset_columns"]):
            report["unchanged"].append(edge_id)
        else:
            held.append(edge)
            report["added"].append(edge_id)
        _order(document, node_id)
    report["datasets_added"] = list(dict.fromkeys(report["datasets_added"]))
    report["datasets_extended"] = list(dict.fromkeys(report["datasets_extended"]))
    return report


def remove(document: dict, keys: list[str], cascade: bool) -> dict:
    datasets = document["datasets"]
    edge_ids = {edge["edge_id"] for _, edge in _edges(document)}
    unknown = [key for key in keys if key not in datasets and key not in edge_ids]
    if unknown:
        raise AkgError(f"not in the document: {unknown}")
    removing = set(keys)
    blocked = {key: refs for key in keys if (refs := _referrers(document, key, removing))}
    if blocked and not cascade:
        raise AkgError(
            "still referred to; remove the referrers first or pass --cascade: "
            + json.dumps(blocked)
        )
    removed: list[str] = []
    for key in keys:
        if key in datasets:
            for node_id, dataset in datasets.items():
                if node_id == key:
                    continue
                for edge in [edge for edge in dataset.get("edges") or [] if edge["to_node_id"] == key]:
                    removed += _remove_edge(document, edge["edge_id"])
            del datasets[key]
        else:
            _remove_edge(document, key)
        _drop_references(document, key)
        removed.append(key)
    return {"removed": list(dict.fromkeys(removed))}


def exists(document: dict, keys: list[str]) -> dict:
    edge_ids = {edge["edge_id"] for _, edge in _edges(document)}
    return {key: "present" if key in document["datasets"] or key in edge_ids
            else "absent" for key in keys}


def annotate(document: dict, key: str, patch, from_node_id: str | None = None,
             from_columns: list[str] | None = None) -> dict:
    if key in document["datasets"] and from_node_id is None:
        element = document["datasets"][key]
    else:
        matches = [
            edge for node_id, edge in _edges(document)
            if edge["edge_id"] == key and from_node_id in (None, node_id)
            and (not from_columns or edge["from_dataset_columns"] == from_columns)
        ]
        if not matches:
            raise AkgError(f"{key} is not in the document; add it first")
        if len(matches) > 1:
            raise AkgError(
                f"{key} is held by more than one directed edge; name --from and --from-columns"
            )
        element = matches[0]
    if not isinstance(patch, dict):
        raise AkgError("an annotation patch must be a JSON object applied to `usage`")
    usage = merge_patch(element.get("usage"), patch)
    if usage:
        element["usage"] = usage
    else:
        element.pop("usage", None)
    return {"annotated": key, "usage": element.get("usage")}


def migrate(document: dict, socket_path: Path) -> dict:
    """Convert a `relationships` map into directed edges, each in the dataset traversal leaves.

    The start is `usage.from`, else `endpoint_a`. Claims are kept as written; fields the earlier
    format lacked, such as the effective descriptions, are fetched from the service.
    """
    relationships = document.pop("relationships", None)
    if relationships is None:
        raise AkgError("the document has no relationships map to migrate")
    converted = []
    for edge_id, relationship in relationships.items():
        usage = dict(relationship.get("usage") or {})
        start = relationship["endpoint_a"]
        if usage.get("from") == relationship["endpoint_b"]["node_id"]:
            start = relationship["endpoint_b"]
        usage.pop("from", None)
        node_id, columns = start["node_id"], start["dataset_columns"]
        if node_id not in document["datasets"]:
            raise AkgError(f"{edge_id} starts at {node_id}, which is not in the document")
        edge = project_edge(dict(relationship, edge_id=edge_id), node_id, columns)
        record = result_of(socket_path, "graph.get_relationship", {
            "edge_id": edge_id, "from_node_id": node_id, "from_dataset_columns": columns,
            "response_format": "records",
        })
        for field, value in project_edge(
            record, node_id, columns, endpoint_descriptions(record)
        ).items():
            edge.setdefault(field, value)
        for field in ("stats",):
            if relationship.get(field):
                edge[field] = relationship[field]
        if usage:
            edge["usage"] = usage
        document["datasets"][node_id].setdefault("edges", []).append(edge)
        _order(document, node_id)
        converted.append({"edge_id": edge_id, "node_id": node_id})
    starts = {item["edge_id"]: item["node_id"] for item in converted}
    for gap in (document.get("gaps") or {}).values():
        if "relationships" in gap:
            gap["edges"] = [{"node_id": starts[edge_id], "edge_id": edge_id}
                            for edge_id in gap.pop("relationships") if edge_id in starts]
    ordered = {"format_version": FORMAT_VERSION}
    ordered.update((key, value) for key, value in document.items() if key != "format_version")
    document.clear()
    document.update(ordered)
    return {"migrated": converted}


def patch_entry(document: dict, collection: str, entry_id: str, patch) -> dict:
    entries = document.get(collection) or {}
    if patch is None:
        removed = entries.pop(entry_id, None) is not None
        result = {"removed" if removed else "absent": entry_id}
    else:
        if not isinstance(patch, dict):
            raise AkgError(f"a {collection} patch must be a JSON object or null")
        entries[entry_id] = merge_patch(entries.get(entry_id), patch)
        result = {"set": entry_id, collection[:-1]: entries[entry_id]}
    if entries:
        document[collection] = entries
    else:
        document.pop(collection, None)
    return result


def show(document: dict, full: bool) -> str:
    if full:
        return json.dumps(document, indent=2, ensure_ascii=False)
    datasets = document["datasets"]
    lines = [
        f"status {document.get('status')} | {len(datasets)} datasets | "
        f"{len(_edges(document))} edges | {_components(document)} component(s)"
    ]
    for node_id, dataset in datasets.items():
        usage = dataset.get("usage") or {}
        uses = usage.get("columns") or {}
        columns = ",".join(
            f"{name}[{uses[name].get('as')}]" if name in uses else name
            for name in dict.fromkeys([*(dataset.get("columns") or {}), *uses])
        )
        role = f" role={usage['role']}" if usage.get("role") else ""
        lines.append(f"dataset {node_id} ({dataset.get('name')}){role} columns={columns or '-'}")
        for edge in dataset.get("edges") or []:
            keep = (edge.get("usage") or {}).get("keep")
            claims = (
                f"{edge['multiplicity']}/{edge['match_existence']} | reverse "
                f"{edge['reverse_multiplicity']}/{edge['reverse_match_existence']}"
            )
            lines.append(f"  edge {edge['edge_id']}")
            lines.append(
                f"  {_end(node_id, edge['from_dataset_columns'])} -> "
                f"{_end(edge['to_node_id'], edge['to_dataset_columns'])} {claims}"
                + (f" keep={','.join(keep)}" if keep else "")
            )
    for key in ("comparisons", "gaps"):
        for entry_id, entry in (document.get(key) or {}).items():
            lines.append(f"{key[:-1]} {entry_id}: {json.dumps(entry, ensure_ascii=False)}")
    return "\n".join(lines)


# Helpers.

def _merge_dataset(document: dict, node_id: str, projected: dict) -> str:
    datasets = document["datasets"]
    if node_id not in datasets:
        datasets[node_id] = projected
        return "added"
    current = datasets[node_id]
    changed = False
    for field, value in projected.items():
        if field not in current:
            current[field] = value
            changed = True
        elif field == "columns" and isinstance(current[field], dict):
            for name, facts in value.items():
                if name not in current[field]:
                    current[field][name] = facts
                    changed = True
                    continue
                for key, fact in facts.items():
                    if key not in current[field][name]:
                        current[field][name][key] = fact
                        changed = True
    _order(document, node_id)
    return "extended" if changed else "unchanged"


def _edges(document: dict) -> list[tuple[str, dict]]:
    return [(node_id, edge) for node_id, dataset in document["datasets"].items()
            for edge in dataset.get("edges") or []]


def _find(edges: list[dict], edge_id: str, columns: list[str]) -> dict | None:
    return next((edge for edge in edges
                 if edge["edge_id"] == edge_id and edge["from_dataset_columns"] == columns), None)


def _order(document: dict, node_id: str) -> None:
    order = {field: index for index, field in enumerate(DATASET_ORDER)}
    dataset = document["datasets"][node_id]
    document["datasets"][node_id] = dict(
        sorted(dataset.items(), key=lambda item: order.get(item[0], len(order)))
    )


def _remove_edge(document: dict, edge_id: str) -> list[str]:
    for dataset in document["datasets"].values():
        if "edges" in dataset:
            dataset["edges"] = [edge for edge in dataset["edges"] if edge["edge_id"] != edge_id]
            if not dataset["edges"]:
                del dataset["edges"]
    _drop_references(document, edge_id)
    return [edge_id]


def _referrers(document: dict, key: str, removing: set[str]) -> list[str]:
    refs: list[str] = []
    for node_id, edge in _edges(document):
        if node_id != key and edge["to_node_id"] == key and edge["edge_id"] not in removing:
            refs.append(f"datasets[{node_id}].edges[{edge['edge_id']}]")
    for entry_id, comparison in (document.get("comparisons") or {}).items():
        named = list(comparison.get("anchors") or [])
        named += [column.get("node_id") for column in comparison.get("shared_columns") or []]
        if key in named:
            refs.append(f"comparisons[{entry_id}]")
    for entry_id, gap in (document.get("gaps") or {}).items():
        named = list(gap.get("datasets") or [])
        named += [item for reference in gap.get("edges") or []
                  for item in (reference.get("node_id"), reference.get("edge_id"))]
        if key in named:
            refs.append(f"gaps[{entry_id}]")
    return refs


def _drop_references(document: dict, key: str) -> None:
    for comparison in (document.get("comparisons") or {}).values():
        if "anchors" in comparison:
            comparison["anchors"] = [node_id for node_id in comparison["anchors"] if node_id != key]
        if "shared_columns" in comparison:
            comparison["shared_columns"] = [
                column for column in comparison["shared_columns"] if column.get("node_id") != key
            ]
    for gap in (document.get("gaps") or {}).values():
        if "datasets" in gap:
            gap["datasets"] = [item for item in gap["datasets"] if item != key]
        if "edges" in gap:
            gap["edges"] = [reference for reference in gap["edges"]
                            if key not in (reference.get("node_id"), reference.get("edge_id"))]


def _components(document: dict) -> int:
    parent = {node_id: node_id for node_id in document["datasets"]}

    def root(node_id: str) -> str:
        while parent[node_id] != node_id:
            node_id = parent[node_id]
        return node_id

    for a, edge in _edges(document):
        if edge["to_node_id"] in parent:
            parent[root(a)] = root(edge["to_node_id"])
    return len({root(node_id) for node_id in parent})


def _end(node_id: str, columns: list[str]) -> str:
    return f"{node_id}[{','.join(columns)}]"


def _names(text: str) -> list[str]:
    return [name for name in text.split(",") if name]


def _json(text: str):
    """Parse a patch given as JSON text, `-` for standard input, or `@path` for a file."""
    if text == "-":
        text = sys.stdin.read()
    elif text.startswith("@"):
        text = Path(text[1:]).read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise AkgError(f"invalid JSON patch: {error}") from error


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--socket", help="default: $DOG_SOCKET or the service home's socket")
    parser = argparse.ArgumentParser(description="Build an AKG file from the graph service")
    commands = parser.add_subparsers(dest="command", required=True)

    command = commands.add_parser("init", parents=[common])
    command.add_argument("file", type=Path)
    command.add_argument("--question", required=True)
    command.add_argument("--objective")

    command = commands.add_parser("add-dataset", parents=[common])
    command.add_argument("file", type=Path)
    command.add_argument("node_ids", nargs="+")
    command.add_argument("--detail", choices=DETAIL_LEVELS, default="essential")
    command.add_argument("--columns", default="", help="comma-separated column names")

    command = commands.add_parser("add-edge", parents=[common])
    command.add_argument("file", type=Path)
    command.add_argument("node_id", help="the dataset traversal starts from")
    command.add_argument("edge_ids", nargs="+")
    command.add_argument("--from-columns", default="",
                         help="comma-separated start columns; needed when both ends lie on NODE_ID")
    command.add_argument("--no-endpoints", action="store_true",
                         help="do not add missing end datasets or join columns")

    command = commands.add_parser("remove", parents=[common])
    command.add_argument("file", type=Path)
    command.add_argument("keys", nargs="+")
    command.add_argument("--cascade", action="store_true")

    command = commands.add_parser("exists", parents=[common])
    command.add_argument("file", type=Path)
    command.add_argument("keys", nargs="+")

    command = commands.add_parser("show", parents=[common])
    command.add_argument("file", type=Path)
    command.add_argument("--full", action="store_true")

    for name in ("annotate", "gap", "comparison"):
        command = commands.add_parser(name, parents=[common])
        command.add_argument("file", type=Path)
        command.add_argument("key")
        command.add_argument("patch")
        if name == "annotate":
            command.add_argument("--from", dest="from_node_id",
                                 help="with an edge_id KEY: the dataset that holds the edge")
            command.add_argument("--from-columns", default="",
                                 help="with an edge_id KEY: the edge's start columns")

    command = commands.add_parser("migrate", parents=[common])
    command.add_argument("file", type=Path)

    args = parser.parse_args(argv)
    socket_path = (Path(args.socket).expanduser() if args.socket else default_socket()).resolve()
    path = args.file
    try:
        if args.command == "init":
            output = init(path, socket_path, args.question, args.objective)
        elif args.command in ("exists", "show"):
            document = load(path, converted=True)
            if args.command == "show":
                print(show(document, args.full))
                return 0
            output = exists(document, args.keys)
        else:
            document = load(path, converted=args.command != "migrate")
            if args.command == "add-dataset":
                output = add_datasets(
                    document, socket_path, args.node_ids, args.detail, _names(args.columns)
                )
            elif args.command == "add-edge":
                output = add_edges(
                    document, socket_path, args.node_id, args.edge_ids,
                    _names(args.from_columns), not args.no_endpoints,
                )
            elif args.command == "remove":
                output = remove(document, args.keys, args.cascade)
            elif args.command == "annotate":
                output = annotate(document, args.key, _json(args.patch), args.from_node_id,
                                  _names(args.from_columns))
            elif args.command == "migrate":
                output = migrate(document, socket_path)
            else:
                output = patch_entry(document, f"{args.command}s", args.key, _json(args.patch))
            save(path, document)
    except ServiceError as error:
        print(json.dumps({"error": error.error.get("message"), "file_unchanged": True}))
        return 1
    except (AkgError, ValueError, OSError) as error:
        print(json.dumps({"error": str(error), "file_unchanged": True}))
        return 1
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
