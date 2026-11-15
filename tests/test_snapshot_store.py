import json
from pathlib import Path

import pytest

from data_ontology_graph.builder import build_snapshot_from_yaml
from data_ontology_graph.model.relationship import (
    JoinAnnotation,
)
from data_ontology_graph.store.snapshot_store import CurrentArtifactStore
from graph_records import first_relationship


ROOT = Path(__file__).resolve().parents[1]
VALID_EXAMPLE = ROOT / "resources" / "schema" / "examples" / "intermediary-valid.yaml"


def test_snapshot_round_trip() -> None:
    snapshot, _ = build_snapshot_from_yaml(VALID_EXAMPLE)
    edge_id = first_relationship(snapshot).edge_id
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


def test_published_snapshot_derives_the_same_canonical_relationship(tmp_path: Path) -> None:
    snapshot, _ = build_snapshot_from_yaml(VALID_EXAMPLE)
    canonical = first_relationship(snapshot)

    artifact = tmp_path / "current"
    store = CurrentArtifactStore(artifact)
    store.publish(snapshot)
    assert not (artifact / "edges.json").exists()
    loaded = first_relationship(store.load())

    assert loaded.endpoint_a.node_id == "dataset_a"
    assert loaded.endpoint_b.node_id == "dataset_b"
    assert loaded.model_dump(mode="json") == canonical.model_dump(mode="json")

def test_build_publish_load_and_reporting_do_not_enumerate_pairs(tmp_path, monkeypatch) -> None:
    from data_ontology_graph.model import derivation

    def unexpected_pair(**kwargs):
        pytest.fail("build, persistence, validation, and reports must not construct pairs")

    monkeypatch.setattr(derivation, "JoinRelationship", unexpected_pair)
    snapshot, report = build_snapshot_from_yaml(VALID_EXAMPLE)
    assert report.entity_definition_count == 2
    assert not any(location.startswith("edges[") for location in report.unknown_fields)
    left, right = snapshot.memberships.by_identity["customer_identity"]
    edge_id = snapshot.memberships.edge_id(left, right)
    snapshot.annotations = [JoinAnnotation(edge_id=edge_id, description="selected pair")]
    store = CurrentArtifactStore(tmp_path / "current")
    store.publish(snapshot)
    loaded = store.load()
    assert loaded.annotations[0].edge_id == edge_id
    assert loaded.memberships.entity_definition_count == 2
    assert "edges" not in loaded.model_dump()
    assert set(path.name for path in store.directory.iterdir()) == {
        "nodes.json", "annotations.json", "entity_relationships.json"
    }


def test_stored_relationship_artifact_is_refused_with_republication_advice(tmp_path) -> None:
    snapshot, _ = build_snapshot_from_yaml(VALID_EXAMPLE)
    store = CurrentArtifactStore(tmp_path / "current")
    store.publish(snapshot)
    (store.directory / "edges.json").write_text(json.dumps({"version": snapshot.version, "edges": []}))
    with pytest.raises(ValueError, match="republish the graph from its YAML source"):
        store.load()


def test_sparse_annotations_require_a_resolvable_unique_pair() -> None:
    snapshot, _ = build_snapshot_from_yaml(VALID_EXAMPLE)
    edge_id = first_relationship(snapshot).edge_id
    for annotations, message in [
        ([{"edge_id": "missing"}], "unknown edge"),
        ([{"edge_id": edge_id}, {"edge_id": edge_id}], "annotation edge_id values must be unique"),
    ]:
        with pytest.raises(ValueError, match=message):
            type(snapshot).model_validate({**snapshot.model_dump(), "annotations": annotations})


STATED = ROOT / "tests" / "fixtures" / "stated_relationships" / "catalog.yaml"


def test_cross_entity_relationships_round_trip_and_rebuild_the_index(tmp_path) -> None:
    snapshot, _ = build_snapshot_from_yaml(STATED)
    store = CurrentArtifactStore(tmp_path / "current")
    store.publish(snapshot)
    loaded = store.load()
    assert loaded.entity_relationships == snapshot.entity_relationships
    index = loaded.entity_relationship_index
    assert list(index.related("hashed_id_identity")) == ["click_identity", "conversion_identity"]
    assert index.between("click_identity", "impression_identity") is index.between(
        "impression_identity", "click_identity"
    )
    assert list(index.related("employee_identity")) == ["employee_identity"]
    assert index.relationship_count == 6


def test_artifact_without_cross_entity_relationship_file_has_none(tmp_path) -> None:
    snapshot, _ = build_snapshot_from_yaml(STATED)
    store = CurrentArtifactStore(tmp_path / "current")
    store.publish(snapshot)
    (store.directory / "entity_relationships.json").unlink()
    assert store.load().entity_relationships == []


def test_cross_entity_relationship_file_must_match_the_snapshot_version(tmp_path) -> None:
    snapshot, _ = build_snapshot_from_yaml(STATED)
    store = CurrentArtifactStore(tmp_path / "current")
    store.publish(snapshot)
    path = store.directory / "entity_relationships.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["version"] = "2000-01-01T00:00:00Z"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="entity_relationships.json version does not match"):
        store.load()
