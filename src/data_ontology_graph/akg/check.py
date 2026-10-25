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

from data_ontology_graph.akg.model import AkgDocument, DirectedEdge
from data_ontology_graph.builder.intermediary import _format_location
from data_ontology_graph.model.relationship import JoinEndpoint, edge_id_for


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
    if isinstance(payload, dict) and "relationships" in payload:
        return [
            _error(
                "$.relationships",
                "unconverted_relationships",
                "the document uses the earlier relationships map; run `akg.py migrate FILE`",
            )
        ]
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


def _references(document: AkgDocument, dangling: Severity) -> list[AkgFinding]:
    findings: list[AkgFinding] = []
    datasets = document.datasets

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
        if node_id in datasets and column not in (datasets[node_id].columns or {}):
            findings.append(
                AkgFinding(
                    location=location,
                    rule="unlisted_column",
                    severity=dangling,
                    message=f"column {column!r} is not listed in dataset {node_id!r}",
                )
            )

    for node_id, dataset in datasets.items():
        usage = dataset.usage
        for column in (usage.columns or {}) if usage else {}:
            require_column(node_id, column, f"$.datasets[{node_id!r}].usage.columns[{column!r}]")

        seen: set[tuple[str, tuple[str, ...]]] = set()
        for index, edge in enumerate(dataset.edges or []):
            location = f"$.datasets[{node_id!r}].edges[{index}]"
            canonical = _edge_id(node_id, edge)
            if canonical != edge.edge_id:
                findings.append(_error(location, "edge_key", f"canonical edge ID is {canonical!r}"))
            key = (edge.edge_id, tuple(edge.from_dataset_columns))
            if key in seen:
                findings.append(
                    _error(location, "duplicate_edge", "the dataset already holds this directed edge")
                )
            seen.add(key)
            require_dataset(edge.to_node_id, f"{location}.to_node_id")
            for keep, kept in enumerate((edge.usage.keep or []) if edge.usage else []):
                if kept not in (node_id, edge.to_node_id):
                    findings.append(
                        _error(
                            f"{location}.usage.keep[{keep}]",
                            "not_an_endpoint",
                            f"{kept!r} is neither the start nor the end of this directed edge",
                        )
                    )

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
            held = datasets.get(reference.node_id)
            if held is None or all(edge.edge_id != reference.edge_id for edge in held.edges or []):
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


def _edge_id(node_id: str, edge: DirectedEdge) -> str | None:
    try:
        return edge_id_for(
            JoinEndpoint(node_id=node_id, identity_id=edge.identity_id,
                         dataset_columns=edge.from_dataset_columns),
            JoinEndpoint(node_id=edge.to_node_id, identity_id=edge.identity_id,
                         dataset_columns=edge.to_dataset_columns),
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
