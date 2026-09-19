from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from data_ontology_graph.api.ontology import (
    column_guidance,
    hops_from,
    node_detail,
    path_payloads,
    search_nodes,
)
from data_ontology_graph.query.sql_fragments import hop_join_type, join_on_sql
from data_ontology_graph.store.snapshot_store import SnapshotStore


def create_app(snapshot_root: Path | None = None) -> FastAPI:
    root = snapshot_root or Path("data/snapshots")
    store = SnapshotStore(root)
    snapshot = None
    try:
        snapshot = store.load_latest()
    except FileNotFoundError:
        pass
    app = FastAPI(title="Data Ontology Graph", version="0.1.0")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/graph/snapshot")
    def graph_snapshot() -> dict:
        current = _require_snapshot(snapshot)
        return {
            "version": current.version,
            "schema_fingerprint": current.schema_fingerprint,
            "built_at": current.built_at.isoformat(),
            "node_count": len(current.nodes),
            "edge_count": len(current.edges),
        }

    @app.get("/graph/nodes")
    def graph_nodes() -> list[dict]:
        current = _require_snapshot(snapshot)
        return [
            {"node_id": node.node_id, "table_name": node.table_name, "table_role": node.table_role.value}
            for node in current.nodes
        ]

    @app.get("/graph/nodes/{node_id:path}")
    def graph_node(node_id: str) -> dict:
        current = _require_snapshot(snapshot)
        try:
            return node_detail(current, node_id)
        except KeyError as exc:
            raise HTTPException(404, f"unknown node {node_id}") from exc

    @app.get("/graph/edges")
    def graph_edges() -> list[dict]:
        current = _require_snapshot(snapshot)
        return [edge.model_dump(mode="json") for edge in current.edges]

    @app.get("/ontology/search")
    def ontology_search(q: str) -> list[dict]:
        return search_nodes(_require_snapshot(snapshot), q)

    @app.get("/ontology/nodes/{node_id:path}/hops")
    def ontology_hops(node_id: str) -> list[dict]:
        return hops_from(_require_snapshot(snapshot), node_id)

    @app.get("/ontology/nodes/{node_id:path}/columns")
    def ontology_columns(node_id: str) -> list[dict]:
        try:
            return column_guidance(_require_snapshot(snapshot), node_id)
        except KeyError as exc:
            raise HTTPException(404, f"unknown node {node_id}") from exc

    class PathRequest(BaseModel):
        from_node_id: str
        to_node_id: str
        max_hops: int = 4

    @app.post("/ontology/paths")
    def ontology_paths(request: PathRequest) -> list[dict]:
        return path_payloads(
            _require_snapshot(snapshot),
            request.from_node_id,
            request.to_node_id,
            request.max_hops,
        )

    class JoinOnRequest(BaseModel):
        edge_id: str
        from_node_id: str

    @app.post("/ontology/sql/join-on")
    def ontology_join_on(request: JoinOnRequest) -> dict:
        current = _require_snapshot(snapshot)
        edge = next((item for item in current.edges if item.edge_id == request.edge_id), None)
        if edge is None:
            raise HTTPException(404, f"unknown edge {request.edge_id}")
        to_node_id = edge.opposite(request.from_node_id).node_id
        nodes = current.node_map()
        sql = join_on_sql(edge, nodes[request.from_node_id], nodes[to_node_id])
        source = edge.endpoint(request.from_node_id)
        return {
            "sql_on": sql,
            "recommended_join": hop_join_type(source),
            "transform": source.transform,
        }

    app.state.store = store
    app.state.snapshot = snapshot
    return app


def _require_snapshot(snapshot):
    if snapshot is None:
        raise HTTPException(404, "no snapshot")
    return snapshot


app = create_app()
