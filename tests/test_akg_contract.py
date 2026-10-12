import copy
import json
from pathlib import Path

import pytest
import yaml

from data_ontology_graph.akg import akg_json_schema, load_akg_yaml, validate_akg_payload
from data_ontology_graph.akg.cli import main
from data_ontology_graph.akg.model import AkgDocument
from data_ontology_graph.akg.resolve import dispatcher_call, resolve_akg
from data_ontology_graph.builder import build_snapshot_from_yaml
from data_ontology_graph.builder.intermediary import intermediary_json_schema
from data_ontology_graph.rpc.protocol import JsonRpcDispatcher
from data_ontology_graph.service.read import GraphReadService


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "resources" / "schema" / "akg.schema.json"
LENDING = ROOT / "tests" / "fixtures" / "lending"
VALID = ["akg-one-cut.yaml", "akg-forest.yaml", "akg-data-gap.yaml"]
INVALID_CASES = yaml.safe_load((LENDING / "akg-invalid.yaml").read_text(encoding="utf-8"))["cases"]


def _payload(name: str) -> dict:
    return yaml.safe_load((LENDING / name).read_text(encoding="utf-8"))


def _call():
    snapshot, _, _ = build_snapshot_from_yaml(LENDING / "catalog.yaml")
    return dispatcher_call(JsonRpcDispatcher(GraphReadService(snapshot)))


def _resolve(payload: dict):
    return resolve_akg(AkgDocument.model_validate(payload), _call())


def _parent(document: object, path: str) -> tuple[object, str | int]:
    *parts, last = [int(part) if part.isdigit() else part for part in path.split(".")]
    for part in parts:
        document = document[part]
    return document, last


def _get(document: object, path: str) -> object:
    parent, key = _parent(document, path)
    return copy.deepcopy(parent[key])


def _apply(document: dict, case: dict) -> dict:
    if "delete" in case:
        parent, key = _parent(document, case["delete"])
        del parent[key]
    if "set" in case:
        parent, key = _parent(document, case["set"]["path"])
        parent[key] = case["set"]["value"]
    if "append" in case:
        change = case["append"]
        value = _get(document, change["from"]) if "from" in change else change["value"]
        parent, key = _parent(document, change["path"])
        parent[key].append(value)
    if "copy" in case:
        parent, key = _parent(document, case["copy"]["to"])
        parent[key] = _get(document, case["copy"]["from"])
    return document


def test_source_controlled_schema_matches_validator_model() -> None:
    assert json.loads(SCHEMA.read_text(encoding="utf-8")) == akg_json_schema()


def test_schema_references_graph_model_instead_of_redefining_it() -> None:
    schema = akg_json_schema()
    graph_definitions = intermediary_json_schema()["$defs"]
    assert not set(schema["$defs"]) & set(graph_definitions)

    references: list[str] = []

    def collect(value: object) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("$ref"), str):
                references.append(value["$ref"])
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(schema)
    external = {ref.split("#/$defs/")[1] for ref in references if not ref.startswith("#")}
    assert {"IntermediaryNode", "RelationshipDefinition", "LogicalIdentityDefinition"} <= external
    assert external <= set(graph_definitions)


@pytest.mark.parametrize("name", VALID)
def test_valid_fixtures_satisfy_contract_and_snapshot(name: str) -> None:
    document = load_akg_yaml(LENDING / name)
    assert resolve_akg(document, _call()) == []


@pytest.mark.parametrize("case", INVALID_CASES, ids=[case["case"] for case in INVALID_CASES])
def test_each_contract_violation_is_rejected(case: dict) -> None:
    report = validate_akg_payload(_apply(_payload(case["base"]), case))
    assert report.valid is False
    assert [finding.rule for finding in report.findings] == [case["expected"]]


def test_forest_may_be_disconnected_and_records_data_gap() -> None:
    forest = load_akg_yaml(LENDING / "akg-forest.yaml").akgs[0]
    gap = load_akg_yaml(LENDING / "akg-data-gap.yaml").akgs[0]
    assert len(forest.cuts) == 2 and not forest.reasoning.data_gaps
    assert len(gap.cuts) == 2 and gap.reasoning.data_gaps[0].cuts == [0, 1]


def test_changed_claim_is_reported_by_element_and_field() -> None:
    findings = _resolve(_payload("akg-inverted-claim.yaml"))
    assert [(finding.location, finding.rule) for finding in findings] == [
        ("$.akgs[0].cuts[0].edges[0].a_to_b.match_existence", "snapshot_mismatch")
    ]
    assert "document has \"optional\", snapshot has \"always\"" in findings[0].message


def test_edge_may_be_written_in_either_endpoint_order() -> None:
    payload = _payload("akg-one-cut.yaml")
    edge = payload["akgs"][0]["cuts"][0]["edges"][0]
    edge["endpoint_a"], edge["endpoint_b"] = edge["endpoint_b"], edge["endpoint_a"]
    edge["a_to_b"], edge["b_to_a"] = edge["b_to_a"], edge["a_to_b"]
    assert _resolve(payload) == []


def test_changed_node_metadata_and_snapshot_identity_are_reported() -> None:
    payload = _payload("akg-one-cut.yaml")
    payload["snapshot"]["schema_fingerprint"] = "0000000000000000"
    payload["akgs"][0]["cuts"][0]["nodes"][2]["descriptor"]["display_name"] = "Region"
    locations = [finding.location for finding in _resolve(payload)]
    assert locations == [
        "$.snapshot.schema_fingerprint",
        "$.akgs[0].cuts[0].nodes[2].descriptor",
    ]


def test_unknown_node_is_reported() -> None:
    payload = _payload("akg-data-gap.yaml")
    payload["akgs"][0]["cuts"][1]["nodes"][0]["node_id"] = "sqlite:lending.branch"
    payload["akgs"][0]["reasoning"]["data_gaps"][0]["node_ids"] = ["sqlite:lending.loan"]
    payload["akgs"][0]["reasoning"]["attributes"] = payload["akgs"][0]["reasoning"]["attributes"][:1]
    findings = _resolve(payload)
    assert [(finding.location, finding.rule) for finding in findings] == [
        ("$.akgs[0].cuts[1].nodes[0]", "unknown_element")
    ]


def test_cli_validates_contract_and_snapshot(lending_socket: Path, capsys) -> None:
    assert main(["validate", str(LENDING / "akg-one-cut.yaml")]) == 0
    assert main(["validate", str(LENDING / "akg-forest.yaml"), "--socket", str(lending_socket)]) == 0
    assert (
        main(["validate", str(LENDING / "akg-inverted-claim.yaml"), "--socket", str(lending_socket)])
        == 1
    )
    output = capsys.readouterr().out
    assert "[snapshot_mismatch]" in output
    assert "valid against the contract and snapshot" in output
