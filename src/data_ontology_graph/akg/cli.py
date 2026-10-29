from __future__ import annotations

import argparse
import sys
from pathlib import Path

from data_ontology_graph.akg.check import (
    AkgFinding,
    check_document,
    has_errors,
    load_payload,
    write_payload,
)
from data_ontology_graph.akg.export import export_markdown
from data_ontology_graph.home import default_socket
from data_ontology_graph.akg.resolve import (
    GraphSource,
    ServiceSource,
    YamlSource,
    resolve_document,
    socket_call,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check, finalize, and export AKG documents")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser(
        "check", help="Report findings; with --socket or --yaml, also resolve against the graph"
    )
    check.add_argument("file", type=Path)
    _add_graph_source(check, required=False)

    finalize = commands.add_parser(
        "finalize", help="Check with the finalize rules, resolve against the graph, mark final"
    )
    finalize.add_argument("file", type=Path)
    _add_graph_source(finalize, required=False)

    export = commands.add_parser("export", help="Write a read-only copy for human review")
    export.add_argument("file", type=Path)
    export.add_argument("--format", choices=["markdown"], default="markdown")
    export.add_argument("--output", type=Path, help="Write here instead of standard output")

    args = parser.parse_args(argv)
    if args.command == "export":
        return _export(args.file, args.output)

    final = args.command == "finalize"
    payload, findings = load_payload(args.file)
    if not findings:
        findings = check_document(payload, final=final)
        source = _graph_source(args, final)
        if source is not None and not has_errors(findings):
            findings.extend(resolve_document(payload, source))

    for finding in findings:
        _print(finding)
    errors = sum(finding.severity == "error" for finding in findings)
    warnings = sum(finding.severity == "warning" for finding in findings)
    print(f"{args.file}: {errors} error(s), {warnings} warning(s)")
    if errors:
        return 1
    if final:
        payload["status"] = "final"
        write_payload(args.file, payload)
        print(f"{args.file}: final")
    return 0


def _add_graph_source(parser: argparse.ArgumentParser, *, required: bool) -> None:
    group = parser.add_mutually_exclusive_group(required=required)
    group.add_argument("--socket", type=Path,
                       help="Graph service socket (finalize default: the service home's)")
    group.add_argument("--yaml", type=Path, help="YAML intermediary file or directory")


def _graph_source(args: argparse.Namespace, final: bool) -> GraphSource | None:
    if args.socket is not None or (final and args.yaml is None):
        # finalize always resolves; without a source it uses the service home's socket.
        return ServiceSource(socket_call(args.socket or default_socket()))
    if args.yaml is not None:
        return YamlSource.load(args.yaml)
    return None


def _export(path: Path, output: Path | None) -> int:
    payload, findings = load_payload(path)
    if not findings:
        findings = [finding for finding in check_document(payload) if finding.severity == "error"]
    if findings:
        for finding in findings:
            _print(finding)
        return 1
    text = export_markdown(payload)
    if output is None:
        sys.stdout.write(text)
    else:
        output.write_text(text, encoding="utf-8")
    return 0


def _print(finding: AkgFinding) -> None:
    position = f":{finding.line}:{finding.column}" if finding.line else ""
    print(f"{finding.severity:<7} {finding.location}{position} [{finding.rule}] {finding.message}")


if __name__ == "__main__":
    raise SystemExit(main())
