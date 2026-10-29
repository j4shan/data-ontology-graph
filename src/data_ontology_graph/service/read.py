from __future__ import annotations

from collections import defaultdict
from threading import Event
from typing import Any

from data_ontology_graph.model.claims import ClaimModel
from data_ontology_graph.model.dataset import DatasetNode, EntityDefinition
from data_ontology_graph.model.intermediary import LogicalIdentity
from data_ontology_graph.model.enums import EntityUniverse
from data_ontology_graph.model.relationship import JoinRelationship
from data_ontology_graph.model.snapshot import GraphSnapshot
from data_ontology_graph.service.contracts import (
    ConnectingSubgraphRequest,
    ConnectingSubgraphResponse,
    DatasetDetail,
    EdgesRequest,
    EdgesResponse,
    IdentityDetail,
    IdentityRequest,
    PathsRequest,
    PathsResponse,
    RelationshipDetail,
    RelationshipRequest,
    SearchRequest,
    SearchResponse,
    SnapshotInfo,
    SubgraphRequest,
    SubgraphResponse,
)
from data_ontology_graph.query.connecting import connecting_tree
from data_ontology_graph.query.neighbourhood import (
    DirectedEdge,
    EdgeGroup,
    directed_edge_from,
    directed_edges_by_dataset,
    expand,
    group_edges,
)
from data_ontology_graph.query.paths import PathGraph
from data_ontology_graph.service.search import LexicalSearchIndex
from data_ontology_graph.service.tables import (
    DEFINITION_HEADER,
    RELATIONSHIP_HEADER,
    ResponseFormat,
    collection,
    to_table,
)
from data_ontology_graph.service.views import COLUMN_FIELDS, View, definition_label, pick


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
        self.directed_edges = directed_edges_by_dataset(snapshot.edges)
        self.paths = PathGraph(snapshot.nodes, snapshot.edges)
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
                [{"node_id": node_id, **_definition_payload(self._node(node_id), definition)}
                 for node_id, definition in selected],
                DEFINITION_HEADER, request.response_format,
            ),
            datasets=self._dataset_collection(
                sorted({node_id for node_id, _ in selected}), request.response_format,
            ),
            truncated=len(matching) > request.limit,
        )

    def get_dataset(self, node_id: str) -> DatasetDetail:
        self._node(node_id)
        return DatasetDetail(**self._dataset_record(node_id, "full"))

    def get_relationship(
        self,
        edge_id: str,
        from_node_id: str | None = None,
        response_format: ResponseFormat = "table",
        from_dataset_columns: list[str] | None = None,
    ) -> RelationshipDetail:
        request = RelationshipRequest(
            edge_id=edge_id, from_node_id=from_node_id,
            from_dataset_columns=from_dataset_columns, response_format=response_format,
        )
        relationship = self._edge(request.edge_id)
        edge = None
        if request.from_node_id is not None:
            edge = self._edge_from(relationship, request.from_node_id, request.from_dataset_columns)
        objects = _GraphObjects(self, request.response_format)
        record = objects.add_relationship(relationship)
        view = View.resolve("standard", None)
        return RelationshipDetail(
            **record,
            from_node_id=request.from_node_id,
            from_dataset_columns=list(edge.source.dataset_columns) if edge else None,
            edge_fields=list(view.edge) if edge else None,
            edge=self._edge_array(edge, view) if edge else None,
            datasets=objects.datasets(),
            entity_definitions=objects.entity_definitions(),
        )

    def get_edges(
        self,
        node_id: str,
        limit: int = 200,
        response_format: ResponseFormat = "table",
        detail: str = "standard",
        fields: dict[str, list[str]] | None = None,
        identity_id: str | None = None,
        from_dataset_columns: list[str] | None = None,
    ) -> EdgesResponse:
        request = EdgesRequest(
            node_id=node_id, limit=limit, response_format=response_format, detail=detail,
            fields=fields or {}, identity_id=identity_id, from_dataset_columns=from_dataset_columns,
        )
        node = self._node(request.node_id)
        view = View.resolve(request.detail, request.fields)
        neighbourhood = expand(
            self.index.directed_edges, [request.node_id], 1, limit=request.limit,
            edge_filter=self._definition_filter(node, request), referenced_only=True,
        )
        datasets = [
            self._dataset_values(node_id, distance, neighbourhood.groups.get(node_id), view)
            for node_id, distance in neighbourhood.datasets
        ]
        return EdgesResponse(
            node_id=request.node_id,
            limit=request.limit,
            **self._present(datasets, view, request.response_format, distance=True),
            truncated=neighbourhood.truncated,
        )

    def expand_subgraph(self, request: SubgraphRequest) -> SubgraphResponse:
        seeds = list(dict.fromkeys(request.seed_node_ids))
        for seed in seeds:
            self._node(seed)
        if len(seeds) > request.max_nodes:
            raise ValueError("max_nodes must be at least the number of unique seed nodes")
        view = View.resolve(request.detail, request.fields)
        neighbourhood = expand(
            self.index.directed_edges, seeds, request.max_depth,
            max_nodes=request.max_nodes, limit=request.limit,
        )
        datasets = [
            self._dataset_values(node_id, distance, neighbourhood.groups.get(node_id), view)
            for node_id, distance in neighbourhood.datasets
        ]
        return SubgraphResponse(
            snapshot=self.snapshot_info(),
            seed_node_ids=seeds,
            max_depth=request.max_depth,
            max_nodes=request.max_nodes,
            limit=request.limit,
            **self._present(datasets, view, request.response_format, distance=True),
            truncated=neighbourhood.truncated,
        )

    def find_paths(
        self, request: PathsRequest, cancel_event: Event | None = None,
    ) -> PathsResponse:
        self._node(request.from_node_id)
        self._node(request.to_node_id)
        view = View.resolve(request.detail, request.fields, paths=True)
        allowed = (set(request.allowed_multiplicities)
                   if request.allowed_multiplicities is not None else None)
        graph = self.index.paths
        pairs, truncated = graph.k_shortest(
            request.from_node_id, request.to_node_id, request.limit, request.max_edges, allowed,
            cancelled=(cancel_event.is_set if cancel_event is not None else lambda: False),
        )
        paths = [
            [directed_edge_from(self.index.edges[graph.edge_id(a, b)], graph.keys[a]) for a, b in path]
            for path in pairs
        ]
        node_ids = sorted({
            node_id for path in paths for edge in path
            for node_id in (edge.source.node_id, edge.target.node_id)
        })
        datasets = [self._dataset_values(node_id, None, None, view) for node_id in node_ids]
        presented = self._present(datasets, view, request.response_format, distance=False)
        presented["paths"] = [[self._edge_array(edge, view) for edge in path] for path in paths]
        return PathsResponse(
            snapshot=self.snapshot_info(),
            from_node_id=request.from_node_id,
            to_node_id=request.to_node_id,
            path_count=len(paths),
            **presented,
            truncated=truncated or bool(cancel_event is not None and cancel_event.is_set()),
        )

    def find_connecting_subgraph(
        self, request: ConnectingSubgraphRequest,
    ) -> ConnectingSubgraphResponse:
        if len(request.node_ids) > self.max_connecting_datasets:
            raise ValueError(f"at most {self.max_connecting_datasets} datasets are allowed")
        terminals = sorted(request.node_ids)
        for node_id in terminals:
            self._node(node_id)
        view = View.resolve(request.detail, request.fields)
        result = connecting_tree(self.index.adjacency, terminals)
        tree = set(result.edge_ids)
        datasets = [
            self._dataset_values(
                node_id, None,
                group_edges(
                    edge for edge in self.index.directed_edges.get(node_id, ())
                    if edge.edge_id in tree
                ),
                view,
            )
            for node_id in result.node_ids
        ]
        return ConnectingSubgraphResponse(
            snapshot=self.snapshot_info(), node_ids=terminals, status=result.status,
            **self._present(datasets, view, request.response_format, distance=False),
            truncated=False,
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

    def _dataset_record(self, node_id: str, detail: Detail) -> dict[str, Any]:
        """One dataset as the navigation record at ``detail``, without response-only fields."""
        view = View.resolve(detail)
        return pick(self._dataset_field_values(node_id, view), view.record_fields())

    def _dataset_collection(self, node_ids: list[str], response_format: ResponseFormat) -> Any:
        """Datasets beside other graph objects, as `standard` records (system design 2.4.4)."""
        records = [self._dataset_record(node_id, "standard") for node_id in node_ids]
        return collection(records, list(View.resolve("standard").record_fields()), response_format)

    @staticmethod
    def _definition_filter(node: DatasetNode, request: EdgesRequest):
        """Keep the directed edges leaving the requested entity definitions, if any are named."""
        if request.identity_id is None:
            return None
        matched = {
            definition.key(node.node_id) for definition in node.entity_definitions
            if definition.identity_id == request.identity_id
            and request.from_dataset_columns in (None, definition.dataset_columns)
        }
        if not matched:
            columns = f" on {request.from_dataset_columns}" if request.from_dataset_columns else ""
            raise ValueError(
                f"{node.node_id!r} has no entity definition of {request.identity_id!r}{columns}"
            )
        return lambda edge: edge.source.identity_key() in matched

    def _edge_from(
        self, relationship: JoinRelationship, node_id: str, columns: list[str] | None,
    ) -> DirectedEdge:
        ends = [
            endpoint for endpoint in (relationship.endpoint_a, relationship.endpoint_b)
            if endpoint.node_id == node_id
            and (columns is None or endpoint.dataset_columns == columns)
        ]
        if not ends:
            raise ValueError(f"{node_id!r} {columns or ''} is not an endpoint of edge {relationship.edge_id!r}")
        if len(ends) > 1:
            raise ValueError(
                f"both endpoints of {relationship.edge_id!r} lie on {node_id!r}; name from_dataset_columns"
            )
        return directed_edge_from(relationship, ends[0].identity_key())

    def _edge_array(self, edge: DirectedEdge, view: View) -> list[Any]:
        """One directed edge as an array of ``view.edge`` positions (system design 2.4.1)."""
        values = {
            "edge": (
                f"{definition_label(edge.source.node_id, edge.source.dataset_columns)} -> "
                f"{definition_label(edge.target.node_id, edge.target.dataset_columns)}"
            ),
            "identity_id": edge.source.identity_id,
            "multiplicity": edge.outgoing.multiplicity.value,
            "match_existence": edge.outgoing.match_existence.value,
            "reverse_multiplicity": edge.reverse.multiplicity.value,
            "reverse_match_existence": edge.reverse.match_existence.value,
            "from_description": lambda: self._effective_description(edge.source),
            "to_description": lambda: self._effective_description(edge.target),
            "annotation": lambda: self._annotation(edge.edge_id),
            "edge_id": edge.edge_id,
        }
        return [value() if callable(value) else value
                for value in (values[field] for field in view.edge)]

    def _annotation(self, edge_id: str) -> dict[str, Any] | None:
        annotation = self.index.annotations.get(edge_id)
        return annotation.model_dump(mode="json") if annotation else None

    def _effective_description(self, endpoint) -> str | None:
        node = self._node(endpoint.node_id)
        definition = self.index.definitions[endpoint.identity_key()]
        effective = definition.effective_description(node.columns)
        return effective[0] if effective else None

    def _dataset_values(
        self, node_id: str, distance: int | None, groups: list[EdgeGroup] | None, view: View,
    ) -> dict[str, Any]:
        """One dataset as a nested record at ``view``, with its edge groups when it lists them."""
        values = self._dataset_field_values(node_id, view) | {"distance": distance}
        record = pick(values, view.dataset_fields(distance=distance is not None))
        if groups is not None:
            record["edge_groups"] = self._edge_groups(groups, view)
        return record

    def _dataset_field_values(self, node_id: str, view: View) -> dict[str, Any]:
        """Every dataset field by dotted name; entity definitions at ``view``."""
        node = self._node(node_id)
        descriptor = node.descriptor
        accessor = node.accessor.model_dump(mode="json", by_alias=True)
        return {
            "node_id": node_id,
            "qualified_name": descriptor.qualified_name,
            "distance": None,
            "edge_count": len(self.index.directed_edges.get(node_id, ())),
            "accessor.schema_id": accessor["schema_id"],
            "grain": node.model_dump(mode="json", include={"grain"})["grain"],
            "descriptor.description": descriptor.description,
            "unknown_fields": node.unknown_fields(),
            "descriptor.display_name": descriptor.display_name,
            "descriptor.synonyms": descriptor.synonyms,
            "descriptor.tags": descriptor.tags,
            "accessor.properties": accessor["properties"],
            "columns": [
                {field: column.model_dump(mode="json")[field] for field in COLUMN_FIELDS}
                for column in node.columns
            ],
            "entity_definitions": [
                pick(_definition_payload(node, definition), view.entity_definition)
                for definition in node.entity_definitions
            ],
        }

    def _edge_groups(self, groups: list[EdgeGroup], view: View) -> list[dict[str, Any]]:
        """Edge groups by logical entity ID, each holding its entity definitions' directed edges."""
        by_identity: dict[str, list[dict[str, Any]]] = {}
        for group in groups:
            by_identity.setdefault(group.source.identity_id, []).append({
                "dataset_columns": group.source.dataset_columns,
                "edge_count": group.edge_count,
                "truncated": group.truncated,
                "edges": [self._edge_array(edge, view) for edge in group.edges],
            })
        return [
            {"identity_id": identity_id, "entity_definitions": definitions}
            for identity_id, definitions in by_identity.items()
        ]

    def _present(
        self,
        datasets: list[dict[str, Any]],
        view: View,
        response_format: ResponseFormat,
        *,
        distance: bool,
    ) -> dict[str, Any]:
        """Records nest edge groups, columns, and definitions; tables split them, keyed by node_id."""
        common = {"detail": view.detail, "fields": view.added, "edge_fields": list(view.edge)}
        if response_format == "records":
            return {**common, "datasets": datasets}
        nested = ("edge_groups", "columns", "entity_definitions")
        fields = [f for f in view.dataset_fields(distance=distance) if f not in nested]
        tables: dict[str, Any] = {
            "datasets": to_table(
                [{k: v for k, v in record.items() if k not in nested} for record in datasets],
                fields,
            ),
        }
        if any("edge_groups" in record for record in datasets):
            tables["edge_groups"] = [
                {"node_id": record["node_id"], **group}
                for record in datasets for group in record.get("edge_groups", ())
            ]
        if "columns" in view.dataset:
            tables["columns"] = to_table(
                [{"node_id": r["node_id"], **c} for r in datasets for c in r["columns"]],
                ["node_id", *COLUMN_FIELDS],
            )
        if "entity_definitions" in view.dataset:
            tables["entity_definitions"] = to_table(
                [{"node_id": r["node_id"], **d} for r in datasets for d in r["entity_definitions"]],
                ["node_id", *view.entity_definition],
            )
        return {**common, **tables}


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
        return self.service._dataset_collection(sorted(self._definitions), self.response_format)

    def entity_definitions(self) -> Any:
        """The endpoint entity definitions, in node_id, logical entity ID, then column order."""
        records = [
            {
                "node_id": node_id,
                **_definition_payload(
                    self.service._node(node_id), self.service.index.definitions[key]
                ),
            }
            for node_id in sorted(self._definitions)
            for key in sorted(self._definitions[node_id])
        ]
        return collection(records, DEFINITION_HEADER, self.response_format)


def _claim_payload(subject: ClaimModel) -> dict[str, Any]:
    """Serialize an object with its unknown claims resolved for the caller."""
    return {**subject.model_dump(mode="json"), "unknown_fields": subject.unknown_fields()}


def _definition_payload(node: DatasetNode, definition: EntityDefinition) -> dict[str, Any]:
    """An entity definition with its effective description and where that text comes from."""
    effective = definition.effective_description(node.columns)
    return {
        **_claim_payload(definition),
        "effective_description": effective[0] if effective else None,
        "description_source": effective[1] if effective else None,
    }

