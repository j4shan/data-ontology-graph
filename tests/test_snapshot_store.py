from pathlib import Path

from data_ontology_graph.builder import build_snapshot_from_yaml
from data_ontology_graph.model.relationship import JoinAnnotation
from data_ontology_graph.store.snapshot_store import CurrentArtifactStore


ROOT = Path(__file__).resolve().parents[1]
VALID_EXAMPLE = ROOT / "resources" / "schema" / "examples" / "intermediary-valid.yaml"


def test_snapshot_round_trip() -> None:
    snapshot, _, _ = build_snapshot_from_yaml(VALID_EXAMPLE)
    edge_id = snapshot.edges[0].edge_id
    snapshot.annotations = [
        JoinAnnotation(edge_id=edge_id, weight=2.0, description="customer relationship")
    ]

    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as directory:
        store = CurrentArtifactStore(Path(directory) / "current")
        store.publish(snapshot)
        loaded = store.load()

    assert loaded.model_dump(mode="json") == snapshot.model_dump(mode="json")
    assert loaded.annotations[0].weight == 2.0
    assert loaded.nodes[0].descriptor.display_name == "Dataset A"
