from datetime import datetime, timezone
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field, model_validator

from data_ontology_graph.model.dataset import DatasetNode
from data_ontology_graph.model.intermediary import LogicalIdentity
from data_ontology_graph.model.relationship import (
    JoinAnnotation,
    JoinRelationship,
)


SNAPSHOT_VERSION = "4.0"


def schema_fingerprint() -> str:
    payload = "".join(
        [
            DatasetNode.model_json_schema().__str__(),
            LogicalIdentity.model_json_schema().__str__(),
            JoinRelationship.model_json_schema().__str__(),
            JoinAnnotation.model_json_schema().__str__(),
        ]
    )
    return sha256(payload.encode()).hexdigest()[:16]


class GraphSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = SNAPSHOT_VERSION
    schema_fingerprint: str | None = None
    built_at: datetime
    logical_identities: list[LogicalIdentity] = Field(default_factory=list)
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
        identity_ids = [identity.identity_id for identity in self.logical_identities]
        if len(identity_ids) != len(set(identity_ids)):
            raise ValueError("logical identity_id values must be unique")
        definitions = {
            key
            for node in self.nodes
            for key in node.entity_definition_map()
        }
        known_identities = set(identity_ids)
        for node in self.nodes:
            for definition in node.entity_definitions:
                if definition.identity_id not in known_identities:
                    raise ValueError(
                        f"node {node.node_id} references unknown logical identity "
                        f"{definition.identity_id}"
                    )
        for edge in self.edges:
            for endpoint in (edge.endpoint_a, edge.endpoint_b):
                if endpoint.node_id not in nodes:
                    raise ValueError(
                        f"edge {edge.edge_id} references unknown dataset {endpoint.node_id}"
                    )
            if edge.endpoint_a.identity_id or edge.endpoint_b.identity_id:
                if edge.endpoint_a.identity_key() not in definitions:
                    raise ValueError(
                        f"edge {edge.edge_id} endpoint_a does not resolve to an entity definition"
                    )
                if edge.endpoint_b.identity_key() not in definitions:
                    raise ValueError(
                        f"edge {edge.edge_id} endpoint_b does not resolve to an entity definition"
                    )
                if edge.endpoint_a.identity_id != edge.endpoint_b.identity_id:
                    raise ValueError(
                        f"edge {edge.edge_id} endpoints use different logical identities"
                    )
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
