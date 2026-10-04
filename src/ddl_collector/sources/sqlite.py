"""SQLite source family: read-only DDL, description, and profiling evidence."""

from __future__ import annotations

import csv
import io
import re
import sqlite3
from contextlib import closing
from functools import cache
from importlib import resources
from pathlib import Path

from ddl_collector.config import SourceIntegrityError, SourceRef
from ddl_collector.evidence import (
    ColumnEvidence,
    EvidenceRef,
    ForeignKeyEvidence,
    KeyEvidence,
    SourceEvidence,
    TableEvidence,
)


_TEMPLATE_MARKER = re.compile(r"^-- name: (\w+)\s*$", re.MULTILINE)


@cache
def profile_templates() -> dict[str, str]:
    text = resources.files(__package__).joinpath("sqlite_profile.sql").read_text(encoding="utf-8")
    parts = _TEMPLATE_MARKER.split(text)
    templates: dict[str, str] = {}
    for name, body in zip(parts[1::2], parts[2::2]):
        statement = "\n".join(
            line for line in body.splitlines() if not line.lstrip().startswith("--")
        ).strip()
        templates[name] = statement.rstrip(";")
    return templates


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def connect_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


class SqliteSourceFamily:
    name = "sqlite"
    accessor_schema_id = "accessor.sqlite.v1"

    def __init__(self, profile: bool = True) -> None:
        self.profile = profile

    def collect(self, ref: SourceRef, source_files: dict[str, str]) -> SourceEvidence:
        database = _database_file(ref, source_files)
        relative_db = f"{ref.relative_catalog_dir}/{database.name}"
        descriptions = _read_descriptions(ref, source_files)
        tables: list[TableEvidence] = []
        with closing(connect_read_only(database)) as connection:
            for table_name in _table_names(connection):
                table = _table_evidence(connection, table_name, relative_db)
                _apply_descriptions(table, descriptions.get(table_name.casefold()))
                if self.profile:
                    _profile_table(connection, table, relative_db)
                tables.append(table)
            if self.profile:
                names = {table.name: table for table in tables}
                for table in tables:
                    for foreign_key in table.foreign_keys:
                        if foreign_key.referenced_table in names:
                            _profile_foreign_key(connection, table, foreign_key, relative_db)
        return SourceEvidence(
            family=self.name,
            catalog=ref.catalog,
            source_files=source_files,
            accessor_schema_id=self.accessor_schema_id,
            tables=tables,
            accessor_properties={
                table.name: {
                    "host": ref.host,
                    "database_path": ref.accessor_path(database.name),
                    "schema": table.schema_name,
                    "object": table.name,
                }
                for table in tables
            },
        )


def _database_file(ref: SourceRef, source_files: dict[str, str]) -> Path:
    candidates = sorted(
        relative
        for relative in source_files
        if relative.startswith(ref.relative_catalog_dir + "/")
        and relative.rsplit("/", 1)[-1].endswith((".sqlite", ".db", ".sqlite3"))
        and relative.count("/") == ref.relative_catalog_dir.count("/") + 1
    )
    if len(candidates) != 1:
        raise SourceIntegrityError(
            f"expected exactly one registered SQLite file in {ref.relative_catalog_dir}/, "
            f"found {candidates}"
        )
    return ref.data_dir / candidates[0]


def _table_names(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    return [row[0] for row in rows]


def _table_evidence(connection: sqlite3.Connection, table: str, source: str) -> TableEvidence:
    quoted = quote_identifier(table)
    columns = [
        ColumnEvidence(
            name=name,
            declared_type=(declared or "").strip(),
            not_null=bool(not_null),
            primary_key_position=int(pk),
            refs=[EvidenceRef(kind="S", source=source, location=f"PRAGMA table_info({table})")],
        )
        for _, name, declared, not_null, _default, pk in connection.execute(
            f"PRAGMA table_info({quoted})"
        ).fetchall()
    ]
    keys: list[KeyEvidence] = []
    primary = [column.name for column in sorted(columns, key=lambda c: c.primary_key_position)
               if column.primary_key_position]
    if primary:
        keys.append(
            KeyEvidence(
                kind="primary",
                columns=primary,
                refs=[EvidenceRef(kind="S", source=source, location=f"PRAGMA table_info({table}).pk")],
            )
        )
    for _, index_name, unique, origin, partial in connection.execute(
        f"PRAGMA index_list({quoted})"
    ).fetchall():
        if not unique or partial or origin == "pk":
            continue
        index_columns = [
            row[2]
            for row in connection.execute(
                f"PRAGMA index_info({quote_identifier(index_name)})"
            ).fetchall()
        ]
        if None in index_columns or index_columns == primary:
            continue
        keys.append(
            KeyEvidence(
                kind="unique",
                columns=index_columns,
                refs=[EvidenceRef(kind="S", source=source, location=f"PRAGMA index_list({table}) {index_name}")],
            )
        )
    grouped: dict[int, list[tuple[int, str, str, str | None]]] = {}
    for fk_id, seq, parent, child_column, parent_column, *_ in connection.execute(
        f"PRAGMA foreign_key_list({quoted})"
    ).fetchall():
        grouped.setdefault(fk_id, []).append((seq, parent, child_column, parent_column))
    foreign_keys: list[ForeignKeyEvidence] = []
    warnings: list[str] = []
    for fk_id in sorted(grouped):
        rows = sorted(grouped[fk_id])
        parent = rows[0][1]
        child_columns = [row[2] for row in rows]
        parent_columns = [row[3] for row in rows]
        if any(column is None for column in parent_columns):
            warnings.append(
                f"foreign key {fk_id} on {child_columns} references {parent} without named "
                "columns; it is reported but not proposed"
            )
            continue
        foreign_keys.append(
            ForeignKeyEvidence(
                columns=child_columns,
                referenced_table=parent,
                referenced_columns=parent_columns,
                refs=[EvidenceRef(kind="S", source=source, location=f"PRAGMA foreign_key_list({table}) id={fk_id}")],
            )
        )
    return TableEvidence(
        name=table, columns=columns, keys=keys, foreign_keys=foreign_keys, warnings=warnings
    )


def _read_descriptions(
    ref: SourceRef, source_files: dict[str, str]
) -> dict[str, tuple[str, dict[str, dict[str, str]]]]:
    """Map casefolded table name to (relative CSV path, casefolded column -> description row)."""
    prefix = f"{ref.relative_catalog_dir}/database_description/"
    descriptions: dict[str, tuple[str, dict[str, dict[str, str]]]] = {}
    for relative in sorted(source_files):
        if not (relative.startswith(prefix) and relative.endswith(".csv")):
            continue
        raw = (ref.data_dir / relative).read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252")
        rows: dict[str, dict[str, str]] = {}
        for row in csv.DictReader(io.StringIO(text)):
            # BIRD headers end with a trailing comma, so a shifted value description can land
            # in the unnamed last field. Prefer the named field and fall back to that one.
            trailing = row.get("") or ""
            clean = {
                (key or "").strip(): (value or "").strip()
                for key, value in row.items()
                if key and isinstance(value, str)
            }
            if not clean.get("value_description") and isinstance(trailing, str):
                clean["value_description"] = trailing.strip()
            original = clean.get("original_column_name", "")
            if original:
                rows[original.casefold()] = clean
        table = relative[len(prefix):-len(".csv")]
        descriptions[table.casefold()] = (relative, rows)
    return descriptions


def _apply_descriptions(
    table: TableEvidence, description: tuple[str, dict[str, dict[str, str]]] | None
) -> None:
    if description is None:
        table.warnings.append("no description file")
        return
    relative, rows = description
    matched: set[str] = set()
    for column in table.columns:
        row = rows.get(column.name.casefold())
        if row is None:
            continue
        matched.add(column.name.casefold())
        column.description = row.get("column_description", "")
        column.value_description = row.get("value_description", "")
        alias = row.get("column_name", "")
        if alias and alias.casefold() != column.name.casefold():
            column.synonyms = [alias]
        column.refs.append(
            EvidenceRef(kind="S", source=relative, location=f"original_column_name={column.name}")
        )
    unmatched = sorted(set(rows) - matched)
    if unmatched:
        table.warnings.append(f"description rows without a column: {unmatched}")


def _scalar(connection: sqlite3.Connection, name: str, **identifiers: str) -> int:
    statement = profile_templates()[name].format(**identifiers)
    value = connection.execute(statement).fetchone()[0]
    return int(value or 0)


def _profile_table(connection: sqlite3.Connection, table: TableEvidence, source: str) -> None:
    quoted = quote_identifier(table.name)
    table.row_count = _scalar(connection, "row_count", table=quoted)
    for column in table.columns:
        statement = profile_templates()["column_stats"].format(
            table=quoted, column=quote_identifier(column.name)
        )
        nulls, distinct = connection.execute(statement).fetchone()
        column.null_count = int(nulls or 0)
        column.distinct_count = int(distinct or 0)
        column.refs.append(EvidenceRef(kind="D", source=source, location=f"column_stats({table.name}.{column.name})"))
    for key in table.keys:
        key.duplicate_groups = _scalar(
            connection,
            "key_duplicate_groups",
            table=quoted,
            key_not_null=_not_null(None, key.columns),
            key_columns=", ".join(quote_identifier(column) for column in key.columns),
        )
        key.refs.append(EvidenceRef(kind="D", source=source, location=f"key_duplicate_groups({table.name})"))


def _profile_foreign_key(
    connection: sqlite3.Connection,
    table: TableEvidence,
    foreign_key: ForeignKeyEvidence,
    source: str,
) -> None:
    identifiers = {
        "child": quote_identifier(table.name),
        "parent": quote_identifier(foreign_key.referenced_table),
        "child_not_null": _not_null("c", foreign_key.columns),
        "child_columns": ", ".join(f"c.{quote_identifier(c)}" for c in foreign_key.columns),
        "join_condition": " AND ".join(
            f"p.{quote_identifier(parent)} = c.{quote_identifier(child)}"
            for child, parent in zip(foreign_key.columns, foreign_key.referenced_columns)
        ),
    }
    foreign_key.child_null_rows = _scalar(connection, "fk_child_null_rows", **identifiers)
    foreign_key.orphan_rows = _scalar(connection, "fk_orphan_rows", **identifiers)
    foreign_key.unreferenced_parent_rows = _scalar(
        connection, "fk_unreferenced_parent_rows", **identifiers
    )
    foreign_key.max_children_per_parent = _scalar(
        connection, "fk_max_children_per_parent", **identifiers
    )
    foreign_key.refs.append(
        EvidenceRef(
            kind="D",
            source=source,
            location=f"fk_coverage({table.name}.{'+'.join(foreign_key.columns)} -> "
            f"{foreign_key.referenced_table})",
        )
    )


def _not_null(alias: str | None, columns: list[str]) -> str:
    prefix = f"{alias}." if alias else ""
    return " AND ".join(f"{prefix}{quote_identifier(column)} IS NOT NULL" for column in columns)
