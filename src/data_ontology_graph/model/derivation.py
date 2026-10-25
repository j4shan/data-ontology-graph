"""Relationships derived from entity definitions.

Every two entity definitions of one logical entity are related, on different datasets or on
the same one. Their directional claims follow from the definitions' own properties.
"""

from collections import defaultdict
from collections.abc import Iterable
from itertools import combinations

from data_ontology_graph.model.dataset import DatasetNode, EntityDefinition
from data_ontology_graph.model.enums import EntityUniverse, MatchExistence, Multiplicity
from data_ontology_graph.model.relationship import (
    JoinEndpoint,
    JoinRelationship,
    RelationshipDirection,
    edge_id_for,
)


_MULTIPLICITY = {
    (True, True): Multiplicity.ONE_TO_ONE,
    (False, True): Multiplicity.MANY_TO_ONE,
    (True, False): Multiplicity.ONE_TO_MANY,
    (False, False): Multiplicity.MANY_TO_MANY,
}


def multiplicity_between(source_unique: object, target_unique: object) -> Multiplicity:
    """Multiplicity from a key with ``source_unique`` to one with ``target_unique``."""
    return _MULTIPLICITY.get((source_unique, target_unique), Multiplicity.UNKNOWN)


def derived_multiplicity(source: EntityDefinition, target: EntityDefinition) -> Multiplicity:
    """Multiplicity from ``source`` to ``target``, from the uniqueness of both."""
    return multiplicity_between(source.unique, target.unique)


def contained(source: EntityDefinition, target: EntityDefinition) -> bool | None:
    """Whether ``source``'s key values are all among ``target``'s; None when unknown."""
    if source.conforming() and target.entity_universe == EntityUniverse.COMPLETE:
        return True
    if (
        source.entity_universe == EntityUniverse.COMPLETE
        and target.entity_universe == EntityUniverse.PARTIAL
    ):
        return False
    return None


def derived_match_existence(
    source: EntityDefinition, target: EntityDefinition
) -> MatchExistence:
    """Whether every ``source`` record has a match in ``target``."""
    containment = contained(source, target)
    if source.total is False or containment is False:
        return MatchExistence.OPTIONAL
    if source.total is True and containment is True:
        return MatchExistence.ALWAYS
    return MatchExistence.UNKNOWN


def derived_direction(source: EntityDefinition, target: EntityDefinition) -> RelationshipDirection:
    return RelationshipDirection(
        multiplicity=derived_multiplicity(source, target),
        match_existence=derived_match_existence(source, target),
    )


def derive_relationships(nodes: Iterable[DatasetNode]) -> list[JoinRelationship]:
    """One relationship for every two entity definitions of the same logical entity, by edge ID."""
    by_identity: dict[str, list[tuple[str, EntityDefinition]]] = defaultdict(list)
    for node in nodes:
        for definition in node.entity_definitions:
            by_identity[definition.identity_id].append((node.node_id, definition))

    relationships = []
    for identity_id in sorted(by_identity):
        members = sorted(by_identity[identity_id], key=lambda item: item[1].key(item[0]))
        for (node_a, definition_a), (node_b, definition_b) in combinations(members, 2):
            endpoint_a = _endpoint(node_a, definition_a)
            endpoint_b = _endpoint(node_b, definition_b)
            relationships.append(
                JoinRelationship(
                    edge_id=edge_id_for(endpoint_a, endpoint_b),
                    endpoint_a=endpoint_a,
                    endpoint_b=endpoint_b,
                    a_to_b=derived_direction(definition_a, definition_b),
                    b_to_a=derived_direction(definition_b, definition_a),
                )
            )
    return sorted(relationships, key=lambda relationship: relationship.edge_id)


def _endpoint(node_id: str, definition: EntityDefinition) -> JoinEndpoint:
    return JoinEndpoint(
        node_id=node_id,
        identity_id=definition.identity_id,
        dataset_columns=definition.dataset_columns,
    )
