"""Detail levels and caller-added fields for navigation responses (system design 2.4.6-2.4.8).

A dataset or entity-definition field name is a dotted path into a record. A directed edge is an
array whose positions the response's ``edge_fields`` header names. Basic fields are always
present; a detail level adds its fields, and a caller may add more by naming them per object.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

Detail = Literal["essential", "standard", "full"]
FieldObject = Literal["dataset", "edge", "entity_definition"]

DATASET_FIELDS = (
    "node_id", "qualified_name", "distance", "edge_count", "accessor.schema_id", "grain",
    "descriptor.description", "unknown_fields", "descriptor.display_name", "descriptor.synonyms",
    "descriptor.tags",
    "accessor.properties", "columns", "entity_definitions",
)
EDGE_FIELDS = (
    "edge", "identity_id", "multiplicity", "match_existence", "reverse_multiplicity", "reverse_match_existence",
    "from_description", "to_description", "annotation", "edge_id",
)
"""Directed-edge array positions in order; ``edge_id`` is always last.

``identity_id`` is a basic position where no edge group carries the logical entity ID, in paths.
"""
RESPONSE_ONLY = ("distance", "edge_count")
"""Dataset fields that describe a navigation response, not the dataset."""
DEFINITION_FIELDS = (
    "identity_id", "dataset_columns", "entity_universe", "unique", "total", "conforms",
    "entity_expression", "entity_metadata", "description", "effective_description",
    "description_source", "unknown_fields",
)
COLUMN_FIELDS = ("name", "description", "value_description", "synonyms")

_BASIC = {
    "dataset": ("node_id", "qualified_name"),
    "edge": ("edge", "edge_id"),
    "entity_definition": ("identity_id", "dataset_columns"),
}
_LEVELS: dict[str, dict[Detail, tuple[str, ...]]] = {
    "dataset": {
        "essential": ("distance", "edge_count", "accessor.schema_id"),
        "standard": ("grain", "descriptor.description", "unknown_fields"),
        "full": ("descriptor.display_name", "descriptor.synonyms", "descriptor.tags",
                 "accessor.properties", "columns", "entity_definitions"),
    },
    "edge": {
        "essential": ("multiplicity", "match_existence"),
        "standard": ("reverse_multiplicity", "reverse_match_existence", "from_description",
                     "to_description"),
        "full": ("annotation",),
    },
    "entity_definition": {
        "essential": (),
        "standard": (),
        "full": DEFINITION_FIELDS,
    },
}
_CATALOG = {"dataset": DATASET_FIELDS, "edge": EDGE_FIELDS, "entity_definition": DEFINITION_FIELDS}
_ORDER: tuple[Detail, ...] = ("essential", "standard", "full")

_QUOTED = (",", "[", "]", '"', "->")


def definition_label(node_id: str, columns: Sequence[str]) -> str:
    """``node_id[col,...]``, quoting a column name that holds a delimiter, as in ``t["a,b"]``."""
    names = (
        json.dumps(column, ensure_ascii=False) if any(mark in column for mark in _QUOTED)
        else column
        for column in columns
    )
    return f"{node_id}[{','.join(names)}]"


def split_edge_label(label: str) -> tuple[tuple[str, list[str]], tuple[str, list[str]]]:
    """``(node_id, columns)`` of the start and end of ``"start[...] -> end[...]"``."""
    sides: list[tuple[str, list[str]]] = []
    decoder = json.JSONDecoder()
    index = 0
    for expected_end in (" -> ", ""):
        bracket = label.find("[", index)
        if bracket < 0:
            raise ValueError(f"not a directed edge: {label!r}")
        node_id, index = label[index:bracket], bracket + 1
        columns: list[str] = []
        while True:
            if label.startswith('"', index):
                name, index = decoder.raw_decode(label, index)
            else:
                stop = min((i for i in (label.find(",", index), label.find("]", index)) if i >= 0),
                           default=-1)
                if stop < 0:
                    raise ValueError(f"not a directed edge: {label!r}")
                name, index = label[index:stop], stop
            columns.append(name)
            if label.startswith(",", index):
                index += 1
                continue
            if not label.startswith("]", index):
                raise ValueError(f"not a directed edge: {label!r}")
            index += 1
            break
        sides.append((node_id, columns))
        if expected_end:
            if not label.startswith(expected_end, index):
                raise ValueError(f"not a directed edge: {label!r}")
            index += len(expected_end)
    if index != len(label):
        raise ValueError(f"not a directed edge: {label!r}")
    return sides[0], sides[1]


@dataclass(frozen=True)
class View:
    detail: Detail
    added: dict[str, list[str]]
    dataset: tuple[str, ...]
    edge: tuple[str, ...]
    entity_definition: tuple[str, ...]

    @classmethod
    def resolve(
        cls, detail: Detail, fields: dict[str, list[str]] | None = None, *, paths: bool = False,
    ) -> "View":
        added = {name: list(dict.fromkeys(values)) for name, values in (fields or {}).items()}
        selected: dict[str, set[str]] = {}
        for name, catalog in _CATALOG.items():
            unknown = [field for field in added.get(name, []) if field not in catalog]
            if unknown:
                raise ValueError(f"unknown {name} fields: {unknown}")
            chosen = set(_BASIC[name])
            for level in _ORDER[: _ORDER.index(detail) + 1]:
                chosen.update(_LEVELS[name][level])
            chosen.update(added.get(name, []))
            selected[name] = chosen
        if paths:
            selected["edge"].add("identity_id")
        if added.get("entity_definition"):
            selected["dataset"].add("entity_definitions")
        return cls(
            detail=detail,
            added=added,
            **{name: tuple(f for f in _CATALOG[name] if f in selected[name]) for name in _CATALOG},
        )

    def dataset_fields(self, *, distance: bool) -> tuple[str, ...]:
        return tuple(f for f in self.dataset if distance or f != "distance")

    def record_fields(self) -> tuple[str, ...]:
        """Dataset fields outside navigation, without the response-only ones."""
        return tuple(f for f in self.dataset if f not in RESPONSE_ONLY)


def pick(values: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """A nested record holding ``fields``, read from a flat map of dotted field names."""
    record: dict[str, Any] = {}
    for field in fields:
        *parents, leaf = field.split(".")
        target = record
        for parent in parents:
            target = target.setdefault(parent, {})
        target[leaf] = values[field]
    return record
