from enum import Enum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from data_ontology_graph.model.enums import UNKNOWN_TOKEN


def is_unknown(value: object) -> bool:
    """Return whether a typed claim value is the explicit unknown state."""
    return isinstance(value, Enum) and value.value == UNKNOWN_TOKEN


class ClaimModel(BaseModel):
    """Base for objects whose typed claims may hold an explicit ``unknown`` value.

    Subclasses name their claim field paths. Descriptive text is free text and is never a claim.
    """

    model_config = ConfigDict(extra="forbid")

    claim_fields: ClassVar[tuple[str, ...]] = ()

    def unknown_fields(self) -> list[str]:
        return sorted(path for path in self.claim_fields if is_unknown(self.claim_value(path)))

    def claim_value(self, path: str) -> object:
        value: object = self
        for part in path.split("."):
            value = getattr(value, part)
        return value
