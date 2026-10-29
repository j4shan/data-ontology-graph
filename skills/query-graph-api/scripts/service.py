#!/usr/bin/env python3
"""Start, stop, and check the local graph service on demand.

Standard library only. The service runs as a user-owned `launchd` job described by
`service.plist` in the service home ($DOG_HOME or ~/.data-ontology-graph), which the graph
service's setup writes. Nothing starts the service at login: `start` loads the job and waits
until the service answers; `stop` unloads it.

    service.py start [--wait SECONDS]
    service.py stop
    service.py status

Each command prints one JSON line with `state` and, when something is wrong, a `message` to relay
to the user. States: running, started, stopped, not_running, not_set_up, not_ready, blocked.
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from graph_call import call, service_home  # noqa: E402

DEFAULT_WAIT_SECONDS = 30.0
OK_STATES = {"running", "started", "stopped", "not_running"}
run = subprocess.run  # replaced in tests


def answers(socket_path: Path) -> bool:
    try:
        return "result" in call(socket_path, "graph.snapshot_info", {})
    except (OSError, ValueError):
        return False


def launchctl(*arguments: str, check: bool = True) -> subprocess.CompletedProcess:
    return run(["launchctl", *arguments], check=check, capture_output=True, text=True)


def job() -> dict | None:
    plist = service_home() / "service.plist"
    if not plist.exists():
        return None
    payload = plistlib.loads(plist.read_bytes())
    arguments = payload["ProgramArguments"]
    return {
        "plist": plist,
        "label": payload["Label"],
        "socket": Path(arguments[arguments.index("--socket") + 1]),
        "log": payload.get("StandardErrorPath"),
    }


def status() -> dict:
    found = job()
    if found is None:
        return _not_set_up()
    outcome = {"socket": str(found["socket"])}
    if answers(found["socket"]):
        return {"state": "running", **outcome}
    if _loaded(found):
        return {"state": "not_ready", **outcome, "message": _log_hint(found)}
    return {"state": "stopped", **outcome}


def start(wait_seconds: float) -> dict:
    found = job()
    if found is None:
        return _not_set_up()
    outcome = {"socket": str(found["socket"])}
    if answers(found["socket"]):
        return {"state": "running", **outcome}
    domain = f"gui/{os.getuid()}"
    if _loaded(found):
        launchctl("kickstart", f"{domain}/{found['label']}")
    else:
        launchctl("bootstrap", domain, str(found["plist"]))
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if answers(found["socket"]):
            return {"state": "started", **outcome}
        time.sleep(0.2)
    return {"state": "not_ready", **outcome, "message": _log_hint(found)}


def stop() -> dict:
    found = job()
    if found is None:
        return _not_set_up()
    if not _loaded(found):
        return {"state": "not_running"}
    launchctl("bootout", f"gui/{os.getuid()}/{found['label']}")
    return {"state": "stopped"}


def _loaded(found: dict) -> bool:
    return launchctl("print", f"gui/{os.getuid()}/{found['label']}", check=False).returncode == 0


def _not_set_up() -> dict:
    return {
        "state": "not_set_up",
        "message": (
            f"The graph service is not set up: {service_home() / 'service.plist'} does not exist. "
            "Ask the user to publish a graph and set up the graph service."
        ),
    }


def _log_hint(found: dict) -> str:
    return (
        "The graph service did not answer. It may still be loading a large graph, or it is "
        f"failing to start; the log is {found['log']}."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start, stop, and check the local graph service")
    commands = parser.add_subparsers(dest="command", required=True)
    start_parser = commands.add_parser("start")
    start_parser.add_argument("--wait", type=float, default=DEFAULT_WAIT_SECONDS)
    commands.add_parser("stop")
    commands.add_parser("status")
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            outcome = start(args.wait)
        elif args.command == "stop":
            outcome = stop()
        else:
            outcome = status()
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", None) or str(error)
        outcome = {
            "state": "blocked",
            "message": (
                f"Could not control the graph service with launchctl ({detail.strip()}). "
                "Ask the user to start the graph service."
            ),
        }
    print(json.dumps(outcome))
    return 0 if outcome["state"] in OK_STATES else 1


if __name__ == "__main__":
    sys.exit(main())
