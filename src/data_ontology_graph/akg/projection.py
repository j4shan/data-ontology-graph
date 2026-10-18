"""Project graph objects into the trimmed fields an AKG element carries.

Inputs are JSON objects in the graph's own node and relationship shape, as the service serves
them or as the YAML intermediary dumps them. The skill's `scripts/akg.py` repeats these rules in
the standard library; a test keeps the two in agreement.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


DETAIL_LEVELS = ("essential", "standard", "full")
UNKNOWN = "unknown"


def source_of(schema_id: str) -> str:
    """Return the accessor family, the middle segment of `accessor.<family>.<version>`."""
    parts = schema_id.split(".")
    return parts[1] if len(parts) >= 3 else schema_id


def project_dataset(
    node: Mapping[str, Any],
    detail: str = "essential",
    columns: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Return the dataset fields for one graph node at a detail level.

    `essential` keeps the name, source, grain, and the named columns. `standard` adds the
    description, every column, and entity definitions. `full` adds synonyms and tags.
    """
    if detail not in DETAIL_LEVELS:
        raise ValueError(f"unknown detail level {detail!r}; use one of {DETAIL_LEVELS}")
    full = detail == "full"
    descriptor = node["descriptor"]
    inventory = {column["name"]: column for column in node["columns"]}
    if detail == "essential":
        selected = list(dict.fromkeys(columns or []))
    else:
        selected = list(inventory)
    missing = [name for name in selected if name not in inventory]
    if missing:
        raise ValueError(f"{node['node_id']} has no columns {missing}")

    dataset: dict[str, Any] = {
        "name": descriptor["qualified_name"],
        "source": source_of(node["accessor"]["schema_id"]),
        "grain": _grain(node["grain"]),
    }
    if detail != "essential" and descriptor.get("description"):
        dataset["description"] = descriptor["description"]
    if selected:
        dataset["columns"] = {name: _column(inventory[name], full) for name in selected}
    if detail != "essential":
        dataset["entity_definitions"] = [
            {
                "identity_id": definition["identity_id"],
                "dataset_columns": definition["dataset_columns"],
                "entity_universe": definition["entity_universe"],
            }
            for definition in node.get("entity_definitions", [])
        ]
    if full:
        for field in ("synonyms", "tags"):
            if descriptor.get(field):
                dataset[field] = descriptor[field]
    return dataset


def project_relationship(relationship: Mapping[str, Any]) -> dict[str, Any]:
    """Return the relationship fields: both endpoints and both direction claims.

    Served relationship records carry `identity_id` once beside the endpoints; YAML
    relationships carry it on each endpoint. Endpoint order is kept as given.
    """
    return {
        side: {
            "node_id": relationship[side]["node_id"],
            "identity_id": relationship[side].get("identity_id", relationship.get("identity_id")),
            "dataset_columns": relationship[side]["dataset_columns"],
        }
        for side in ("endpoint_a", "endpoint_b")
    } | {
        direction: {key: relationship[direction][key] for key in ("multiplicity", "match_existence")}
        for direction in ("a_to_b", "b_to_a")
    }


def _grain(grain: Any) -> list[str] | str:
    if grain == UNKNOWN:
        return UNKNOWN
    columns: list[str] = []
    for component in grain["components"]:
        columns.extend(column for column in component["dataset_columns"] if column not in columns)
    return columns


def _column(column: Mapping[str, Any], full: bool) -> dict[str, Any]:
    fields = ("description", "value_description", "synonyms") if full else (
        "description",
        "value_description",
    )
    return {field: column[field] for field in fields if column.get(field)}
