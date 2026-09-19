from data_ontology_graph.builder import build_snapshot
from data_ontology_graph.model.dataset import ColumnMetadata, DatasetNode, DeclaredForeignKey
from data_ontology_graph.model.relationship import JoinEndpoint, make_relationship
from data_ontology_graph.model.snapshot import empty_sql_db_source
from data_ontology_graph.query.paths import find_paths
from data_ontology_graph.query.sql_fragments import join_on_sql


def test_join_on_applies_transform() -> None:
    raw = DatasetNode(
        node_id="sql_db:demo.identity",
        table_name="identity",
        data_source=empty_sql_db_source("demo", "identity"),
        columns=[ColumnMetadata(name="IdentityKey")],
        primary_key=["IdentityKey"],
    )
    device = DatasetNode(
        node_id="sql_db:demo.device",
        table_name="device",
        data_source=empty_sql_db_source("demo", "device"),
        columns=[ColumnMetadata(name="DeviceIdHash64")],
        primary_key=["DeviceIdHash64"],
    )
    rel = make_relationship(
        JoinEndpoint(node_id=raw.node_id, columns=["IdentityKey"], is_unique=True, transform="xxhash64"),
        JoinEndpoint(node_id=device.node_id, columns=["DeviceIdHash64"], is_unique=True),
    )
    sql = join_on_sql(rel, raw, device)
    assert sql == 'xxhash64("identity"."IdentityKey") = "device"."DeviceIdHash64"'


def test_find_paths_ranks_shorter_first() -> None:
    a = DatasetNode(
        node_id="a",
        table_name="a",
        data_source=empty_sql_db_source("demo", "a"),
        columns=[ColumnMetadata(name="a_id")],
        primary_key=["a_id"],
    )
    b = DatasetNode(
        node_id="b",
        table_name="b",
        data_source=empty_sql_db_source("demo", "b"),
        columns=[ColumnMetadata(name="b_id"), ColumnMetadata(name="a_id")],
        primary_key=["b_id"],
    )
    c = DatasetNode(
        node_id="c",
        table_name="c",
        data_source=empty_sql_db_source("demo", "c"),
        columns=[ColumnMetadata(name="c_id"), ColumnMetadata(name="b_id")],
        primary_key=["c_id"],
    )
    b = b.model_copy(
        update={
            "foreign_key_declarations": [
                DeclaredForeignKey(local_columns=["a_id"], ref_table="a", ref_columns=["a_id"])
            ]
        }
    )
    c = c.model_copy(
        update={
            "foreign_key_declarations": [
                DeclaredForeignKey(local_columns=["b_id"], ref_table="b", ref_columns=["b_id"])
            ]
        }
    )
    snapshot, _, _ = build_snapshot([a, b, c])
    paths = find_paths(snapshot, a.node_id, c.node_id, max_hops=3)
    assert paths
    assert len(paths[0]) == 2
