"""Project graph objects into the trimmed fields an AKG element carries.

Inputs are JSON objects in the graph's own node and relationship shape, as the service serves
them or as the YAML intermediary dumps them. A relationship is projected as the directed edge
leaving one of its endpoints. The skill's `scripts/akg.py` repeats these rules in
the standard library; a test keeps the two in agreement.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from data_ontology_graph.model.dataset import effective_description


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
        descriptions = {name: column.get("description", "") for name, column in inventory.items()}
        dataset["entity_definitions"] = [
            _definition(definition, descriptions)
            for definition in node.get("entity_definitions", [])
        ]
    if full:
        for field in ("synonyms", "tags"):
            if descriptor.get(field):
                dataset[field] = descriptor[field]
    return dataset


def project_edge(
    relationship: Mapping[str, Any],
    from_node_id: str,
    from_dataset_columns: list[str],
    descriptions: Mapping[tuple[str, tuple[str, ...]], str] | None = None,
) -> dict[str, Any]:
    """Return the directed edge of a relationship leaving one endpoint, with both claims.

    Served relationship records carry `identity_id` once beside the endpoints; YAML
    relationships carry it on each endpoint. `descriptions` maps an endpoint's
    (`node_id`, `dataset_columns`) to its effective description.
    """
    sides = [(relationship[side], forward, reverse) for side, forward, reverse in (
        ("endpoint_a", "a_to_b", "b_to_a"), ("endpoint_b", "b_to_a", "a_to_b"),
    )]
    for start, forward, reverse in sides:
        if start["node_id"] == from_node_id and start["dataset_columns"] == from_dataset_columns:
            end = relationship["endpoint_b" if forward == "a_to_b" else "endpoint_a"]
            break
    else:
        raise ValueError(
            f"{from_node_id}{from_dataset_columns} is not an endpoint of {relationship['edge_id']}"
        )
    edge = {
        "edge_id": relationship["edge_id"],
        "identity_id": start.get("identity_id", relationship.get("identity_id")),
        "from_dataset_columns": start["dataset_columns"],
        "to_node_id": end["node_id"],
        "to_dataset_columns": end["dataset_columns"],
        "multiplicity": relationship[forward]["multiplicity"],
        "match_existence": relationship[forward]["match_existence"],
        "reverse_multiplicity": relationship[reverse]["multiplicity"],
        "reverse_match_existence": relationship[reverse]["match_existence"],
    }
    for field, endpoint in (("from_description", start), ("to_description", end)):
        text = (descriptions or {}).get((endpoint["node_id"], tuple(endpoint["dataset_columns"])))
        if text:
            edge[field] = text
    return edge


def endpoint_descriptions(record: Mapping[str, Any]) -> dict[tuple[str, tuple[str, ...]], str]:
    """Effective descriptions of a `graph.get_relationship` record's entity definitions."""
    return {
        (definition["node_id"], tuple(definition["dataset_columns"])):
            definition["effective_description"]
        for definition in record.get("entity_definitions", [])
        if definition.get("effective_description")
    }


def _definition(definition: Mapping[str, Any], descriptions: Mapping[str, str]) -> dict[str, Any]:
    projected = {
        "identity_id": definition["identity_id"],
        "dataset_columns": definition["dataset_columns"],
        "entity_universe": definition["entity_universe"],
    }
    effective = effective_description(
        definition.get("description", ""),
        definition["dataset_columns"],
        definition.get("entity_expression", []),
        descriptions,
    )
    if effective:
        projected["description"], projected["description_source"] = effective
    return projected


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
