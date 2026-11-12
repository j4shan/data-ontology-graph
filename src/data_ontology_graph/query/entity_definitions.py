"""Entity-definition discovery over memberships, without relationship derivation."""

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from heapq import nsmallest

from data_ontology_graph.model.dataset import DefinitionKey
from data_ontology_graph.model.derivation import RelationshipIndex
from data_ontology_graph.model.enums import EntityUniverse


@dataclass
class EntityDefinitionDiscovery:
    memberships: RelationshipIndex
    identity_id: str
    primary_by_dataset: dict[str, list[DefinitionKey]]
    node_ids: list[str]

    @property
    def primary_definition_count(self) -> int:
        return sum(len(self.primary_by_dataset[node_id]) for node_id in self.node_ids)

    def histogram(self, check_cancelled: Callable[[], None]) -> tuple[list[dict], int]:
        definitions: Counter[str] = Counter()
        datasets: Counter[str] = Counter()
        for node_id in self.node_ids:
            check_cancelled()
            identities = []
            for key in self.memberships.by_dataset[node_id]:
                check_cancelled()
                if key.identity_id != self.identity_id:
                    identities.append(key.identity_id)
            definitions.update(identities)
            datasets.update(set(identities))
        top = nsmallest(20, definitions, key=lambda identity: (-definitions[identity], identity))
        return [
            {"identity_id": identity, "entity_definition_count": definitions[identity],
             "dataset_count": datasets[identity]}
            for identity in top
        ], len(definitions)

    def page_definitions(
        self, node_ids: list[str], targets: list[str], check_cancelled: Callable[[], None],
    ) -> list[DefinitionKey]:
        target_entities = set(targets) - {self.identity_id}
        selected = []
        for node_id in node_ids:
            primary = set(self.primary_by_dataset[node_id])
            for key in self.memberships.by_dataset[node_id]:
                check_cancelled()
                if key in primary or key.identity_id in target_entities:
                    selected.append(key)
        return selected


def discover_entity_definitions(
    memberships: RelationshipIndex,
    identity_id: str,
    entity_universe: list[EntityUniverse] | None,
    target_identity_ids: list[str],
    check_cancelled: Callable[[], None],
) -> EntityDefinitionDiscovery:
    universes = set(entity_universe) if entity_universe is not None else None
    primary: dict[str, list[DefinitionKey]] = defaultdict(list)
    for key in memberships.by_identity.get(identity_id, ()):
        check_cancelled()
        if universes is None or memberships.definitions[key].entity_universe in universes:
            primary[key.node_id].append(key)
    selected = set(primary)
    # Start with shorter postings; every identity is considered at most once.
    for target in sorted(target_identity_ids, key=lambda entity: len(memberships.by_identity.get(entity, ()))):
        if not selected:
            break
        matching = set()
        for key in memberships.by_identity.get(target, ()):
            check_cancelled()
            if key.node_id in selected:
                matching.add(key.node_id)
        selected.intersection_update(matching)
    return EntityDefinitionDiscovery(memberships, identity_id, dict(primary), sorted(selected))
