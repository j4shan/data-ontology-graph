import json
from pathlib import Path

import pytest

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


def test_snapshot_reconstructs_canonical_pair_order_and_directions(tmp_path: Path) -> None:
    snapshot, _, _ = build_snapshot_from_yaml(VALID_EXAMPLE)
    canonical = snapshot.edges[0]
    reversed_relationship = JoinRelationship(
        edge_id=edge_id_for(canonical.endpoint_b, canonical.endpoint_a),
        endpoint_a=canonical.endpoint_b,
        endpoint_b=canonical.endpoint_a,
        a_to_b=canonical.b_to_a,
        b_to_a=canonical.a_to_b,
    )
    snapshot = type(snapshot).model_validate({
        **snapshot.model_dump(), "edges": [reversed_relationship],
    })

    artifact = tmp_path / "current"
    store = CurrentArtifactStore(artifact)
    store.publish(snapshot)
    assert not (artifact / "edges.json").exists()
    persisted = store.load().edges[0].model_dump(mode="json")

    assert persisted["endpoint_a"]["node_id"] == "dataset_a"
    assert persisted["endpoint_b"]["node_id"] == "dataset_b"
    assert persisted["a_to_b"] == canonical.a_to_b.model_dump(mode="json")
    assert persisted["b_to_a"] == canonical.b_to_a.model_dump(mode="json")
    loaded = store.load().edges[0]
    assert loaded.model_dump(mode="json") == canonical.model_dump(mode="json")


def test_build_publish_load_and_reporting_do_not_enumerate_pairs(tmp_path, monkeypatch) -> None:
    from data_ontology_graph.model import derivation

    def unexpected_pair(**kwargs):
        pytest.fail("build, persistence, validation, and reports must not construct pairs")

    monkeypatch.setattr(derivation, "JoinRelationship", unexpected_pair)
    snapshot, report, _ = build_snapshot_from_yaml(VALID_EXAMPLE)
    assert report.edge_count == len(snapshot.memberships) == 1
    assert not any(location.startswith("edges[") for location in report.unknown_fields)
    left, right = snapshot.memberships.by_identity["customer_identity"]
    edge_id = snapshot.memberships.edge_id(left, right)
    snapshot.annotations = [JoinAnnotation(edge_id=edge_id, description="selected pair")]
    store = CurrentArtifactStore(tmp_path / "current")
    store.publish(snapshot)
    loaded = store.load()
    assert loaded.annotations[0].edge_id == edge_id
    assert len(loaded.memberships) == 1
    assert "edges" not in loaded.model_dump()
    assert set(path.name for path in store.directory.iterdir()) == {"nodes.json", "annotations.json"}


def test_legacy_artifact_is_validated_and_republished_without_edges(tmp_path) -> None:
    snapshot, _, _ = build_snapshot_from_yaml(VALID_EXAMPLE)
    canonical = snapshot.edges[0]
    snapshot.annotations = [JoinAnnotation(edge_id=canonical.edge_id, tags=["legacy"])]
    store = CurrentArtifactStore(tmp_path / "current")
    store.publish(snapshot)
    legacy_path = store.directory / "edges.json"
    legacy_path.write_text(json.dumps({
        "version": snapshot.version, "edges": [canonical.model_dump(mode="json")],
    }))
    loaded = store.load()
    assert loaded.legacy_edges is None
    assert loaded.edges[0] == canonical
    assert loaded.annotations == snapshot.annotations
    # Replacing a valid old artifact must succeed and discard its redundant edge file.
    store.publish(loaded)
    assert not legacy_path.exists()
    assert store.load().model_dump() == snapshot.model_dump()


@pytest.mark.parametrize("problem", ["claim", "duplicate", "version", "missing_endpoint"])
def test_invalid_legacy_relationships_are_rejected(tmp_path, problem) -> None:
    snapshot, _, _ = build_snapshot_from_yaml(VALID_EXAMPLE)
    store = CurrentArtifactStore(tmp_path / "current")
    store.publish(snapshot)
    edge = snapshot.edges[0].model_dump(mode="json")
    legacy = {"version": snapshot.version, "edges": [edge]}
    if problem == "claim":
        edge["a_to_b"]["multiplicity"] = "unknown"
    elif problem == "duplicate":
        legacy["edges"].append(edge)
    elif problem == "version":
        legacy["version"] = "2000-01-01T00:00:00Z"
    else:
        edge["endpoint_b"]["node_id"] = "missing"
        from data_ontology_graph.model.relationship import JoinEndpoint
        edge["edge_id"] = edge_id_for(
            JoinEndpoint.model_validate(edge["endpoint_a"]),
            JoinEndpoint.model_validate(edge["endpoint_b"]),
        )
    (store.directory / "edges.json").write_text(json.dumps(legacy))
    with pytest.raises(ValueError):
        store.load()


def test_sparse_annotations_require_a_resolvable_unique_pair() -> None:
    snapshot, _, _ = build_snapshot_from_yaml(VALID_EXAMPLE)
    edge_id = snapshot.edges[0].edge_id
    for annotations, message in [
        ([{"edge_id": "missing"}], "unknown edge"),
        ([{"edge_id": edge_id}, {"edge_id": edge_id}], "annotation edge_id values must be unique"),
    ]:
        with pytest.raises(ValueError, match=message):
            type(snapshot).model_validate({**snapshot.model_dump(), "annotations": annotations})
