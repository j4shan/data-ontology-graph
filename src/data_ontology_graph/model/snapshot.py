from datetime import datetime, timezone
from hashlib import sha256

from pydantic import BaseModel, Field, model_validator

from data_ontology_graph.model.dataset import DatasetNode
from data_ontology_graph.model.relationship import (
    JoinAnnotation,
    JoinRelationship,
    assert_primaries_own_edges,
)
from data_ontology_graph.model.source import S3Source, SqlDbSource


SNAPSHOT_VERSION = "2.0"


def schema_fingerprint() -> str:
    payload = "".join(
        [
            DatasetNode.model_json_schema().__str__(),
            JoinRelationship.model_json_schema().__str__(),
            JoinAnnotation.model_json_schema().__str__(),
        ]
    )
    return sha256(payload.encode()).hexdigest()[:16]


class GraphSnapshot(BaseModel):
    version: str = SNAPSHOT_VERSION
    schema_fingerprint: str | None = None
    built_at: datetime
    nodes: list[DatasetNode]
    edges: list[JoinRelationship]
    annotations: list[JoinAnnotation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph(self) -> "GraphSnapshot":
        ids = [node.node_id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("node_id values must be unique")
        edge_ids = [edge.edge_id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("edge_id values must be unique")
        nodes = {node.node_id: node for node in self.nodes}
        assert_primaries_own_edges(nodes, self.edges)
        known_edges = set(edge_ids)
        for annotation in self.annotations:
            if annotation.edge_id not in known_edges:
                raise ValueError(f"annotation references unknown edge {annotation.edge_id}")
        return self

    def node_map(self) -> dict[str, DatasetNode]:
        return {node.node_id: node for node in self.nodes}

    def annotation_map(self) -> dict[str, JoinAnnotation]:
        return {annotation.edge_id: annotation for annotation in self.annotations}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def empty_sql_db_source(database: str, table: str, dialect: str = "sqlite") -> SqlDbSource:
    return SqlDbSource(
        host="local",
        database=database,
        schema="main",
        table=table,
        dialect=dialect,
    )


# Keep S3Source imported so the discriminated union stays in schema output.
_ = S3Source
