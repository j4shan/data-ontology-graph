"""Cross-entity relationships between logical entities (`product/graph-model.md#3.9`).

A cross-entity relationship states in descriptive text how two registered logical entities relate
in the business. It carries no typed claims and no dataset references, and it never alters a
relationship between entity definitions.
"""

from collections.abc import Iterable
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EntityRelationship(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoints: tuple[Annotated[str, Field(min_length=1)], Annotated[str, Field(min_length=1)]] = Field(
        description=(
            "The unordered pair of logical entity IDs, in ascending lexical order. Both may name "
            "the same logical entity."
        ),
    )
    descriptions: list[str] = Field(
        min_length=1,
        description="One nonblank, distinct description per way the two logical entities relate.",
    )

    @field_validator("endpoints")
    @classmethod
    def endpoints_must_be_ordered(cls, value: tuple[str, str]) -> tuple[str, str]:
        if any(not endpoint.strip() for endpoint in value):
            raise ValueError("endpoints must not be blank")
        if value[0] > value[1]:
            raise ValueError("endpoints must be in ascending lexical order")
        return value

    @field_validator("descriptions")
    @classmethod
    def descriptions_must_be_distinct(cls, value: list[str]) -> list[str]:
        if any(not description.strip() for description in value):
            raise ValueError("descriptions must not be blank")
        if len(value) != len(set(value)):
            raise ValueError("descriptions must be distinct within one cross-entity relationship")
        return value


def duplicate_pair_messages(relationships: Iterable[EntityRelationship]) -> list[str]:
    """One message per endpoint pair listed more than once."""
    seen: set[tuple[str, str]] = set()
    messages: list[str] = []
    for relationship in relationships:
        if relationship.endpoints in seen:
            messages.append(
                f"cross-entity relationship {list(relationship.endpoints)} is listed more than once"
            )
        seen.add(relationship.endpoints)
    return messages


class EntityRelationshipIndex:
    """Adjacency from each logical entity to each related logical entity and their relationship.

    Each relationship is one object referenced under both endpoints, or once for a self pair
    (system design 3.4.4).
    """

    def __init__(self, relationships: Iterable[EntityRelationship]) -> None:
        adjacency: dict[str, dict[str, EntityRelationship]] = {}
        count = 0
        for relationship in relationships:
            left, right = relationship.endpoints
            adjacency.setdefault(left, {})[right] = relationship
            adjacency.setdefault(right, {})[left] = relationship
            count += 1
        self.adjacency = {
            identity_id: dict(sorted(related.items()))
            for identity_id, related in sorted(adjacency.items())
        }
        self.relationship_count = count

    def related(self, identity_id: str) -> dict[str, EntityRelationship]:
        """Related logical entities of ``identity_id`` in ascending ID order."""
        return self.adjacency.get(identity_id, {})

    def between(self, left: str, right: str) -> EntityRelationship | None:
        return self.adjacency.get(left, {}).get(right)
