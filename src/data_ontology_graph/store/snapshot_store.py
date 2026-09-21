import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from data_ontology_graph.model.dataset import DatasetNode
from data_ontology_graph.model.relationship import JoinAnnotation
from data_ontology_graph.model.snapshot import GraphSnapshot, schema_fingerprint


class SnapshotStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def load(self, directory: Path) -> GraphSnapshot:
        nodes_doc = json.loads((directory / "nodes.json").read_text(encoding="utf-8"))
        edges_doc = json.loads((directory / "edges.json").read_text(encoding="utf-8"))
        _require_same_envelope(nodes_doc, edges_doc, "edges.json")
        annotations_path = directory / "annotations.json"
        annotations = []
        if annotations_path.exists():
            annotations_doc = json.loads(annotations_path.read_text(encoding="utf-8"))
            _require_same_envelope(nodes_doc, annotations_doc, "annotations.json")
            annotations = [JoinAnnotation.model_validate(item) for item in annotations_doc["annotations"]]
        return GraphSnapshot.model_validate(
            {
                "version": nodes_doc["version"],
                "schema_fingerprint": nodes_doc.get("schema_fingerprint"),
                "built_at": nodes_doc["built_at"],
                "logical_identities": nodes_doc.get("logical_identities", []),
                "nodes": nodes_doc["nodes"],
                "edges": edges_doc["edges"],
                "annotations": annotations,
            }
        )


class CurrentArtifactStore:
    """Publish one complete current artifact without retaining prior releases."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def load(self) -> GraphSnapshot:
        return SnapshotStore(self.directory.parent).load(self.directory)

    def publish(self, snapshot: GraphSnapshot) -> Path:
        target = self.directory
        parent = target.parent
        parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not target.is_dir():
            raise RuntimeError(f"current artifact path is not a directory: {target}")
        if target.exists():
            try:
                self.load()
            except Exception as error:
                raise RuntimeError(
                    f"refusing to replace a directory that is not a loadable artifact: {target}"
                ) from error

        staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.candidate-", dir=parent))
        backup = parent / f".{target.name}.previous-{uuid.uuid4().hex}"
        moved_current = False
        try:
            _write_snapshot_directory(staging, snapshot)
            SnapshotStore(parent).load(staging)
            if target.exists():
                os.replace(target, backup)
                moved_current = True
            try:
                os.replace(staging, target)
            except Exception:
                if moved_current:
                    os.replace(backup, target)
                    moved_current = False
                raise
        finally:
            if staging.exists():
                shutil.rmtree(staging)

        if moved_current:
            shutil.rmtree(backup)
        return target


def _serialize_node(node: DatasetNode) -> dict:
    return node.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
        exclude_defaults=True,
    )


def _write_snapshot_directory(directory: Path, snapshot: GraphSnapshot) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    envelope = {
        "version": snapshot.version,
        "schema_fingerprint": snapshot.schema_fingerprint or schema_fingerprint(),
        "built_at": snapshot.built_at.isoformat(),
    }
    nodes_doc = {
        **envelope,
        "logical_identities": [
            identity.model_dump(mode="json", exclude_defaults=True)
            for identity in snapshot.logical_identities
        ],
        "nodes": [_serialize_node(node) for node in snapshot.nodes],
    }
    edges_doc = {
        **envelope,
        "edges": [
            edge.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
            for edge in snapshot.edges
        ],
    }
    annotations_doc = {
        **envelope,
        "annotations": [
            annotation.model_dump(mode="json", exclude_defaults=True)
            for annotation in snapshot.annotations
        ],
    }
    (directory / "nodes.json").write_text(json.dumps(nodes_doc, indent=2), encoding="utf-8")
    (directory / "edges.json").write_text(json.dumps(edges_doc, indent=2), encoding="utf-8")
    (directory / "annotations.json").write_text(
        json.dumps(annotations_doc, indent=2),
        encoding="utf-8",
    )


def _require_same_envelope(reference: dict, candidate: dict, filename: str) -> None:
    for field in ("version", "schema_fingerprint", "built_at"):
        if candidate.get(field) != reference.get(field):
            raise ValueError(f"{filename} {field} does not match nodes.json")
