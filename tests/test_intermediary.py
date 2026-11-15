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
from testkit import INVALID_EXAMPLE, LENDING, SCHEMAS, STATED, VALID_EXAMPLE


SCHEMA = SCHEMAS / "intermediary.schema.json"
DIRECTORY_SCHEMA = SCHEMAS / "intermediary-directory.schema.json"


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
            "schema_version": "5",
            "logical_identities": payload["logical_identities"],
        },
    )
    node_paths = ["nodes-b.yaml", "nodes-a.yaml"] if split_nodes else ["nodes.yaml"]
    if split_nodes:
        _write_yaml(
            yaml_directory / node_paths[0],
            {"schema_version": "5", "nodes": [payload["nodes"][1]]},
        )
        _write_yaml(
            yaml_directory / node_paths[1],
            {"schema_version": "5", "nodes": [payload["nodes"][0]]},
        )
    else:
        _write_yaml(
            yaml_directory / node_paths[0],
            {"schema_version": "5", "nodes": payload["nodes"]},
        )
    _write_yaml(
        tmp_path / "directory-manifest.yaml",
        {
            "schema_version": "5",
            "logical_identities": "identities.yaml",
            "nodes": node_paths,
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
    # The valid example also shows a cross-entity relationship.
    assert [relationship.endpoints for relationship in load_intermediary_yaml(VALID_EXAMPLE).entity_relationships] == [
        ("customer_identity", "customer_identity")
    ]

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


def test_unknown_top_level_keys_are_rejected(tmp_path: Path) -> None:
    payload = yaml.safe_load(VALID_EXAMPLE.read_text(encoding="utf-8"))
    payload["notes"] = []
    invalid = tmp_path / "unknown-key.yaml"
    invalid.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    report = validate_intermediary_yaml(invalid)
    assert report.valid is False
    assert report.findings[0].location == "$.notes"
    assert report.findings[0].rule == "extra_forbidden"


def test_definition_properties_are_required_and_may_be_unknown(tmp_path: Path) -> None:
    payload = yaml.safe_load(VALID_EXAMPLE.read_text(encoding="utf-8"))
    definition = payload["nodes"][0]["entity_definitions"][0]
    del definition["total"]
    definition["unique"] = "unknown"
    invalid = tmp_path / "missing-total.yaml"
    invalid.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    report = validate_intermediary_yaml(invalid)
    assert report.valid is False
    assert [finding.location for finding in report.findings] == [
        "$.nodes[0].entity_definitions[0].total"
    ]


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
    snapshot, report = build_snapshot_from_yaml(yaml_directory)

    assert [node.node_id for node in definition.nodes] == sorted(
        node["node_id"] for node in payload["nodes"]
    )
    assert report.node_count == len(payload["nodes"])
    assert report.entity_definition_count == 2


def test_directory_requires_valid_sibling_manifest(tmp_path: Path) -> None:
    yaml_directory = tmp_path / "yaml"
    yaml_directory.mkdir()
    assert _rules(yaml_directory) == {"missing_manifest"}

    (tmp_path / "directory-manifest.yaml").write_text("nodes: [\n", encoding="utf-8")
    report = validate_intermediary_yaml(yaml_directory)
    assert report.valid is False
    assert report.findings[0].rule == "yaml_syntax"
    assert report.findings[0].line is not None


def test_manifest_requires_the_schema_version_and_all_collection_owners(tmp_path: Path) -> None:
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


def test_directory_rejects_unlisted_and_unsupported_files(tmp_path: Path) -> None:
    yaml_directory, _ = _manifest_directory(tmp_path)
    _write_yaml(yaml_directory / "surprise.yaml", {"schema_version": "5", "nodes": []})
    (yaml_directory / "notes.json").write_text("{}", encoding="utf-8")

    report = validate_intermediary_yaml(yaml_directory)
    assert report.valid is False
    assert {(finding.location, finding.rule) for finding in report.findings} >= {
        ("surprise.yaml", "unlisted_file"),
        ("notes.json", "unsupported_file"),
    }


def test_directory_rejects_missing_listed_file(tmp_path: Path) -> None:
    yaml_directory, _ = _manifest_directory(tmp_path)
    (yaml_directory / "nodes-a.yaml").unlink()

    assert "missing_file" in _rules(yaml_directory)


def test_manifest_rejects_duplicate_and_cross_collection_paths(tmp_path: Path) -> None:
    yaml_directory, _ = _manifest_directory(tmp_path)
    _write_yaml(
        tmp_path / "directory-manifest.yaml",
        {
            "schema_version": "5",
            "logical_identities": "identities.yaml",
            "nodes": ["nodes.yaml", "nodes.yaml"],
        },
    )

    report = validate_intermediary_yaml(yaml_directory)
    assert report.valid is False
    assert any("unique" in finding.message for finding in report.findings)

    _write_yaml(
        tmp_path / "directory-manifest.yaml",
        {
            "schema_version": "5",
            "logical_identities": "shared.yaml",
            "nodes": ["shared.yaml"],
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
            "schema_version": "5",
            "logical_identities": str((tmp_path / "outside.yaml").resolve()),
            "nodes": ["../outside.yaml"],
        },
    )

    report = validate_intermediary_yaml(yaml_directory)
    assert report.valid is False
    assert sum(finding.rule == "invalid_collection_path" for finding in report.findings) == 2


def test_manifest_rejects_symlink_escape(tmp_path: Path) -> None:
    yaml_directory, _ = _manifest_directory(tmp_path)
    outside = tmp_path / "outside.yaml"
    _write_yaml(outside, {"schema_version": "5", "logical_identities": {}})
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
            "schema_version": "5",
            "logical_identities": payload["logical_identities"],
            "nodes": payload["nodes"],
        },
    )
    _write_yaml(
        yaml_directory / "nodes-a.yaml",
        {"schema_version": "5", "logical_identities": payload["logical_identities"]},
    )

    report = validate_intermediary_yaml(yaml_directory)
    assert report.valid is False
    assert sum(finding.rule == "collection_ownership" for finding in report.findings) >= 2


def test_collection_file_rejects_malformed_yaml(tmp_path: Path) -> None:
    yaml_directory, _ = _manifest_directory(tmp_path)
    (yaml_directory / "nodes-a.yaml").write_text(
        "schema_version: '5'\nnodes: [\n",
        encoding="utf-8",
    )

    report = validate_intermediary_yaml(yaml_directory)
    assert report.valid is False
    assert report.findings[0].location == "nodes-a.yaml:$"
    assert report.findings[0].rule == "yaml_syntax"


def test_collection_files_require_the_manifest_schema_version(tmp_path: Path) -> None:
    yaml_directory, payload = _manifest_directory(tmp_path)
    _write_yaml(
        yaml_directory / "nodes-a.yaml",
        {"schema_version": "3", "nodes": [payload["nodes"][0]]},
    )

    assert "conflicting_schema_version" in _rules(yaml_directory)


def test_directory_rejects_duplicate_nodes_across_node_files(tmp_path: Path) -> None:
    yaml_directory, payload = _manifest_directory(tmp_path)
    _write_yaml(
        yaml_directory / "nodes-b.yaml",
        {"schema_version": "5", "nodes": [payload["nodes"][0]]},
    )

    report = validate_intermediary_yaml(yaml_directory)
    assert report.valid is False
    assert any(finding.rule == "duplicate_definition" for finding in report.findings)


def test_build_report_lists_input_unknowns_without_enumerating_pairs() -> None:
    _, report = build_snapshot_from_yaml(VALID_EXAMPLE)

    assert report.unknown_fields == [
        "nodes[dataset_a].entity_definitions[customer_identity:c1+c2+c3].total",
        "nodes[dataset_b].grain",
    ]


def test_unreviewed_universe_status_is_reported_as_unknown() -> None:
    _, report = build_snapshot_from_yaml(LENDING)
    universe_gaps = [
        location for location in report.unknown_fields if location.endswith(".entity_universe")
    ]
    assert len(universe_gaps) == 2
    assert not any("lending.region].entity_definitions" in item for item in universe_gaps)


def _stated_payload() -> dict:
    return yaml.safe_load(STATED.read_text(encoding="utf-8"))


def _stated_findings(tmp_path: Path, relationships: list) -> list[str]:
    payload = _stated_payload()
    payload["entity_relationships"] = relationships
    path = tmp_path / "catalog.yaml"
    _write_yaml(path, payload)
    return [finding.message for finding in validate_intermediary_yaml(path).findings]


def test_cross_entity_relationships_build_in_ascending_pair_order() -> None:
    snapshot, report = build_snapshot_from_yaml(STATED)
    pairs = [relationship.endpoints for relationship in snapshot.entity_relationships]
    assert pairs == sorted(pairs)
    assert report.entity_relationship_count == 6
    assert snapshot.entity_relationship_index.between("calendar_day_identity", "order_identity").descriptions == [
        "An order is placed on one calendar day.",
        "An order is shipped on one calendar day once it ships.",
    ]


def test_cross_entity_relationships_are_optional() -> None:
    snapshot, report = build_snapshot_from_yaml(LENDING)
    assert report.entity_relationship_count == 0
    assert snapshot.entity_relationship_index.adjacency == {}


def test_cross_entity_relationship_rules_reject_each_invalid_case(tmp_path: Path) -> None:
    def single(endpoints, descriptions=("A order is placed on one calendar day.",)):
        return [{"endpoints": list(endpoints), "descriptions": list(descriptions)}]

    cases = {
        "unknown logical entities ['missing_identity']": single(["calendar_day_identity", "missing_identity"]),
        "ascending lexical order": single(["order_identity", "calendar_day_identity"]),
        "must not be blank": single(["calendar_day_identity", "order_identity"], [" "]),
        "distinct within one cross-entity relationship": single(
            ["calendar_day_identity", "order_identity"], ["Same.", "Same."]
        ),
        "at least 1 item": single(["calendar_day_identity", "order_identity"], []),
        "is listed more than once": single(["calendar_day_identity", "order_identity"]) * 2,
    }
    for expected, relationships in cases.items():
        messages = _stated_findings(tmp_path, relationships)
        assert any(expected in message for message in messages), (expected, messages)


def test_cross_entity_relationships_load_from_their_manifest_collection(tmp_path: Path) -> None:
    yaml_directory, _ = _manifest_directory(tmp_path)
    _write_yaml(
        yaml_directory / "relationships.yaml",
        {
            "schema_version": "5",
            "entity_relationships": [
                {
                    "endpoints": ["customer_identity", "customer_identity"],
                    "descriptions": ["A customer may refer another customer."],
                }
            ],
        },
    )
    manifest_path = tmp_path / "directory-manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["entity_relationships"] = "relationships.yaml"
    _write_yaml(manifest_path, manifest)
    definition = load_intermediary_directory(yaml_directory)
    assert [relationship.endpoints for relationship in definition.entity_relationships] == [
        ("customer_identity", "customer_identity")
    ]


def test_cross_entity_relationship_collection_must_be_a_listed_list(tmp_path: Path) -> None:
    yaml_directory, _ = _manifest_directory(tmp_path)
    _write_yaml(
        yaml_directory / "relationships.yaml",
        {"schema_version": "5", "entity_relationships": {"not": "a list"}},
    )
    assert "unlisted_file" in _rules(yaml_directory)
    manifest_path = tmp_path / "directory-manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["entity_relationships"] = "relationships.yaml"
    _write_yaml(manifest_path, manifest)
    assert "list_type" in _rules(yaml_directory)
