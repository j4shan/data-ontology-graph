"""`ddl-collector`: staged, reviewable preparation of intermediary YAML.

Exit codes: 0 success, 1 validation failure or refused publication, 2 malformed survey or
invalid input. Every stage works inside one session directory given by ``--scratch``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from ddl_collector.config import (
    DEFAULT_HOST,
    DEFAULT_SOURCE_ROOT,
    SessionPaths,
    SessionState,
    SourceIntegrityError,
    SourceRef,
    dump_yaml,
    verify_sources,
    write_text_atomic,
)
from ddl_collector.draft import Draft, build_draft, propose_decisions, write_catalog_directory
from ddl_collector.evidence import SourceEvidence
from ddl_collector.publish import PublishRefused, publish_catalog
from ddl_collector.sources import FAMILIES, family
from ddl_collector.survey import (
    Decision,
    SurveyError,
    dump_decisions,
    load_decisions,
    parse_survey,
    render_survey,
)
from ddl_collector.validate import CollectorReport, validate_catalog_directory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ddl-collector", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    extract = commands.add_parser("extract", help="read a source and write the first draft and survey")
    extract.add_argument("--critic-root", type=Path, required=True)
    extract.add_argument("--catalog", required=True)
    extract.add_argument("--family", choices=sorted(FAMILIES), default="sqlite")
    extract.add_argument("--source-root", default=DEFAULT_SOURCE_ROOT)
    extract.add_argument("--host", default=DEFAULT_HOST)
    extract.add_argument("--no-profile", action="store_true", help="skip read-only data profiling")

    for name, help_text in (
        ("survey", "regenerate the survey for unresolved decisions"),
        ("apply", "apply the filled survey, rebuild the draft, and validate"),
        ("validate", "validate the current draft and report unresolved decisions"),
    ):
        commands.add_parser(name, help=help_text)

    publish = commands.add_parser("publish", help="publish the finalized catalog directory")
    publish.add_argument("--catalog-root", type=Path, required=True)

    for sub in commands.choices.values():
        sub.add_argument("--scratch", type=Path, required=True, help="session directory")

    args = parser.parse_args(argv)
    paths = SessionPaths(args.scratch)
    try:
        if args.command == "extract":
            return _extract(args, paths)
        state, evidence, decisions = _load(paths)
        if args.command == "survey":
            write_text_atomic(paths.survey, render_survey(state.catalog, state.round + 1, decisions))
            return _emit({"survey": str(paths.survey), "unresolved": _unresolved(decisions)})
        if args.command == "apply":
            return _apply(paths, state, evidence, decisions)
        if args.command == "validate":
            report = _rebuild(paths, evidence, decisions)
            _emit(report.model_dump(mode="json"))
            return 0 if report.valid and not report.draft_findings else 1
        if args.command == "publish":
            draft = build_draft(evidence, decisions)
            target, report = publish_catalog(state, evidence, decisions, draft, args.catalog_root)
            return _emit(
                {
                    "published": str(target),
                    "nodes": report.node_count,
                    "edges": report.edge_count,
                    "unknown_fields": len(report.unknown_fields),
                }
            )
    except SurveyError as error:
        _emit({"error": "survey_rejected", "problems": error.problems}, stream=sys.stderr)
        return 2
    except (SourceIntegrityError, FileNotFoundError, ValueError) as error:
        _emit({"error": type(error).__name__, "message": str(error)}, stream=sys.stderr)
        return 2
    except PublishRefused as error:
        _emit({"error": "publish_refused", "reasons": error.reasons}, stream=sys.stderr)
        return 1
    return 2


def _extract(args: argparse.Namespace, paths: SessionPaths) -> int:
    ref = SourceRef(
        catalog=args.catalog,
        critic_root=args.critic_root.resolve(),
        source_root=args.source_root,
        host=args.host,
    )
    source_files = verify_sources(ref)
    evidence = family(args.family, profile=not args.no_profile).collect(ref, source_files)
    state = SessionState(
        catalog=ref.catalog,
        family=args.family,
        critic_root=str(ref.critic_root),
        source_root=ref.source_root,
        host=ref.host,
        source_files=source_files,
    )
    decisions = propose_decisions(evidence)
    paths.root.mkdir(parents=True, exist_ok=True)
    write_text_atomic(paths.state, dump_yaml(state.model_dump(mode="json")))
    write_text_atomic(paths.evidence, evidence.model_dump_json(indent=2) + "\n")
    write_text_atomic(paths.decisions, dump_decisions(decisions))
    report = _rebuild(paths, evidence, decisions)
    write_text_atomic(paths.survey, render_survey(state.catalog, 1, decisions))
    return _emit(_summary(paths, report))


def _apply(
    paths: SessionPaths, state: SessionState, evidence: SourceEvidence, decisions: list[Decision]
) -> int:
    round_number = state.round + 1
    decisions = parse_survey(paths.survey.read_text(encoding="utf-8"), decisions, round_number)
    state = state.model_copy(update={"round": round_number})
    write_text_atomic(paths.decisions, dump_decisions(decisions))
    write_text_atomic(paths.state, dump_yaml(state.model_dump(mode="json")))
    report = _rebuild(paths, evidence, decisions)
    write_text_atomic(paths.survey, render_survey(state.catalog, round_number + 1, decisions))
    _emit(_summary(paths, report))
    return 0 if report.valid and not report.draft_findings else 1


def _rebuild(paths: SessionPaths, evidence: SourceEvidence, decisions: list[Decision]) -> CollectorReport:
    draft: Draft = build_draft(evidence, decisions)
    write_catalog_directory(paths.draft, draft)
    report = validate_catalog_directory(paths.draft / "yaml", decisions, draft.findings)
    write_text_atomic(paths.report, report.model_dump_json(indent=2) + "\n")
    return report


def _load(paths: SessionPaths) -> tuple[SessionState, SourceEvidence, list[Decision]]:
    if not paths.state.is_file():
        raise FileNotFoundError(f"no session at {paths.root}; run extract first")
    state = SessionState.model_validate(yaml.safe_load(paths.state.read_text(encoding="utf-8")))
    evidence = SourceEvidence.model_validate_json(paths.evidence.read_text(encoding="utf-8"))
    decisions = load_decisions(paths.decisions.read_text(encoding="utf-8"))
    return state, evidence, decisions


def _summary(paths: SessionPaths, report: CollectorReport) -> dict[str, object]:
    return {
        "session": str(paths.root),
        "draft": str(paths.draft),
        "survey": str(paths.survey),
        "valid": report.valid,
        "validation_findings": len(report.findings),
        "draft_findings": [f.model_dump() for f in report.draft_findings],
        "decisions": report.decisions,
        "unresolved": len(report.unresolved),
        "nodes": report.node_count,
        "edges": report.edge_count,
        "unknown_fields": len(report.unknown_fields),
    }


def _unresolved(decisions: list[Decision]) -> list[str]:
    return sorted(d.decision_id for d in decisions if d.status in {"open", "blocking"})


def _emit(payload: object, stream=None) -> int:
    print(json.dumps(payload, indent=2), file=stream or sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
