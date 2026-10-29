from __future__ import annotations

import argparse
from pathlib import Path

from data_ontology_graph.builder import build_snapshot_from_yaml
from data_ontology_graph.builder.report import ExplicitBuildReport
from data_ontology_graph.home import default_artifact, ensure_service_home
from data_ontology_graph.store.snapshot_store import CurrentArtifactStore


def publish_current_artifact(
    yaml_directory: Path,
    artifact_directory: Path,
) -> tuple[Path, ExplicitBuildReport]:
    snapshot, report, _ = build_snapshot_from_yaml(yaml_directory)
    published = CurrentArtifactStore(artifact_directory).publish(snapshot)
    return published, report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build and replace the current ontology graph artifact"
    )
    parser.add_argument("--yaml-dir", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, default=None,
                        help="artifact to replace (default: the service home's current-graph)")
    args = parser.parse_args()
    if args.artifact_dir is None:
        ensure_service_home()
    published, _ = publish_current_artifact(args.yaml_dir, args.artifact_dir or default_artifact())
    print(published)


if __name__ == "__main__":
    main()
