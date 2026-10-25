"""Header-and-row tables for graph-object collections, and their lossless record form.

A table column name is a dotted path into the record: ``to.node_id`` is the ``node_id`` field of
the record's ``to`` object. A cell holds the value at that
path, which may itself be a list or an object with provider-specific keys.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

ResponseFormat = Literal["table", "records"]


class Table(BaseModel):
    model_config = ConfigDict(extra="forbid")

    header: list[str]
    rows: list[list[Any]]


def to_table(records: list[dict[str, Any]], header: list[str]) -> Table:
    rows = []
    for record in records:
        row = [_get(record, column) for column in header]
        if _expand(header, row) != record:
            raise ValueError(f"header {header} does not cover record {record}")
        rows.append(row)
    return Table(header=header, rows=rows)


def to_records(table: Table | dict[str, Any]) -> list[dict[str, Any]]:
    """Expand a table into records, nesting each dotted column name."""
    if isinstance(table, Table):
        table = table.model_dump()
    return [_expand(table["header"], row) for row in table["rows"]]


def _expand(header: list[str], row: list[Any]) -> dict[str, Any]:
    record: dict[str, Any] = {}
    for column, value in zip(header, row, strict=True):
        *parents, leaf = column.split(".")
        target = record
        for parent in parents:
            target = target.setdefault(parent, {})
        target[leaf] = value
    return record


def collection(
    records: list[dict[str, Any]], header: list[str], response_format: ResponseFormat,
) -> Table | list[dict[str, Any]]:
    return to_table(records, header) if response_format == "table" else records


def _get(record: dict[str, Any], column: str) -> Any:
    value: Any = record
    for part in column.split("."):
        value = value[part]
    return value


RELATIONSHIP_HEADER = [
    "edge_id", "identity_id",
    "endpoint_a.node_id", "endpoint_a.dataset_columns",
    "endpoint_b.node_id", "endpoint_b.dataset_columns",
    "a_to_b.multiplicity", "a_to_b.match_existence",
    "b_to_a.multiplicity", "b_to_a.match_existence",
    "unknown_fields", "annotation",
]
DATASET_HEADER = [
    "node_id",
    "descriptor.qualified_name", "descriptor.description",
    "descriptor.synonyms", "descriptor.tags",
    "accessor.schema_id", "accessor.properties",
]
DEFINITION_HEADER = [
    "node_id", "identity_id", "dataset_columns", "entity_universe", "unique", "total",
    "conforms", "entity_expression", "entity_metadata", "description", "effective_description",
    "description_source", "unknown_fields",
]
