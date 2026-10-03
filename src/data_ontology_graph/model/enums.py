from enum import Enum


UNKNOWN_TOKEN = "unknown"


class Cardinality(str, Enum):
    ONE_TO_ONE = "1:1"
    N_TO_ONE = "N:1"
    ONE_TO_N = "1:N"
    M_TO_N = "M:N"
    UNKNOWN = UNKNOWN_TOKEN


class Multiplicity(str, Enum):
    ONE_TO_ONE = "1:1"
    ONE_TO_MANY = "1:many"
    MANY_TO_ONE = "many:1"
    MANY_TO_MANY = "many:many"
    UNKNOWN = UNKNOWN_TOKEN


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

