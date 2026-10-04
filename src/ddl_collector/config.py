from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath

import yaml
from pydantic import BaseModel, Field, field_validator


DEFAULT_SOURCE_ROOT = "/opt/data-ontology/sources"
DEFAULT_HOST = "localhost"
_DATA_DIR = Path("resources/data")
_HASH_LINE = re.compile(r"^([0-9a-f]{64})\s+(\S.*)$")


class SourceIntegrityError(ValueError):
    """A curated source is missing, unlisted, or differs from its recorded hash."""


class SourceRef(BaseModel):
    """Where one curated catalog lives and how a published accessor will locate it.

    ``critic_root`` is the local Critic checkout read during preparation. ``source_root`` is
    the canonical absolute root written into accessors; each host links it to its own copy of
    Critic's ``resources/data/dev_databases/``.
    """

    catalog: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_\-]+$")
    critic_root: Path
    source_root: str = DEFAULT_SOURCE_ROOT
    host: str = Field(default=DEFAULT_HOST, min_length=1)

    @field_validator("source_root")
    @classmethod
    def source_root_must_be_absolute(cls, value: str) -> str:
        if not PurePosixPath(value).is_absolute():
            raise ValueError("source_root must be an absolute POSIX path")
        return value.rstrip("/") or "/"

    @property
    def data_dir(self) -> Path:
        return self.critic_root / _DATA_DIR

    @property
    def catalog_dir(self) -> Path:
        return self.data_dir / "dev_databases" / self.catalog

    @property
    def relative_catalog_dir(self) -> str:
        return f"dev_databases/{self.catalog}"

    def accessor_path(self, relative_to_catalog: str) -> str:
        return str(PurePosixPath(self.source_root) / self.catalog / relative_to_catalog)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def recorded_hashes(ref: SourceRef) -> dict[str, str]:
    """Return the SHA-256 values Critic's SOURCES.md records for this catalog's files.

    Keys are paths relative to Critic ``resources/data/``. Only entries under the catalog's
    ``dev_databases/<catalog>/`` directory are returned.
    """
    sources = ref.data_dir / "SOURCES.md"
    if not sources.is_file():
        raise SourceIntegrityError(f"source registry not found: {sources}")
    prefix = ref.relative_catalog_dir + "/"
    hashes: dict[str, str] = {}
    for line in sources.read_text(encoding="utf-8").splitlines():
        match = _HASH_LINE.match(line.strip())
        if match and match.group(2).startswith(prefix):
            hashes[match.group(2)] = match.group(1)
    if not hashes:
        raise SourceIntegrityError(
            f"SOURCES.md records no hashes for {prefix!r}; register the catalog in Critic first"
        )
    return dict(sorted(hashes.items()))


def verify_sources(ref: SourceRef) -> dict[str, str]:
    """Check every recorded catalog file against its hash and return the verified hashes."""
    expected = recorded_hashes(ref)
    problems: list[str] = []
    for relative, sha in expected.items():
        path = ref.data_dir / relative
        if not path.is_file():
            problems.append(f"missing {relative}")
        elif file_sha256(path) != sha:
            problems.append(f"hash mismatch {relative}")
    if problems:
        raise SourceIntegrityError("; ".join(problems))
    return expected


class _BlockDumper(yaml.SafeDumper):
    """Deterministic, alias-free YAML with block literals for multi-line text."""

    def ignore_aliases(self, data: object) -> bool:
        return True


def _represent_str(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_BlockDumper.add_representer(str, _represent_str)


def dump_yaml(payload: object) -> str:
    return yaml.dump(
        payload,
        Dumper=_BlockDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=100,
    )


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


class SessionState(BaseModel):
    """Durable state of one preparation session under ``scratch/<session_id>/``."""

    catalog: str
    family: str
    critic_root: str
    source_root: str
    host: str
    source_files: dict[str, str]
    round: int = 0

    def source_ref(self) -> SourceRef:
        return SourceRef(
            catalog=self.catalog,
            critic_root=Path(self.critic_root),
            source_root=self.source_root,
            host=self.host,
        )


class SessionPaths:
    def __init__(self, scratch: Path) -> None:
        self.root = Path(scratch)

    @property
    def state(self) -> Path:
        return self.root / "session.yaml"

    @property
    def evidence(self) -> Path:
        return self.root / "evidence.json"

    @property
    def decisions(self) -> Path:
        return self.root / "decisions.yaml"

    @property
    def survey(self) -> Path:
        return self.root / "survey.md"

    @property
    def draft(self) -> Path:
        return self.root / "draft"

    @property
    def report(self) -> Path:
        return self.root / "report.json"
