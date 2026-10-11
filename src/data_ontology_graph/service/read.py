from __future__ import annotations

from collections import defaultdict, deque
from threading import Event
from typing import Any

from data_ontology_graph.model.claims import ClaimModel
from data_ontology_graph.model.dataset import DatasetNode, EntityDefinition
from data_ontology_graph.model.intermediary import LogicalIdentity
from data_ontology_graph.model.enums import EntityUniverse, Multiplicity
from data_ontology_graph.model.relationship import JoinRelationship
from data_ontology_graph.model.snapshot import GraphSnapshot
from data_ontology_graph.service.contracts import (
    ConnectingSubgraphRequest,
    ConnectingSubgraphResponse,
    DatasetDetail,
    HopsRequest,
    HopsResponse,
    IdentityDetail,
    IdentityRequest,
    PathsRequest,
    PathsResponse,
    RelationshipDetail,
    SearchRequest,
    SearchResponse,
    SnapshotInfo,
    SubgraphRequest,
    SubgraphResponse,
)
from data_ontology_graph.query.connecting import connecting_tree
from data_ontology_graph.service.search import LexicalSearchIndex
from data_ontology_graph.service.tables import (
    COLUMN_HEADER,
    DATASET_DETAIL_HEADER,
    DATASET_HEADER,
    DEFINITION_HEADER,
    PATH_STEP_HEADER,
    RELATIONSHIP_HEADER,
    STEP_HEADER,
    SUBGRAPH_DATASET_HEADER,
    ResponseFormat,
    collection,
)


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
    def __init__(self, snapshot: GraphSnapshot, *, max_connecting_datasets: int = 16) -> None:
        if max_connecting_datasets < 2:
            raise ValueError("max_connecting_datasets must be at least 2")
        self.max_connecting_datasets = max_connecting_datasets
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
        normalized, groups, truncated = self.index.search.search(
            request.query,
            request.limit,
            request.kind,
        )
        return SearchResponse(
            snapshot=self.snapshot_info(),
            query=request.query,
            normalized_query=normalized,
            groups=groups,
            truncated=truncated,
        )

    def get_identity(
        self,
        identity_id: str,
        entity_universe: list[EntityUniverse] | None = None,
        limit: int = 100,
        response_format: ResponseFormat = "table",
    ) -> IdentityDetail:
        request = IdentityRequest(
            identity_id=identity_id, entity_universe=entity_universe, limit=limit,
            response_format=response_format,
        )
        identity = self._identity(request.identity_id)
        universes = (set(request.entity_universe)
                     if request.entity_universe is not None else None)
        # Definitions are indexed in node_id, then dataset_columns order.
        matching = [
            (node_id, definition)
            for node_id, definition in self.index.definitions_by_identity.get(identity_id, ())
            if universes is None or definition.entity_universe in universes
        ]
        selected = matching[:request.limit]
        return IdentityDetail(
            identity_id=identity.identity_id,
            name=identity.name,
            description=identity.description,
            synonyms=identity.synonyms,
            entity_definitions=collection(
                [{"node_id": node_id, **_claim_payload(definition)}
                 for node_id, definition in selected],
                DEFINITION_HEADER, request.response_format,
            ),
            datasets=collection(
                [self._dataset_record(node_id)
                 for node_id in sorted({node_id for node_id, _ in selected})],
                DATASET_HEADER, request.response_format,
            ),
            truncated=len(matching) > request.limit,
        )

    def get_dataset(self, node_id: str) -> DatasetDetail:
        return self._dataset_detail(self._node(node_id))

    def get_relationship(
        self,
        edge_id: str,
        from_node_id: str | None = None,
        response_format: ResponseFormat = "table",
    ) -> RelationshipDetail:
        edge = self._edge(edge_id)
        direction = None
        reverse_direction = None
        unknown_fields = edge.unknown_fields()
        if from_node_id is not None:
            if from_node_id not in {edge.endpoint_a.node_id, edge.endpoint_b.node_id}:
                raise ValueError(
                    f"from_node_id {from_node_id!r} is not an endpoint of edge {edge_id!r}"
                )
            step = _step(edge, from_node_id)
            direction = step["direction"]
            reverse_direction = step["reverse_direction"]
            unknown_fields = step["unknown_fields"]
        objects = _GraphObjects(self, response_format)
        record = objects.add_relationship(edge)
        return RelationshipDetail(
            **{**record, "unknown_fields": unknown_fields},
            from_node_id=from_node_id,
            direction=direction,
            reverse_direction=reverse_direction,
            datasets=objects.datasets(),
            entity_definitions=objects.entity_definitions(),
        )

    def get_hops(
        self, node_id: str, limit: int = 100, response_format: ResponseFormat = "table",
    ) -> HopsResponse:
        request = HopsRequest(node_id=node_id, limit=limit, response_format=response_format)
        self._node(request.node_id)
        edges = sorted(self.index.adjacency.get(node_id, ()), key=lambda edge: edge.edge_id)
        objects = _GraphObjects(self, request.response_format)
        hops = []
        for edge in edges[:request.limit]:
            objects.add_relationship(edge)
            hops.append(_step(edge, node_id))
        return HopsResponse(
            node_id=node_id,
            hops=collection(hops, STEP_HEADER, request.response_format),
            relationships=objects.relationships(),
            datasets=objects.datasets(),
            entity_definitions=objects.entity_definitions(),
            truncated=len(edges) > request.limit,
        )

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
        objects = _GraphObjects(self, request.response_format)
        for edge_id in selected_edge_ids:
            objects.add_relationship(self.index.edges[edge_id])
        return SubgraphResponse(
            snapshot=self.snapshot_info(),
            seed_node_ids=seeds,
            max_depth=request.max_depth,
            max_nodes=request.max_nodes,
            max_edges=request.max_edges,
            **self._dataset_detail_collections(
                selected_nodes, SUBGRAPH_DATASET_HEADER, request.response_format,
            ),
            relationships=objects.relationships(),
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
        allowed_multiplicities: list[Multiplicity] | None = None,
        cancel_event: Event | None = None,
        response_format: ResponseFormat = "table",
    ) -> PathsResponse:
        request = PathsRequest(
            from_node_id=from_node_id,
            to_node_id=to_node_id,
            max_hops=max_hops,
            limit=limit,
            allowed_multiplicities=allowed_multiplicities,
            response_format=response_format,
        )
        from_node_id = request.from_node_id
        to_node_id = request.to_node_id
        max_hops = request.max_hops
        limit = request.limit
        self._node(from_node_id)
        self._node(to_node_id)
        allowed = (set(request.allowed_multiplicities)
                   if request.allowed_multiplicities is not None else None)
        # Paths rank by hop count, then edge IDs, so each hop count is a complete rank
        # tier. Search tier by tier and stop once the limit is filled, plus one more path
        # to report truncation. A partial path extends only while the target stays within
        # max_hops.
        distance = self._distances_to(to_node_id, max_hops)
        frontier: list[tuple[str, list[tuple[str, str, JoinRelationship]], set[str]]] = [
            (from_node_id, [], {from_node_id})
        ]
        found: list[list[tuple[str, str, JoinRelationship]]] = []
        cancelled = False
        depth = 0
        while frontier and depth < max_hops and len(found) <= limit and not cancelled:
            depth += 1
            tier: list[list[tuple[str, str, JoinRelationship]]] = []
            next_frontier = []
            for current, hops, seen in frontier:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    break
                for edge in self.index.adjacency.get(current, ()):
                    if allowed is not None and edge.direction_from(current).multiplicity not in allowed:
                        continue
                    nxt = edge.opposite(current).node_id
                    if nxt in seen:
                        continue
                    if nxt == to_node_id:
                        tier.append([*hops, (current, nxt, edge)])
                    elif depth + distance.get(nxt, max_hops + 1) <= max_hops:
                        next_frontier.append((nxt, [*hops, (current, nxt, edge)], seen | {nxt}))
                if len(found) == limit and tier:
                    # The limit is already filled; one more path proves truncation.
                    break
            tier.sort(key=lambda path: tuple(edge.edge_id for _, _, edge in path))
            found.extend(tier)
            frontier = next_frontier

        objects = _GraphObjects(self, request.response_format)
        hops = []
        # Each hop row names its path by rank; a path's hops are its rows in order.
        for rank, path in enumerate(found[:limit]):
            for source, _, edge in path:
                objects.add_relationship(edge)
                hops.append({"path": rank, **_step(edge, source)})
        return PathsResponse(
            snapshot=self.snapshot_info(),
            from_node_id=from_node_id,
            to_node_id=to_node_id,
            path_count=len(found[:limit]),
            hops=collection(hops, PATH_STEP_HEADER, request.response_format),
            relationships=objects.relationships(),
            datasets=objects.datasets(),
            entity_definitions=objects.entity_definitions(),
            truncated=cancelled or len(found) > limit,
        )

    def _distances_to(self, node_id: str, max_hops: int) -> dict[str, int]:
        """Unfiltered hop distance to ``node_id``, a lower bound for any simple path."""
        distance = {node_id: 0}
        queue = deque([node_id])
        while queue:
            current = queue.popleft()
            if distance[current] >= max_hops:
                continue
            for edge in self.index.adjacency.get(current, ()):
                nxt = edge.opposite(current).node_id
                if nxt not in distance:
                    distance[nxt] = distance[current] + 1
                    queue.append(nxt)
        return distance

    def find_connecting_subgraph(
        self, request: ConnectingSubgraphRequest,
    ) -> ConnectingSubgraphResponse:
        if len(request.node_ids) > self.max_connecting_datasets:
            raise ValueError(f"at most {self.max_connecting_datasets} datasets are allowed")
        terminals = sorted(request.node_ids)
        for node_id in terminals:
            self._node(node_id)
        result = connecting_tree(self.index.adjacency, terminals)
        objects = _GraphObjects(self, request.response_format)
        for edge_id in result.edge_ids:
            objects.add_relationship(self.index.edges[edge_id])
        return ConnectingSubgraphResponse(
            snapshot=self.snapshot_info(), node_ids=terminals, status=result.status,
            **self._dataset_detail_collections(
                [(node_id, None) for node_id in result.node_ids],
                DATASET_DETAIL_HEADER, request.response_format,
            ),
            relationships=objects.relationships(),
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
            grain=node.model_dump(mode="json", include={"grain"})["grain"],
            columns=[item.model_dump(mode="json") for item in node.columns],
            entity_definitions=[_claim_payload(item) for item in node.entity_definitions],
            unknown_fields=node.unknown_fields(),
        )

    def _dataset_record(self, node_id: str) -> dict[str, Any]:
        node = self._node(node_id)
        return {
            "node_id": node_id,
            "descriptor": node.descriptor.model_dump(mode="json"),
            "accessor": node.accessor.model_dump(mode="json", by_alias=True),
        }

    def _dataset_detail_collections(
        self,
        nodes: list[tuple[str, int | None]],
        header: list[str],
        response_format: ResponseFormat,
    ) -> dict[str, Any]:
        """Dataset detail split into dataset, column, and entity-definition collections."""
        datasets, columns, definitions = [], [], []
        for node_id, distance in nodes:
            detail = self.get_dataset(node_id)
            datasets.append({
                "node_id": node_id,
                **({"distance": distance} if distance is not None else {}),
                "descriptor": detail.descriptor,
                "accessor": detail.accessor,
                "grain": detail.grain,
                "unknown_fields": detail.unknown_fields,
            })
            columns.extend({"node_id": node_id, **column} for column in detail.columns)
            definitions.extend(
                {"node_id": node_id, **definition} for definition in detail.entity_definitions
            )
        return {
            "datasets": collection(datasets, header, response_format),
            "columns": collection(columns, COLUMN_HEADER, response_format),
            "entity_definitions": collection(definitions, DEFINITION_HEADER, response_format),
        }


class _GraphObjects:
    """Relationships and datasets a response references, each listed once by its ID."""

    def __init__(self, service: GraphReadService, response_format: ResponseFormat) -> None:
        self.service = service
        self.response_format = response_format
        self._relationships: dict[str, dict[str, Any]] = {}
        self._definitions: dict[str, set[DefinitionKey]] = defaultdict(set)

    def add_relationship(self, edge: JoinRelationship) -> dict[str, Any]:
        record = self._relationships.get(edge.edge_id)
        if record is None:
            annotation = self.service.index.annotations.get(edge.edge_id)
            record = {
                "edge_id": edge.edge_id,
                "identity_id": edge.endpoint_a.identity_id,
                "endpoint_a": {
                    "node_id": edge.endpoint_a.node_id,
                    "dataset_columns": edge.endpoint_a.dataset_columns,
                },
                "endpoint_b": {
                    "node_id": edge.endpoint_b.node_id,
                    "dataset_columns": edge.endpoint_b.dataset_columns,
                },
                "a_to_b": edge.a_to_b.model_dump(mode="json"),
                "b_to_a": edge.b_to_a.model_dump(mode="json"),
                "unknown_fields": edge.unknown_fields(),
                "annotation": annotation.model_dump(mode="json") if annotation else None,
            }
            self._relationships[edge.edge_id] = record
            for endpoint in (edge.endpoint_a, edge.endpoint_b):
                self._definitions[endpoint.node_id].add(endpoint.identity_key())
        return record

    def relationships(self) -> Any:
        records = [record for _, record in sorted(self._relationships.items())]
        return collection(records, RELATIONSHIP_HEADER, self.response_format)

    def datasets(self) -> Any:
        """Endpoint datasets in node_id order."""
        records = [self.service._dataset_record(node_id) for node_id in sorted(self._definitions)]
        return collection(records, DATASET_HEADER, self.response_format)

    def entity_definitions(self) -> Any:
        """The endpoint entity definitions, in node_id, identity, then column order."""
        records = [
            {"node_id": node_id, **_claim_payload(self.service.index.definitions[key])}
            for node_id in sorted(self._definitions)
            for key in sorted(self._definitions[node_id])
        ]
        return collection(records, DEFINITION_HEADER, self.response_format)


def _step(edge: JoinRelationship, source: str) -> dict[str, Any]:
    """A traversal of ``edge`` away from ``source``, with claims relative to that direction."""
    target = edge.opposite(source).node_id
    return {
        "edge_id": edge.edge_id,
        "from_node_id": source,
        "to_node_id": target,
        "direction": edge.direction_from(source).model_dump(mode="json"),
        "reverse_direction": edge.direction_from(target).model_dump(mode="json"),
        "unknown_fields": edge.unknown_fields_from(source),
    }


def _claim_payload(subject: ClaimModel) -> dict[str, Any]:
    """Serialize an object with its unknown claims resolved for the caller."""
    return {**subject.model_dump(mode="json"), "unknown_fields": subject.unknown_fields()}
