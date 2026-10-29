import importlib.util
import json
import plistlib
import subprocess
from pathlib import Path

import pytest

from data_ontology_graph import home as core_home


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "query-graph-api" / "scripts"
LABEL = "com.data-ontology-graph.service"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"bundled_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "environment",
    [{}, {"DOG_HOME": "/tmp/dog-home"}, {"DOG_SOCKET": "/tmp/dog.sock"},
     {"DOG_HOME": "~/elsewhere", "DOG_SOCKET": "~/x.sock"}],
)
def test_bundled_scripts_resolve_the_same_home_and_socket(environment: dict, monkeypatch) -> None:
    for name in ("DOG_HOME", "DOG_SOCKET"):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    graph_call = _load("graph_call")
    assert graph_call.service_home() == core_home.service_home()
    assert graph_call.default_socket() == core_home.default_socket()


def test_default_home_is_private_and_holds_every_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DOG_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("DOG_SOCKET", raising=False)
    home = core_home.ensure_service_home()
    assert (home.stat().st_mode & 0o777) == 0o700
    assert core_home.default_socket() == home / "graph.sock"
    assert core_home.default_artifact() == home / "current-graph"
    assert core_home.default_plist() == home / "service.plist"
    assert core_home.default_logs() == home / "logs"


def test_default_socket_path_fits_the_socket_limit() -> None:
    assert len(str(Path(core_home.DEFAULT_HOME).expanduser() / "graph.sock").encode()) <= 100


class FakeRun:
    def __init__(self, loaded: bool = False, fail: str | None = None) -> None:
        self.loaded = loaded
        self.fail = fail
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], check: bool, **_: object) -> subprocess.CompletedProcess:
        self.calls.append(command)
        operation = command[1]
        if operation == self.fail:
            raise subprocess.CalledProcessError(5, command, stderr="Operation not permitted")
        if operation == "bootstrap":
            self.loaded = True
        elif operation == "bootout":
            self.loaded = False
        code = 0 if operation != "print" or self.loaded else 113
        return subprocess.CompletedProcess(command, code)


@pytest.fixture
def service(tmp_path: Path, monkeypatch, lending_socket: Path):
    """The bundled service script against a home whose plist names the test socket."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("DOG_HOME", str(home))
    module = _load("service")
    (home / "service.plist").write_bytes(
        plistlib.dumps(
            {
                "Label": LABEL,
                "ProgramArguments": ["python", "-m", "server", "--snapshot-dir", "x",
                                     "--socket", str(lending_socket)],
                "StandardErrorPath": str(home / "logs" / "graph-service.stderr.log"),
            }
        )
    )
    return module


def _run(module, capsys, *args: str) -> tuple[int, dict]:
    code = module.main(list(args))
    return code, json.loads(capsys.readouterr().out)


def test_status_and_start_report_a_running_service_without_launchctl_changes(
    service, capsys
) -> None:
    fake = FakeRun(loaded=True)
    service.run = fake
    assert _run(service, capsys, "status") == (0, {"state": "running", "socket": _socket(service)})
    assert _run(service, capsys, "start")[1]["state"] == "running"
    assert all(command[1] == "print" for command in fake.calls)


def test_start_loads_the_job_then_waits_for_the_service(service, capsys, monkeypatch) -> None:
    fake = FakeRun()
    service.run = fake
    answers = iter([False, False, True])
    monkeypatch.setattr(service, "answers", lambda _: next(answers))
    code, outcome = _run(service, capsys, "start")
    assert (code, outcome["state"]) == (0, "started")
    assert [command[1] for command in fake.calls] == ["print", "bootstrap"]


def test_start_reports_not_ready_with_the_log(service, capsys, monkeypatch) -> None:
    service.run = FakeRun()
    monkeypatch.setattr(service, "answers", lambda _: False)
    code, outcome = _run(service, capsys, "start", "--wait", "0.3")
    assert (code, outcome["state"]) == (1, "not_ready")
    assert "graph-service.stderr.log" in outcome["message"]


def test_stop_unloads_only_a_loaded_job(service, capsys) -> None:
    loaded = FakeRun(loaded=True)
    service.run = loaded
    assert _run(service, capsys, "stop") == (0, {"state": "stopped"})
    assert loaded.calls[-1][1] == "bootout"
    service.run = FakeRun()
    assert _run(service, capsys, "stop") == (0, {"state": "not_running"})


def test_blocked_launchctl_is_reported_with_a_message(service, capsys, monkeypatch) -> None:
    service.run = FakeRun(fail="bootstrap")
    monkeypatch.setattr(service, "answers", lambda _: False)
    code, outcome = _run(service, capsys, "start")
    assert (code, outcome["state"]) == (1, "blocked")
    assert "Operation not permitted" in outcome["message"]


def test_missing_setup_is_reported_with_a_message(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("DOG_HOME", str(tmp_path / "empty"))
    module = _load("service")
    module.run = FakeRun()
    code, outcome = _run(module, capsys, "start")
    assert (code, outcome["state"]) == (1, "not_set_up")
    assert "service.plist" in outcome["message"]
    assert module.run.calls == []


def _socket(module) -> str:
    return str(module.job()["socket"])
