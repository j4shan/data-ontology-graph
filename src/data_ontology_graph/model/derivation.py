"""Logical-entity memberships and relationships derived only when consumed."""

from collections import defaultdict
from collections.abc import Mapping

from data_ontology_graph.model import ids
from data_ontology_graph.model.dataset import DatasetNode, DefinitionKey, EntityDefinition
from data_ontology_graph.model.enums import EntityUniverse, MatchExistence, Multiplicity
from data_ontology_graph.model.relationship import (
    JoinEndpoint,
    JoinRelationship,
    RelationshipDirection,
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


def step_multiplicity(source: EntityDefinition, target: EntityDefinition) -> Multiplicity:
    """Multiplicity from ``source``'s logical entity to ``target``'s on their common records.

    The two definitions are of different logical entities on one dataset (graph-model 3.16). A
    unique ``source`` puts each instance of its entity in at most one record, so it reaches at
    most one instance of ``target``'s entity: ``many:1``.
    """
    return multiplicity_between(target.unique, source.unique)


def step_match_existence(target: EntityDefinition) -> MatchExistence:
    """Whether every common record has a value of ``target``'s logical entity (graph-model 3.17)."""
    if target.total is False:
        return MatchExistence.OPTIONAL
    if target.total is True and target.conforms is True:
        return MatchExistence.ALWAYS
    return MatchExistence.UNKNOWN


def derived_direction(source: EntityDefinition, target: EntityDefinition) -> RelationshipDirection:
    return RelationshipDirection(
        multiplicity=derived_multiplicity(source, target),
        match_existence=derived_match_existence(source, target),
    )


class MembershipIndex:
    """Logical-entity memberships, one entry per entity definition.

    A relationship is derived fresh from two entity definitions when requested (graph-model 3.1).
    The index neither stores nor lists relationships, and caches none. Each definition is
    numbered from 1 in ascending key order, and a relationship's ``edge_id`` joins its
    endpoints' IDs (system design 3.3.1, 3.6.1).
    """

    def __init__(self, nodes: Mapping[str, DatasetNode]) -> None:
        self.nodes = nodes
        """Dataset nodes by ``node_id``; each holds its entity definitions."""
        self.definitions: dict[DefinitionKey, EntityDefinition] = {}
        by_identity: dict[str, list[DefinitionKey]] = defaultdict(list)
        for node in nodes.values():
            for definition in node.entity_definitions:
                key = definition.key(node.node_id)
                if key in self.definitions:
                    raise ValueError("entity definitions must be unique by identity_id and dataset_columns")
                self.definitions[key] = definition
                by_identity[definition.identity_id].append(key)
        self.by_identity = {identity: sorted(keys) for identity, keys in by_identity.items()}
        self._keys: list[DefinitionKey] = sorted(self.definitions)
        self.ordinals: dict[DefinitionKey, int] = {
            key: position for position, key in enumerate(self._keys, start=1)
        }

    @property
    def entity_definition_count(self) -> int:
        return len(self.definitions)

    @staticmethod
    def endpoint(key: DefinitionKey) -> JoinEndpoint:
        """The entity definition ``key`` as a relationship endpoint (graph-model 3.1)."""
        return JoinEndpoint(
            node_id=key.node_id, identity_id=key.identity_id, dataset_columns=list(key.dataset_columns),
        )

    def definition_id(self, key: DefinitionKey) -> str:
        """The snapshot-local ID of the entity definition ``key`` (system design 3.6.1)."""
        return ids.format_id(ids.DEFINITION, self.ordinals[key])

    def definition_keys(self, node_id: str) -> list[DefinitionKey]:
        """The dataset's entity definitions in ascending key order; KeyError for an unknown dataset."""
        node = self.nodes[node_id]
        return sorted(definition.key(node_id) for definition in node.entity_definitions)

    def degree(self, node_id: str) -> int:
        """Outgoing directed edges, counting a same-dataset relationship twice."""
        return sum(
            len(self.by_identity[definition.identity_id]) - 1
            for definition in self.nodes[node_id].entity_definitions
        )

    def edge_order(self, left: DefinitionKey, right: DefinitionKey) -> tuple[int, int]:
        """The relationship's endpoint ordinals in ascending order, its sort key."""
        if left == right or left.identity_id != right.identity_id:
            raise ValueError("a relationship requires two distinct definitions of the same logical entity")
        low, high = sorted((self.ordinals[left], self.ordinals[right]))
        return low, high

    def edge_id(self, left: DefinitionKey, right: DefinitionKey) -> str:
        return ids.edge_id(*self.edge_order(left, right))

    def resolve(self, edge_id: str) -> tuple[DefinitionKey, DefinitionKey]:
        """The canonical endpoint pair an ``edge_id`` names; KeyError when it names none."""
        ordinals = ids.edge_ordinals(edge_id)
        if ordinals is None or ordinals[1] > len(self._keys):
            raise KeyError(edge_id)
        left, right = (self._keys[ordinal - 1] for ordinal in ordinals)
        if left.identity_id != right.identity_id:
            raise KeyError(edge_id)
        return left, right

    def pair(self, left: DefinitionKey, right: DefinitionKey) -> JoinRelationship:
        a, b = sorted((left, right))
        return JoinRelationship(
            edge_id=self.edge_id(a, b),
            endpoint_a=self.endpoint(a), endpoint_b=self.endpoint(b),
            a_to_b=derived_direction(self.definitions[a], self.definitions[b]),
            b_to_a=derived_direction(self.definitions[b], self.definitions[a]),
        )

    def relationship(self, edge_id: str) -> JoinRelationship:
        """The relationship an existing ``edge_id`` names; KeyError when it names none."""
        return self.pair(*self.resolve(edge_id))
