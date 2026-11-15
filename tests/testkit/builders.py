"""Builders for synthetic datasets, entity definitions, and read services."""
from pathlib import Path

import yaml

from data_ontology_graph.builder import build_snapshot_from_yaml
from data_ontology_graph.model.dataset import (
    ColumnMetadata,
    DatasetAccessor,
    DatasetDescriptor,
    DatasetNode,
    EntityDefinition,
)
from data_ontology_graph.model.derivation import multiplicity_between
from data_ontology_graph.model.enums import EntityUniverse, Unknown
from data_ontology_graph.model.intermediary import LogicalIdentity
from data_ontology_graph.model.snapshot import GraphSnapshot
from data_ontology_graph.service.read import GraphReadService
from testkit import snapshot_of


def definition(
    columns: list[str] | None = None,
    *,
    universe: str = "partial",
    unique: bool | str = "unknown",
    total: bool | str = True,
    conforms: bool | str = "unknown",
    identity_id: str = "device",
) -> EntityDefinition:
    """An entity definition whose claims default to the least committal values."""
    return EntityDefinition(
        identity_id=identity_id,
        dataset_columns=columns or ["id"],
        entity_universe=universe,
        unique=unique,
        total=total,
        conforms=conforms,
    )


def dataset_node(name: str, definitions: list[EntityDefinition], *, grain="unknown") -> DatasetNode:
    """A SQLite dataset ``dataset:<name>`` holding the columns its definitions use."""
    columns = sorted({column for item in definitions for column in item.dataset_columns})
    return DatasetNode(
        node_id=f"dataset:{name}",
        descriptor=DatasetDescriptor(qualified_name=f"example.main.{name}", display_name=name),
        accessor=DatasetAccessor(
            kind="sqlite",
            endpoint="/srv/sqlite/example.sqlite",
            properties={"host": "localhost", "schema": "main", "object": name},
        ),
        grain=grain,
        columns=[ColumnMetadata(name=column) for column in columns],
        entity_definitions=definitions,
    )


# The fan-out catalog: one seed dataset whose tenant definition reaches many datasets.
SEED = "fanout:seed"
TENANT, EMPLOYEE, WAREHOUSE = "tenant_identity", "employee_identity", "warehouse_identity"


def role(identity: str, column: str | None = None, unique: bool = False) -> EntityDefinition:
    """A total, conforming definition; unique ones cover the complete universe."""
    return EntityDefinition(
        identity_id=identity, dataset_columns=[column or identity], unique=unique,
        total=True, conforms=True, entity_universe="complete" if unique else "partial",
    )


def fanout_service(size: int = 210) -> GraphReadService:
    """One synthetic catalog, including repeated roles and histogram groups beyond the top 20."""
    specs = [(SEED, [role(TENANT, unique=True), role("source_only")])]
    for i in range(size):
        definitions = [role(TENANT)]
        if i % 2 == 0:
            definitions.append(role(EMPLOYEE))
        if i == 0:
            definitions.append(role(EMPLOYEE, "manager_id"))
        if i % 3 == 0:
            definitions.append(role(WAREHOUSE))
        if i < 30:
            definitions.append(role(f"kind_{i:02}"))
        specs.append((f"fanout:n{i:04}", definitions))
    nodes = [DatasetNode(
        node_id=name, descriptor={"qualified_name": name, "display_name": name},
        accessor={"kind": "fixture", "endpoint": "fanout", "properties": {"object": name}},
        grain="unknown", entity_definitions=definitions,
        columns=[{"name": column} for column in sorted({c for d in definitions for c in d.dataset_columns})],
    ) for name, definitions in specs]
    identities = sorted({d.identity_id for node in nodes for d in node.entity_definitions} | {"unused"})
    return GraphReadService(GraphSnapshot(
        version="2026-11-01T00:00:00Z", nodes=nodes,
        logical_identities=[{"identity_id": identity, "name": identity} for identity in identities],
    ))


def with_roles(size: int = 5) -> GraphReadService:
    """The fan-out catalog with a second tenant role and a channel role on ``fanout:n0000``."""
    snapshot = fanout_service(size).index.snapshot
    node = next(node for node in snapshot.nodes if node.node_id == "fanout:n0000")
    node.columns.extend([ColumnMetadata(name="tenant_alias"), ColumnMetadata(name="channel_id")])
    node.entity_definitions.extend([
        role(TENANT, "tenant_alias", unique=True), role("channel", "channel_id"),
    ])
    payload = snapshot.model_dump()
    payload["logical_identities"].append({"identity_id": "channel", "name": "Channel"})
    return GraphReadService(GraphSnapshot.model_validate(payload))


UNIQUE = {
    "1:1": (True, True),
    "many:1": (False, True),
    "1:many": (True, False),
    "many:many": (False, False),
    "unknown": (Unknown.UNKNOWN, True),
}
"""Uniqueness of a link's (left, right) entity definitions that yields its forward multiplicity."""


def topology_service(names, links, **kwargs) -> GraphReadService:
    """Small topologies built from the lending fixture's account dataset.

    Each link joins its two datasets on a logical entity of its own, so a path passes through a
    dataset by arriving on one link's entity definition and leaving on another's. A link's
    multiplicities come from the `unique` claims of its two entity definitions, and every
    entity definition is `total`, conforming, and `complete`, so match existence is `always`.
    """
    snapshot = snapshot_of()
    template = next(node for node in snapshot.nodes if node.node_id == "sqlite:lending.account")
    template_definition = next(d for d in template.entity_definitions if d.identity_id == "account_identity")
    link_identities = {tuple(link[:2]): f"{link[0]}~{link[1]}" for link in links}
    unique: dict[tuple[str, str], object] = {}
    for link in links:
        left, right = link[:2]
        forward = link[2] if len(link) > 2 else "1:1"
        identity = link_identities[(left, right)]
        unique[(left, identity)], unique[(right, identity)] = UNIQUE[forward]
        if len(link) > 3:
            assert multiplicity_between(*reversed(UNIQUE[forward])).value == link[3], link
    nodes = []
    for name in names:
        node = template.model_copy(deep=True)
        node.node_id = name
        node.accessor = node.accessor.model_copy(
            update={"properties": {**node.accessor.properties, "object": name}}
        )
        identities = [identity for pair, identity in link_identities.items() if name in pair]
        node.columns = [ColumnMetadata(name=f"{identity}_id") for identity in identities] or [
            ColumnMetadata(name="id")
        ]
        node.grain = Unknown.UNKNOWN
        node.entity_definitions = [
            template_definition.model_copy(deep=True, update={
                "identity_id": identity, "dataset_columns": [f"{identity}_id"],
                "unique": unique[(name, identity)], "total": True, "conforms": True,
                "entity_universe": EntityUniverse.COMPLETE,
            })
            for identity in identities
        ]
        nodes.append(node)
    identities = [
        LogicalIdentity(identity_id=identity, name=identity)
        for identity in sorted(set(link_identities.values()))
    ]
    data = snapshot.model_dump()
    data.update(logical_identities=identities, nodes=nodes, annotations=[])
    return GraphReadService(type(snapshot).model_validate(data), **kwargs)


def same_dataset_service(tmp_path: Path) -> GraphReadService:
    """A link table holding two device definitions, beside the device dataset."""
    accessor = lambda name: {"kind": "sqlite", "endpoint": "/d.db", "properties": {
        "host": "h", "schema": "main", "object": name}}
    device = lambda columns, **claims: {
        "identity_id": "device", "dataset_columns": columns, **claims}
    payload = {
        "schema_version": "5",
        "logical_identities": {"device": {"name": "Device"}},
        "nodes": [
            {"node_id": "net.device", "descriptor": {"qualified_name": "net.main.device",
                                                     "display_name": "device"},
             "accessor": accessor("device"),
             "grain": {"components": [{"identity_id": "device", "dataset_columns": ["device_id"]}]},
             "columns": [{"name": "device_id"}],
             "entity_definitions": [device(["device_id"], entity_universe="complete",
                                           unique=True, total=True, conforms=True)]},
            {"node_id": "net.device_link", "descriptor": {"qualified_name": "net.main.device_link",
                                                          "display_name": "device_link"},
             "accessor": accessor("device_link"), "grain": "unknown",
             "columns": [{"name": "device_a", "description": "source device"},
                         {"name": "device_b", "description": "target device"}],
             "entity_definitions": [
                 device(["device_a"], entity_universe="partial", unique=False, total=True,
                        conforms=True),
                 device(["device_b"], entity_universe="partial", unique=False, total=False,
                        conforms=True),
             ]},
        ],
    }
    path = tmp_path / "devices.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return GraphReadService(build_snapshot_from_yaml(path)[0])
