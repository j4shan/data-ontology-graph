from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

from data_ontology_graph.store.snapshot_store import CurrentArtifactStore


DEFAULT_LABEL = "com.data-ontology-graph.service"
LaunchctlRunner = Callable[..., subprocess.CompletedProcess]


def launchd_payload(
    snapshot_directory: Path,
    socket_path: Path,
    log_directory: Path,
    label: str = DEFAULT_LABEL,
) -> dict:
    snapshot_directory = snapshot_directory.resolve()
    socket_path = socket_path.resolve()
    log_directory = log_directory.resolve()
    return {
        "Label": label,
        "ProgramArguments": [
            sys.executable,
            "-m",
            "data_ontology_graph.rpc.server",
            "--snapshot-dir",
            str(snapshot_directory),
            "--socket",
            str(socket_path),
        ],
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ProcessType": "Background",
        "StandardOutPath": str(log_directory / "graph-service.stdout.log"),
        "StandardErrorPath": str(log_directory / "graph-service.stderr.log"),
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
    }


def write_launchd_plist(
    output: Path,
    snapshot_directory: Path,
    socket_path: Path,
    log_directory: Path,
    label: str = DEFAULT_LABEL,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    log_directory.mkdir(parents=True, exist_ok=True)
    payload = launchd_payload(snapshot_directory, socket_path, log_directory, label)
    output.write_bytes(plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True))


def launchctl_command(
    action: str,
    plist_path: Path,
    label: str = DEFAULT_LABEL,
    uid: int | None = None,
) -> list[str]:
    user_id = os.getuid() if uid is None else uid
    domain = f"gui/{user_id}"
    service = f"{domain}/{label}"
    commands = {
        "install": ["launchctl", "bootstrap", domain, str(plist_path.resolve())],
        "start": ["launchctl", "kickstart", service],
        "reload": ["launchctl", "kickstart", "-k", service],
        "status": ["launchctl", "print", service],
        "uninstall": ["launchctl", "bootout", domain, str(plist_path.resolve())],
    }
    try:
        return commands[action]
    except KeyError as error:
        raise ValueError(f"unsupported launchd action: {action}") from error


def run_launchd_action(
    action: str,
    snapshot_directory: Path,
    socket_path: Path,
    output: Path,
    log_directory: Path,
    label: str = DEFAULT_LABEL,
    runner: LaunchctlRunner = subprocess.run,
) -> Sequence[str] | None:
    if action in {"generate", "install", "start", "reload"}:
        CurrentArtifactStore(snapshot_directory).load()

    if action in {"generate", "install"}:
        write_launchd_plist(
            output=output,
            snapshot_directory=snapshot_directory,
            socket_path=socket_path,
            log_directory=log_directory,
            label=label,
        )
    if action == "generate":
        return None

    command = launchctl_command(action, output, label)
    runner(command, check=True)
    if action == "uninstall" and output.exists():
        output.unlink()
    return command


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the graph-service launchd daemon")
    parser.add_argument(
        "action",
        nargs="?",
        default="generate",
        choices=("generate", "install", "start", "reload", "status", "uninstall"),
    )
    parser.add_argument("--snapshot-dir", type=Path)
    parser.add_argument("--socket", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--label", default=DEFAULT_LABEL)
    args = parser.parse_args()
    required_by_action = {
        "generate": ("snapshot_dir", "socket", "output", "log_dir"),
        "install": ("snapshot_dir", "socket", "output", "log_dir"),
        "start": ("snapshot_dir",),
        "reload": ("snapshot_dir",),
        "status": (),
        "uninstall": ("output",),
    }
    missing = [name for name in required_by_action[args.action] if getattr(args, name) is None]
    if missing:
        parser.error(
            f"{args.action} requires "
            + ", ".join(f"--{name.replace('_', '-')}" for name in missing)
        )
    run_launchd_action(
        action=args.action,
        snapshot_directory=args.snapshot_dir or Path("."),
        socket_path=args.socket or Path("."),
        output=args.output or Path("."),
        log_directory=args.log_dir or Path("."),
        label=args.label,
    )


if __name__ == "__main__":
    main()
