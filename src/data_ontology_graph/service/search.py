from __future__ import annotations

import re
import unicodedata
from enum import IntEnum
from typing import Iterable

import marisa_trie

from data_ontology_graph.model.snapshot import GraphSnapshot
from data_ontology_graph.service.contracts import SearchHit, SearchSubject


_CAMEL_BOUNDARY_1 = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_CAMEL_BOUNDARY_2 = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_RECORD_FORMAT = "<IB"


class SearchField(IntEnum):
    STABLE_ID = 1
    CANONICAL_NAME = 2
    SYNONYM = 3
    TAG = 4
    QUALIFIED_NAME = 5
    ACCESSOR = 6
    DATASET_COLUMNS = 7
    ENTITY_EXPRESSION = 8
    ENTITY_METADATA = 9
    DESCRIPTION = 10
    COLUMN = 11


_FIELD_NAMES = {field.value: field.name.lower() for field in SearchField}

# Whole-value description placeholders that carry no descriptive meaning. Sources: pandas
# default ``na_values``, null literals in SQL, JSON, JavaScript, Python, R, and spreadsheets,
# and stock "not yet written" phrases from data catalogs and issue trackers. Entries are
# compared after ``normalize_term``, so case, punctuation, and spacing variants match; text
# made only of punctuation, such as ``?`` or ``--``, already normalizes to no terms.
_PLACEHOLDER_TEXT = (
    # Null and missing-value literals
    "null", "nil", "none", "nothing", "void", "undefined", "nan", "NaN", "NaT", "<NA>",
    "#N/A", "#N/A N/A", "#NA", "N/A", "NA", "n.a.", "n/d", "-1.#IND", "1.#IND", "-1.#QNAN",
    "1.#QNAN", "-NaN", "#NULL!", "(null)", "(none)", "(blank)", "(empty)",
    "missing", "missing value", "missing data", "empty", "blank", "no value", "no data",
    # Unknown or unassessed
    "unknown", "unk", "not known", "unknown value", "undetermined", "unspecified",
    "not specified", "not defined", "not set", "unset", "not provided", "not recorded",
    "not documented", "undocumented", "not applicable", "not available", "no info",
    "no information", "no description", "no description available", "description not available",
    "none provided", "none given", "no comment", "no comments",
    # Not yet written
    "tbd", "tba", "tbc", "to be determined", "to be defined", "to be decided", "to be confirmed",
    "to be added", "to be documented", "todo", "to do", "fixme", "placeholder", "lorem ipsum",
    "xxx", "xxxx",
)


def normalize_term(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = _CAMEL_BOUNDARY_2.sub(" ", value)
    value = _CAMEL_BOUNDARY_1.sub(" ", value)
    value = value.casefold()
    normalized = "".join(character if character.isalnum() else " " for character in value)
    return " ".join(normalized.split())


def index_terms(value: str) -> set[str]:
    normalized = normalize_term(value)
    if not normalized:
        return set()
    terms = {normalized}
    terms.update(normalized.split())
    return terms


PLACEHOLDER_TERMS = frozenset(
    term for term in (normalize_term(value) for value in _PLACEHOLDER_TEXT) if term
)


def is_placeholder(value: str) -> bool:
    """Return whether description text is only a placeholder such as ``N/A`` or ``unknown``."""
    return normalize_term(value) in PLACEHOLDER_TERMS


def descriptive_text(value: str) -> str:
    """Return description text for indexing, or nothing when it is only a placeholder."""
    return "" if is_placeholder(value) else value


class LexicalSearchIndex:
    """Static trie over descriptive terms.

    A description whose whole value is a placeholder contributes no terms.
    Unknown claims are never search terms; each subject reports its unknown fields instead.
    """

    def __init__(self, snapshot: GraphSnapshot) -> None:
        subjects: list[SearchSubject] = []
        entries: set[tuple[str, int, int]] = set()

        def add_subject(subject: SearchSubject, fields: Iterable[tuple[SearchField, str]]) -> None:
            ordinal = len(subjects)
            subjects.append(subject)
            for field, value in fields:
                for term in index_terms(value):
                    entries.add((term, ordinal, int(field)))

        for identity in sorted(snapshot.logical_identities, key=lambda item: item.identity_id):
            add_subject(
                SearchSubject(
                    kind="identity",
                    key=identity.identity_id,
                    label=identity.name,
                    identity_id=identity.identity_id,
                ),
                [
                    (SearchField.STABLE_ID, identity.identity_id),
                    (SearchField.CANONICAL_NAME, identity.name),
                    (SearchField.DESCRIPTION, descriptive_text(identity.description)),
                    *((SearchField.SYNONYM, synonym) for synonym in identity.synonyms),
                ],
            )

        for node in sorted(snapshot.nodes, key=lambda item: item.node_id):
            accessor_fields = [
                (SearchField.ACCESSOR, value)
                for value in _string_values(node.accessor.properties)
            ]
            add_subject(
                SearchSubject(
                    kind="dataset",
                    key=node.node_id,
                    label=node.descriptor.display_name,
                    node_id=node.node_id,
                    unknown_fields=node.unknown_fields(),
                ),
                [
                    (SearchField.STABLE_ID, node.node_id),
                    (SearchField.CANONICAL_NAME, node.descriptor.display_name),
                    (SearchField.QUALIFIED_NAME, node.descriptor.qualified_name),
                    (SearchField.DESCRIPTION, descriptive_text(node.descriptor.description)),
                    (SearchField.ACCESSOR, node.accessor.schema_id),
                    *(
                        (SearchField.SYNONYM, synonym)
                        for synonym in node.descriptor.synonyms
                    ),
                    *((SearchField.TAG, tag) for tag in node.descriptor.tags),
                    *accessor_fields,
                ],
            )

            for definition in node.entity_definitions:
                key = _definition_key(
                    node.node_id,
                    definition.identity_id,
                    definition.dataset_columns,
                )
                metadata_fields = [
                    (SearchField.ENTITY_METADATA, value)
                    for value in _string_values(definition.entity_metadata)
                ]
                add_subject(
                    SearchSubject(
                        kind="entity_definition",
                        key=key,
                        label=definition.entity_expression[0]
                        if definition.entity_expression
                        else definition.identity_id,
                        node_id=node.node_id,
                        identity_id=definition.identity_id,
                        dataset_columns=definition.dataset_columns,
                        unknown_fields=definition.unknown_fields(),
                    ),
                    [
                        (SearchField.STABLE_ID, definition.identity_id),
                        *(
                            (SearchField.DATASET_COLUMNS, column)
                            for column in definition.dataset_columns
                        ),
                        *(
                            (SearchField.ENTITY_EXPRESSION, expression)
                            for expression in definition.entity_expression
                        ),
                        *metadata_fields,
                    ],
                )

            for column in node.columns:
                add_subject(
                    SearchSubject(
                        kind="column",
                        key=f"{node.node_id}|column|{column.name}",
                        label=column.name,
                        node_id=node.node_id,
                        column_name=column.name,
                    ),
                    [
                        (SearchField.COLUMN, column.name),
                        (SearchField.DESCRIPTION, descriptive_text(column.description)),
                        (SearchField.DESCRIPTION, descriptive_text(column.value_description)),
                        *((SearchField.SYNONYM, synonym) for synonym in column.synonyms),
                    ],
                )

        packed_entries = [
            (term, (ordinal, field))
            for term, ordinal, field in sorted(entries)
        ]
        self._subjects = tuple(subjects)
        self._trie = marisa_trie.RecordTrie(
            _RECORD_FORMAT,
            packed_entries,
            order=marisa_trie.LABEL_ORDER,
        )

    def search(self, query: str, limit: int = 50) -> tuple[str, list[SearchHit], bool]:
        normalized = normalize_term(query)
        if not normalized:
            return normalized, [], False

        candidates: list[tuple[str, str, int, int]] = []
        for ordinal, field in self._trie.get(normalized, []):
            candidates.append(("exact", normalized, ordinal, field))

        prefix_items = sorted(
            self._trie.iteritems(normalized),
            key=lambda item: (item[0], item[1][1], item[1][0]),
        )
        for term, (ordinal, field) in prefix_items:
            if term != normalized:
                candidates.append(("prefix", term, ordinal, field))

        hits: list[SearchHit] = []
        seen: set[tuple[str, str]] = set()
        for match_kind, term, ordinal, field in sorted(
            candidates,
            key=lambda item: (
                0 if item[0] == "exact" else 1,
                item[3],
                item[1],
                self._subjects[item[2]].kind,
                self._subjects[item[2]].key,
            ),
        ):
            subject = self._subjects[ordinal]
            subject_key = (subject.kind, subject.key)
            if subject_key in seen:
                continue
            seen.add(subject_key)
            hits.append(
                SearchHit(
                    subject=subject,
                    match_kind=match_kind,
                    matched_term=term,
                    matched_field=_FIELD_NAMES[field],
                )
            )

        return normalized, hits[:limit], len(hits) > limit


def _definition_key(node_id: str, identity_id: str, dataset_columns: list[str]) -> str:
    return f"{node_id}|{identity_id}|{'+'.join(dataset_columns)}"


def _string_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [
            item
            for key, child in value.items()
            for item in [str(key), *_string_values(child)]
        ]
    if isinstance(value, list):
        return [item for child in value for item in _string_values(child)]
    return []
