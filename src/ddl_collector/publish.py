"""Publish a finalized preparation session as a durable catalog directory."""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from importlib import metadata
from pathlib import Path
from typing import Any

from ddl_collector.config import (
    SessionState,
    dump_yaml,
    verify_sources,
    write_text_atomic,
)
from ddl_collector.draft import Draft, write_catalog_directory
from ddl_collector.evidence import SourceEvidence
from ddl_collector.survey import Decision, render_decision_log
from ddl_collector.validate import CollectorReport, validate_catalog_directory


class PublishRefused(RuntimeError):
    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("; ".join(reasons))


def publish_catalog(
    state: SessionState,
    evidence: SourceEvidence,
    decisions: list[Decision],
    draft: Draft,
    catalog_root: Path,
) -> tuple[Path, CollectorReport]:
    """Write ``<catalog_root>/<catalog>/`` atomically, or raise PublishRefused.

    The directory holds the manifest, ``yaml/``, ``decisions.md``, and ``provenance.yaml``.
    Publication requires verified sources, no open or blocking decision, no draft finding, and
    a catalog that passes the builder's validation in its final location layout.
    """
    reasons: list[str] = []
    try:
        current = verify_sources(state.source_ref())
    except ValueError as error:
        current = {}
        reasons.append(f"source verification failed: {error}")
    if current and current != state.source_files:
        reasons.append("sources changed since extraction; run extract again")
    unresolved = sorted(d.decision_id for d in decisions if d.status in {"open", "blocking"})
    if unresolved:
        reasons.append(f"unresolved decisions: {unresolved}")
    reasons.extend(f"{f.decision_id} [{f.rule}]: {f.message}" for f in draft.findings)
    if reasons:
        raise PublishRefused(reasons)

    catalog_root = Path(catalog_root)
    catalog_root.mkdir(parents=True, exist_ok=True)
    target = catalog_root / state.catalog
    token = uuid.uuid4().hex
    staging = catalog_root / f".{state.catalog}.staging-{token}"
    try:
        write_catalog_directory(staging, draft)
        report = validate_catalog_directory(staging / "yaml", decisions, draft.findings)
        if not report.valid:
            raise PublishRefused(
                [f"{f.location} [{f.rule}]: {f.message}" for f in report.findings]
            )
        write_text_atomic(staging / "decisions.md", render_decision_log(state.catalog, decisions))
        write_text_atomic(
            staging / "provenance.yaml",
            dump_yaml(_provenance(state, evidence, decisions, report)),
        )
        _swap(staging, target, token)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return target, report


def _swap(staging: Path, target: Path, token: str) -> None:
    previous = target.with_name(f".{target.name}.previous-{token}")
    if target.exists():
        os.replace(target, previous)
    try:
        os.replace(staging, target)
    except BaseException:
        if previous.exists():
            os.replace(previous, target)
        raise
    if previous.exists():
        shutil.rmtree(previous)


def _provenance(
    state: SessionState,
    evidence: SourceEvidence,
    decisions: list[Decision],
    report: CollectorReport,
) -> dict[str, Any]:
    return {
        "catalog": state.catalog,
        "schema_version": "3",
        "source": {
            "family": evidence.family,
            "accessor_schema_id": evidence.accessor_schema_id,
            "source_root": state.source_root,
            "host": state.host,
            "files": dict(sorted(state.source_files.items())),
        },
        "generator": _generator(),
        "review": {
            "rounds": state.round,
            "decisions": report.decisions,
        },
        "counts": {
            "identities": report.identity_count,
            "nodes": report.node_count,
            "edges": report.edge_count,
        },
        "unknown_fields": report.unknown_fields,
    }


def _generator() -> dict[str, Any]:
    try:
        version = metadata.version("data-ontology-graph")
    except metadata.PackageNotFoundError:
        version = None
    repository = Path(__file__).resolve().parents[2]
    commit = _git(repository, "rev-parse", "HEAD")
    status = _git(repository, "status", "--porcelain", "--", "src")
    return {
        "package": "data-ontology-graph",
        "version": version,
        "commit": commit,
        "source_modified": bool(status) if commit else None,
    }


def _git(repository: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip()
