"""Turn source evidence and owner decisions into manifest-layout intermediary YAML.

Static keys and observed data only produce proposals. Every grain, identity, and relationship
starts as an open decision; the draft applies the current proposal or answer so it can be
validated, and publication waits until no decision is open or blocking.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ddl_collector.config import dump_yaml, write_text_atomic
from ddl_collector.evidence import (
    ForeignKeyEvidence,
    KeyEvidence,
    SourceEvidence,
    TableEvidence,
)
from ddl_collector.survey import Decision


SCHEMA_VERSION = "3"
MANIFEST_FILENAME = "directory-manifest.yaml"
IDENTITIES_FILE = "identities.yaml"
RELATIONSHIPS_FILE = "relationships.yaml"
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9_.-]")


class DraftFinding(BaseModel):
    decision_id: str
    rule: str
    message: str


class Draft(BaseModel):
    logical_identities: dict[str, dict[str, Any]]
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    findings: list[DraftFinding]

    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "logical_identities": self.logical_identities,
            "nodes": self.nodes,
            "edges": self.edges,
        }


def node_id_for(evidence: SourceEvidence, table: str) -> str:
    return f"{evidence.family}:{evidence.catalog}.{table}"


def grain_decision_id(table: str) -> str:
    return f"grain.{table}"


def relationship_decision_id(table: str, foreign_key: ForeignKeyEvidence) -> str:
    return f"relationship.{table}.{'+'.join(foreign_key.columns)}.{foreign_key.referenced_table}"


def propose_decisions(evidence: SourceEvidence) -> list[Decision]:
    decisions: list[Decision] = []
    for table in evidence.tables:
        decisions.append(_grain_decision(evidence, table))
    for table in evidence.tables:
        for foreign_key in table.foreign_keys:
            decisions.append(_relationship_decision(evidence, table, foreign_key))
    return decisions


def build_draft(evidence: SourceEvidence, decisions: list[Decision]) -> Draft:
    by_id = {decision.decision_id: decision for decision in decisions}
    findings: list[DraftFinding] = []
    identities: dict[str, dict[str, Any]] = {}
    grain_identity: dict[str, tuple[str, list[str]]] = {}
    definitions: dict[str, dict[tuple[str, tuple[str, ...]], dict[str, Any]]] = {
        table.name: {} for table in evidence.tables
    }
    grains: dict[str, Any] = {}

    for table in evidence.tables:
        decision = by_id[grain_decision_id(table.name)]
        grains[table.name] = "unknown"
        if decision.status in {"unknown", "waived"}:
            continue
        resolved = decision.resolved()
        columns = sorted(resolved.get("columns") or [])
        if not columns:
            continue
        missing = sorted(set(columns) - set(table.column_names()))
        if missing:
            findings.append(
                DraftFinding(
                    decision_id=decision.decision_id,
                    rule="unknown_grain_column",
                    message=f"grain columns {missing} are not columns of {table.name}",
                )
            )
            continue
        component: dict[str, Any] = {"dataset_columns": columns}
        identity_id = resolved.get("identity_id")
        if identity_id:
            name = resolved.get("identity_name") or identity_id
            registered = identities.get(identity_id)
            if registered is not None and registered["name"] != name:
                findings.append(
                    DraftFinding(
                        decision_id=decision.decision_id,
                        rule="conflicting_identity_name",
                        message=f"{identity_id!r} is already named {registered['name']!r}",
                    )
                )
            identities.setdefault(identity_id, {"name": name, "description": ""})
            definitions[table.name][(identity_id, tuple(columns))] = _entity_definition(
                identity_id, columns, resolved.get("entity_universe", "unknown")
            )
            grain_identity[table.name] = (identity_id, columns)
            component = {"identity_id": identity_id, "dataset_columns": columns}
        grains[table.name] = {"components": [component]}

    edges: list[dict[str, Any]] = []
    for table in evidence.tables:
        for foreign_key in table.foreign_keys:
            decision = by_id[relationship_decision_id(table.name, foreign_key)]
            resolved = decision.resolved()
            if decision.status in {"unknown", "waived"} or not resolved.get("include", True):
                continue
            target = grain_identity.get(foreign_key.referenced_table)
            parent_columns = sorted(foreign_key.referenced_columns)
            if target is None or target[1] != parent_columns:
                findings.append(
                    DraftFinding(
                        decision_id=decision.decision_id,
                        rule="unregistered_target_identity",
                        message=(
                            f"{foreign_key.referenced_table}.{parent_columns} is not a confirmed "
                            "grain identity; answer its grain decision or exclude this relationship"
                        ),
                    )
                )
                continue
            identity_id = target[0]
            child_columns = sorted(foreign_key.columns)
            key = (identity_id, tuple(child_columns))
            definitions[table.name].setdefault(
                key,
                _entity_definition(identity_id, child_columns, resolved.get("entity_universe", "unknown")),
            )
            edges.append(
                {
                    "endpoint_a": {
                        "node_id": node_id_for(evidence, table.name),
                        "identity_id": identity_id,
                        "dataset_columns": child_columns,
                    },
                    "endpoint_b": {
                        "node_id": node_id_for(evidence, foreign_key.referenced_table),
                        "identity_id": identity_id,
                        "dataset_columns": parent_columns,
                    },
                    "a_to_b": dict(resolved["a_to_b"]),
                    "b_to_a": dict(resolved["b_to_a"]),
                }
            )

    nodes = [
        _node(evidence, table, grains[table.name], list(definitions[table.name].values()))
        for table in evidence.tables
    ]
    return Draft(
        logical_identities=dict(sorted(identities.items())),
        nodes=nodes,
        edges=edges,
        findings=findings,
    )


def write_catalog_directory(target: Path, draft: Draft) -> None:
    """Write the manifest beside a ``yaml/`` directory of collection-owned files.

    ``target`` is replaced as a whole; the caller provides atomicity across directories.
    """
    if target.exists():
        shutil.rmtree(target)
    yaml_dir = target / "yaml"
    yaml_dir.mkdir(parents=True)
    node_files: list[str] = []
    used: set[str] = {IDENTITIES_FILE, RELATIONSHIPS_FILE}
    for node in draft.nodes:
        stem = _UNSAFE_FILENAME.sub("_", node["descriptor"]["display_name"])
        filename = f"nodes-{stem}.yaml"
        suffix = 2
        while filename in used:
            filename = f"nodes-{stem}-{suffix}.yaml"
            suffix += 1
        used.add(filename)
        node_files.append(filename)
        write_text_atomic(
            yaml_dir / filename, dump_yaml({"schema_version": SCHEMA_VERSION, "nodes": [node]})
        )
    write_text_atomic(
        yaml_dir / IDENTITIES_FILE,
        dump_yaml({"schema_version": SCHEMA_VERSION, "logical_identities": draft.logical_identities}),
    )
    write_text_atomic(
        yaml_dir / RELATIONSHIPS_FILE,
        dump_yaml({"schema_version": SCHEMA_VERSION, "edges": draft.edges}),
    )
    write_text_atomic(
        target / MANIFEST_FILENAME,
        dump_yaml(
            {
                "schema_version": SCHEMA_VERSION,
                "logical_identities": IDENTITIES_FILE,
                "nodes": node_files,
                "edges": RELATIONSHIPS_FILE,
            }
        ),
    )


def _grain_decision(evidence: SourceEvidence, table: TableEvidence) -> Decision:
    primary = table.primary_key()
    node_id = node_id_for(evidence, table.name)
    if primary is None:
        proposal: dict[str, Any] = {
            "columns": [],
            "identity_id": None,
            "identity_name": None,
            "entity_universe": "unknown",
        }
        question = (
            f"`{table.name}` declares no primary key. Which columns identify one record, and do "
            "they realize a business identity? Answer `unknown` if the record boundary is not "
            "known; the grain then stays an explicit unknown."
        )
    else:
        identity_id = f"{_snake(table.name)}_identity"
        proposal = {
            "columns": sorted(primary.columns),
            "identity_id": identity_id,
            "identity_name": f"{_title(table.name)} identity",
            "entity_universe": "unknown",
        }
        question = (
            f"Do columns {_columns(primary.columns)} identify one record of `{table.name}`, and does that "
            f"key realize the business identity `{identity_id}`? Override `identity_id` or "
            "`identity_name` to reuse or rename an identity, set `identity_id: null` for a "
            "record boundary that is not an identity, and set `entity_universe` to `complete` "
            "only if this dataset holds the whole population of that identity."
        )
    return Decision(
        decision_id=grain_decision_id(table.name),
        topic="grain",
        affected=f"nodes[{node_id}].grain",
        required=True,
        question=question,
        evidence=_grain_evidence(table, primary),
        proposal=proposal,
    )


def _grain_evidence(table: TableEvidence, primary: KeyEvidence | None) -> list[str]:
    items: list[str] = []
    if table.row_count is not None:
        items.append(f"D: {table.row_count} rows")
    for key in table.keys:
        observed = (
            f"; {key.duplicate_groups} duplicate key groups"
            if key.duplicate_groups is not None
            else ""
        )
        items.append(f"S: declared {key.kind} key {_columns(key.columns)}{observed}")
        items.extend(ref.label() for ref in key.refs)
    if primary is None and table.row_count is not None:
        for column in table.columns:
            if column.distinct_count == table.row_count and not column.null_count:
                items.append(f"D: column {column.name} is unique and non-null in the data")
    items.extend(f"warning: {warning}" for warning in table.warnings)
    return items


def _relationship_decision(
    evidence: SourceEvidence, table: TableEvidence, foreign_key: ForeignKeyEvidence
) -> Decision:
    child_unique = _columns_unique(table, foreign_key.columns)
    a_to_b = {
        "multiplicity": _known(child_unique, "1:1", "many:1"),
        "match_existence": _known(
            None
            if foreign_key.orphan_rows is None
            else foreign_key.orphan_rows == 0 and foreign_key.child_null_rows == 0,
            "always",
            "optional",
        ),
    }
    b_to_a = {
        "multiplicity": "1:1"
        if child_unique
        else _known(
            None
            if foreign_key.max_children_per_parent is None
            else foreign_key.max_children_per_parent <= 1,
            "1:1",
            "1:many",
        ),
        "match_existence": _known(
            None
            if foreign_key.unreferenced_parent_rows is None
            else foreign_key.unreferenced_parent_rows == 0,
            "always",
            "optional",
        ),
    }
    child = f"`{table.name}` ({_columns(foreign_key.columns)})"
    parent = f"`{foreign_key.referenced_table}` ({_columns(foreign_key.referenced_columns)})"
    evidence_items = [f"S: declared foreign key {child} -> {parent}"]
    if foreign_key.orphan_rows is not None:
        evidence_items.append(
            f"D: {foreign_key.child_null_rows} child rows with a null key, "
            f"{foreign_key.orphan_rows} orphan child rows, "
            f"{foreign_key.unreferenced_parent_rows} parent rows without a child, "
            f"at most {foreign_key.max_children_per_parent} child rows per parent"
        )
    evidence_items.extend(ref.label() for ref in foreign_key.refs)
    return Decision(
        decision_id=relationship_decision_id(table.name, foreign_key),
        topic="relationship",
        affected=(
            f"edges[{node_id_for(evidence, table.name)} -> "
            f"{node_id_for(evidence, foreign_key.referenced_table)}]"
        ),
        required=False,
        question=(
            f"Does {child} identify the same business entity as {parent}? The proposed claims "
            "come from the current data, which shows what is true now, not what is guaranteed. "
            "Keep `always` only where the rule holds by design; set `include: false` to drop "
            "the relationship. Direction `a_to_b` reads from the referencing dataset."
        ),
        evidence=evidence_items,
        proposal={
            "include": True,
            "entity_universe": "unknown",
            "a_to_b": a_to_b,
            "b_to_a": b_to_a,
        },
    )


def _columns_unique(table: TableEvidence, columns: list[str]) -> bool | None:
    wanted = sorted(columns)
    for key in table.keys:
        if sorted(key.columns) == wanted and key.duplicate_groups in (0, None):
            return True
    if table.row_count is None:
        return None
    if len(columns) == 1:
        column = next(c for c in table.columns if c.name == columns[0])
        if column.distinct_count is None or column.null_count is None:
            return None
        return column.distinct_count == table.row_count - column.null_count
    return None


def _columns(columns: list[str]) -> str:
    return ", ".join(f"`{column}`" for column in columns)


def _known(flag: bool | None, when_true: str, when_false: str) -> str:
    if flag is None:
        return "unknown"
    return when_true if flag else when_false


def _entity_definition(identity_id: str, columns: list[str], universe: str) -> dict[str, Any]:
    return {
        "identity_id": identity_id,
        "dataset_columns": columns,
        "entity_universe": universe,
        "entity_expression": [", ".join(f"[{column}]" for column in columns)],
        "entity_metadata": {"expression_context": "SQLite column reference"},
    }


def _node(
    evidence: SourceEvidence,
    table: TableEvidence,
    grain: Any,
    definitions: list[dict[str, Any]],
) -> dict[str, Any]:
    columns: list[dict[str, Any]] = []
    for column in table.columns:
        entry: dict[str, Any] = {"name": column.name}
        if column.description:
            entry["description"] = column.description
        if column.value_description:
            entry["value_description"] = column.value_description
        if column.synonyms:
            entry["synonyms"] = list(column.synonyms)
        columns.append(entry)
    return {
        "node_id": node_id_for(evidence, table.name),
        "descriptor": {
            "qualified_name": f"{evidence.catalog}.{table.schema_name}.{table.name}",
            "display_name": table.name,
        },
        "accessor": {
            "schema_id": evidence.accessor_schema_id,
            "properties": dict(evidence.accessor_properties[table.name]),
        },
        "grain": grain,
        "columns": columns,
        "entity_definitions": definitions,
    }


def _snake(name: str) -> str:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return re.sub(r"[^A-Za-z0-9]+", "_", spaced).strip("_").lower() or "dataset"


def _title(name: str) -> str:
    return _snake(name).replace("_", " ").capitalize()
