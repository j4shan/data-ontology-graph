import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

from data_ontology_graph.builder import build_snapshot_from_yaml
from data_ontology_graph.rpc.launchd import (
    launchctl_command,
    launchd_payload,
    main,
    run_launchd_action,
    write_launchd_plist,
)
from data_ontology_graph.store.snapshot_store import CurrentArtifactStore


ROOT = Path(__file__).resolve().parents[1]
LENDING = ROOT / "tests" / "fixtures" / "lending" / "catalog.yaml"
LABEL = "com.data-ontology-graph.service"


class FakeLaunchctl:
    """Records launchctl calls; `print` succeeds only while the job is loaded."""

    def __init__(self, loaded: bool = False) -> None:
        self.loaded = loaded
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], check: bool, **_: object) -> subprocess.CompletedProcess:
        self.calls.append(command)
        operation = command[1]
        if operation == "bootstrap":
            self.loaded = True
        elif operation == "bootout":
            self.loaded = False
        code = 0 if operation != "print" or self.loaded else 113
        return subprocess.CompletedProcess(command, code)


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    monkeypatch.setenv("DOG_HOME", str(home))
    monkeypatch.delenv("DOG_SOCKET", raising=False)
    return home


def _publish(artifact: Path) -> None:
    snapshot, _, _ = build_snapshot_from_yaml(LENDING)
    CurrentArtifactStore(artifact).publish(snapshot)


def test_launchd_payload_pins_snapshot_and_socket(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    socket = tmp_path / "graph.sock"
    payload = launchd_payload(snapshot, socket, tmp_path / "logs")

    arguments = payload["ProgramArguments"]
    assert arguments[:3] == [sys.executable, "-m", "data_ontology_graph.rpc.server"]
    assert arguments[arguments.index("--snapshot-dir") + 1] == str(snapshot.resolve())
    assert arguments[arguments.index("--socket") + 1] == str(socket.resolve())
    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] == {"SuccessfulExit": False}


def test_launchd_plist_is_valid_and_creates_log_directory(tmp_path: Path) -> None:
    output = tmp_path / "graph.plist"
    logs = tmp_path / "logs"
    write_launchd_plist(
        output=output,
        snapshot_directory=tmp_path / "snapshot",
        socket_path=Path("/tmp/data-ontology-graph-test.sock"),
        log_directory=logs,
    )
    assert plistlib.loads(output.read_bytes())["Label"] == LABEL
    assert logs.is_dir()


def test_launchctl_operations_target_one_user_job(tmp_path: Path) -> None:
    plist = tmp_path / "service.plist"
    service = f"gui/501/{LABEL}"
    assert launchctl_command("load", plist, uid=501) == [
        "launchctl", "bootstrap", "gui/501", str(plist.resolve())
    ]
    assert launchctl_command("unload", plist, uid=501) == ["launchctl", "bootout", service]
    assert launchctl_command("restart", plist, uid=501) == [
        "launchctl", "kickstart", "-k", service
    ]
    assert launchctl_command("print", plist, uid=501) == ["launchctl", "print", service]


def test_setup_writes_the_plist_into_a_private_home_without_starting(home: Path) -> None:
    _publish(home / "current-graph")
    fake = FakeLaunchctl()
    outcome = run_launchd_action("setup", runner=fake)
    assert outcome == {"state": "set_up", "plist": str(home / "service.plist")}
    assert fake.calls == []
    payload = plistlib.loads((home / "service.plist").read_bytes())
    arguments = payload["ProgramArguments"]
    assert arguments[arguments.index("--socket") + 1] == str((home / "graph.sock").resolve())
    assert arguments[arguments.index("--snapshot-dir") + 1] == str((home / "current-graph").resolve())
    assert payload["StandardErrorPath"].startswith(str((home / "logs").resolve()))
    assert (home.stat().st_mode & 0o777) == 0o700
    assert "LaunchAgents" not in str(home / "service.plist")


def test_setup_rejects_a_missing_artifact(home: Path) -> None:
    with pytest.raises(FileNotFoundError):
        run_launchd_action("setup", runner=FakeLaunchctl())
    assert not (home / "service.plist").exists()


def test_actions_before_setup_report_not_set_up(home: Path) -> None:
    for action in ("start", "stop", "status", "reload"):
        assert run_launchd_action(action, runner=FakeLaunchctl())["state"] == "not_set_up"


def test_start_loads_the_job_and_waits_until_the_service_answers(home: Path) -> None:
    _publish(home / "current-graph")
    run_launchd_action("setup", runner=FakeLaunchctl())
    fake = FakeLaunchctl()
    answers = iter([False, False, True])
    outcome = run_launchd_action("start", runner=fake, probe=lambda _: next(answers))
    assert outcome["state"] == "started"
    assert [command[1] for command in fake.calls] == ["print", "bootstrap"]


def test_start_is_a_no_op_when_the_service_already_answers(home: Path) -> None:
    _publish(home / "current-graph")
    run_launchd_action("setup", runner=FakeLaunchctl())
    fake = FakeLaunchctl(loaded=True)
    assert run_launchd_action("start", runner=fake, probe=lambda _: True)["state"] == "running"
    assert [command[1] for command in fake.calls] == ["print"]


def test_start_reports_not_ready_when_the_service_never_answers(home: Path) -> None:
    _publish(home / "current-graph")
    run_launchd_action("setup", runner=FakeLaunchctl())
    outcome = run_launchd_action(
        "start", runner=FakeLaunchctl(), probe=lambda _: False, wait_seconds=0.3
    )
    assert outcome["state"] == "not_ready"
    assert outcome["log"].endswith("graph-service.stderr.log")


def test_stop_unloads_only_a_loaded_job(home: Path) -> None:
    _publish(home / "current-graph")
    run_launchd_action("setup", runner=FakeLaunchctl())
    loaded = FakeLaunchctl(loaded=True)
    assert run_launchd_action("stop", runner=loaded)["state"] == "stopped"
    assert [command[1] for command in loaded.calls] == ["print", "bootout"]
    assert run_launchd_action("stop", runner=FakeLaunchctl())["state"] == "not_running"


def test_status_distinguishes_running_loading_and_stopped(home: Path) -> None:
    _publish(home / "current-graph")
    run_launchd_action("setup", runner=FakeLaunchctl())
    def state(loaded: bool, answering: bool) -> str:
        outcome = run_launchd_action(
            "status", runner=FakeLaunchctl(loaded), probe=lambda _: answering
        )
        return outcome["state"]

    assert state(loaded=True, answering=True) == "running"
    assert state(loaded=True, answering=False) == "starting_or_failing"
    assert state(loaded=False, answering=False) == "stopped"


def test_reload_restarts_a_loaded_job(home: Path) -> None:
    _publish(home / "current-graph")
    run_launchd_action("setup", runner=FakeLaunchctl())
    fake = FakeLaunchctl(loaded=True)
    assert run_launchd_action("reload", runner=fake, probe=lambda _: True)["state"] == "started"
    assert fake.calls[-1][1:3] == ["kickstart", "-k"]


def test_cli_setup_prints_the_outcome(home: Path, capsys) -> None:
    _publish(home / "current-graph")
    assert main(["setup"]) == 0
    assert capsys.readouterr().out.startswith("state=set_up plist=")
