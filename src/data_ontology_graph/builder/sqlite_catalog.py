from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path

from data_ontology_graph.model.dataset import ColumnMetadata, DatasetNode, DeclaredForeignKey
from data_ontology_graph.model.source import SqlDbSource, make_node_id


def require_sqlite_version() -> tuple[int, ...]:
    version = sqlite3.sqlite_version_info
    if version < (3, 41):
        raise RuntimeError(f"SQLite 3.41+ required, found {sqlite3.sqlite_version}")
    return version


def ingest_sqlite(path: Path, database: str | None = None) -> list[DatasetNode]:
    require_sqlite_version()
    db_id = database or Path(path).stem
    connection = sqlite3.connect(path)
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return [ingest_table(connection, db_id, table) for table in tables]
    finally:
        connection.close()


def ingest_table(connection: sqlite3.Connection, database: str, table: str) -> DatasetNode:
    info = list(connection.execute(f'PRAGMA table_info("{table}")'))
    columns = [
        ColumnMetadata(name=row[1], data_type=row[2] or "", is_nullable=not bool(row[3]))
        for row in info
    ]
    primary_key = [row[1] for row in sorted(info, key=lambda item: item[5]) if row[5]]
    unique_keys = _unique_keys(connection, table, primary_key)
    foreign_keys = _foreign_keys(connection, table)
    source = SqlDbSource(
        host="local",
        database=database,
        schema="main",
        table=table,
        dialect="sqlite",
    )
    return DatasetNode(
        node_id=make_node_id(source),
        table_name=table,
        data_source=source,
        columns=columns,
        primary_key=primary_key,
        unique_keys=unique_keys,
        foreign_key_declarations=foreign_keys,
    )


def _unique_keys(connection: sqlite3.Connection, table: str, primary_key: list[str]) -> list[list[str]]:
    keys: list[list[str]] = []
    for index in connection.execute(f'PRAGMA index_list("{table}")'):
        _seq, name, unique, origin, _partial = index[0], index[1], index[2], index[3], index[4]
        if not unique or origin == "pk":
            continue
        columns = [row[2] for row in connection.execute(f'PRAGMA index_info("{name}")')]
        if columns and columns != primary_key:
            keys.append(columns)
    return keys


def _foreign_keys(connection: sqlite3.Connection, table: str) -> list[DeclaredForeignKey]:
    grouped: dict[int, list[tuple]] = defaultdict(list)
    for row in connection.execute(f'PRAGMA foreign_key_list("{table}")'):
        grouped[row[0]].append(row)
    declarations: list[DeclaredForeignKey] = []
    for rows in grouped.values():
        rows = sorted(rows, key=lambda item: item[1])
        local = [row[3] for row in rows]
        ref_columns = [row[4] for row in rows]
        declarations.append(
            DeclaredForeignKey(
                local_columns=local,
                ref_table=rows[0][2],
                ref_columns=ref_columns,
            )
        )
    return declarations
