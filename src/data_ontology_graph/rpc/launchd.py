"""Run the graph service on demand as a user-owned `launchd` job.

`setup` writes the job's property list into the service home. Because the property list lives
outside `~/Library/LaunchAgents`, `launchd` never starts the service at login: `start` loads the
job, which starts the service at once, and `stop` unloads it. While the job is loaded, `launchd`
restarts the service after an unexpected failure. Logging out also unloads the job.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Sequence

from data_ontology_graph.home import (
    default_artifact,
    default_logs,
    default_plist,
    default_socket,
    ensure_service_home,
)
from data_ontology_graph.rpc import client
from data_ontology_graph.store.snapshot_store import CurrentArtifactStore


DEFAULT_LABEL = "com.data-ontology-graph.service"
DEFAULT_WAIT_SECONDS = 30.0
ACTIONS = ("setup", "start", "stop", "reload", "status")
LaunchctlRunner = Callable[..., subprocess.CompletedProcess]
Probe = Callable[[Path], bool]


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
        "load": ["launchctl", "bootstrap", domain, str(plist_path.resolve())],
        "kick": ["launchctl", "kickstart", service],
        "restart": ["launchctl", "kickstart", "-k", service],
        "unload": ["launchctl", "bootout", service],
        "print": ["launchctl", "print", service],
    }
    try:
        return commands[action]
    except KeyError as error:
        raise ValueError(f"unsupported launchctl operation: {action}") from error


def socket_answers(socket_path: Path) -> bool:
    """Return whether a graph service answers `graph.snapshot_info` on the socket."""
    try:
        return "result" in client.call(socket_path, "graph.snapshot_info", {})
    except (OSError, ValueError):
        return False


def run_launchd_action(
    action: str,
    *,
    plist_path: Path | None = None,
    snapshot_directory: Path | None = None,
    socket_path: Path | None = None,
    log_directory: Path | None = None,
    label: str = DEFAULT_LABEL,
    runner: LaunchctlRunner = subprocess.run,
    probe: Probe = socket_answers,
    wait_seconds: float = DEFAULT_WAIT_SECONDS,
) -> dict:
    """Perform one lifecycle action and return its outcome as `{state, ...}`."""
    plist_path = plist_path or default_plist()
    if action == "setup":
        ensure_service_home()
        snapshot_directory = snapshot_directory or default_artifact()
        CurrentArtifactStore(snapshot_directory).load()
        write_launchd_plist(
            output=plist_path,
            snapshot_directory=snapshot_directory,
            socket_path=socket_path or default_socket(),
            log_directory=log_directory or default_logs(),
            label=label,
        )
        return {"state": "set_up", "plist": str(plist_path)}
    if action not in ACTIONS:
        raise ValueError(f"unsupported launchd action: {action}")

    if not plist_path.exists():
        return {"state": "not_set_up", "plist": str(plist_path)}
    payload = plistlib.loads(plist_path.read_bytes())
    label = payload["Label"]
    arguments = payload["ProgramArguments"]
    socket_path = Path(arguments[arguments.index("--socket") + 1])
    loaded = _loaded(plist_path, label, runner)
    outcome = {"socket": str(socket_path), "log": payload.get("StandardErrorPath")}

    if action == "status":
        if probe(socket_path):
            return {"state": "running", **outcome}
        return {"state": "starting_or_failing" if loaded else "stopped", **outcome}
    if action == "stop":
        if loaded:
            runner(launchctl_command("unload", plist_path, label), check=True)
            return {"state": "stopped", **outcome}
        return {"state": "not_running", **outcome}

    if action == "start" and probe(socket_path):
        return {"state": "running", **outcome}
    CurrentArtifactStore(Path(arguments[arguments.index("--snapshot-dir") + 1])).load()
    if not loaded:
        operation = "load"
    else:
        operation = "restart" if action == "reload" else "kick"
    runner(launchctl_command(operation, plist_path, label), check=True)
    if action == "reload":
        # Let the old process release the socket before probing for the new one.
        time.sleep(0.2)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if probe(socket_path):
            return {"state": "started", **outcome}
        time.sleep(0.2)
    return {"state": "not_ready", **outcome}


def _loaded(plist_path: Path, label: str, runner: LaunchctlRunner) -> bool:
    result = runner(
        launchctl_command("print", plist_path, label), check=False, capture_output=True
    )
    return result.returncode == 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the graph service on demand as a user-owned launchd job"
    )
    parser.add_argument("action", choices=ACTIONS)
    parser.add_argument("--snapshot-dir", type=Path, help="setup: artifact to serve")
    parser.add_argument("--socket", type=Path, help="setup: socket to serve on")
    parser.add_argument("--log-dir", type=Path, help="setup: log directory")
    parser.add_argument("--label", default=DEFAULT_LABEL, help="setup: launchd job label")
    parser.add_argument("--wait", type=float, default=DEFAULT_WAIT_SECONDS,
                        help="start, reload: seconds to wait for the service to answer")
    args = parser.parse_args(argv)
    outcome = run_launchd_action(
        args.action,
        snapshot_directory=args.snapshot_dir,
        socket_path=args.socket,
        log_directory=args.log_dir,
        label=args.label,
        wait_seconds=args.wait,
    )
    print(" ".join(f"{key}={value}" for key, value in outcome.items()))
    return 0 if outcome["state"] in {"set_up", "running", "started", "stopped", "not_running"} else 1


if __name__ == "__main__":
    sys.exit(main())
