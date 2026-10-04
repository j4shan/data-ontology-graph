import sqlite3
from pathlib import Path

import pytest

from ddl_collector.config import (
    SourceIntegrityError,
    SourceRef,
    file_sha256,
    verify_sources,
)
from ddl_collector.sources import SqliteSourceFamily, family
from ddl_collector.sources.sqlite import connect_read_only, profile_templates


def _ref(critic_root: Path, **overrides) -> SourceRef:
    return SourceRef(catalog="minibank", critic_root=critic_root, **overrides)


def _collect(critic_root: Path, profile: bool = True):
    ref = _ref(critic_root)
    return SqliteSourceFamily(profile=profile).collect(ref, verify_sources(ref))


def test_verify_sources_returns_recorded_catalog_hashes(critic_root):
    hashes = verify_sources(_ref(critic_root))

    assert sorted(hashes) == [
        "dev_databases/minibank/database_description/branch.csv",
        "dev_databases/minibank/database_description/customer.csv",
        "dev_databases/minibank/minibank.sqlite",
    ]


def test_verify_sources_rejects_a_changed_file(critic_root):
    csv_file = critic_root / "resources/data/dev_databases/minibank/database_description/branch.csv"
    csv_file.write_text(csv_file.read_text(encoding="utf-8") + "extra,row,,,,\n", encoding="utf-8")

    with pytest.raises(SourceIntegrityError, match="hash mismatch .*branch.csv"):
        verify_sources(_ref(critic_root))


def test_verify_sources_rejects_an_unregistered_catalog(critic_root):
    with pytest.raises(SourceIntegrityError, match="records no hashes"):
        verify_sources(SourceRef(catalog="other", critic_root=critic_root))


def test_source_root_must_be_absolute(critic_root):
    with pytest.raises(ValueError, match="absolute"):
        _ref(critic_root, source_root="relative/root")


def test_unknown_family_is_rejected():
    with pytest.raises(ValueError, match="unknown source family"):
        family("parquet")


def test_read_only_connection_refuses_writes(critic_root):
    database = critic_root / "resources/data/dev_databases/minibank/minibank.sqlite"
    connection = connect_read_only(database)
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM branch")
    finally:
        connection.close()


def test_collect_leaves_every_source_file_unchanged(critic_root):
    hashes = verify_sources(_ref(critic_root))
    _collect(critic_root)

    data = critic_root / "resources/data"
    assert {relative: file_sha256(data / relative) for relative in hashes} == hashes


def test_collect_reads_structure_keys_and_foreign_keys(critic_root):
    evidence = _collect(critic_root, profile=False)

    assert [table.name for table in evidence.tables] == [
        "account",
        "account_note",
        "branch",
        "customer",
    ]
    branch = evidence.table("branch")
    assert branch.column_names() == ["branch_id", "name"]
    assert [(key.kind, key.columns) for key in branch.keys] == [
        ("primary", ["branch_id"]),
        ("unique", ["name"]),
    ]
    assert evidence.table("account_note").primary_key() is None
    [foreign_key] = evidence.table("customer").foreign_keys
    assert (foreign_key.columns, foreign_key.referenced_table, foreign_key.referenced_columns) == (
        ["branch_id"],
        "branch",
        ["branch_id"],
    )
    assert foreign_key.orphan_rows is None


def test_collect_applies_descriptions_and_shifted_value_descriptions(critic_root):
    evidence = _collect(critic_root, profile=False)

    customer = {column.name: column for column in evidence.table("customer").columns}
    assert customer["branch_id"].description == "the branch that serves the customer"
    assert customer["branch_id"].synonyms == ["home branch"]
    assert customer["segment"].synonyms == []
    assert customer["segment"].value_description == (
        '"R" stands for retail\n"B" stands for business'
    )
    branch = {column.name: column for column in evidence.table("branch").columns}
    assert branch["name"].value_description == "unique per bank"
    assert evidence.table("account").warnings == ["no description file"]


def test_collect_profiles_tables_and_foreign_key_coverage(critic_root):
    evidence = _collect(critic_root)

    account = evidence.table("account")
    assert account.row_count == 4
    customer_id = next(column for column in account.columns if column.name == "customer_id")
    assert (customer_id.null_count, customer_id.distinct_count) == (1, 2)
    [to_customer] = account.foreign_keys
    assert (
        to_customer.child_null_rows,
        to_customer.orphan_rows,
        to_customer.unreferenced_parent_rows,
        to_customer.max_children_per_parent,
    ) == (1, 0, 1, 2)
    assert [ref.kind for ref in to_customer.refs] == ["S", "D"]


def test_accessor_properties_use_the_canonical_source_root(critic_root):
    ref = _ref(critic_root, source_root="/srv/sources/", host="data-host")
    evidence = SqliteSourceFamily(profile=False).collect(ref, verify_sources(ref))

    assert evidence.accessor_schema_id == "accessor.sqlite.v1"
    assert evidence.accessor_properties["branch"] == {
        "host": "data-host",
        "database_path": "/srv/sources/minibank/minibank.sqlite",
        "schema": "main",
        "object": "branch",
    }


def test_profile_templates_are_read_only_selects():
    templates = profile_templates()

    assert set(templates) == {
        "row_count",
        "column_stats",
        "key_duplicate_groups",
        "fk_child_null_rows",
        "fk_orphan_rows",
        "fk_unreferenced_parent_rows",
        "fk_max_children_per_parent",
    }
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in templates.values())
