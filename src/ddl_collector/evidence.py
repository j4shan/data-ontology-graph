"""Source-independent evidence records.

Evidence classes follow the YAML preparation requirements: ``S`` is a static resource such as
DDL or a description file, and ``D`` is an observation from read-only inspection of the data.
Evidence supports proposals and survey questions; it never establishes business meaning alone.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ddl_collector.config import SourceRef


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceRef(EvidenceModel):
    kind: Literal["S", "D"]
    source: str
    location: str

    def label(self) -> str:
        return f"{self.kind}: {self.source} {self.location}"


class ColumnEvidence(EvidenceModel):
    name: str
    declared_type: str = ""
    not_null: bool = False
    primary_key_position: int = 0
    description: str = ""
    value_description: str = ""
    synonyms: list[str] = Field(default_factory=list)
    null_count: int | None = None
    distinct_count: int | None = None
    refs: list[EvidenceRef] = Field(default_factory=list)


class KeyEvidence(EvidenceModel):
    kind: Literal["primary", "unique"]
    columns: list[str]
    duplicate_groups: int | None = None
    refs: list[EvidenceRef] = Field(default_factory=list)


class ForeignKeyEvidence(EvidenceModel):
    columns: list[str]
    referenced_table: str
    referenced_columns: list[str]
    child_null_rows: int | None = None
    orphan_rows: int | None = None
    unreferenced_parent_rows: int | None = None
    max_children_per_parent: int | None = None
    refs: list[EvidenceRef] = Field(default_factory=list)


class TableEvidence(EvidenceModel):
    name: str
    schema_name: str = "main"
    row_count: int | None = None
    columns: list[ColumnEvidence]
    keys: list[KeyEvidence] = Field(default_factory=list)
    foreign_keys: list[ForeignKeyEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def primary_key(self) -> KeyEvidence | None:
        return next((key for key in self.keys if key.kind == "primary"), None)

    def column_names(self) -> list[str]:
        return [column.name for column in self.columns]


class SourceEvidence(EvidenceModel):
    family: str
    catalog: str
    source_files: dict[str, str]
    accessor_schema_id: str
    tables: list[TableEvidence]
    accessor_properties: dict[str, dict[str, Any]] = Field(default_factory=dict)

    def table(self, name: str) -> TableEvidence:
        for table in self.tables:
            if table.name == name:
                return table
        raise KeyError(name)


class SourceFamily(Protocol):
    """A data-source family adapter: one per family, such as SQLite."""

    name: str
    accessor_schema_id: str

    def collect(self, ref: SourceRef, source_files: dict[str, str]) -> SourceEvidence:
        """Read the source read-only and return its structured evidence."""
        ...
