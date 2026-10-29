"""Check an AKG document and report findings by location, rule, and severity.

No check refuses to load a parseable document. Errors block `finalize`; warnings mark draft
states that `finalize` treats as errors; info notes keys the contract does not name.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ValidationError
from yaml import YAMLError

from data_ontology_graph.akg.model import AkgDocument, Dataset
from data_ontology_graph.builder.intermediary import _format_location
from data_ontology_graph.model.relationship import JoinEndpoint, edge_id_for
from data_ontology_graph.service.views import EDGE_FIELDS as API_EDGE_FIELDS, split_edge_label


Severity = Literal["error", "warning", "info"]


class AkgFinding(BaseModel):
    location: str
    rule: str
    severity: Severity
    message: str
    line: int | None = None
    column: int | None = None


def load_payload(path: Path | str) -> tuple[Any, list[AkgFinding]]:
    """Read JSON, or YAML for a `.yaml`/`.yml` file. A parse error is one error finding."""
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    try:
        if source.suffix in (".yaml", ".yml"):
            return yaml.safe_load(text), []
        return json.loads(text), []
    except json.JSONDecodeError as error:
        return None, [_error("$", "parse_error", error.msg, error.lineno, error.colno)]
    except YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        return None, [
            _error(
                "$",
                "parse_error",
                str(error).splitlines()[0],
                mark.line + 1 if mark else None,
                mark.column + 1 if mark else None,
            )
        ]


def write_payload(path: Path | str, payload: Any) -> None:
    """Replace the document atomically, keeping its JSON or YAML form."""
    target = Path(path)
    if target.suffix in (".yaml", ".yml"):
        text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    else:
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, target)


def check_document(payload: Any, *, final: bool = False) -> list[AkgFinding]:
    """Return every finding for one parsed document; `final` applies the finalize rules."""
    try:
        document = AkgDocument.model_validate(payload)
    except ValidationError as error:
        return [
            _error(_format_location(item["loc"]), item["type"], item["msg"])
            for item in error.errors(include_url=False, include_context=False)
        ]
    findings = _references(document, "error" if final else "warning")
    findings.extend(_unknown_keys(document, "$"))
    return findings


def has_errors(findings: list[AkgFinding]) -> bool:
    return any(finding.severity == "error" for finding in findings)


def dataset_location(node_id: str) -> str:
    return f"$.datasets[{node_id!r}]"


def edge_location(node_id: str, identity_id: str, columns: list[str], edge_id: str) -> str:
    return (
        f"{dataset_location(node_id)}.edge_groups[{identity_id!r}]"
        f".entity_definitions[{columns!r}].edges[{edge_id!r}]"
    )


def _references(document: AkgDocument, dangling: Severity) -> list[AkgFinding]:
    findings: list[AkgFinding] = []
    datasets: dict[str, Dataset] = {}
    for index, dataset in enumerate(document.datasets):
        if dataset.node_id in datasets:
            findings.append(
                _error(f"$.datasets[{index}]", "duplicate_dataset",
                       f"dataset {dataset.node_id!r} appears more than once")
            )
        datasets.setdefault(dataset.node_id, dataset)

    fields = document.edge_fields
    if fields[0] != "edge" or fields[-1] != "edge_id" or len(set(fields)) != len(fields) or any(
        field not in API_EDGE_FIELDS for field in fields
    ):
        findings.append(
            _error("$.edge_fields", "edge_fields",
                   "must start with `edge`, end with `edge_id`, and name directed-edge fields once")
        )
        return findings

    def require_dataset(node_id: str, location: str) -> bool:
        if node_id in datasets:
            return True
        findings.append(
            AkgFinding(
                location=location,
                rule="dangling_reference",
                severity=dangling,
                message=f"names dataset {node_id!r}, which is not in the document",
            )
        )
        return False

    def require_column(node_id: str, column: str, location: str) -> None:
        listed = {item.name for item in datasets[node_id].columns or []} if node_id in datasets else set()
        if node_id in datasets and column not in listed:
            findings.append(
                AkgFinding(
                    location=location,
                    rule="unlisted_column",
                    severity=dangling,
                    message=f"column {column!r} is not listed in dataset {node_id!r}",
                )
            )

    held: dict[str, set[str]] = {}
    for node_id, dataset in datasets.items():
        usage = dataset.usage
        for column in (usage.columns or {}) if usage else {}:
            require_column(node_id, column, f"{dataset_location(node_id)}.usage.columns[{column!r}]")
        for group in dataset.edge_groups or []:
            for definition in group.entity_definitions:
                edge_ids = _check_definition(
                    node_id, group.identity_id, definition, fields, findings, require_dataset,
                )
                held.setdefault(node_id, set()).update(edge_ids)

    for key, comparison in (document.comparisons or {}).items():
        location = f"$.comparisons[{key!r}]"
        for index, node_id in enumerate(comparison.anchors):
            require_dataset(node_id, f"{location}.anchors[{index}]")
        for index, reference in enumerate(comparison.shared_columns):
            item = f"{location}.shared_columns[{index}]"
            if require_dataset(reference.node_id, item):
                require_column(reference.node_id, reference.column, item)

    for key, gap in (document.gaps or {}).items():
        location = f"$.gaps[{key!r}]"
        for index, node_id in enumerate(gap.datasets or []):
            require_dataset(node_id, f"{location}.datasets[{index}]")
        for index, reference in enumerate(gap.edges or []):
            if reference.edge_id not in held.get(reference.node_id, set()):
                findings.append(
                    AkgFinding(
                        location=f"{location}.edges[{index}]",
                        rule="dangling_reference",
                        severity=dangling,
                        message=(
                            f"names directed edge {reference.edge_id!r} of dataset "
                            f"{reference.node_id!r}, which is not in the document"
                        ),
                    )
                )
    return findings


def _check_definition(node_id, identity_id, definition, fields, findings, require_dataset) -> set[str]:
    """Check one entity definition's directed edges; return the edge IDs it holds."""
    columns = definition.dataset_columns
    seen: set[str] = set()
    ends: dict[str, str] = {}
    readable = True
    for index, array in enumerate(definition.edges):
        base = (
            f"{dataset_location(node_id)}.edge_groups[{identity_id!r}]"
            f".entity_definitions[{columns!r}].edges[{index}]"
        )
        if len(array) != len(fields):
            findings.append(_error(base, "edge_length",
                                   f"has {len(array)} positions; `edge_fields` names {len(fields)}"))
            readable = False
            continue
        values = dict(zip(fields, array))
        try:
            (start_node, start_columns), (end_node, end_columns) = split_edge_label(values["edge"])
        except (TypeError, ValueError) as error:
            findings.append(_error(base, "edge_label", str(error)))
            readable = False
            continue
        edge_id = values["edge_id"]
        location = edge_location(node_id, identity_id, columns, str(edge_id))
        if (start_node, start_columns) != (node_id, columns):
            findings.append(
                _error(location, "edge_start",
                       f"starts at {start_node}{start_columns}, not at the entity definition "
                       "that holds it")
            )
        canonical = _edge_id(identity_id, (start_node, start_columns), (end_node, end_columns))
        if canonical != edge_id:
            findings.append(_error(location, "edge_key", f"canonical edge ID is {canonical!r}"))
        if edge_id in seen:
            findings.append(
                _error(location, "duplicate_edge", "the entity definition already holds this edge")
            )
        seen.add(edge_id)
        ends[edge_id] = end_node
        require_dataset(end_node, f"{location}.edge")
    # Usage keys are checked only when every directed edge of the definition could be read.
    for edge_id, usage in (definition.usage or {}).items() if readable else ():
        location = (
            f"{dataset_location(node_id)}.edge_groups[{identity_id!r}]"
            f".entity_definitions[{columns!r}].usage[{edge_id!r}]"
        )
        if edge_id not in ends:
            findings.append(
                _error(location, "usage_key", "names no directed edge of this entity definition")
            )
            continue
        for keep, kept in enumerate(usage.keep or []):
            if kept not in (node_id, ends[edge_id]):
                findings.append(
                    _error(f"{location}.keep[{keep}]", "not_an_endpoint",
                           f"{kept!r} is neither the start nor the end of this directed edge")
                )
    return seen


def _edge_id(identity_id: str, start: tuple[str, list[str]], end: tuple[str, list[str]]) -> str | None:
    try:
        return edge_id_for(
            JoinEndpoint(node_id=start[0], identity_id=identity_id, dataset_columns=start[1]),
            JoinEndpoint(node_id=end[0], identity_id=identity_id, dataset_columns=end[1]),
        )
    except ValidationError:
        return None


def _unknown_keys(value: Any, location: str) -> list[AkgFinding]:
    findings: list[AkgFinding] = []
    if isinstance(value, BaseModel):
        for key in value.model_extra or {}:
            findings.append(
                AkgFinding(
                    location=f"{location}.{key}",
                    rule="unknown_key",
                    severity="info",
                    message="key is not part of the contract; it is kept and not checked",
                )
            )
        for name, field in type(value).model_fields.items():
            findings.extend(_unknown_keys(getattr(value, name), f"{location}.{field.alias or name}"))
    elif isinstance(value, dict):
        for key, item in value.items():
            findings.extend(_unknown_keys(item, f"{location}[{key!r}]"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(_unknown_keys(item, f"{location}[{index}]"))
    return findings


def _error(
    location: str, rule: str, message: str, line: int | None = None, column: int | None = None
) -> AkgFinding:
    return AkgFinding(
        location=location, rule=rule, severity="error", message=message, line=line, column=column
    )
