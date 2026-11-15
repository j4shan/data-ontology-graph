"""A recording stand-in for ``subprocess.run`` calls to ``launchctl``."""
import subprocess


class FakeLaunchctl:
    """Records launchctl calls; `print` succeeds only while the job is loaded.

    ``fail`` names an operation that raises ``CalledProcessError`` as a blocked launchctl would.
    """

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
