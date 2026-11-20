from enum import Enum


UNKNOWN_TOKEN = "unknown"


class Multiplicity(str, Enum):
    ONE_TO_ONE = "1:1"
    ONE_TO_MANY = "1:many"
    MANY_TO_ONE = "many:1"
    MANY_TO_MANY = "many:many"
    UNKNOWN = UNKNOWN_TOKEN

    def mirrored(self) -> "Multiplicity":
        """The same multiplicity read in the opposite direction."""
        if self is Multiplicity.ONE_TO_MANY:
            return Multiplicity.MANY_TO_ONE
        if self is Multiplicity.MANY_TO_ONE:
            return Multiplicity.ONE_TO_MANY
        return self


class MatchExistence(str, Enum):
    ALWAYS = "always"
    OPTIONAL = "optional"
    UNKNOWN = UNKNOWN_TOKEN


class EntityUniverse(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = UNKNOWN_TOKEN


class Unknown(str, Enum):
    """Explicit unknown for a structured claim, such as a grain, that has no enum of its own."""

    UNKNOWN = UNKNOWN_TOKEN

