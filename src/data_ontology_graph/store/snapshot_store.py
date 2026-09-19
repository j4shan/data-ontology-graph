import json
from pathlib import Path

from data_ontology_graph.model.relationship import JoinAnnotation
from data_ontology_graph.model.snapshot import GraphSnapshot, schema_fingerprint


class SnapshotStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def write(self, snapshot: GraphSnapshot) -> Path:
        directory = self.root / snapshot.version / snapshot.built_at.strftime("%Y%m%dT%H%M%SZ")
        directory.mkdir(parents=True, exist_ok=True)
        envelope = {
            "version": snapshot.version,
            "schema_fingerprint": snapshot.schema_fingerprint or schema_fingerprint(),
            "built_at": snapshot.built_at.isoformat(),
        }
        nodes_doc = {**envelope, "nodes": [node.model_dump(mode="json", by_alias=True) for node in snapshot.nodes]}
        edges_doc = {**envelope, "edges": [edge.model_dump(mode="json") for edge in snapshot.edges]}
        annotations_doc = {
            **envelope,
            "annotations": [annotation.model_dump(mode="json") for annotation in snapshot.annotations],
        }
        (directory / "nodes.json").write_text(json.dumps(nodes_doc, indent=2), encoding="utf-8")
        (directory / "edges.json").write_text(json.dumps(edges_doc, indent=2), encoding="utf-8")
        (directory / "annotations.json").write_text(json.dumps(annotations_doc, indent=2), encoding="utf-8")
        (self.root / "latest").write_text(str(directory), encoding="utf-8")
        return directory

    def load_latest(self) -> GraphSnapshot:
        latest = (self.root / "latest").read_text(encoding="utf-8").strip()
        return self.load(Path(latest))

    def load(self, directory: Path) -> GraphSnapshot:
        nodes_doc = json.loads((directory / "nodes.json").read_text(encoding="utf-8"))
        edges_doc = json.loads((directory / "edges.json").read_text(encoding="utf-8"))
        annotations_path = directory / "annotations.json"
        annotations = []
        if annotations_path.exists():
            annotations_doc = json.loads(annotations_path.read_text(encoding="utf-8"))
            annotations = [JoinAnnotation.model_validate(item) for item in annotations_doc["annotations"]]
        return GraphSnapshot.model_validate(
            {
                "version": nodes_doc["version"],
                "schema_fingerprint": nodes_doc.get("schema_fingerprint"),
                "built_at": nodes_doc["built_at"],
                "nodes": nodes_doc["nodes"],
                "edges": edges_doc["edges"],
                "annotations": annotations,
            }
        )
