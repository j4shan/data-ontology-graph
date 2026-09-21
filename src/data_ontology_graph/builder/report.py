from pydantic import BaseModel


class ExplicitBuildReport(BaseModel):
    node_count: int
    edge_count: int
