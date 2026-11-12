"""Logical-entity memberships and relationships derived only when consumed."""

from collections import defaultdict
from collections.abc import Mapping

from data_ontology_graph.model.dataset import DatasetNode, DefinitionKey, EntityDefinition
from data_ontology_graph.model.enums import EntityUniverse, MatchExistence, Multiplicity
from data_ontology_graph.model.relationship import (
    JoinEndpoint,
    JoinRelationship,
    RelationshipDirection,
    edge_id_for,
    endpoint_token,
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


class RelationshipIndex:
    """Logical-entity memberships, one entry per entity definition.

    A relationship is derived fresh from two entity definitions when requested (graph-model 3.1).
    The index neither stores nor lists relationships, and caches none.
    """

    def __init__(self, nodes: Mapping[str, DatasetNode]) -> None:
        self.nodes = nodes
        """Dataset nodes by ``node_id``; each holds its entity definitions."""
        self.definitions: dict[DefinitionKey, EntityDefinition] = {}
        by_identity: dict[str, list[DefinitionKey]] = defaultdict(list)
        self._by_token: dict[str, list[DefinitionKey]] = defaultdict(list)
        for node in nodes.values():
            for definition in node.entity_definitions:
                key = definition.key(node.node_id)
                if key in self.definitions:
                    raise ValueError("entity definitions must be unique by identity_id and dataset_columns")
                self.definitions[key] = definition
                self._by_token[endpoint_token(self.endpoint(key))].append(key)
                by_identity[definition.identity_id].append(key)
        self.by_identity = {identity: sorted(keys) for identity, keys in by_identity.items()}
        self._count = sum(len(keys) * (len(keys) - 1) // 2 for keys in self.by_identity.values())

    def __len__(self) -> int:
        return self._count

    @staticmethod
    def endpoint(key: DefinitionKey) -> JoinEndpoint:
        """The entity definition ``key`` as a relationship endpoint (graph-model 3.1)."""
        return JoinEndpoint(
            node_id=key.node_id, identity_id=key.identity_id, dataset_columns=list(key.dataset_columns),
        )

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

    def edge_id(self, left: DefinitionKey, right: DefinitionKey) -> str:
        if left == right or left.identity_id != right.identity_id:
            raise ValueError("a relationship requires two distinct definitions of the same logical entity")
        return edge_id_for(self.endpoint(left), self.endpoint(right))

    def resolve(self, edge_id: str) -> tuple[DefinitionKey, DefinitionKey]:
        """Resolve an existing ID without assuming its unescaped delimiters occur only once."""
        found = None
        offset = 0
        while (position := edge_id.find("__", offset)) >= 0:
            for left in self._by_token.get(edge_id[:position], ()):
                for right in self._by_token.get(edge_id[position + 2:], ()):
                    if left < right and left.identity_id == right.identity_id:
                        if found is not None:
                            raise ValueError(f"ambiguous relationship ID {edge_id!r}")
                        found = (left, right)
            offset = position + 1
        if found is None:
            raise KeyError(edge_id)
        return found

    def pair(self, left: DefinitionKey, right: DefinitionKey) -> JoinRelationship:
        edge_id = self.edge_id(left, right)
        # The legacy ID format is unescaped: never silently select one colliding pair.
        a, b = self.resolve(edge_id)
        return JoinRelationship(
            edge_id=edge_id,
            endpoint_a=self.endpoint(a), endpoint_b=self.endpoint(b),
            a_to_b=derived_direction(self.definitions[a], self.definitions[b]),
            b_to_a=derived_direction(self.definitions[b], self.definitions[a]),
        )

    def relationship(self, edge_id: str) -> JoinRelationship:
        """The relationship an existing ``edge_id`` names; KeyError when it names none."""
        return self.pair(*self.resolve(edge_id))

