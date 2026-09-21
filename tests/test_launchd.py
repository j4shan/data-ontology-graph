import os
import plistlib
import sys
from pathlib import Path

import pytest

from data_ontology_graph.builder import build_snapshot_from_yaml
from data_ontology_graph.rpc.launchd import (
    launchctl_command,
    launchd_payload,
    run_launchd_action,
    write_launchd_plist,
)
from data_ontology_graph.store.snapshot_store import CurrentArtifactStore


ROOT = Path(__file__).resolve().parents[1]
FINANCIAL = ROOT / "resources" / "data" / "dev_overlays" / "financial" / "catalog.yaml"


def test_launchd_payload_pins_snapshot_and_socket(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    socket = tmp_path / "graph.sock"
    logs = tmp_path / "logs"
    payload = launchd_payload(snapshot, socket, logs)

    arguments = payload["ProgramArguments"]
    assert arguments[:3] == [sys.executable, "-m", "data_ontology_graph.rpc.server"]
    assert arguments[arguments.index("--snapshot-dir") + 1] == str(snapshot.resolve())
    assert arguments[arguments.index("--socket") + 1] == str(socket.resolve())
    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] == {"SuccessfulExit": False}


def test_launchd_plist_is_valid_and_creates_log_directory(tmp_path: Path) -> None:
    output = tmp_path / "LaunchAgents" / "graph.plist"
    logs = tmp_path / "logs"
    write_launchd_plist(
        output=output,
        snapshot_directory=tmp_path / "snapshot",
        socket_path=Path("/tmp/data-ontology-graph-test.sock"),
        log_directory=logs,
    )

    payload = plistlib.loads(output.read_bytes())
    assert payload["Label"] == "com.data-ontology-graph.service"
    assert logs.is_dir()


def test_launchctl_commands_use_one_user_service_and_stable_plist(tmp_path: Path) -> None:
    plist = tmp_path / "graph.plist"
    assert launchctl_command("install", plist, uid=501) == [
        "launchctl",
        "bootstrap",
        "gui/501",
        str(plist.resolve()),
    ]
    assert launchctl_command("reload", plist, uid=501) == [
        "launchctl",
        "kickstart",
        "-k",
        "gui/501/com.data-ontology-graph.service",
    ]
    assert launchctl_command("status", plist, uid=501) == [
        "launchctl",
        "print",
        "gui/501/com.data-ontology-graph.service",
    ]


def test_install_validates_artifact_writes_plist_and_invokes_launchctl(tmp_path: Path) -> None:
    artifact = tmp_path / "current"
    snapshot, _, _ = build_snapshot_from_yaml(FINANCIAL)
    CurrentArtifactStore(artifact).publish(snapshot)
    plist = tmp_path / "LaunchAgents" / "graph.plist"
    calls: list[tuple[list[str], bool]] = []

    def runner(command: list[str], check: bool) -> None:
        calls.append((command, check))

    command = run_launchd_action(
        "install",
        snapshot_directory=artifact,
        socket_path=tmp_path / "graph.sock",
        output=plist,
        log_directory=tmp_path / "logs",
        runner=runner,
    )

    assert plist.exists()
    assert command == calls[0][0]
    assert calls[0][1] is True
    assert command[:3] == ["launchctl", "bootstrap", f"gui/{os.getuid()}"]


def test_install_rejects_missing_artifact_before_launchctl(tmp_path: Path) -> None:
    called = False

    def runner(command: list[str], check: bool) -> None:
        nonlocal called
        called = True

    with pytest.raises(FileNotFoundError):
        run_launchd_action(
            "install",
            snapshot_directory=tmp_path / "missing",
            socket_path=tmp_path / "graph.sock",
            output=tmp_path / "graph.plist",
            log_directory=tmp_path / "logs",
            runner=runner,
        )
    assert called is False
