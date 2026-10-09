import json
from pathlib import Path

from data_ontology_graph.builder import build_snapshot_from_yaml
from data_ontology_graph.model.relationship import (
    JoinAnnotation,
    JoinRelationship,
    edge_id_for,
)
from data_ontology_graph.store.snapshot_store import CurrentArtifactStore


ROOT = Path(__file__).resolve().parents[1]
VALID_EXAMPLE = ROOT / "resources" / "schema" / "examples" / "intermediary-valid.yaml"


def test_snapshot_round_trip() -> None:
    snapshot, _, _ = build_snapshot_from_yaml(VALID_EXAMPLE)
    edge_id = snapshot.edges[0].edge_id
    snapshot.annotations = [
        JoinAnnotation(edge_id=edge_id, description="customer relationship", tags=["core"])
    ]

    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as directory:
        store = CurrentArtifactStore(Path(directory) / "current")
        store.publish(snapshot)
        loaded = store.load()

    assert loaded.model_dump(mode="json") == snapshot.model_dump(mode="json")
    assert loaded.annotations[0].tags == ["core"]
    assert loaded.nodes[0].descriptor.display_name == "Dataset A"


def test_snapshot_persists_canonical_edge_order_and_swapped_directions(tmp_path: Path) -> None:
    snapshot, _, _ = build_snapshot_from_yaml(VALID_EXAMPLE)
    canonical = snapshot.edges[0]
    reversed_relationship = JoinRelationship(
        edge_id=edge_id_for(canonical.endpoint_b, canonical.endpoint_a),
        endpoint_a=canonical.endpoint_b,
        endpoint_b=canonical.endpoint_a,
        a_to_b=canonical.b_to_a,
        b_to_a=canonical.a_to_b,
    )
    snapshot.edges = [reversed_relationship]

    artifact = tmp_path / "current"
    store = CurrentArtifactStore(artifact)
    store.publish(snapshot)
    persisted = json.loads((artifact / "edges.json").read_text(encoding="utf-8"))["edges"][0]

    assert persisted["endpoint_a"]["node_id"] == "dataset_a"
    assert persisted["endpoint_b"]["node_id"] == "dataset_b"
    assert persisted["a_to_b"] == canonical.a_to_b.model_dump(mode="json")
    assert persisted["b_to_a"] == canonical.b_to_a.model_dump(mode="json")
    loaded = store.load().edges[0]
    assert loaded.model_dump(mode="json") == canonical.model_dump(mode="json")
