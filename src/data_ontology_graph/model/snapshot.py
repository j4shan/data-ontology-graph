from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from data_ontology_graph.model.dataset import DatasetNode, duplicate_accessor_messages
from data_ontology_graph.model.derivation import RelationshipIndex, RelationshipSequence
from data_ontology_graph.model.intermediary import LogicalIdentity
from data_ontology_graph.model.relationship import (
    JoinAnnotation,
    JoinRelationship,
)




class GraphSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
        description="The UTC build time to the second; it identifies the published data.",
    )
    logical_identities: list[LogicalIdentity] = Field(default_factory=list)
    nodes: list[DatasetNode]
    legacy_edges: list[JoinRelationship] | None = Field(
        default=None, validation_alias="edges", exclude=True, repr=False,
    )
    annotations: list[JoinAnnotation] = Field(default_factory=list)
    _memberships: RelationshipIndex = PrivateAttr()

    @model_validator(mode="after")
    def validate_graph(self) -> "GraphSnapshot":
        ids = [node.node_id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("node_id values must be unique")
        duplicates = duplicate_accessor_messages(self.nodes)
        if duplicates:
            raise ValueError("; ".join(duplicates))
        nodes = {node.node_id: node for node in self.nodes}
        identity_ids = [identity.identity_id for identity in self.logical_identities]
        if len(identity_ids) != len(set(identity_ids)):
            raise ValueError("logical entity ID (identity_id) values must be unique")
        known_identities = set(identity_ids)
        for node in self.nodes:
            for definition in node.entity_definitions:
                if definition.identity_id not in known_identities:
                    raise ValueError(
                        f"node {node.node_id} references unknown logical entity "
                        f"{definition.identity_id}"
                    )
        self._memberships = RelationshipIndex(self.nodes)
        edge_ids = set()
        for edge in self.legacy_edges or ():
            if edge.edge_id in edge_ids:
                raise ValueError("edge_id values must be unique")
            edge_ids.add(edge.edge_id)
            for endpoint in (edge.endpoint_a, edge.endpoint_b):
                if endpoint.node_id not in nodes:
                    raise ValueError(
                        f"edge {edge.edge_id} references unknown dataset {endpoint.node_id}"
                    )
                if endpoint.identity_key() not in self._memberships.definitions:
                    raise ValueError(
                        f"edge {edge.edge_id} endpoint does not resolve to an entity definition"
                    )
            expected = self._memberships.pair(
                edge.endpoint_a.identity_key(), edge.endpoint_b.identity_key(),
            )
            if edge != expected:
                raise ValueError(f"edge {edge.edge_id} claims disagree with its entity definitions")
        self.legacy_edges = None
        annotated = set()
        for annotation in self.annotations:
            if annotation.edge_id in annotated:
                raise ValueError("annotation edge_id values must be unique")
            annotated.add(annotation.edge_id)
            try:
                self._memberships.resolve(annotation.edge_id)
            except KeyError:
                raise ValueError(f"annotation references unknown edge {annotation.edge_id}")
        return self

    @property
    def memberships(self) -> RelationshipIndex:
        return self._memberships

    @property
    def edges(self) -> RelationshipSequence:
        """An opt-in view; pairwise records are not part of snapshot serialization."""
        return RelationshipSequence(self._memberships)

    def node_map(self) -> dict[str, DatasetNode]:
        return {node.node_id: node for node in self.nodes}

    def annotation_map(self) -> dict[str, JoinAnnotation]:
        return {annotation.edge_id: annotation for annotation in self.annotations}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def snapshot_version(moment: datetime | None = None) -> str:
    """The snapshot version for a build at `moment` (default now): UTC, second resolution."""
    return (moment or now_utc()).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
