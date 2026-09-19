import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from data_ontology_graph.api.app import create_app
from data_ontology_graph.builder import build_snapshot, ingest_sqlite
from data_ontology_graph.model.relationship import JoinAnnotation
from data_ontology_graph.store.snapshot_store import SnapshotStore

ROOT = Path(__file__).resolve().parents[1]
STUDENT = ROOT / "resources" / "data" / "dev_databases" / "student_club" / "student_club.sqlite"
OVERLAYS = ROOT / "resources" / "data" / "dev_overlays" / "student_club" / "overlay.json"
ANNOTATIONS = ROOT / "resources" / "data" / "dev_overlays" / "student_club" / "annotations.json"


def _write_student_club_snapshot(root: Path) -> None:
    overlays = json.loads(OVERLAYS.read_text())
    annotations = [JoinAnnotation.model_validate(item) for item in json.loads(ANNOTATIONS.read_text())["annotations"]]
    nodes = ingest_sqlite(STUDENT, database="student_club")
    snapshot, _, _ = build_snapshot(nodes, overlays, annotations)
    SnapshotStore(root).write(snapshot)


def _client(tmp_path: Path) -> TestClient:
    root = tmp_path / "snapshots"
    _write_student_club_snapshot(root)
    return TestClient(create_app(root))


def test_health_and_openapi(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client.get("/health").json()["status"] == "ok"
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    assert spec.json()["info"]["title"] == "Data Ontology Graph"
    paths = spec.json()["paths"]
    assert not any(path.startswith("/updates") for path in paths)


def test_http_api_does_not_accept_updates(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for path in (
        "/updates/catalog",
        "/updates/overlay",
        "/updates/annotations",
        "/updates/rebuild",
    ):
        response = client.post(path, json={})
        assert response.status_code == 404


def test_read_snapshot_search_hops_paths_and_sql(tmp_path: Path) -> None:
    client = _client(tmp_path)

    snapshot = client.get("/graph/snapshot")
    assert snapshot.status_code == 200
    assert snapshot.json()["edge_count"] >= 1

    search = client.get("/ontology/search", params={"q": "member"})
    assert search.status_code == 200
    ids = {item["node_id"] for item in search.json()}
    assert "sql_db:student_club.member" in ids

    detail = client.get("/graph/nodes/sql_db:student_club.event")
    assert detail.status_code == 200
    assert detail.json()["table_role"] == "dimension"
    assert detail.json()["grain"]

    hops = client.get("/ontology/nodes/sql_db:student_club.expense/hops")
    assert hops.status_code == 200
    assert hops.json()

    paths = client.post(
        "/ontology/paths",
        json={
            "from_node_id": "sql_db:student_club.expense",
            "to_node_id": "sql_db:student_club.event",
            "max_hops": 4,
        },
    )
    assert paths.status_code == 200
    assert paths.json()
    first = paths.json()[0]
    assert first["length"] >= 1
    assert first["hops"][0]["recommended_join"] in {"INNER", "LEFT"}
    assert "sql_on" in first["hops"][0]

    hop = first["hops"][0]
    join = client.post(
        "/ontology/sql/join-on",
        json={"edge_id": hop["edge_id"], "from_node_id": hop["from_node_id"]},
    )
    assert join.status_code == 200
    sql_on = join.json()["sql_on"]
    assert " = " in sql_on

    columns = client.get("/ontology/nodes/sql_db:student_club.expense/columns")
    assert columns.status_code == 200
    assert any(item["name"] == "cost" for item in columns.json())

    from_table = hop["from_node_id"].rsplit(".", 1)[-1]
    to_table = hop["to_node_id"].rsplit(".", 1)[-1]
    query = f'SELECT 1 FROM "{from_table}" {join.json()["recommended_join"]} JOIN "{to_table}" ON {sql_on} LIMIT 1'
    connection = sqlite3.connect(STUDENT)
    try:
        connection.execute(query).fetchall()
    finally:
        connection.close()
