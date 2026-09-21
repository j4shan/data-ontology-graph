from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from data_ontology_graph.model.dataset import DatasetNode, EntityDefinition
from data_ontology_graph.model.intermediary import LogicalIdentity
from data_ontology_graph.model.relationship import JoinRelationship
from data_ontology_graph.model.snapshot import GraphSnapshot
from data_ontology_graph.service.contracts import (
    DatasetDetail,
    HopDetail,
    IdentityDetail,
    PathsRequest,
    PathsResponse,
    RelationshipDetail,
    SearchRequest,
    SearchResponse,
    SnapshotInfo,
    SubgraphRequest,
    SubgraphResponse,
)
from data_ontology_graph.service.search import LexicalSearchIndex


DefinitionKey = tuple[str, str, tuple[str, ...]]


class GraphReadIndex:
    def __init__(self, snapshot: GraphSnapshot) -> None:
        self.snapshot = snapshot
        self.nodes = {node.node_id: node for node in snapshot.nodes}
        self.identities = {
            identity.identity_id: identity for identity in snapshot.logical_identities
        }
        self.definitions: dict[DefinitionKey, EntityDefinition] = {
            key: definition
            for node in snapshot.nodes
            for key, definition in node.entity_definition_map().items()
        }
        definitions_by_identity: dict[str, list[tuple[str, EntityDefinition]]] = defaultdict(list)
        for node in snapshot.nodes:
            for definition in node.entity_definitions:
                definitions_by_identity[definition.identity_id].append((node.node_id, definition))
        self.definitions_by_identity = {
            identity_id: tuple(sorted(items, key=lambda item: (item[0], item[1].dataset_columns)))
            for identity_id, items in definitions_by_identity.items()
        }
        self.edges = {edge.edge_id: edge for edge in snapshot.edges}
        adjacency: dict[str, list[JoinRelationship]] = defaultdict(list)
        for edge in snapshot.edges:
            adjacency[edge.endpoint_a.node_id].append(edge)
            adjacency[edge.endpoint_b.node_id].append(edge)
        self.adjacency = {
            node_id: tuple(sorted(edges, key=lambda item: item.edge_id))
            for node_id, edges in adjacency.items()
        }
        self.annotations = snapshot.annotation_map()
        self.search = LexicalSearchIndex(snapshot)


class GraphReadService:
    def __init__(self, snapshot: GraphSnapshot) -> None:
        self.index = GraphReadIndex(snapshot)

    def snapshot_info(self) -> SnapshotInfo:
        snapshot = self.index.snapshot
        return SnapshotInfo(
            version=snapshot.version,
            schema_fingerprint=snapshot.schema_fingerprint,
            built_at=snapshot.built_at.isoformat(),
            node_count=len(snapshot.nodes),
            edge_count=len(snapshot.edges),
            identity_count=len(snapshot.logical_identities),
        )

    def search(self, request: SearchRequest) -> SearchResponse:
        normalized, hits, truncated = self.index.search.search(request.query, request.limit)
        return SearchResponse(
            snapshot=self.snapshot_info(),
            query=request.query,
            normalized_query=normalized,
            hits=hits,
            truncated=truncated,
        )

    def get_identity(self, identity_id: str) -> IdentityDetail:
        identity = self._identity(identity_id)
        definitions = [
            self._resolved_definition(node_id, definition)
            for node_id, definition in self.index.definitions_by_identity.get(identity_id, ())
        ]
        return IdentityDetail(
            identity_id=identity.identity_id,
            name=identity.name,
            description=identity.description,
            synonyms=identity.synonyms,
            definitions=definitions,
        )

    def get_dataset(self, node_id: str) -> DatasetDetail:
        return self._dataset_detail(self._node(node_id))

    def get_relationship(self, edge_id: str) -> RelationshipDetail:
        edge = self._edge(edge_id)
        annotation = self.index.annotations.get(edge.edge_id)
        return RelationshipDetail(
            edge_id=edge.edge_id,
            identity_id=edge.endpoint_a.identity_id,
            endpoint_a=self._resolved_endpoint(edge.endpoint_a.identity_key()),
            endpoint_b=self._resolved_endpoint(edge.endpoint_b.identity_key()),
            a_to_b=edge.a_to_b.model_dump(mode="json"),
            b_to_a=edge.b_to_a.model_dump(mode="json"),
            annotation=annotation.model_dump(mode="json") if annotation else None,
        )

    def get_hops(self, node_id: str) -> list[HopDetail]:
        self._node(node_id)
        hops = []
        for edge in self.index.adjacency.get(node_id, ()):
            other = edge.opposite(node_id)
            hops.append(
                HopDetail(
                    edge_id=edge.edge_id,
                    from_node_id=node_id,
                    to_node_id=other.node_id,
                    identity_id=edge.endpoint(node_id).identity_id,
                    from_endpoint=self._resolved_endpoint(edge.endpoint(node_id).identity_key()),
                    to_endpoint=self._resolved_endpoint(other.identity_key()),
                    direction=edge.direction_from(node_id).model_dump(mode="json"),
                    reverse_direction=edge.direction_from(other.node_id).model_dump(mode="json"),
                )
            )
        return hops

    def expand_subgraph(self, request: SubgraphRequest) -> SubgraphResponse:
        seeds = list(dict.fromkeys(request.seed_node_ids))
        for seed in seeds:
            self._node(seed)

        distances = {seed: 0 for seed in seeds}
        queue = deque(seeds)
        edge_ids: set[str] = set()
        while queue:
            current = queue.popleft()
            depth = distances[current]
            if depth >= request.max_depth:
                continue
            for edge in self.index.adjacency.get(current, ()):
                other = edge.opposite(current).node_id
                edge_ids.add(edge.edge_id)
                if other not in distances:
                    distances[other] = depth + 1
                    queue.append(other)

        ordered_nodes = sorted(distances.items(), key=lambda item: (item[1], item[0]))
        selected_nodes = ordered_nodes[: request.max_nodes]
        selected_node_ids = {node_id for node_id, _ in selected_nodes}
        eligible_edge_ids = [
            edge_id
            for edge_id in sorted(edge_ids)
            if self.index.edges[edge_id].endpoint_a.node_id in selected_node_ids
            and self.index.edges[edge_id].endpoint_b.node_id in selected_node_ids
        ]
        selected_edge_ids = eligible_edge_ids[: request.max_edges]
        nodes = [
            {
                "distance": distance,
                "dataset": self.get_dataset(node_id).model_dump(mode="json"),
            }
            for node_id, distance in selected_nodes
        ]
        edges = [self.get_relationship(edge_id) for edge_id in selected_edge_ids]
        return SubgraphResponse(
            snapshot=self.snapshot_info(),
            seed_node_ids=seeds,
            max_depth=request.max_depth,
            max_nodes=request.max_nodes,
            max_edges=request.max_edges,
            nodes=nodes,
            edges=edges,
            truncated=(
                len(ordered_nodes) > request.max_nodes
                or len(eligible_edge_ids) > request.max_edges
            ),
        )

    def find_paths(
        self,
        from_node_id: str,
        to_node_id: str,
        max_hops: int = 4,
        limit: int = 50,
    ) -> PathsResponse:
        request = PathsRequest(
            from_node_id=from_node_id,
            to_node_id=to_node_id,
            max_hops=max_hops,
            limit=limit,
        )
        from_node_id = request.from_node_id
        to_node_id = request.to_node_id
        max_hops = request.max_hops
        limit = request.limit
        self._node(from_node_id)
        self._node(to_node_id)
        queue: deque[tuple[str, list[tuple[str, str, JoinRelationship]], set[str]]] = deque(
            [(from_node_id, [], {from_node_id})]
        )
        found: list[list[tuple[str, str, JoinRelationship]]] = []
        while queue:
            current, hops, seen = queue.popleft()
            if len(hops) >= max_hops:
                continue
            for edge in self.index.adjacency.get(current, ()):
                nxt = edge.opposite(current).node_id
                if nxt in seen:
                    continue
                path = [*hops, (current, nxt, edge)]
                if nxt == to_node_id:
                    found.append(path)
                else:
                    queue.append((nxt, path, seen | {nxt}))

        found.sort(
            key=lambda path: (
                len(path),
                -sum(
                    self.index.annotations.get(edge.edge_id).weight
                    if edge.edge_id in self.index.annotations
                    else 1.0
                    for _, _, edge in path
                ),
                tuple(edge.edge_id for _, _, edge in path),
            )
        )
        payloads = []
        for path in found[:limit]:
            payloads.append(
                {
                    "length": len(path),
                    "hops": [
                        {
                            "edge_id": edge.edge_id,
                            "from_node_id": source,
                            "to_node_id": target,
                            "identity_id": edge.endpoint(source).identity_id,
                            "from_endpoint": self._resolved_endpoint(
                                edge.endpoint(source).identity_key()
                            ),
                            "to_endpoint": self._resolved_endpoint(
                                edge.endpoint(target).identity_key()
                            ),
                            "direction": edge.direction_from(source).model_dump(mode="json"),
                        }
                        for source, target, edge in path
                    ],
                }
            )
        return PathsResponse(
            snapshot=self.snapshot_info(),
            from_node_id=from_node_id,
            to_node_id=to_node_id,
            paths=payloads,
            truncated=len(found) > limit,
        )

    def _identity(self, identity_id: str) -> LogicalIdentity:
        try:
            return self.index.identities[identity_id]
        except KeyError as error:
            raise KeyError(f"unknown identity {identity_id}") from error

    def _node(self, node_id: str) -> DatasetNode:
        try:
            return self.index.nodes[node_id]
        except KeyError as error:
            raise KeyError(f"unknown dataset {node_id}") from error

    def _edge(self, edge_id: str) -> JoinRelationship:
        try:
            return self.index.edges[edge_id]
        except KeyError as error:
            raise KeyError(f"unknown relationship {edge_id}") from error

    def _dataset_detail(self, node: DatasetNode) -> DatasetDetail:
        return DatasetDetail(
            node_id=node.node_id,
            descriptor=node.descriptor.model_dump(mode="json"),
            accessor=node.accessor.model_dump(mode="json", by_alias=True),
            grain=node.grain.model_dump(mode="json") if node.grain else None,
            columns=[item.model_dump(mode="json") for item in node.columns],
            entity_definitions=[
                item.model_dump(mode="json") for item in node.entity_definitions
            ],
        )

    def _resolved_definition(
        self,
        node_id: str,
        definition: EntityDefinition,
    ) -> dict[str, Any]:
        node = self._node(node_id)
        return {
            "node_id": node_id,
            "dataset": {
                "descriptor": node.descriptor.model_dump(mode="json"),
                "accessor": node.accessor.model_dump(mode="json", by_alias=True),
            },
            **definition.model_dump(mode="json"),
        }

    def _resolved_endpoint(self, key: DefinitionKey) -> dict[str, Any]:
        try:
            definition = self.index.definitions[key]
        except KeyError as error:
            raise KeyError(f"unresolved entity definition {key}") from error
        return self._resolved_definition(key[0], definition)
