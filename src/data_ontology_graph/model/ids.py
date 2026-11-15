"""Snapshot-local IDs (system design 3.6).

An entity definition, column, or cross-entity relationship is numbered from 1 in ascending order
of its natural key, and written as a one-letter kind prefix and that decimal ordinal: ``D12``,
``C3``, ``X1``. A relationship between entity definitions is not stored, so its ``edge_id`` joins
its endpoints' IDs: ``D12-D40``. IDs are built only from governed parts, so they never depend on
contributor-written text, and they are valid only in the snapshot that assigned them.
"""

import re

DEFINITION = "D"
COLUMN = "C"
ENTITY_RELATIONSHIP = "X"

_ORDINAL = r"[1-9][0-9]{0,17}"
"""A decimal ordinal from 1 without leading zeros, short enough to always convert to an int."""
_EDGE = re.compile(rf"{DEFINITION}({_ORDINAL})-{DEFINITION}({_ORDINAL})")


def format_id(prefix: str, ordinal: int) -> str:
    if ordinal < 1:
        raise ValueError("ordinals start at 1")
    return f"{prefix}{ordinal}"


def ordinal_of(prefix: str, text: str) -> int | None:
    """The ordinal of a canonical ``<prefix><ordinal>`` ID, else None."""
    match = re.fullmatch(rf"{re.escape(prefix)}({_ORDINAL})", text)
    return int(match.group(1)) if match else None


def edge_id(left: int, right: int) -> str:
    """The relationship ID of two definition ordinals, in ascending order."""
    low, high = sorted((left, right))
    if low == high:
        raise ValueError("a relationship joins two distinct entity definitions")
    return f"{format_id(DEFINITION, low)}-{format_id(DEFINITION, high)}"


def edge_ordinals(text: str) -> tuple[int, int] | None:
    """The two definition ordinals of a canonical ``D<i>-D<j>`` with ``i < j``, else None."""
    match = _EDGE.fullmatch(text)
    if not match:
        return None
    left, right = int(match.group(1)), int(match.group(2))
    return (left, right) if left < right else None


def order(text: str) -> tuple[int, int]:
    """Sort key of a relationship ID: its definition ordinals, compared numerically."""
    ordinals = edge_ordinals(text)
    if ordinals is None:
        raise ValueError(f"not a relationship ID: {text!r}")
    return ordinals
