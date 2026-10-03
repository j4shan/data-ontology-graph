from pydantic import BaseModel, Field

from data_ontology_graph.model.claims import ClaimModel
from data_ontology_graph.model.intermediary import IntermediaryDefinition


class ExplicitBuildReport(BaseModel):
    node_count: int
    edge_count: int
    unknown_fields: list[str] = Field(default_factory=list)


def unknown_field_locations(definition: IntermediaryDefinition) -> list[str]:
    """Locate every explicitly unknown claim by stable IDs in authored orientation."""
    locations: list[str] = []
    for node in sorted(definition.nodes, key=lambda item: item.node_id):
        node_location = f"nodes[{node.node_id}]"
        locations.extend(_locations(node, node_location))
        for entity in node.entity_definitions:
            key = f"{entity.identity_id}:{'+'.join(entity.dataset_columns)}"
            locations.extend(_locations(entity, f"{node_location}.entity_definitions[{key}]"))
    for edge in sorted(definition.edges, key=lambda item: item.canonical_edge_id()):
        locations.extend(_locations(edge, f"edges[{edge.canonical_edge_id()}]"))
    return locations


def _locations(subject: ClaimModel, location: str) -> list[str]:
    return [f"{location}.{path}" for path in subject.unknown_fields()]
