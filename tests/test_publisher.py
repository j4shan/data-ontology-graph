import json
import os
from pathlib import Path

import pytest

from data_ontology_graph.builder import IntermediaryValidationError
from data_ontology_graph.builder.publish import publish_current_artifact
from data_ontology_graph.store.snapshot_store import CurrentArtifactStore, SnapshotStore


ROOT = Path(__file__).resolve().parents[1]
VALID_EXAMPLE = ROOT / "resources" / "schema" / "examples" / "intermediary-valid.yaml"


def _yaml_directory(tmp_path: Path) -> Path:
    directory = tmp_path / "yaml"
    directory.mkdir()
    (directory / "catalog.yaml").write_text(
        VALID_EXAMPLE.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return directory


def _artifact_bytes(directory: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(directory.iterdir())}


def test_publisher_replaces_one_current_artifact(tmp_path: Path) -> None:
    yaml_directory = _yaml_directory(tmp_path)
    artifact = tmp_path / "current"

    published, report = publish_current_artifact(yaml_directory, artifact)

    assert published == artifact
    assert report.node_count == 2
    assert {path.name for path in artifact.iterdir()} == {
        "annotations.json",
        "edges.json",
        "nodes.json",
    }
    assert CurrentArtifactStore(artifact).load().nodes
    assert not [path for path in tmp_path.iterdir() if ".previous-" in path.name]


def test_invalid_build_leaves_current_artifact_unchanged(tmp_path: Path) -> None:
    yaml_directory = _yaml_directory(tmp_path)
    artifact = tmp_path / "current"
    publish_current_artifact(yaml_directory, artifact)
    before = _artifact_bytes(artifact)
    (yaml_directory / "unsupported.json").write_text("{}", encoding="utf-8")

    with pytest.raises(IntermediaryValidationError):
        publish_current_artifact(yaml_directory, artifact)

    assert _artifact_bytes(artifact) == before


def test_publisher_refuses_to_replace_an_unrelated_directory(tmp_path: Path) -> None:
    yaml_directory = _yaml_directory(tmp_path)
    artifact = tmp_path / "current"
    artifact.mkdir()
    marker = artifact / "user-data.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(RuntimeError, match="not a loadable artifact"):
        publish_current_artifact(yaml_directory, artifact)

    assert marker.read_text(encoding="utf-8") == "keep"


def test_failed_replacement_restores_current_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    yaml_directory = _yaml_directory(tmp_path)
    artifact = tmp_path / "current"
    publish_current_artifact(yaml_directory, artifact)
    before = _artifact_bytes(artifact)
    real_replace = os.replace

    def fail_candidate_promotion(source: Path, destination: Path) -> None:
        if Path(source).name.startswith(".current.candidate-") and Path(destination) == artifact:
            raise OSError("promotion failed")
        real_replace(source, destination)

    monkeypatch.setattr("data_ontology_graph.store.snapshot_store.os.replace", fail_candidate_promotion)

    with pytest.raises(OSError, match="promotion failed"):
        publish_current_artifact(yaml_directory, artifact)

    assert _artifact_bytes(artifact) == before
    assert not [path for path in tmp_path.iterdir() if ".previous-" in path.name]


def test_loader_rejects_mixed_build_envelopes(tmp_path: Path) -> None:
    yaml_directory = _yaml_directory(tmp_path)
    artifact = tmp_path / "current"
    publish_current_artifact(yaml_directory, artifact)
    edges_path = artifact / "edges.json"
    edges = json.loads(edges_path.read_text(encoding="utf-8"))
    edges["built_at"] = "2000-01-01T00:00:00+00:00"
    edges_path.write_text(json.dumps(edges), encoding="utf-8")

    with pytest.raises(ValueError, match="edges.json built_at does not match nodes.json"):
        SnapshotStore(tmp_path).load(artifact)
