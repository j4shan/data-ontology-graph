import hashlib
import shutil
import sqlite3
from pathlib import Path

import pytest


MINIBANK = Path(__file__).parent / "fixtures" / "minibank"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_critic_tree(root: Path, catalog: str = "minibank") -> Path:
    """Build a Critic-style source tree for the minibank fixture under ``root``."""
    data = root / "resources" / "data"
    catalog_dir = data / "dev_databases" / catalog
    (catalog_dir / "database_description").mkdir(parents=True)
    with sqlite3.connect(catalog_dir / f"{catalog}.sqlite") as connection:
        connection.executescript((MINIBANK / "schema.sql").read_text(encoding="utf-8"))
    connection.close()
    for csv_file in sorted((MINIBANK / "database_description").glob("*.csv")):
        shutil.copy(csv_file, catalog_dir / "database_description" / csv_file.name)
    lines = [
        f"{_sha256(path)}  {path.relative_to(data).as_posix()}"
        for path in sorted(catalog_dir.rglob("*"))
        if path.is_file()
    ]
    (data / "SOURCES.md").write_text(
        "# Test data sources\n\n### `" + catalog + "` hashes\n\n```\n" + "\n".join(lines) + "\n```\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def critic_root(tmp_path: Path) -> Path:
    return build_critic_tree(tmp_path / "critic")
