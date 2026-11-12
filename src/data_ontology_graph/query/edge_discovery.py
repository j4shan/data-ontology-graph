"""Dataset-neighbour discovery and histograms over logical-entity memberships."""

from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass
from heapq import nsmallest

from data_ontology_graph.model.dataset import DefinitionKey
from data_ontology_graph.model.derivation import MembershipIndex
from data_ontology_graph.query.neighbourhood import DirectedEdge, EdgeGroup


@dataclass
class EdgeDiscovery:
    memberships: MembershipIndex
    source_keys: list[DefinitionKey]
    connected: frozenset[str]
    targets_by_identity: dict[str, list[DefinitionKey]]

    def histogram(self) -> tuple[list[dict], int]:
        definitions: Counter[str] = Counter()
        datasets: Counter[str] = Counter()
        for node_id in self.connected:
            node = self.memberships.nodes[node_id]
            identities = [definition.identity_id for definition in node.entity_definitions]
            definitions.update(identities)
            datasets.update(set(identities))
        top = nsmallest(20, definitions, key=lambda identity: (-definitions[identity], identity))
        return [
            {"identity_id": identity, "entity_definition_count": definitions[identity],
             "dataset_count": datasets[identity]}
            for identity in top
        ], len(definitions)

    def page(self, offset: int, limit: int) -> tuple[list[EdgeGroup], bool]:
        """Page each source definition, deriving only the pairs listed on this page."""
        groups = []
        more = False
        index = self.memberships
        for source in self.source_keys:
            targets = self.targets_by_identity[source.identity_id]
            own_position = bisect_left(targets, source)
            contains_self = own_position < len(targets) and targets[own_position] == source
            count = len(targets) - int(contains_self)
            if count == 0:
                continue
            more = more or count > offset + limit
            edges = []
            for position in range(offset, min(offset + limit, count)):
                target = targets[position + int(contains_self and position >= own_position)]
                edges.append(DirectedEdge(
                    index.pair(source, target), index.endpoint(source), index.endpoint(target),
                ))
            groups.append(EdgeGroup(index.endpoint(source), count, edges))
        return groups, more


def discover_edges(
    memberships: MembershipIndex,
    node_id: str,
    identity_id: str | None,
    from_dataset_columns: list[str] | None,
    target_identity_ids: list[str],
) -> EdgeDiscovery:
    """Select the complete neighbourhood before any detail limit or pair derivation."""
    source_keys = [
        key for key in memberships.definition_keys(node_id)
        if (identity_id is None or key.identity_id == identity_id)
        and (from_dataset_columns is None or key.dataset_columns == tuple(from_dataset_columns))
    ]
    if identity_id is not None and not source_keys:
        columns = f" on {from_dataset_columns}" if from_dataset_columns else ""
        raise ValueError(f"{node_id!r} has no entity definition of {identity_id!r}{columns}")
    source_identities = {key.identity_id for key in source_keys}
    targets = {
        key.node_id for identity in source_identities for key in memberships.by_identity[identity]
    }
    for target_identity in target_identity_ids:
        targets.intersection_update(
            key.node_id for key in memberships.by_identity.get(target_identity, ())
        )
    connected = frozenset(targets - {node_id})
    return EdgeDiscovery(
        memberships, source_keys, connected,
        {identity: [key for key in memberships.by_identity[identity] if key.node_id in targets]
         for identity in source_identities},
    )
