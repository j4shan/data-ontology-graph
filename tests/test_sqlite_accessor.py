import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from data_ontology_graph.model.dataset import DatasetAccessor, SqliteAccessorProperties


def _accessor(**overrides: str) -> DatasetAccessor:
    properties = {
        "host": "localhost",
        "database_path": "/srv/sqlite/shop.sqlite",
        "schema": "main",
        "object": "order",
        **overrides,
    }
    return DatasetAccessor(schema_id="accessor.sqlite.v1", properties=properties)


def test_sqlite_accessor_requires_host_absolute_path_and_qualified_object() -> None:
    assert _accessor().properties["schema"] == "main"

    with pytest.raises(ValidationError, match="absolute path"):
        _accessor(database_path="shop.sqlite")
    with pytest.raises(ValidationError, match="absolute path"):
        _accessor(database_path="~/shop.sqlite")
    for missing in ("host", "schema", "object"):
        properties = _accessor().properties
        properties.pop(missing)
        with pytest.raises(ValidationError, match=missing):
            DatasetAccessor(schema_id="accessor.sqlite.v1", properties=properties)


def test_sqlite_accessor_rejects_credentials() -> None:
    with pytest.raises(ValidationError, match="password"):
        _accessor(password="dummy")


@pytest.mark.skipif(shutil.which("sqlite3") is None, reason="sqlite3 CLI is not installed")
def test_sqlite_cli_locates_a_table_from_accessor_properties(tmp_path: Path) -> None:
    database = tmp_path / "deployed" / "shop.sqlite"
    database.parent.mkdir()
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE "order" (order_id INTEGER PRIMARY KEY, note TEXT)')
        connection.execute("INSERT INTO \"order\" VALUES (7, 'seven')")
    connection.close()

    accessor = _accessor(database_path=str(database))
    properties = SqliteAccessorProperties.model_validate(accessor.properties)
    assert properties.host == "localhost"

    result = subprocess.run(
        [
            "sqlite3",
            "-readonly",
            properties.database_path,
            f"SELECT order_id, note FROM {_quote(properties.schema_name)}"
            f".{_quote(properties.object)}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "7|seven"


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
