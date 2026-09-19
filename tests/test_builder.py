import sqlite3
from pathlib import Path

import pytest

from data_ontology_graph.builder import (
    build_snapshot,
    detect_contradictions,
    ingest_sqlite,
    require_sqlite_version,
)
from data_ontology_graph.model.dataset import ColumnMetadata, DatasetNode, DeclaredForeignKey, KeySpec
from data_ontology_graph.model.enums import DatasetLayer, KeyKind, Precedence, TableRole
from data_ontology_graph.model.relationship import JoinEndpoint, make_relationship
from data_ontology_graph.model.snapshot import empty_sql_db_source


def test_sqlite_version_floor() -> None:
    version = require_sqlite_version()
    assert version >= (3, 41)


def _node(
    table: str,
    columns: list[str],
    primary_key: list[str],
    fks: list[DeclaredForeignKey] | None = None,
    **kwargs,
) -> DatasetNode:
    return DatasetNode(
        node_id=f"sql_db:demo.{table}",
        table_name=table,
        data_source=empty_sql_db_source("demo", table),
        columns=[ColumnMetadata(name=name) for name in columns],
        primary_key=primary_key,
        foreign_key_declarations=fks or [],
        **kwargs,
    )


def test_declared_fk_from_in_memory_sqlite(tmp_path: Path) -> None:
    path = tmp_path / "tiny.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE campaign (
            CampaignId INTEGER PRIMARY KEY,
            name TEXT
        );
        CREATE TABLE event (
            EventId INTEGER PRIMARY KEY,
            CampaignId INTEGER NOT NULL,
            FOREIGN KEY (CampaignId) REFERENCES campaign (CampaignId)
        );
        """
    )
    connection.close()
    nodes = ingest_sqlite(path, database="tiny")
    snapshot, report, contradictions = build_snapshot(nodes)
    assert report.declared_edges == 1
    assert report.unresolved_declared == 0
    assert report.self_referential == 0
    assert report.total >= 1
    assert contradictions == []
    assert any(
        {edge.endpoint_a.node_id, edge.endpoint_b.node_id}
        == {"sql_db:tiny.campaign", "sql_db:tiny.event"}
        for edge in snapshot.edges
    )


def test_inferred_lcn_and_transform() -> None:
    device = DatasetNode(
        node_id="sql_db:demo.device",
        table_name="device",
        data_source=empty_sql_db_source("demo", "device"),
        columns=[
            ColumnMetadata(name="DeviceIdHash64", logical_name="device_identity"),
        ],
        primary_key=["DeviceIdHash64"],
    )
    raw = DatasetNode(
        node_id="sql_db:demo.identity",
        table_name="identity",
        data_source=empty_sql_db_source("demo", "identity"),
        columns=[
            ColumnMetadata(
                name="IdentityKey",
                logical_name="device_identity",
                logical_transform="xxhash64",
            ),
            ColumnMetadata(name="row_id"),
        ],
        primary_key=["row_id"],
    )
    snapshot, report, _ = build_snapshot([device, raw])
    assert report.inferred_edges >= 1
    edge = next(
        item
        for item in snapshot.edges
        if {item.endpoint_a.node_id, item.endpoint_b.node_id}
        == {device.node_id, raw.node_id}
    )
    identity_side = edge.endpoint(raw.node_id)
    assert identity_side.transform == "xxhash64"
    assert identity_side.columns == ["IdentityKey"]
    assert edge.endpoint(device.node_id).columns == ["DeviceIdHash64"]
    assert edge.precedence == Precedence.INFERRED


def test_declared_outranks_inferred() -> None:
    campaign = _node("campaign", ["CampaignId"], ["CampaignId"])
    event = _node(
        "event",
        ["EventId", "CampaignId"],
        ["EventId"],
        fks=[
            DeclaredForeignKey(
                local_columns=["CampaignId"],
                ref_table="campaign",
                ref_columns=["CampaignId"],
            )
        ],
    )
    _, report, _ = build_snapshot([campaign, event])
    assert report.declared_edges == 1
    assert report.inferred_edges >= 1
    assert report.total == 1


def test_replica_excluded_from_joins() -> None:
    campaign = _node("campaign", ["CampaignId"], ["CampaignId"])
    replica = DatasetNode(
        node_id="sql_db:demo.campaign_copy",
        table_name="campaign_copy",
        data_source=empty_sql_db_source("demo", "campaign_copy"),
        columns=[ColumnMetadata(name="CampaignId")],
        primary_key=["CampaignId"],
        dataset_layer=DatasetLayer.SECONDARY,
        primary_ref={"qualified_name": "campaign", "source_type": "sql_db"},
    )
    event = _node(
        "event",
        ["EventId", "CampaignId"],
        ["EventId"],
        fks=[
            DeclaredForeignKey(
                local_columns=["CampaignId"],
                ref_table="campaign",
                ref_columns=["CampaignId"],
            )
        ],
    )
    snapshot, _, _ = build_snapshot([campaign, replica, event])
    replica_node = next(node for node in snapshot.nodes if node.node_id == replica.node_id)
    primary = next(node for node in snapshot.nodes if node.node_id == campaign.node_id)
    assert replica_node.primary_ref is not None
    assert replica_node.primary_ref.node_id == campaign.node_id
    assert replica.node_id in primary.replica_node_ids
    assert all(
        replica.node_id not in {edge.endpoint_a.node_id, edge.endpoint_b.node_id}
        for edge in snapshot.edges
    )


def test_degenerate_key_not_a_structural_source() -> None:
    dim = _node("dim", ["TxnId"], ["TxnId"])
    fact = DatasetNode(
        node_id="sql_db:demo.fact",
        table_name="fact",
        data_source=empty_sql_db_source("demo", "fact"),
        columns=[
            ColumnMetadata(name="TxnId", key_spec=KeySpec(kind=KeyKind.DEGENERATE)),
            ColumnMetadata(name="row_id"),
        ],
        primary_key=["row_id"],
    )
    snapshot, _, _ = build_snapshot([dim, fact])
    assert snapshot.edges == []


def test_contradiction_report() -> None:
    left = make_relationship(
        JoinEndpoint(node_id="a", columns=["x"], is_unique=False),
        JoinEndpoint(node_id="b", columns=["y1"], is_unique=True),
    )
    right = make_relationship(
        JoinEndpoint(node_id="a", columns=["x"], is_unique=False),
        JoinEndpoint(node_id="b", columns=["y2"], is_unique=True),
    )
    findings = detect_contradictions([left, right])
    assert len(findings) == 1
    assert findings[0].target_node_id == "b"
    assert set(findings[0].target_column_sets) == {("y1",), ("y2",)}


def test_overlay_sets_dimension_universe() -> None:
    campaign = _node("campaign", ["CampaignId"], ["CampaignId"])
    snapshot, _, _ = build_snapshot(
        [campaign],
        overlays={
            campaign.node_id: {
                "table_role": TableRole.DIMENSION.value,
                "is_entity_universe": True,
                "synonyms": ["campaigns"],
            }
        },
    )
    node = snapshot.nodes[0]
    assert node.table_role == TableRole.DIMENSION
    assert node.is_entity_universe is True
    assert node.synonyms == ["campaigns"]
    assert node.grain
