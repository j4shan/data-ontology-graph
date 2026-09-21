from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import yaml
from pydantic import BaseModel, Field, ValidationError
from yaml import YAMLError

from data_ontology_graph.model.intermediary import IntermediaryDefinition


_YAML_SUFFIXES = {".yaml", ".yml"}
_TOP_LEVEL_KEYS = {"schema_version", "logical_identities", "nodes", "edges"}


class ValidationFinding(BaseModel):
    location: str
    rule: str
    message: str
    line: int | None = None
    column: int | None = None


class IntermediaryValidationReport(BaseModel):
    valid: bool
    findings: list[ValidationFinding] = Field(default_factory=list)


class IntermediaryValidationError(ValueError):
    def __init__(self, path: Path, findings: list[ValidationFinding]) -> None:
        self.path = path
        self.findings = findings
        details = "; ".join(
            f"{finding.location} [{finding.rule}]: {finding.message}"
            for finding in findings
        )
        super().__init__(f"intermediary validation failed for {path}: {details}")


def intermediary_json_schema() -> dict[str, Any]:
    return IntermediaryDefinition.model_json_schema()


def write_intermediary_json_schema(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(intermediary_json_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def validate_intermediary_yaml(path: Path | str) -> IntermediaryValidationReport:
    source = Path(path)
    if source.is_dir():
        _, findings = _assemble_intermediary_directory(source)
        return IntermediaryValidationReport(valid=not findings, findings=findings)
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    except YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        finding = ValidationFinding(
            location="$",
            rule="yaml_syntax",
            message=str(error).splitlines()[0],
            line=mark.line + 1 if mark else None,
            column=mark.column + 1 if mark else None,
        )
        return IntermediaryValidationReport(valid=False, findings=[finding])

    findings = _validation_findings(payload)
    if findings:
        return IntermediaryValidationReport(valid=False, findings=findings)
    return IntermediaryValidationReport(valid=True)


def load_intermediary_yaml(path: Path | str) -> IntermediaryDefinition:
    source = Path(path)
    if source.is_dir():
        return load_intermediary_directory(source)
    report = validate_intermediary_yaml(source)
    if not report.valid:
        raise IntermediaryValidationError(source, report.findings)
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    return IntermediaryDefinition.model_validate(payload)


def load_intermediary_directory(path: Path | str) -> IntermediaryDefinition:
    source = Path(path)
    payload, findings = _assemble_intermediary_directory(source)
    if findings:
        raise IntermediaryValidationError(source, findings)
    assert payload is not None
    definition = IntermediaryDefinition.model_validate(payload)
    return definition.model_copy(
        update={
            "logical_identities": dict(sorted(definition.logical_identities.items())),
            "nodes": sorted(definition.nodes, key=lambda node: node.node_id),
            "edges": sorted(definition.edges, key=lambda edge: edge.canonical_edge_id()),
        }
    )


def _assemble_intermediary_directory(
    source: Path,
) -> tuple[dict[str, Any] | None, list[ValidationFinding]]:
    if not source.is_dir():
        return None, [
            ValidationFinding(
                location="$",
                rule="directory_type",
                message=f"expected a YAML directory: {source}",
            )
        ]

    files = sorted(
        (path for path in source.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(source).as_posix(),
    )
    unsupported = [path for path in files if path.suffix.casefold() not in _YAML_SUFFIXES]
    if unsupported:
        return None, [
            ValidationFinding(
                location=path.relative_to(source).as_posix(),
                rule="unsupported_file",
                message="finalized YAML directories may contain only .yaml or .yml files",
            )
            for path in unsupported
        ]

    yaml_files = [path for path in files if path.suffix.casefold() in _YAML_SUFFIXES]
    if not yaml_files:
        return None, [
            ValidationFinding(
                location="$",
                rule="missing_yaml",
                message="finalized YAML directory contains no .yaml or .yml files",
            )
        ]

    schema_version: object | None = None
    schema_version_seen = False
    schema_version_source: str | None = None
    logical_identities: dict[str, Any] = {}
    identity_sources: dict[str, str] = {}
    nodes: list[Any] = []
    node_sources: dict[str, str] = {}
    edges: list[Any] = []
    findings: list[ValidationFinding] = []

    for path in yaml_files:
        relative = path.relative_to(source).as_posix()
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except YAMLError as error:
            mark = getattr(error, "problem_mark", None)
            findings.append(
                ValidationFinding(
                    location=f"{relative}:$",
                    rule="yaml_syntax",
                    message=str(error).splitlines()[0],
                    line=mark.line + 1 if mark else None,
                    column=mark.column + 1 if mark else None,
                )
            )
            continue
        if not isinstance(document, Mapping):
            findings.append(
                ValidationFinding(
                    location=f"{relative}:$",
                    rule="mapping_type",
                    message="each YAML file must contain a top-level mapping",
                )
            )
            continue

        extra_keys = sorted(
            (key for key in document if key not in _TOP_LEVEL_KEYS),
            key=str,
        )
        for key in extra_keys:
            findings.append(
                ValidationFinding(
                    location=f"{relative}:$.{key}",
                    rule="extra_forbidden",
                    message="unsupported top-level field",
                )
            )

        if "schema_version" in document:
            value = document["schema_version"]
            if not schema_version_seen:
                schema_version = value
                schema_version_source = relative
                schema_version_seen = True
            elif value != schema_version:
                findings.append(
                    ValidationFinding(
                        location=f"{relative}:$.schema_version",
                        rule="conflicting_schema_version",
                        message=(
                            f"schema_version conflicts with {schema_version_source}: "
                            f"{value!r} != {schema_version!r}"
                        ),
                    )
                )

        identities = document.get("logical_identities", {})
        if not isinstance(identities, Mapping):
            findings.append(
                ValidationFinding(
                    location=f"{relative}:$.logical_identities",
                    rule="mapping_type",
                    message="logical_identities must be a mapping",
                )
            )
        else:
            for identity_id, definition in identities.items():
                if identity_id in logical_identities:
                    findings.append(
                        ValidationFinding(
                            location=f"{relative}:$.logical_identities.{identity_id}",
                            rule="duplicate_definition",
                            message=(
                                "logical identity is already defined in "
                                f"{identity_sources[identity_id]}"
                            ),
                        )
                    )
                else:
                    logical_identities[identity_id] = definition
                    identity_sources[identity_id] = relative

        file_nodes = document.get("nodes", [])
        if not isinstance(file_nodes, list):
            findings.append(
                ValidationFinding(
                    location=f"{relative}:$.nodes",
                    rule="list_type",
                    message="nodes must be a list",
                )
            )
        else:
            for index, node in enumerate(file_nodes):
                node_id = node.get("node_id") if isinstance(node, Mapping) else None
                if isinstance(node_id, str) and node_id in node_sources:
                    findings.append(
                        ValidationFinding(
                            location=f"{relative}:$.nodes[{index}].node_id",
                            rule="duplicate_definition",
                            message=f"node is already defined in {node_sources[node_id]}",
                        )
                    )
                else:
                    if isinstance(node_id, str):
                        node_sources[node_id] = relative
                    nodes.append(node)

        file_edges = document.get("edges", [])
        if not isinstance(file_edges, list):
            findings.append(
                ValidationFinding(
                    location=f"{relative}:$.edges",
                    rule="list_type",
                    message="edges must be a list",
                )
            )
        else:
            edges.extend(file_edges)

    if findings:
        return None, findings

    payload = {
        "schema_version": schema_version,
        "logical_identities": logical_identities,
        "nodes": nodes,
        "edges": edges,
    }
    validation_findings = _validation_findings(payload)
    return (None, validation_findings) if validation_findings else (payload, [])


def _validation_findings(payload: object) -> list[ValidationFinding]:
    try:
        IntermediaryDefinition.model_validate(payload)
    except ValidationError as error:
        return [
            ValidationFinding(
                location=_format_location(item["loc"]),
                rule=item["type"],
                message=item["msg"],
            )
            for item in error.errors(include_url=False, include_context=False)
        ]
    return []


def _format_location(parts: tuple[str | int, ...]) -> str:
    location = "$"
    for part in parts:
        if isinstance(part, int):
            location += f"[{part}]"
        else:
            location += f".{part}"
    return location
