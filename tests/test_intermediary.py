import json
from pathlib import Path

import yaml

from data_ontology_graph.builder import (
    IntermediaryValidationError,
    build_snapshot_from_yaml,
    load_intermediary_directory,
    load_intermediary_yaml,
    validate_intermediary_yaml,
)
from data_ontology_graph.builder.intermediary import (
    intermediary_directory_json_schema,
    intermediary_json_schema,
)
from data_ontology_graph.model.enums import EntityUniverse, MatchExistence, Multiplicity
from data_ontology_graph.store.snapshot_store import CurrentArtifactStore


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "resources" / "schema" / "intermediary.schema.json"
DIRECTORY_SCHEMA = ROOT / "resources" / "schema" / "intermediary-directory.schema.json"
VALID_EXAMPLE = ROOT / "resources" / "schema" / "examples" / "intermediary-valid.yaml"
INVALID_EXAMPLE = ROOT / "resources" / "schema" / "examples" / "intermediary-invalid.yaml"
LENDING = ROOT / "tests" / "fixtures" / "lending" / "catalog.yaml"


def _write_yaml(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _manifest_directory(tmp_path: Path, *, split_nodes: bool = True) -> tuple[Path, dict]:
    payload = yaml.safe_load(VALID_EXAMPLE.read_text(encoding="utf-8"))
    yaml_directory = tmp_path / "yaml"
    yaml_directory.mkdir()
    _write_yaml(
        yaml_directory / "identities.yaml",
        {
            "schema_version": "3",
            "logical_identities": payload["logical_identities"],
        },
    )
    node_paths = ["nodes-b.yaml", "nodes-a.yaml"] if split_nodes else ["nodes.yaml"]
    if split_nodes:
        _write_yaml(
            yaml_directory / node_paths[0],
            {"schema_version": "3", "nodes": [payload["nodes"][1]]},
        )
        _write_yaml(
            yaml_directory / node_paths[1],
            {"schema_version": "3", "nodes": [payload["nodes"][0]]},
        )
    else:
        _write_yaml(
            yaml_directory / node_paths[0],
            {"schema_version": "3", "nodes": payload["nodes"]},
        )
    _write_yaml(
        yaml_directory / "edges.yaml",
        {"schema_version": "3", "edges": payload["edges"]},
    )
    _write_yaml(
        tmp_path / "directory-manifest.yaml",
        {
            "schema_version": "3",
            "logical_identities": "identities.yaml",
            "nodes": node_paths,
            "edges": "edges.yaml",
        },
    )
    return yaml_directory, payload


def _rules(path: Path) -> set[str]:
    return {finding.rule for finding in validate_intermediary_yaml(path).findings}


def test_source_controlled_schema_matches_validator_model() -> None:
    assert json.loads(SCHEMA.read_text(encoding="utf-8")) == intermediary_json_schema()
    assert json.loads(DIRECTORY_SCHEMA.read_text(encoding="utf-8")) == (
        intermediary_directory_json_schema()
    )


def test_examples_show_acceptance_and_actionable_rejection() -> None:
    assert validate_intermediary_yaml(VALID_EXAMPLE).valid is True

    report = validate_intermediary_yaml(INVALID_EXAMPLE)
    assert report.valid is False
    assert report.findings[0].location == (
        "$.nodes[0].entity_definitions[0].dataset_columns"
    )
    assert report.findings[0].rule == "value_error"
    assert "ascending exact-name order" in report.findings[0].message

    try:
        load_intermediary_yaml(INVALID_EXAMPLE)
    except IntermediaryValidationError as error:
        assert error.findings == report.findings
    else:
        raise AssertionError("invalid intermediary reached ingestion")


def test_yaml_syntax_finding_includes_line_and_column(tmp_path: Path) -> None:
    invalid = tmp_path / "syntax.yaml"
    invalid.write_text("schema_version: '2'\nnodes: [\n", encoding="utf-8")
    report = validate_intermediary_yaml(invalid)
    assert report.valid is False
    assert report.findings[0].rule == "yaml_syntax"
    assert report.findings[0].line is not None
    assert report.findings[0].column is not None


def test_unresolved_edge_endpoint_is_rejected_before_build(tmp_path: Path) -> None:
    payload = yaml.safe_load(VALID_EXAMPLE.read_text(encoding="utf-8"))
    payload["edges"][0]["endpoint_b"]["dataset_columns"] = ["missing"]
    invalid = tmp_path / "unresolved.yaml"
    invalid.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    report = validate_intermediary_yaml(invalid)
    assert report.valid is False
    assert report.findings[0].location == "$"
    assert "does not resolve to a registered entity definition" in report.findings[0].message


def test_unresolved_grain_identity_is_rejected_before_build(tmp_path: Path) -> None:
    payload = yaml.safe_load(VALID_EXAMPLE.read_text(encoding="utf-8"))
    payload["nodes"][0]["grain"]["components"][0]["identity_id"] = "missing"
    invalid = tmp_path / "unresolved-grain.yaml"
    invalid.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    report = validate_intermediary_yaml(invalid)
    assert report.valid is False
    assert "grain component does not resolve" in report.findings[0].message


def test_manifest_directory_is_assembled_deterministically(tmp_path: Path) -> None:
    yaml_directory, payload = _manifest_directory(tmp_path)

    definition = load_intermediary_directory(yaml_directory)
    snapshot, report, _ = build_snapshot_from_yaml(yaml_directory)

    assert [node.node_id for node in definition.nodes] == sorted(
        node["node_id"] for node in payload["nodes"]
    )
    assert [edge.canonical_edge_id() for edge in definition.edges] == sorted(
        edge.canonical_edge_id() for edge in definition.edges
    )
    assert report.node_count == len(payload["nodes"])
    assert len(snapshot.edges) == len(payload["edges"])


def test_standalone_single_file_catalog_remains_supported() -> None:
    assert validate_intermediary_yaml(VALID_EXAMPLE).valid is True
    assert load_intermediary_yaml(VALID_EXAMPLE).schema_version == "3"


def test_directory_requires_valid_sibling_manifest(tmp_path: Path) -> None:
    yaml_directory = tmp_path / "yaml"
    yaml_directory.mkdir()
    assert _rules(yaml_directory) == {"missing_manifest"}

    (tmp_path / "directory-manifest.yaml").write_text("nodes: [\n", encoding="utf-8")
    report = validate_intermediary_yaml(yaml_directory)
    assert report.valid is False
    assert report.findings[0].rule == "yaml_syntax"
    assert report.findings[0].line is not None


def test_manifest_requires_version_three_and_all_collection_owners(tmp_path: Path) -> None:
    yaml_directory = tmp_path / "yaml"
    yaml_directory.mkdir()
    _write_yaml(
        tmp_path / "directory-manifest.yaml",
        {"schema_version": "2", "logical_identities": "identities.yaml", "nodes": []},
    )

    report = validate_intermediary_yaml(yaml_directory)
    assert report.valid is False
    locations = {finding.location for finding in report.findings}
    assert "directory-manifest.yaml:$.schema_version" in locations
    assert "directory-manifest.yaml:$.nodes" in locations
    assert "directory-manifest.yaml:$.edges" in locations


def test_directory_rejects_unlisted_and_unsupported_files(tmp_path: Path) -> None:
    yaml_directory, _ = _manifest_directory(tmp_path)
    _write_yaml(yaml_directory / "surprise.yaml", {"schema_version": "3", "nodes": []})
    (yaml_directory / "notes.json").write_text("{}", encoding="utf-8")

    report = validate_intermediary_yaml(yaml_directory)
    assert report.valid is False
    assert {(finding.location, finding.rule) for finding in report.findings} >= {
        ("surprise.yaml", "unlisted_file"),
        ("notes.json", "unsupported_file"),
    }


def test_directory_rejects_missing_listed_file(tmp_path: Path) -> None:
    yaml_directory, _ = _manifest_directory(tmp_path)
    (yaml_directory / "edges.yaml").unlink()

    assert "missing_file" in _rules(yaml_directory)


def test_manifest_rejects_duplicate_and_cross_collection_paths(tmp_path: Path) -> None:
    yaml_directory, _ = _manifest_directory(tmp_path)
    _write_yaml(
        tmp_path / "directory-manifest.yaml",
        {
            "schema_version": "3",
            "logical_identities": "identities.yaml",
            "nodes": ["nodes.yaml", "nodes.yaml"],
            "edges": "edges.yaml",
        },
    )

    report = validate_intermediary_yaml(yaml_directory)
    assert report.valid is False
    assert any("unique" in finding.message for finding in report.findings)

    _write_yaml(
        tmp_path / "directory-manifest.yaml",
        {
            "schema_version": "3",
            "logical_identities": "shared.yaml",
            "nodes": ["nodes.yaml"],
            "edges": "shared.yaml",
        },
    )
    report = validate_intermediary_yaml(yaml_directory)
    assert report.valid is False
    assert any("exactly once" in finding.message for finding in report.findings)


def test_manifest_rejects_absolute_and_parent_paths(tmp_path: Path) -> None:
    yaml_directory, _ = _manifest_directory(tmp_path)
    _write_yaml(
        tmp_path / "directory-manifest.yaml",
        {
            "schema_version": "3",
            "logical_identities": str((tmp_path / "outside.yaml").resolve()),
            "nodes": ["../outside.yaml"],
            "edges": "edges.yaml",
        },
    )

    report = validate_intermediary_yaml(yaml_directory)
    assert report.valid is False
    assert sum(finding.rule == "invalid_collection_path" for finding in report.findings) == 2


def test_manifest_rejects_symlink_escape(tmp_path: Path) -> None:
    yaml_directory, _ = _manifest_directory(tmp_path)
    outside = tmp_path / "outside.yaml"
    _write_yaml(outside, {"schema_version": "3", "logical_identities": {}})
    (yaml_directory / "escape.yaml").symlink_to(outside)
    manifest = yaml.safe_load(
        (tmp_path / "directory-manifest.yaml").read_text(encoding="utf-8")
    )
    manifest["logical_identities"] = "escape.yaml"
    _write_yaml(tmp_path / "directory-manifest.yaml", manifest)

    assert "path_outside_directory" in _rules(yaml_directory)


def test_collection_file_rejects_mixed_or_wrong_ownership(tmp_path: Path) -> None:
    yaml_directory, payload = _manifest_directory(tmp_path)
    _write_yaml(
        yaml_directory / "identities.yaml",
        {
            "schema_version": "3",
            "logical_identities": payload["logical_identities"],
            "nodes": payload["nodes"],
        },
    )
    _write_yaml(
        yaml_directory / "edges.yaml",
        {"schema_version": "3", "nodes": payload["nodes"]},
    )

    report = validate_intermediary_yaml(yaml_directory)
    assert report.valid is False
    assert sum(finding.rule == "collection_ownership" for finding in report.findings) >= 2


def test_collection_file_rejects_malformed_yaml(tmp_path: Path) -> None:
    yaml_directory, _ = _manifest_directory(tmp_path)
    (yaml_directory / "edges.yaml").write_text(
        "schema_version: '3'\nedges: [\n",
        encoding="utf-8",
    )

    report = validate_intermediary_yaml(yaml_directory)
    assert report.valid is False
    assert report.findings[0].location == "edges.yaml:$"
    assert report.findings[0].rule == "yaml_syntax"


def test_collection_files_require_matching_version_three(tmp_path: Path) -> None:
    yaml_directory, payload = _manifest_directory(tmp_path)
    _write_yaml(
        yaml_directory / "edges.yaml",
        {"schema_version": "2", "edges": payload["edges"]},
    )

    assert "conflicting_schema_version" in _rules(yaml_directory)


def test_directory_rejects_duplicate_nodes_across_node_files(tmp_path: Path) -> None:
    yaml_directory, payload = _manifest_directory(tmp_path)
    _write_yaml(
        yaml_directory / "nodes-b.yaml",
        {"schema_version": "3", "nodes": [payload["nodes"][0]]},
    )

    report = validate_intermediary_yaml(yaml_directory)
    assert report.valid is False
    assert any(finding.rule == "duplicate_definition" for finding in report.findings)


def test_catalog_fixture_builds_only_its_explicit_edges() -> None:
    definition = load_intermediary_yaml(LENDING)
    snapshot, report, contradictions = build_snapshot_from_yaml(LENDING)

    assert len(definition.nodes) == 5
    assert sum(len(node.columns) for node in definition.nodes) == 17
    assert all(column.description for node in definition.nodes for column in node.columns)
    assert len(definition.logical_identities) == 5
    assert len(definition.edges) == 5
    assert len(snapshot.edges) == len(definition.edges)
    assert {edge.edge_id for edge in snapshot.edges} == {
        edge.canonical_edge_id() for edge in definition.edges
    }
    assert contradictions == []

    nodes = {node.descriptor.display_name: node for node in snapshot.nodes}
    loan_columns = nodes["loan"].column_map()
    account_columns = nodes["account"].column_map()
    assert loan_columns["term"].value_description == "unit: month"
    assert "monthly statements" in account_columns["statement_cycle"].value_description

    account_to_region = next(
        edge
        for edge in snapshot.edges
        if {edge.endpoint_a.node_id, edge.endpoint_b.node_id}
        == {"sqlite:lending.account", "sqlite:lending.region"}
    )
    direction = account_to_region.direction_from("sqlite:lending.account")
    assert direction.multiplicity == Multiplicity.MANY_TO_ONE
    assert direction.match_existence == MatchExistence.UNKNOWN


def test_snapshot_round_trip_preserves_yaml_identity_model(tmp_path: Path) -> None:
    snapshot, _, _ = build_snapshot_from_yaml(VALID_EXAMPLE)
    store = CurrentArtifactStore(tmp_path / "current")
    location = store.publish(snapshot)
    loaded = store.load()

    assert loaded.model_dump(mode="json") == snapshot.model_dump(mode="json")
    persisted_nodes = (location / "nodes.json").read_text(encoding="utf-8")
    persisted_edges = (location / "edges.json").read_text(encoding="utf-8")
    assert "foreign_key_declarations" not in persisted_nodes
    assert "logical_entity_key" not in persisted_nodes
    assert "table_name" not in persisted_nodes
    assert "data_source" not in persisted_nodes
    assert '"participation"' not in persisted_edges
    assert '"precedence"' not in persisted_edges
    definition = loaded.nodes[0].entity_definitions[0]
    assert definition.dataset_columns == ["c1", "c2", "c3"]
    assert definition.entity_expression == ["[c1, xxhash64(c2, c3)]"]
    assert definition.entity_metadata["expression_context"] == "Spark SQL"
    assert definition.entity_universe == EntityUniverse.PARTIAL
    assert loaded.nodes[0].grain is not None
    assert len(loaded.nodes[0].grain.components) == 1
    edge_payload = loaded.edges[0].model_dump(mode="json")
    assert "entity_expression" not in yaml.safe_dump(edge_payload)
    assert "expression_context" not in yaml.safe_dump(edge_payload)


def test_build_report_lists_explicit_unknown_claims() -> None:
    _, report, _ = build_snapshot_from_yaml(VALID_EXAMPLE)

    assert report.unknown_fields == [
        "nodes[dataset_b].grain",
        "edges[dataset_a:customer_identity:c1+c2+c3__dataset_b:customer_identity:d1+d2]"
        ".b_to_a.match_existence",
    ]


def test_unreviewed_universe_status_is_reported_as_unknown() -> None:
    _, report, _ = build_snapshot_from_yaml(LENDING)
    universe_gaps = [
        location for location in report.unknown_fields if location.endswith(".entity_universe")
    ]
    assert len(universe_gaps) == 9
    assert not any("lending.region].entity_definitions" in item for item in universe_gaps)
