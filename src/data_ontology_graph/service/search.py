from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable

import marisa_trie

from data_ontology_graph.model.snapshot import GraphSnapshot
from data_ontology_graph.service.contracts import SearchGroup, SearchKind


_CAMEL_BOUNDARY_1 = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_CAMEL_BOUNDARY_2 = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_RECORD_FORMAT = "<IH"
SEARCH_KINDS: tuple[SearchKind, ...] = (
    "column",
    "dataset",
    "entity_definition",
    "identity",
)
MATCH_ROW_HEADER = ["key", "match_type", "match_field", "matched_term", "matched_value"]
SUBJECT_ROW_HEADERS: dict[SearchKind, list[str]] = {
    "column": ["key", "node_id", "column_name"],
    "dataset": ["key", "display_name", "unknown_fields"],
    "entity_definition": [
        "key",
        "entity_expression",
        "node_id",
        "identity_id",
        "dataset_columns",
        "unknown_fields",
    ],
    "identity": ["key", "name"],
}
_MATCH_TYPES = ("exact", "prefix", "phrase", "all_words")
_EXACT, _PREFIX, _PHRASE, _ALL_WORDS = range(len(_MATCH_TYPES))


class SearchField(IntEnum):
    """Indexed field, in the order a subject's match rows list equally good matches."""

    STABLE_ID = 1
    COLUMN = 2
    CANONICAL_NAME = 3
    SYNONYM = 4
    TAG = 5
    QUALIFIED_NAME = 6
    ACCESSOR = 7
    DATASET_COLUMNS = 8
    ENTITY_EXPRESSION = 9
    ENTITY_METADATA = 10
    DESCRIPTION = 11
    VALUE_DESCRIPTION = 12


# Caller-facing ``match_field`` names. The stable ID and canonical name are named after the
# property that holds them in each kind; every other field has one name.
_FIELD_NAMES: dict[SearchField, str] = {
    SearchField.SYNONYM: "synonym",
    SearchField.TAG: "tag",
    SearchField.QUALIFIED_NAME: "qualified_name",
    SearchField.ACCESSOR: "accessor",
    SearchField.DATASET_COLUMNS: "dataset_columns",
    SearchField.ENTITY_EXPRESSION: "entity_expression",
    SearchField.ENTITY_METADATA: "entity_metadata",
    SearchField.DESCRIPTION: "description",
    SearchField.VALUE_DESCRIPTION: "value_description",
    SearchField.COLUMN: "column_name",
}
_KIND_FIELD_NAMES: dict[tuple[SearchKind, SearchField], str] = {
    ("dataset", SearchField.STABLE_ID): "node_id",
    ("dataset", SearchField.CANONICAL_NAME): "display_name",
    ("entity_definition", SearchField.STABLE_ID): "identity_id",
    ("identity", SearchField.STABLE_ID): "identity_id",
    ("identity", SearchField.CANONICAL_NAME): "name",
}


def field_name(kind: SearchKind, field: SearchField) -> str:
    return _KIND_FIELD_NAMES.get((kind, field)) or _FIELD_NAMES[field]


# Values that multi-word queries can match word by word, beyond exact and prefix matches of the
# whole phrase. These are names people remember in fragments.
_WORD_MATCH_FIELDS: frozenset[tuple[SearchKind, SearchField]] = frozenset(
    {
        ("dataset", SearchField.QUALIFIED_NAME),
        ("dataset", SearchField.CANONICAL_NAME),
        ("identity", SearchField.CANONICAL_NAME),
    }
)


@dataclass(frozen=True)
class _Subject:
    kind: SearchKind
    key: str
    sort_label: str
    row: list[str | list[str] | None]
    values: tuple[tuple[SearchField, str], ...]

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
        subjects: list[_Subject] = []
        entries: set[tuple[str, int, int]] = set()

        def add_subject(
            kind: SearchKind,
            key: str,
            label: str,
            row: list[str | list[str] | None],
            fields: Iterable[tuple[SearchField, str]],
        ) -> tuple[int, tuple[tuple[SearchField, str], ...]]:
            ordinal = len(subjects)
            values: list[tuple[SearchField, str]] = []
            for field, value in fields:
                terms = index_terms(value)
                if not terms:
                    continue
                for term in terms:
                    entries.add((term, ordinal, len(values)))
                values.append((field, value))
            subjects.append(
                _Subject(
                    kind=kind,
                    key=key,
                    sort_label=normalize_term(label),
                    row=row,
                    values=tuple(values),
                )
            )
            return ordinal, subjects[ordinal].values

        for identity in sorted(snapshot.logical_identities, key=lambda item: item.identity_id):
            add_subject(
                "identity",
                identity.identity_id,
                identity.name,
                [identity.identity_id, identity.name],
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
                "dataset",
                node.node_id,
                node.descriptor.display_name,
                [node.node_id, node.descriptor.display_name, node.unknown_fields()],
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
                expression = (
                    definition.entity_expression[0] if definition.entity_expression else None
                )
                add_subject(
                    "entity_definition",
                    key,
                    expression or definition.identity_id,
                    [
                        key,
                        expression,
                        node.node_id,
                        definition.identity_id,
                        list(definition.dataset_columns),
                        definition.unknown_fields(),
                    ],
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
                key = f"{node.node_id}|column|{column.name}"
                add_subject(
                    "column",
                    key,
                    column.name,
                    [key, node.node_id, column.name],
                    [
                        (SearchField.COLUMN, column.name),
                        (SearchField.DESCRIPTION, descriptive_text(column.description)),
                        (
                            SearchField.VALUE_DESCRIPTION,
                            descriptive_text(column.value_description),
                        ),
                        *((SearchField.SYNONYM, synonym) for synonym in column.synonyms),
                    ],
                )

        self._subjects = tuple(subjects)
        self._trie = _record_trie(entries)

    def search(
        self,
        query: str,
        limit: int = 50,
        kinds: Iterable[SearchKind] | None = None,
    ) -> tuple[str, list[SearchGroup], bool]:
        """Return one group per selected kind, each with subject rows and match rows.

        Each subject value keeps its best match: exact, then prefix, then, for a multi-word query
        and a value in ``_WORD_MATCH_FIELDS``, phrase, then all_words. Subjects are ordered by
        their best match, then normalized label and key; ``limit`` applies per kind.
        """
        selected = [kind for kind in SEARCH_KINDS if kinds is None or kind in set(kinds)]
        normalized = normalize_term(query)
        if not normalized:
            return normalized, [_group(kind, [], False) for kind in selected], False

        best: dict[int, dict[int, tuple[int, str]]] = {}

        def consider(rank: int, term: str, ordinal: int, value_index: int) -> None:
            if self._subjects[ordinal].kind not in selected:
                return
            matches = best.setdefault(ordinal, {})
            current = matches.get(value_index)
            if current is None or (rank, term) < current:
                matches[value_index] = (rank, term)

        for ordinal, value_index in self._trie.get(normalized, []):
            consider(_EXACT, normalized, ordinal, value_index)
        for term, (ordinal, value_index) in self._trie.iteritems(normalized):
            if term != normalized:
                consider(_PREFIX, term, ordinal, value_index)

        words = normalized.split()
        if len(words) > 1:
            for ordinal, value_index in self._values_with_every_word(words, selected):
                _, value = self._subjects[ordinal].values[value_index]
                rank, term = _word_match(normalize_term(value).split(), words)
                consider(rank, term, ordinal, value_index)

        ranked: dict[SearchKind, list[tuple[int, int]]] = {kind: [] for kind in selected}
        for ordinal, matches in best.items():
            best_rank = min(rank for rank, _ in matches.values())
            ranked[self._subjects[ordinal].kind].append((best_rank, ordinal))

        groups: list[SearchGroup] = []
        any_truncated = False
        for kind in selected:
            ordered = sorted(
                ranked[kind],
                key=lambda item: (
                    item[0],
                    self._subjects[item[1]].sort_label,
                    self._subjects[item[1]].key,
                ),
            )
            truncated = len(ordered) > limit
            any_truncated = any_truncated or truncated
            groups.append(
                _group(
                    kind,
                    [(self._subjects[ordinal], best[ordinal]) for _, ordinal in ordered[:limit]],
                    truncated,
                )
            )
        return normalized, groups, any_truncated


    def _values_with_every_word(
        self,
        words: list[str],
        selected: list[SearchKind],
    ) -> set[tuple[int, int]]:
        """Return word-match values holding a word that equals or starts with each query word.

        Each value is identified by ``(subject ordinal, value index)``, so all words must occur in
        the same value of the same subject.
        """
        common: set[tuple[int, int]] | None = None
        for word in sorted(set(words), key=len, reverse=True):
            found = {
                (ordinal, value_index)
                for _, (ordinal, value_index) in self._trie.iteritems(word)
                if (common is None or (ordinal, value_index) in common)
                and self._subjects[ordinal].kind in selected
                and (
                    self._subjects[ordinal].kind,
                    self._subjects[ordinal].values[value_index][0],
                )
                in _WORD_MATCH_FIELDS
            }
            common = found
            if not common:
                break
        return common or set()


def _word_match(value_words: list[str], query_words: list[str]) -> tuple[int, str]:
    """Rank a value that holds every query word: phrase when consecutive and in order."""
    width = len(query_words)
    for start in range(len(value_words) - width + 1):
        window = value_words[start : start + width]
        if all(word.startswith(query) for word, query in zip(window, query_words)):
            return _PHRASE, " ".join(window)
    matched = [
        next(word for word in value_words if word.startswith(query)) for query in query_words
    ]
    return _ALL_WORDS, " ".join(matched)


def _record_trie(entries: set[tuple[str, int, int]]) -> marisa_trie.RecordTrie:
    return marisa_trie.RecordTrie(
        _RECORD_FORMAT,
        [(term, (ordinal, value_index)) for term, ordinal, value_index in sorted(entries)],
        order=marisa_trie.LABEL_ORDER,
    )


def _group(
    kind: SearchKind,
    subjects: list[tuple[_Subject, dict[int, tuple[int, str]]]],
    truncated: bool,
) -> SearchGroup:
    match_rows: list[list[str]] = []
    for subject, matches in subjects:
        for value_index, (rank, term) in sorted(
            matches.items(),
            key=lambda item: (item[1][0], subject.values[item[0]][0], item[0]),
        ):
            field, value = subject.values[value_index]
            match_rows.append(
                [subject.key, _MATCH_TYPES[rank], field_name(kind, field), term, value]
            )
    return SearchGroup(
        kind=kind,
        truncated=truncated,
        subject_row_header=SUBJECT_ROW_HEADERS[kind],
        subject_rows=[subject.row for subject, _ in subjects],
        match_row_header=MATCH_ROW_HEADER,
        match_rows=match_rows,
    )


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
