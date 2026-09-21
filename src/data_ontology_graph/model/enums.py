from enum import Enum


class Cardinality(str, Enum):
    ONE_TO_ONE = "1:1"
    N_TO_ONE = "N:1"
    ONE_TO_N = "1:N"
    M_TO_N = "M:N"
    UNKNOWN = "unknown"


class Multiplicity(str, Enum):
    ONE_TO_ONE = "1:1"
    ONE_TO_MANY = "1:many"
    MANY_TO_ONE = "many:1"
    MANY_TO_MANY = "many:many"
    UNKNOWN = "unknown"


class MatchExistence(str, Enum):
    ALWAYS = "always"
    OPTIONAL = "optional"
    UNKNOWN = "unknown"
