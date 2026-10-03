from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import yaml
from pydantic import BaseModel, Field, ValidationError
from yaml import YAMLError

from data_ontology_graph.model.intermediary import (
    IntermediaryDefinition,
    IntermediaryDirectoryManifest,
)


_YAML_SUFFIXES = {".yaml", ".yml"}
_COLLECTION_KEYS = {"logical_identities", "nodes", "edges"}
_MANIFEST_FILENAME = "directory-manifest.yaml"


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


def intermediary_directory_json_schema() -> dict[str, Any]:
    return IntermediaryDirectoryManifest.model_json_schema()


def write_intermediary_json_schema(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(intermediary_json_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_intermediary_directory_json_schema(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(intermediary_directory_json_schema(), indent=2, sort_keys=True) + "\n",
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

    manifest_path = source.parent / _MANIFEST_FILENAME
    if not manifest_path.is_file():
        return None, [
            ValidationFinding(
                location=_MANIFEST_FILENAME,
                rule="missing_manifest",
                message=f"expected sibling manifest: {manifest_path}",
            )
        ]

    try:
        manifest_payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        return None, [
            ValidationFinding(
                location=f"{_MANIFEST_FILENAME}:$",
                rule="yaml_syntax",
                message=str(error).splitlines()[0],
                line=mark.line + 1 if mark else None,
                column=mark.column + 1 if mark else None,
            )
        ]

    try:
        manifest = IntermediaryDirectoryManifest.model_validate(manifest_payload)
    except ValidationError as error:
        return None, _validation_error_findings(error, prefix=f"{_MANIFEST_FILENAME}:")

    entries: list[tuple[str, str, str]] = [
        ("logical_identities", manifest.logical_identities, "$.logical_identities"),
        *(("nodes", path, f"$.nodes[{index}]") for index, path in enumerate(manifest.nodes)),
        ("edges", manifest.edges, "$.edges"),
    ]
    source_resolved = source.resolve()
    listed: dict[str, str] = {}
    findings: list[ValidationFinding] = []

    for collection, raw_path, manifest_location in entries:
        location = f"{_MANIFEST_FILENAME}:{manifest_location}"
        relative_path = Path(raw_path)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            findings.append(
                ValidationFinding(
                    location=location,
                    rule="invalid_collection_path",
                    message="collection paths must be relative and must not contain '..'",
                )
            )
            continue
        candidate = source / relative_path
        relative = candidate.relative_to(source).as_posix()
        if relative in listed:
            findings.append(
                ValidationFinding(
                    location=location,
                    rule="duplicate_manifest_path",
                    message=f"collection path is already owned by {listed[relative]!r}",
                )
            )
            continue
        listed[relative] = collection
        if candidate.suffix.casefold() not in _YAML_SUFFIXES:
            findings.append(
                ValidationFinding(
                    location=location,
                    rule="unsupported_file",
                    message="collection paths must name .yaml or .yml files",
                )
            )
            continue
        try:
            candidate.resolve(strict=False).relative_to(source_resolved)
        except ValueError:
            findings.append(
                ValidationFinding(
                    location=location,
                    rule="path_outside_directory",
                    message="collection path resolves outside the finalized YAML directory",
                )
            )
            continue
        if not candidate.is_file():
            findings.append(
                ValidationFinding(
                    location=location,
                    rule="missing_file",
                    message=f"listed collection file does not exist: {relative}",
                )
            )

    files = sorted(
        (path for path in source.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(source).as_posix(),
    )
    if not files:
        findings.append(
            ValidationFinding(
                location="$",
                rule="missing_yaml",
                message="finalized YAML directory contains no .yaml or .yml files",
            )
        )
    for path in files:
        relative = path.relative_to(source).as_posix()
        if path.suffix.casefold() not in _YAML_SUFFIXES:
            findings.append(
                ValidationFinding(
                    location=relative,
                    rule="unsupported_file",
                    message="finalized YAML directories may contain only .yaml or .yml files",
                )
            )
        elif relative not in listed:
            findings.append(
                ValidationFinding(
                    location=relative,
                    rule="unlisted_file",
                    message=f"YAML file is not listed in {_MANIFEST_FILENAME}",
                )
            )

    if findings:
        return None, findings

    logical_identities: dict[str, Any] = {}
    identity_sources: dict[str, str] = {}
    nodes: list[Any] = []
    node_sources: dict[str, str] = {}
    edges: list[Any] = []

    for collection, raw_path, _ in entries:
        path = source / raw_path
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

        required_keys = {"schema_version", collection}
        for key in sorted(required_keys - set(document), key=str):
            findings.append(
                ValidationFinding(
                    location=f"{relative}:$",
                    rule="missing",
                    message=f"collection file must contain {key!r}",
                )
            )
        extra_keys = sorted((key for key in document if key not in required_keys), key=str)
        for key in extra_keys:
            findings.append(
                ValidationFinding(
                    location=f"{relative}:$.{key}",
                    rule=("collection_ownership" if key in _COLLECTION_KEYS else "extra_forbidden"),
                    message=(
                        f"file is owned by {collection!r}, not {key!r}"
                        if key in _COLLECTION_KEYS
                        else "unsupported top-level field"
                    ),
                )
            )

        if document.get("schema_version") != manifest.schema_version:
            findings.append(
                ValidationFinding(
                    location=f"{relative}:$.schema_version",
                    rule="conflicting_schema_version",
                    message=(
                        f"schema_version conflicts with {_MANIFEST_FILENAME}: "
                        f"{document.get('schema_version')!r} != {manifest.schema_version!r}"
                    ),
                )
            )

        if collection == "logical_identities":
            identities = document.get(collection)
            if not isinstance(identities, Mapping):
                findings.append(
                    ValidationFinding(
                        location=f"{relative}:$.logical_identities",
                        rule="mapping_type",
                        message="logical_identities must be a mapping",
                    )
                )
                continue
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
        elif collection == "nodes":
            file_nodes = document.get(collection)
            if not isinstance(file_nodes, list):
                findings.append(
                    ValidationFinding(
                        location=f"{relative}:$.nodes",
                        rule="list_type",
                        message="nodes must be a list",
                    )
                )
                continue
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
        else:
            file_edges = document.get(collection)
            if not isinstance(file_edges, list):
                findings.append(
                    ValidationFinding(
                        location=f"{relative}:$.edges",
                        rule="list_type",
                        message="edges must be a list",
                    )
                )
                continue
            edges.extend(file_edges)

    if findings:
        return None, findings

    payload = {
        "schema_version": manifest.schema_version,
        "logical_identities": logical_identities,
        "nodes": nodes,
        "edges": edges,
    }
    validation_findings = _validation_findings(payload)
    return (None, validation_findings) if validation_findings else (payload, [])


def _validation_error_findings(
    error: ValidationError,
    *,
    prefix: str = "",
) -> list[ValidationFinding]:
    return [
        ValidationFinding(
            location=f"{prefix}{_format_location(item['loc'])}",
            rule=item["type"],
            message=item["msg"],
        )
        for item in error.errors(include_url=False, include_context=False)
    ]


def _validation_findings(payload: object) -> list[ValidationFinding]:
    try:
        IntermediaryDefinition.model_validate(payload)
    except ValidationError as error:
        return _validation_error_findings(error)
    return []


def _format_location(parts: tuple[str | int, ...]) -> str:
    location = "$"
    for part in parts:
        if isinstance(part, int):
            location += f"[{part}]"
        else:
            location += f".{part}"
    return location
