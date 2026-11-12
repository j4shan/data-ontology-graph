from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping
from threading import Event
from typing import Any

from data_ontology_graph.model.claims import ClaimModel
from data_ontology_graph.model.dataset import DatasetNode, DefinitionKey, EntityDefinition, effective_description
from data_ontology_graph.model.intermediary import LogicalIdentity
from data_ontology_graph.model.enums import EntityUniverse
from data_ontology_graph.model.relationship import JoinRelationship
from data_ontology_graph.model.snapshot import GraphSnapshot
from data_ontology_graph.service.contracts import (
    API_VERSION,
    AggregatedEdgesResponse,
    AggregatedEntityDefinitionsResponse,
    ContractModel,
    ConnectingSubgraphRequest,
    ConnectingSubgraphResponse,
    DatasetDetail,
    EdgesRequest,
    EdgesResponse,
    EntityDefinitionsRequest,
    EntityDefinitionsResponse,
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
from data_ontology_graph.query.edge_discovery import discover_edges
from data_ontology_graph.query.entity_definitions import discover_entity_definitions
from data_ontology_graph.query.connecting import connecting_tree
from data_ontology_graph.query.neighbourhood import (
    DirectedEdge,
    EdgeGroup,
    MembershipDirectedEdges,
    directed_edge_from,
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


def _cursor_scope(request: ContractModel, method: str) -> str:
    selection = {"api_version": API_VERSION, "method": method,
                 **request.model_dump(mode="json", exclude={"cursor", "view"})}
    return hashlib.sha256(json.dumps(selection, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _cursor(version: str, scope: str, offset: int) -> str:
    payload = json.dumps({"snapshot": version, "scope": scope, "offset": offset}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def _cursor_offset(cursor: str | None, version: str, scope: str, method: str) -> int:
    if cursor is None:
        return 0
    try:
        payload = json.loads(base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True))
    except (ValueError, binascii.Error, UnicodeError):
        raise ValueError(f"invalid {method} cursor") from None
    if not isinstance(payload, dict) or set(payload) != {"snapshot", "scope", "offset"}:
        raise ValueError(f"invalid {method} cursor")
    if payload["snapshot"] != version:
        raise ValueError(f"{method} cursor belongs to a different snapshot")
    if payload["scope"] != scope:
        raise ValueError(f"{method} cursor does not match the request filters or presentation")
    offset = payload["offset"]
    if type(offset) is not int or offset <= 0:
        raise ValueError(f"invalid {method} cursor offset")
    return offset


class GraphReadIndex:
    def __init__(self, snapshot: GraphSnapshot) -> None:
        self.snapshot = snapshot
        self.fingerprint = hashlib.sha256(snapshot.model_dump_json().encode()).hexdigest()
        self.nodes = snapshot.nodes_by_id
        self.identities = {
            identity.identity_id: identity for identity in snapshot.logical_identities
        }
        self.memberships = snapshot.memberships
        self.definitions = self.memberships.definitions
        self.directed_edges = MembershipDirectedEdges(self.memberships)
        self.paths = PathGraph(self.memberships)
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
            entity_definition_count=self.index.memberships.entity_definition_count,
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

    def get_entity_definitions(
        self,
        identity_id: str,
        entity_universe: list[EntityUniverse] | None = None,
        limit: int = 100,
        response_format: ResponseFormat = "table",
        target_identity_ids: list[str] | None = None,
        view: str = "auto",
        dataset_threshold: int = 200,
        cursor: str | None = None,
        cancel_event: Event | None = None,
    ) -> EntityDefinitionsResponse | AggregatedEntityDefinitionsResponse:
        request = EntityDefinitionsRequest(
            identity_id=identity_id, entity_universe=entity_universe, limit=limit,
            response_format=response_format,
            target_identity_ids=target_identity_ids if target_identity_ids is not None else [],
            view=view, dataset_threshold=dataset_threshold, cursor=cursor,
        )
        identity = self._identity(request.identity_id)
        for target_identity in request.target_identity_ids:
            self._identity(target_identity)

        def check_cancelled() -> None:
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("entity-definition discovery cancelled")

        check_cancelled()
        scope = _cursor_scope(request, "get_entity_definitions")
        offset = _cursor_offset(request.cursor, self.index.fingerprint, scope, "get_entity_definitions")
        discovery = discover_entity_definitions(
            self.index.memberships, request.identity_id, request.entity_universe,
            request.target_identity_ids, check_cancelled,
        )
        dataset_count = len(discovery.node_ids)
        selection = dict(
            snapshot=self.snapshot_info(),
            identity_id=identity.identity_id,
            name=identity.name,
            description=identity.description,
            synonyms=identity.synonyms,
            entity_universe=request.entity_universe,
            target_identity_ids=request.target_identity_ids,
            limit=request.limit,
            dataset_threshold=request.dataset_threshold,
            dataset_count=dataset_count,
            primary_definition_count=discovery.primary_definition_count,
        )
        aggregated = request.view == "aggregated" or (
            request.view == "auto" and request.cursor is None
            and dataset_count > request.dataset_threshold
        )
        if aggregated:
            rows, count = discovery.histogram(check_cancelled)
            rows = [{**row, "name": self.index.identities[row["identity_id"]].name} for row in rows]
            return AggregatedEntityDefinitionsResponse(
                **selection,
                histogram=collection(rows, ["identity_id", "name", "entity_definition_count", "dataset_count"],
                                     request.response_format),
                logical_entity_count=count, truncated=count > len(rows),
            )
        if request.cursor is not None and offset >= dataset_count:
            raise ValueError("cursor is outside the selected dataset range")
        selected = discovery.node_ids[offset:offset + request.limit]
        keys = discovery.page_definitions(selected, request.target_identity_ids, check_cancelled)
        column_descriptions = {
            node_id: {column.name: column.description for column in self._node(node_id).columns}
            for node_id in selected
        }
        definitions = []
        for key in keys:
            check_cancelled()
            definitions.append({
                "node_id": key.node_id,
                **_definition_payload(
                    self._node(key.node_id), self.index.definitions[key], column_descriptions[key.node_id],
                ),
            })
        datasets = []
        for node_id in selected:
            check_cancelled()
            datasets.append(self._dataset_record(node_id, "standard"))
        return EntityDefinitionsResponse(
            **selection,
            entity_definitions=collection(
                definitions, DEFINITION_HEADER, request.response_format,
            ),
            datasets=collection(datasets, list(View.resolve("standard").record_fields()), request.response_format),
            next_cursor=_cursor(self.index.fingerprint, scope, offset + request.limit)
            if offset + request.limit < dataset_count else None,
            truncated=len(selected) < dataset_count,
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
        view: str = "auto",
        fan_out_threshold: int = 200,
        target_identity_ids: list[str] | None = None,
        cursor: str | None = None,
    ) -> EdgesResponse | AggregatedEdgesResponse:
        request = EdgesRequest(
            node_id=node_id, limit=limit, response_format=response_format, detail=detail,
            fields=fields or {}, identity_id=identity_id, from_dataset_columns=from_dataset_columns,
            view=view, fan_out_threshold=fan_out_threshold,
            target_identity_ids=target_identity_ids if target_identity_ids is not None else [],
            cursor=cursor,
        )
        self._node(request.node_id)
        for target_identity in request.target_identity_ids:
            self._identity(target_identity)
        projection = View.resolve(request.detail, request.fields)
        discovery = discover_edges(
            self.index.memberships, request.node_id, request.identity_id,
            request.from_dataset_columns, request.target_identity_ids,
        )
        snapshot = self.snapshot_info()
        selection = {
            "snapshot": snapshot, "node_id": request.node_id, "limit": request.limit,
            "identity_id": request.identity_id, "from_dataset_columns": request.from_dataset_columns,
            "target_identity_ids": request.target_identity_ids,
            "fan_out_count": len(discovery.connected), "fan_out_threshold": request.fan_out_threshold,
        }
        scope = _cursor_scope(request, "get_edges")
        offset = _cursor_offset(request.cursor, self.index.fingerprint, scope, "get_edges")
        aggregated = request.view == "aggregated" or (
            request.view == "auto" and request.cursor is None
            and len(discovery.connected) > request.fan_out_threshold
        )
        if aggregated:
            rows, count = discovery.histogram()
            rows = [{"identity_id": row["identity_id"],
                     "name": self.index.identities[row["identity_id"]].name, **row} for row in rows]
            return AggregatedEdgesResponse(
                **selection, detail=projection.detail, fields=projection.added,
                histogram=collection(rows, ["identity_id", "name", "entity_definition_count", "dataset_count"],
                                     request.response_format),
                logical_entity_count=count, truncated=count > len(rows),
            )
        groups, more = discovery.page(offset, request.limit)
        if request.cursor is not None and not any(group.edges for group in groups):
            raise ValueError("cursor is outside the selected relationship range")
        targets = sorted({edge.target.node_id for group in groups for edge in group.edges} - {request.node_id})
        datasets = [
            self._dataset_values(request.node_id, 0, groups, projection),
            *(self._dataset_values(target, 1, None, projection) for target in targets),
        ]
        return EdgesResponse(
            **selection,
            **self._present(datasets, projection, request.response_format, distance=True),
            next_cursor=_cursor(self.index.fingerprint, scope, offset + request.limit) if more else None,
            truncated=any(group.truncated for group in groups),
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
        memberships = self.index.memberships
        paths = [
            [directed_edge_from(memberships.pair(graph.keys[a], graph.keys[b]), graph.keys[a])
             for a, b in path]
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
        result = connecting_tree(self.index.directed_edges, terminals)
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
            return self.index.memberships.relationship(edge_id)
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
        accessor = node.accessor.model_dump(mode="json")
        values = {
            "node_id": node_id,
            "qualified_name": descriptor.qualified_name,
            "distance": None,
            "edge_count": len(self.index.directed_edges.get(node_id, ())),
            "accessor.kind": accessor["kind"],
            "accessor.endpoint": accessor["endpoint"],
            "accessor.labels": accessor["labels"],
            "grain": node.model_dump(mode="json", include={"grain"})["grain"],
            "descriptor.description": descriptor.description,
            "unknown_fields": node.unknown_fields(),
            "descriptor.display_name": descriptor.display_name,
            "descriptor.synonyms": descriptor.synonyms,
            "descriptor.tags": descriptor.tags,
            "accessor.properties": accessor["properties"],
        }
        if "columns" in view.dataset:
            values["columns"] = [column.model_dump(mode="json") for column in node.columns]
        if "entity_definitions" in view.dataset:
            descriptions = {column.name: column.description for column in node.columns}
            values["entity_definitions"] = [
                pick(_definition_payload(node, definition, descriptions), view.entity_definition)
                for definition in node.entity_definitions
            ]
        return values

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


def _definition_payload(
    node: DatasetNode, definition: EntityDefinition, column_descriptions: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """An entity definition with its effective description and where that text comes from."""
    effective = definition.effective_description(node.columns) if column_descriptions is None else effective_description(
        definition.description, definition.dataset_columns, definition.entity_expression, column_descriptions,
    )
    return {
        **_claim_payload(definition),
        "effective_description": effective[0] if effective else None,
        "description_source": effective[1] if effective else None,
    }

