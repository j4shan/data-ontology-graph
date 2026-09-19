from pydantic import BaseModel


class InferenceReport(BaseModel):
    declared_edges: int = 0
    inferred_edges: int = 0
    unresolved_declared: int = 0
    self_referential: int = 0
    total: int = 0
