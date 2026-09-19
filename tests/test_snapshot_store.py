from data_ontology_graph.model.dataset import DatasetNode
from data_ontology_graph.model.enums import Precedence
from data_ontology_graph.model.relationship import JoinAnnotation, JoinEndpoint, make_relationship
from data_ontology_graph.model.snapshot import GraphSnapshot, empty_sql_db_source, now_utc, schema_fingerprint
from data_ontology_graph.store.snapshot_store import SnapshotStore
from data_ontology_graph.model.dataset import ColumnMetadata


def _node(table: str, columns: list[str], primary_key: list[str]) -> DatasetNode:
    return DatasetNode(
        node_id=f"sql_db:demo.{table}",
        table_name=table,
        data_source=empty_sql_db_source("demo", table),
        columns=[ColumnMetadata(name=name) for name in columns],
        primary_key=primary_key,
    )


def test_snapshot_round_trip(tmp_path) -> None:
    campaign = _node("campaign", ["CampaignId"], ["CampaignId"])
    event = _node("event", ["id", "CampaignId"], ["id"])
    rel = make_relationship(
        JoinEndpoint(node_id=event.node_id, columns=["CampaignId"], is_unique=False),
        JoinEndpoint(node_id=campaign.node_id, columns=["CampaignId"], is_unique=True),
        Precedence.DECLARED,
    )
    snapshot = GraphSnapshot(
        built_at=now_utc(),
        schema_fingerprint=schema_fingerprint(),
        nodes=[campaign, event],
        edges=[rel],
        annotations=[JoinAnnotation(edge_id=rel.edge_id, weight=2.0, description="campaign ref")],
    )
    store = SnapshotStore(tmp_path)
    store.write(snapshot)
    loaded = store.load_latest()
    assert loaded.version == snapshot.version
    assert loaded.schema_fingerprint == snapshot.schema_fingerprint
    assert [node.node_id for node in loaded.nodes] == [node.node_id for node in snapshot.nodes]
    assert [edge.edge_id for edge in loaded.edges] == [rel.edge_id]
    assert loaded.annotations[0].weight == 2.0
    assert loaded.edges[0].precedence == Precedence.DECLARED
