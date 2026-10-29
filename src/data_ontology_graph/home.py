"""The service home: one private, per-user directory known in advance to every component.

The home holds the run configuration (`service.plist`), the published artifact
(`current-graph/`), the socket while the service runs (`graph.sock`), and the service logs
(`logs/`). `DOG_HOME` relocates the whole home and `DOG_SOCKET` overrides only the socket. The
bundled skill scripts repeat these rules in the standard library; a test keeps them equal.
"""

from __future__ import annotations

import os
from pathlib import Path


HOME_ENV = "DOG_HOME"
SOCKET_ENV = "DOG_SOCKET"
DEFAULT_HOME = "~/.data-ontology-graph"


def service_home() -> Path:
    return Path(os.environ.get(HOME_ENV) or DEFAULT_HOME).expanduser()


def ensure_service_home() -> Path:
    """Create the home if needed and keep it owner-only, whoever created it first."""
    home = service_home()
    home.mkdir(parents=True, exist_ok=True)
    home.chmod(0o700)
    return home


def default_socket() -> Path:
    override = os.environ.get(SOCKET_ENV)
    return Path(override).expanduser() if override else service_home() / "graph.sock"


def default_artifact() -> Path:
    return service_home() / "current-graph"


def default_plist() -> Path:
    return service_home() / "service.plist"


def default_logs() -> Path:
    return service_home() / "logs"
