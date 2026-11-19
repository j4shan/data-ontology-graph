import json
from collections.abc import Iterable

from pydantic import BaseModel, Field

from data_ontology_graph.model.claims import ClaimModel
from data_ontology_graph.model.dataset import ACCESSOR_SOFT_LIMIT, DatasetNode
from data_ontology_graph.model.intermediary import IntermediaryDefinition


class ExplicitBuildReport(BaseModel):
    node_count: int
    entity_definition_count: int
    entity_relationship_count: int = 0
    unknown_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def unknown_field_locations(definition: IntermediaryDefinition) -> list[str]:
    """Locate unknown input claims without enumerating implicit relationships."""
    locations: list[str] = []
    for node in sorted(definition.nodes, key=lambda item: item.node_id):
        # JSON keeps free-text node IDs, logical entity IDs, and column names unambiguous.
        node_location = f"nodes[{_json(node.node_id)}]"
        locations.extend(_locations(node, node_location))
        for entity in node.entity_definitions:
            key = _json([entity.identity_id, entity.dataset_columns])
            locations.extend(_locations(entity, f"{node_location}.entity_definitions[{key}]"))
    for relationship in definition.runtime_entity_relationships():
        location = f"entity_relationships[{_json(list(relationship.endpoints))}]"
        locations.extend(_locations(relationship, location))
    return locations


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _locations(subject: ClaimModel, location: str) -> list[str]:
    return [f"{location}.{path}" for path in subject.unknown_fields()]


def accessor_warnings(nodes: Iterable[DatasetNode]) -> list[str]:
    """Warn about each accessor longer than the soft limit; the build continues (graph-model 2.8)."""
    warnings: list[str] = []
    for node in sorted(nodes, key=lambda item: item.node_id):
        length = len(node.accessor.canonical_json())
        if length > ACCESSOR_SOFT_LIMIT:
            warnings.append(
                f"nodes[{node.node_id}].accessor: {length} characters exceeds the "
                f"{ACCESSOR_SOFT_LIMIT}-character soft limit"
            )
    return warnings
