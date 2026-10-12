from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError
from yaml import YAMLError

from data_ontology_graph.akg.model import AkgDocument
from data_ontology_graph.builder.intermediary import (
    ValidationFinding,
    _validation_error_findings,
    intermediary_json_schema,
)


INTERMEDIARY_SCHEMA_FILE = "intermediary.schema.json"


class AkgValidationReport(BaseModel):
    valid: bool
    findings: list[ValidationFinding] = Field(default_factory=list)


class AkgValidationError(ValueError):
    def __init__(self, path: Path, findings: list[ValidationFinding]) -> None:
        self.path = path
        self.findings = findings
        details = "; ".join(
            f"{finding.location} [{finding.rule}]: {finding.message}" for finding in findings
        )
        super().__init__(f"AKG validation failed for {path}: {details}")


def akg_json_schema() -> dict[str, Any]:
    """Return the AKG envelope schema.

    Definitions shared with the intermediary schema are referenced from
    `intermediary.schema.json` instead of being repeated, so a cut always follows the graph's
    node and edge model.
    """
    schema = AkgDocument.model_json_schema()
    shared = intermediary_json_schema()["$defs"]
    definitions = schema["$defs"]
    external = {name for name, body in definitions.items() if shared.get(name) == body}
    for name in external:
        del definitions[name]
    return _rewrite_refs(schema, external)


def write_akg_json_schema(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(akg_json_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def validate_akg_payload(payload: object) -> AkgValidationReport:
    try:
        AkgDocument.model_validate(payload)
    except ValidationError as error:
        return AkgValidationReport(valid=False, findings=_validation_error_findings(error))
    return AkgValidationReport(valid=True)


def validate_akg_yaml(path: Path | str) -> AkgValidationReport:
    source = Path(path)
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
        return AkgValidationReport(valid=False, findings=[finding])
    return validate_akg_payload(payload)


def load_akg_yaml(path: Path | str) -> AkgDocument:
    source = Path(path)
    report = validate_akg_yaml(source)
    if not report.valid:
        raise AkgValidationError(source, report.findings)
    return AkgDocument.model_validate(yaml.safe_load(source.read_text(encoding="utf-8")))


def _rewrite_refs(value: Any, external: set[str]) -> Any:
    if isinstance(value, dict):
        rewritten = {key: _rewrite_refs(item, external) for key, item in value.items()}
        reference = rewritten.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            name = reference.removeprefix("#/$defs/")
            if name in external:
                rewritten["$ref"] = f"{INTERMEDIARY_SCHEMA_FILE}#/$defs/{name}"
        return rewritten
    if isinstance(value, list):
        return [_rewrite_refs(item, external) for item in value]
    return value
