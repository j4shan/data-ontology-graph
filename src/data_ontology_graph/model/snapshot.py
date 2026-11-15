from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from data_ontology_graph.model import ids
from data_ontology_graph.model.dataset import DatasetNode, duplicate_accessor_messages
from data_ontology_graph.model.derivation import MembershipIndex
from data_ontology_graph.model.entity_relationship import (
    EntityRelationship,
    EntityRelationshipIndex,
    duplicate_pair_messages,
)
from data_ontology_graph.model.intermediary import LogicalIdentity
from data_ontology_graph.model.relationship import JoinAnnotation




class GraphSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
        description="The UTC build time to the second; it identifies the published data.",
    )
    logical_identities: list[LogicalIdentity] = Field(default_factory=list)
    nodes: list[DatasetNode]
    annotations: list[JoinAnnotation] = Field(default_factory=list)
    entity_relationships: list[EntityRelationship] = Field(default_factory=list)
    _nodes_by_id: dict[str, DatasetNode] = PrivateAttr()
    _memberships: MembershipIndex = PrivateAttr()
    _entity_relationships: EntityRelationshipIndex = PrivateAttr()
    _column_ordinals: dict[tuple[str, str], int] = PrivateAttr()

    @model_validator(mode="after")
    def validate_graph(self) -> "GraphSnapshot":
        ids = [node.node_id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("node_id values must be unique")
        duplicates = duplicate_accessor_messages(self.nodes)
        if duplicates:
            raise ValueError("; ".join(duplicates))
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
        for relationship in self.entity_relationships:
            unknown = sorted(set(relationship.endpoints) - known_identities)
            if unknown:
                raise ValueError(
                    f"cross-entity relationship {list(relationship.endpoints)} references unknown "
                    f"logical entities {unknown}"
                )
        duplicates = duplicate_pair_messages(self.entity_relationships)
        if duplicates:
            raise ValueError("; ".join(duplicates))
        self._entity_relationships = EntityRelationshipIndex(self.entity_relationships)
        self._nodes_by_id = {node.node_id: node for node in sorted(self.nodes, key=lambda item: item.node_id)}
        self._memberships = MembershipIndex(self._nodes_by_id)
        self._column_ordinals = {
            key: position
            for position, key in enumerate(
                sorted((node.node_id, column.name) for node in self.nodes for column in node.columns),
                start=1,
            )
        }
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
    def memberships(self) -> MembershipIndex:
        return self._memberships

    @property
    def entity_relationship_index(self) -> EntityRelationshipIndex:
        """Cross-entity relationship adjacency, built once at load (system design 3.4.4)."""
        return self._entity_relationships

    @property
    def nodes_by_id(self) -> dict[str, DatasetNode]:
        """Dataset nodes by ``node_id``, built once at load."""
        return self._nodes_by_id

    def column_id(self, node_id: str, name: str) -> str:
        """The snapshot-local ID of a dataset's column (system design 3.6.1)."""
        return ids.format_id(ids.COLUMN, self._column_ordinals[(node_id, name)])

    def annotation_map(self) -> dict[str, JoinAnnotation]:
        return {annotation.edge_id: annotation for annotation in self.annotations}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def snapshot_version(moment: datetime | None = None) -> str:
    """The snapshot version for a build at `moment` (default now): UTC, second resolution."""
    return (moment or now_utc()).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
