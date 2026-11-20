"""Cross-entity relationships between logical entities (`product/graph-model.md#3.9`).

A cross-entity relationship states in descriptive text how two registered logical entities relate
in the business, with one stated multiplicity and match existence for the pair (3.14, 3.15). It
carries no dataset references. Its claims are never derived from, and never alter, a relationship
between entity definitions or its claims (3.12).
"""

from collections.abc import Iterable
from typing import Annotated, ClassVar, NamedTuple

from pydantic import Field, field_validator

from data_ontology_graph.model import ids
from data_ontology_graph.model.claims import ClaimModel, is_unknown
from data_ontology_graph.model.enums import MatchExistence, Multiplicity


class DirectedClaims(NamedTuple):
    """Cross-entity relationship claims read from one of its logical entities."""

    multiplicity: Multiplicity
    match_existence: MatchExistence
    reverse_match_existence: MatchExistence

    def unknown_fields(self) -> list[str]:
        return sorted(name for name, value in self._asdict().items() if is_unknown(value))


class EntityRelationship(ClaimModel):
    claim_fields: ClassVar[tuple[str, ...]] = (
        "multiplicity", "match_existence.0", "match_existence.1",
    )

    endpoints: tuple[Annotated[str, Field(min_length=1)], Annotated[str, Field(min_length=1)]] = Field(
        description=(
            "The unordered pair of logical entity IDs, in ascending lexical order. Both may name "
            "the same logical entity."
        ),
    )
    multiplicity: Multiplicity = Field(
        description=(
            "Multiplicity for the pair, read from the first endpoint to the second; the reverse "
            "direction has the mirrored value. For a self pair the first endpoint is the subject "
            "of the descriptions."
        ),
    )
    match_existence: tuple[MatchExistence, MatchExistence] = Field(
        description=(
            "Match existence for each endpoint, in endpoint order: whether every instance of that "
            "logical entity relates to at least one instance of the other."
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

    def read_from(self, identity_id: str) -> DirectedClaims:
        """The claims read from ``identity_id`` toward the other endpoint.

        A self pair, and the first endpoint, read the claims as stated; the second endpoint reads
        the mirrored multiplicity and the swapped match existence values.
        """
        first, second = self.match_existence
        if identity_id == self.endpoints[0]:
            return DirectedClaims(self.multiplicity, first, second)
        if identity_id == self.endpoints[1]:
            return DirectedClaims(self.multiplicity.mirrored(), second, first)
        raise ValueError(f"{identity_id!r} is not an endpoint of {list(self.endpoints)}")


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
        self._ordinals = {
            pair: position
            for position, pair in enumerate(
                sorted({tuple(sorted((left, right))) for left, related in self.adjacency.items()
                        for right in related}),
                start=1,
            )
        }

    def related(self, identity_id: str) -> dict[str, EntityRelationship]:
        """Related logical entities of ``identity_id`` in ascending ID order."""
        return self.adjacency.get(identity_id, {})

    def relationship_id(self, left: str, right: str) -> str:
        """The snapshot-local ID of the cross-entity relationship between two logical entities."""
        return ids.format_id(ids.ENTITY_RELATIONSHIP, self._ordinals[tuple(sorted((left, right)))])

    def between(self, left: str, right: str) -> EntityRelationship | None:
        return self.adjacency.get(left, {}).get(right)
