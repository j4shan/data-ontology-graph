from collections import defaultdict
from dataclasses import dataclass, field

from data_ontology_graph.builder.report import InferenceReport
from data_ontology_graph.model.dataset import DatasetNode
from data_ontology_graph.model.enums import DatasetLayer, KeyKind, Participation, Precedence, TableRole
from data_ontology_graph.model.relationship import JoinEndpoint, JoinRelationship, make_relationship


@dataclass
class EntityKey:
    node_id: str
    columns: list[str]
    unique: bool
    category: str


@dataclass
class InferStats:
    declared_attempted: int = 0
    inferred_attempted: int = 0
    unresolved_declared: int = 0
    self_referential: int = 0
    merged: dict[str, JoinRelationship] = field(default_factory=dict)


def infer_relationships(nodes: list[DatasetNode]) -> tuple[list[JoinRelationship], InferenceReport]:
    primaries = [node for node in nodes if node.dataset_layer == DatasetLayer.PRIMARY]
    stats = InferStats()
    _infer_declared(primaries, stats)
    _infer_structural(primaries, stats)
    report = InferenceReport(
        declared_edges=stats.declared_attempted,
        inferred_edges=stats.inferred_attempted,
        unresolved_declared=stats.unresolved_declared,
        self_referential=stats.self_referential,
        total=len(stats.merged),
    )
    return list(stats.merged.values()), report


def _infer_declared(nodes: list[DatasetNode], stats: InferStats) -> None:
    by_table: dict[str, list[DatasetNode]] = defaultdict(list)
    for node in nodes:
        by_table[node.table_name.lower()].append(node)
    for node in nodes:
        for declaration in node.foreign_key_declarations:
            stats.declared_attempted += 1
            matches = by_table.get(declaration.ref_table.lower(), [])
            if len(matches) != 1:
                stats.unresolved_declared += 1
                continue
            target = matches[0]
            if target.node_id == node.node_id:
                stats.self_referential += 1
                continue
            source_ep = JoinEndpoint(
                node_id=node.node_id,
                columns=list(declaration.local_columns),
                is_unique=node.covers_unconditional_unique(declaration.local_columns),
                participation=_participation(
                    node, target, declaration.local_columns, covers_full_pk=True
                ),
            )
            target_ep = JoinEndpoint(
                node_id=target.node_id,
                columns=list(declaration.ref_columns),
                is_unique=target.covers_unconditional_unique(declaration.ref_columns),
            )
            _merge(stats, make_relationship(source_ep, target_ep, Precedence.DECLARED))


def _infer_structural(nodes: list[DatasetNode], stats: InferStats) -> None:
    registry = _entity_key_registry(nodes)
    for source in nodes:
        physical_by_lcn: dict[str, list[str]] = defaultdict(list)
        for column in source.columns:
            if column.key_spec and column.key_spec.kind == KeyKind.DEGENERATE:
                continue
            physical_by_lcn[column.effective_logical_name()].append(column.name)
        for target_key in registry:
            if target_key.node_id == source.node_id:
                continue
            if not all(name in physical_by_lcn for name in _logical_names(nodes, target_key)):
                continue
            candidates = _expand_physical(physical_by_lcn, _logical_names(nodes, target_key))
            target = next(node for node in nodes if node.node_id == target_key.node_id)
            for physical in candidates:
                stats.inferred_attempted += 1
                source_ep = JoinEndpoint(
                    node_id=source.node_id,
                    columns=physical,
                    is_unique=source.covers_unconditional_unique(physical),
                    transform=_shared_transform(source, physical),
                    participation=_participation(
                        source,
                        target,
                        physical,
                        covers_full_pk=set(target_key.columns) == set(target.primary_key),
                    ),
                )
                target_ep = JoinEndpoint(
                    node_id=target.node_id,
                    columns=list(target_key.columns),
                    is_unique=target_key.unique,
                    transform=_shared_transform(target, target_key.columns),
                )
                _merge(stats, make_relationship(source_ep, target_ep, Precedence.INFERRED))


def _entity_key_registry(nodes: list[DatasetNode]) -> list[EntityKey]:
    keys: list[EntityKey] = []
    for node in nodes:
        if node.primary_key:
            keys.append(EntityKey(node.node_id, list(node.primary_key), True, "primary_key"))
        for unique in node.unique_keys:
            keys.append(EntityKey(node.node_id, list(unique), True, "unique_key"))
        for columns in node.pk_child_entity.values():
            keys.append(EntityKey(node.node_id, list(columns), False, "pk_child"))
        for columns in node.logical_entity_key.values():
            keys.append(EntityKey(node.node_id, list(columns), False, "logical_entity"))
    return keys


def _logical_names(nodes: list[DatasetNode], key: EntityKey) -> list[str]:
    node = next(item for item in nodes if item.node_id == key.node_id)
    columns = node.column_map()
    return [columns[name].effective_logical_name() for name in key.columns if name in columns]


def _expand_physical(physical_by_lcn: dict[str, list[str]], logical_names: list[str]) -> list[list[str]]:
    if not logical_names:
        return []
    results = [[]]
    for name in logical_names:
        results = [prefix + [column] for prefix in results for column in physical_by_lcn[name]]
    return results


def _shared_transform(node: DatasetNode, columns: list[str]) -> str | None:
    transforms = {
        node.column_map()[name].logical_transform
        for name in columns
        if name in node.column_map()
    }
    transforms.discard(None)
    if len(transforms) == 1:
        return next(iter(transforms))
    return None


def _participation(
    source: DatasetNode,
    target: DatasetNode,
    source_columns: list[str],
    covers_full_pk: bool,
) -> Participation:
    if source.covers_unconditional_unique(source_columns):
        return Participation.UNKNOWN
    columns = source.column_map()
    nullable = any(columns[name].is_nullable for name in source_columns if name in columns)
    if nullable:
        return Participation.PARTIAL
    if (
        covers_full_pk
        and target.primary_key
        and target.is_entity_universe
        and target.table_role == TableRole.DIMENSION
    ):
        return Participation.TOTAL
    return Participation.UNKNOWN


def _merge(stats: InferStats, incoming: JoinRelationship) -> None:
    existing = stats.merged.get(incoming.edge_id)
    if existing is None:
        stats.merged[incoming.edge_id] = incoming
        return
    rank = {Precedence.INFERRED: 0, Precedence.DECLARED: 1}
    if rank[incoming.precedence] >= rank[existing.precedence]:
        stats.merged[incoming.edge_id] = incoming
