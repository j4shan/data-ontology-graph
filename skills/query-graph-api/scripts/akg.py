#!/usr/bin/env python3
"""Build an AKG file incrementally from the Data Ontology Graph service.

Standard library only; imports no graph-core code. Graph objects go from the service into the
file without being retyped: `add-*` fetches them and writes their trimmed fields, and never
changes a graph field already present. Agent reasoning changes only through `annotate`, `gap`,
and `comparison`, which apply RFC 7396 merge-patches given as JSON text, `-` (standard
input), or `@path`. Every write is atomic and resets `status`
to `draft`; `data-ontology-graph-akg finalize` sets `final`.

    akg.py init FILE --question Q [--objective O]
    akg.py add-dataset FILE NODE_ID... [--detail essential|standard|full] [--columns c1,c2]
    akg.py add-relationship FILE EDGE_ID... [--no-endpoints]
    akg.py remove FILE KEY... [--cascade]
    akg.py exists FILE KEY...
    akg.py show FILE [--full]
    akg.py annotate FILE KEY PATCH_JSON
    akg.py gap FILE ID PATCH_JSON
    akg.py comparison FILE ID PATCH_JSON

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

DETAIL_LEVELS = ("essential", "standard", "full")
UNKNOWN = "unknown"
DATASET_ORDER = (
    "name", "source", "grain", "description", "columns", "entity_definitions", "synonyms", "tags",
    "stats", "usage",
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


def project_relationship(relationship: dict) -> dict:
    return {
        side: {
            "node_id": relationship[side]["node_id"],
            "identity_id": relationship[side].get("identity_id", relationship.get("identity_id")),
            "dataset_columns": relationship[side]["dataset_columns"],
        }
        for side in ("endpoint_a", "endpoint_b")
    } | {
        direction: {key: relationship[direction][key] for key in ("multiplicity", "match_existence")}
        for direction in ("a_to_b", "b_to_a")
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

def load(path: Path) -> dict:
    if not path.exists():
        raise AkgError(f"{path} does not exist; run `akg.py init` first")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise AkgError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise AkgError(f"{path} does not hold a JSON object")
    document.setdefault("datasets", {})
    document.setdefault("relationships", {})
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
    document |= {"datasets": {}, "relationships": {}}
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


def add_relationships(
    document: dict, socket_path: Path, edge_ids: list[str], endpoints: bool
) -> dict:
    report: dict[str, list[str]] = {"added": [], "unchanged": [], "datasets_added": [],
                                    "datasets_extended": []}
    for edge_id in edge_ids:
        record = result_of(
            socket_path, "graph.get_relationship", {"edge_id": edge_id, "response_format": "records"}
        )
        relationships = document["relationships"]
        if edge_id in relationships:
            report["unchanged"].append(edge_id)
        else:
            relationships[edge_id] = project_relationship(record)
            report["added"].append(edge_id)
        if not endpoints:
            continue
        for side in ("endpoint_a", "endpoint_b"):
            endpoint = relationships[edge_id][side]
            node = result_of(socket_path, "graph.get_dataset", {"node_id": endpoint["node_id"]})
            projected = project_dataset(node, "essential", endpoint["dataset_columns"])
            outcome = _merge_dataset(document, endpoint["node_id"], projected)
            if outcome != "unchanged":
                report[f"datasets_{outcome}"].append(endpoint["node_id"])
    return report


def remove(document: dict, keys: list[str], cascade: bool) -> dict:
    unknown = [key for key in keys if key not in document["datasets"]
               and key not in document["relationships"]]
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
        if key in document["datasets"]:
            for edge_id, relationship in list(document["relationships"].items()):
                if key in (relationship["endpoint_a"]["node_id"], relationship["endpoint_b"]["node_id"]):
                    del document["relationships"][edge_id]
                    removed.append(edge_id)
                    _drop_references(document, edge_id)
            del document["datasets"][key]
        else:
            document["relationships"].pop(key, None)
        _drop_references(document, key)
        removed.append(key)
    return {"removed": list(dict.fromkeys(removed))}


def exists(document: dict, keys: list[str]) -> dict:
    return {key: "present" if key in document["datasets"] or key in document["relationships"]
            else "absent" for key in keys}


def annotate(document: dict, key: str, patch) -> dict:
    if key in document["datasets"]:
        element = document["datasets"][key]
    elif key in document["relationships"]:
        element = document["relationships"][key]
    else:
        raise AkgError(f"{key} is not in the document; add it first")
    if not isinstance(patch, dict):
        raise AkgError("an annotation patch must be a JSON object applied to `usage`")
    usage = merge_patch(element.get("usage"), patch)
    if usage:
        element["usage"] = usage
    else:
        element.pop("usage", None)
    return {"annotated": key, "usage": element.get("usage")}


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
    datasets, relationships = document["datasets"], document["relationships"]
    lines = [
        f"status {document.get('status')} | {len(datasets)} datasets | "
        f"{len(relationships)} relationships | {_components(document)} component(s)"
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
    for edge_id, relationship in relationships.items():
        usage = relationship.get("usage") or {}
        a, b = relationship["endpoint_a"], relationship["endpoint_b"]
        forward, reverse = "a_to_b", "b_to_a"
        if usage.get("from") == b["node_id"]:
            a, b, forward, reverse = b, a, reverse, forward
        claims = f"{_claims(relationship[forward])} | reverse {_claims(relationship[reverse])}"
        keep = f" keep={','.join(usage['keep'])}" if usage.get("keep") else ""
        oriented = "" if usage.get("from") else " (canonical order; no usage.from)"
        lines.append(f"relationship {edge_id}")
        lines.append(f"  {_end(a)} -> {_end(b)} {claims}{keep}{oriented}")
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
    order = {field: index for index, field in enumerate(DATASET_ORDER)}
    datasets[node_id] = dict(sorted(current.items(), key=lambda item: order.get(item[0], len(order))))
    return "extended" if changed else "unchanged"


def _referrers(document: dict, key: str, removing: set[str]) -> list[str]:
    refs: list[str] = []
    for edge_id, relationship in document["relationships"].items():
        if edge_id in removing:
            continue
        if key in (relationship["endpoint_a"]["node_id"], relationship["endpoint_b"]["node_id"]):
            refs.append(f"relationships[{edge_id}]")
    for entry_id, comparison in (document.get("comparisons") or {}).items():
        named = list(comparison.get("anchors") or [])
        named += [column.get("node_id") for column in comparison.get("shared_columns") or []]
        if key in named:
            refs.append(f"comparisons[{entry_id}]")
    for entry_id, gap in (document.get("gaps") or {}).items():
        if key in (gap.get("datasets") or []) + (gap.get("relationships") or []):
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
        for field in ("datasets", "relationships"):
            if field in gap:
                gap[field] = [item for item in gap[field] if item != key]


def _components(document: dict) -> int:
    parent = {node_id: node_id for node_id in document["datasets"]}

    def root(node_id: str) -> str:
        while parent[node_id] != node_id:
            node_id = parent[node_id]
        return node_id

    for relationship in document["relationships"].values():
        a, b = relationship["endpoint_a"]["node_id"], relationship["endpoint_b"]["node_id"]
        if a in parent and b in parent:
            parent[root(a)] = root(b)
    return len({root(node_id) for node_id in parent})


def _claims(direction: dict) -> str:
    return f"{direction['multiplicity']}/{direction['match_existence']}"


def _end(endpoint: dict) -> str:
    return f"{endpoint['node_id']}[{','.join(endpoint['dataset_columns'])}]"


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

    command = commands.add_parser("add-relationship", parents=[common])
    command.add_argument("file", type=Path)
    command.add_argument("edge_ids", nargs="+")
    command.add_argument("--no-endpoints", action="store_true",
                         help="do not add missing endpoint datasets or join columns")

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

    args = parser.parse_args(argv)
    socket_path = (Path(args.socket).expanduser() if args.socket else default_socket()).resolve()
    path = args.file
    try:
        if args.command == "init":
            output = init(path, socket_path, args.question, args.objective)
        elif args.command in ("exists", "show"):
            document = load(path)
            if args.command == "show":
                print(show(document, args.full))
                return 0
            output = exists(document, args.keys)
        else:
            document = load(path)
            if args.command == "add-dataset":
                columns = [name for name in args.columns.split(",") if name]
                output = add_datasets(document, socket_path, args.node_ids, args.detail, columns)
            elif args.command == "add-relationship":
                output = add_relationships(
                    document, socket_path, args.edge_ids, not args.no_endpoints
                )
            elif args.command == "remove":
                output = remove(document, args.keys, args.cascade)
            elif args.command == "annotate":
                output = annotate(document, args.key, _json(args.patch))
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
