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
from data_ontology_graph.builder.intermediary import intermediary_json_schema
from data_ontology_graph.model.enums import MatchExistence, Multiplicity
from data_ontology_graph.store.snapshot_store import CurrentArtifactStore


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "resources" / "schema" / "intermediary.schema.json"
VALID_EXAMPLE = ROOT / "resources" / "schema" / "examples" / "intermediary-valid.yaml"
INVALID_EXAMPLE = ROOT / "resources" / "schema" / "examples" / "intermediary-invalid.yaml"
FINANCIAL = ROOT / "resources" / "data" / "dev_overlays" / "financial" / "catalog.yaml"


def test_source_controlled_schema_matches_validator_model() -> None:
    assert json.loads(SCHEMA.read_text(encoding="utf-8")) == intermediary_json_schema()


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


def test_directory_fragments_are_assembled_deterministically(tmp_path: Path) -> None:
    payload = yaml.safe_load(VALID_EXAMPLE.read_text(encoding="utf-8"))
    (tmp_path / "z-nodes.yaml").write_text(
        yaml.safe_dump({"nodes": list(reversed(payload["nodes"]))}, sort_keys=False),
        encoding="utf-8",
    )
    (tmp_path / "a-registry.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": payload["schema_version"],
                "logical_identities": payload["logical_identities"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "m-edges.yaml").write_text(
        yaml.safe_dump({"edges": list(reversed(payload["edges"]))}, sort_keys=False),
        encoding="utf-8",
    )

    definition = load_intermediary_directory(tmp_path)
    snapshot, report, _ = build_snapshot_from_yaml(tmp_path)

    assert [node.node_id for node in definition.nodes] == sorted(
        node["node_id"] for node in payload["nodes"]
    )
    assert [edge.canonical_edge_id() for edge in definition.edges] == sorted(
        edge.canonical_edge_id() for edge in definition.edges
    )
    assert report.node_count == len(payload["nodes"])
    assert len(snapshot.edges) == len(payload["edges"])


def test_directory_rejects_unsupported_files_and_duplicate_definitions(tmp_path: Path) -> None:
    (tmp_path / "catalog.yaml").write_text(
        VALID_EXAMPLE.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    unsupported = tmp_path / "notes.json"
    unsupported.write_text("{}", encoding="utf-8")

    report = validate_intermediary_yaml(tmp_path)
    assert report.valid is False
    assert report.findings[0].rule == "unsupported_file"

    unsupported.unlink()
    payload = yaml.safe_load(VALID_EXAMPLE.read_text(encoding="utf-8"))
    duplicate_node = payload["nodes"][0]
    (tmp_path / "duplicate.yaml").write_text(
        yaml.safe_dump({"nodes": [duplicate_node]}, sort_keys=False),
        encoding="utf-8",
    )
    report = validate_intermediary_yaml(tmp_path)
    assert report.valid is False
    assert any(finding.rule == "duplicate_definition" for finding in report.findings)


def test_financial_reference_builds_only_its_explicit_edges() -> None:
    definition = load_intermediary_yaml(FINANCIAL)
    snapshot, report, contradictions = build_snapshot_from_yaml(FINANCIAL)

    assert len(definition.nodes) == 8
    assert sum(len(node.columns) for node in definition.nodes) == 55
    assert all(column.description for node in definition.nodes for column in node.columns)
    assert len(definition.logical_identities) == 8
    assert len(definition.edges) == 8
    assert len(snapshot.edges) == len(definition.edges)
    assert {edge.edge_id for edge in snapshot.edges} == {
        edge.canonical_edge_id() for edge in definition.edges
    }
    assert contradictions == []

    nodes = {node.descriptor.display_name: node for node in snapshot.nodes}
    loan_columns = nodes["loan"].column_map()
    account_columns = nodes["account"].column_map()
    assert loan_columns["payments"].value_description == "unit：month"
    assert "monthly issuance" in account_columns["frequency"].value_description

    account_to_district = next(
        edge
        for edge in snapshot.edges
        if {edge.endpoint_a.node_id, edge.endpoint_b.node_id}
        == {"sql_db:financial.account", "sql_db:financial.district"}
    )
    direction = account_to_district.direction_from("sql_db:financial.account")
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
    assert definition.is_entity_universe is False
    assert loaded.nodes[0].grain is not None
    assert len(loaded.nodes[0].grain.components) == 1
    edge_payload = loaded.edges[0].model_dump(mode="json")
    assert "entity_expression" not in yaml.safe_dump(edge_payload)
    assert "expression_context" not in yaml.safe_dump(edge_payload)
