from __future__ import annotations

import argparse
import sys
from pathlib import Path

from data_ontology_graph.akg.resolve import resolve_akg, socket_call
from data_ontology_graph.akg.validate import load_akg_yaml, validate_akg_yaml


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Work with AKG documents")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser(
        "validate",
        help="Check an AKG document against the contract and, with --socket, the served snapshot",
    )
    validate.add_argument("file", type=Path)
    validate.add_argument(
        "--socket", type=Path, help="Graph service socket; resolves every node and edge"
    )
    args = parser.parse_args(argv)

    report = validate_akg_yaml(args.file)
    findings = list(report.findings)
    if report.valid and args.socket is not None:
        findings.extend(resolve_akg(load_akg_yaml(args.file), socket_call(args.socket)))

    for finding in findings:
        position = f":{finding.line}:{finding.column}" if finding.line else ""
        print(f"{finding.location}{position} [{finding.rule}] {finding.message}")
    if findings:
        print(f"{args.file}: {len(findings)} finding(s)", file=sys.stderr)
        return 1
    scope = "contract and snapshot" if args.socket is not None else "contract"
    print(f"{args.file}: valid against the {scope}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
