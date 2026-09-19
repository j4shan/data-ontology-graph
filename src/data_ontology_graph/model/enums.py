from enum import Enum


class TableRole(str, Enum):
    FACT = "fact"
    DIMENSION = "dimension"
    BRIDGE = "bridge"
    AGGREGATE = "aggregate"
    UNKNOWN = "unknown"


class Additivity(str, Enum):
    FULLY_ADDITIVE = "fully_additive"
    SEMI_ADDITIVE = "semi_additive"
    NON_ADDITIVE = "non_additive"
    DIMENSION = "dimension"
    UNKNOWN = "unknown"


class DatasetLayer(str, Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"


class KeyKind(str, Enum):
    SURROGATE = "surrogate"
    NATURAL = "natural"
    DURABLE = "durable"
    DEGENERATE = "degenerate"


class GrainProvenance(str, Enum):
    DECLARED = "declared"
    INFERRED_FROM_PRIMARY_KEY = "inferred_from_primary_key"


class Participation(str, Enum):
    TOTAL = "total"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class Precedence(str, Enum):
    INFERRED = "inferred"
    DECLARED = "declared"


class Cardinality(str, Enum):
    ONE_TO_ONE = "1:1"
    N_TO_ONE = "N:1"
    ONE_TO_N = "1:N"
    M_TO_N = "M:N"
