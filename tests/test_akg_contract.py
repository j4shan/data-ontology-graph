import copy
import json
from pathlib import Path

import pytest
import yaml

from data_ontology_graph.akg import akg_json_schema, check_document, load_payload
from data_ontology_graph.akg.cli import main
from data_ontology_graph.akg.resolve import ServiceSource, YamlSource, dispatcher_call, resolve_document
from data_ontology_graph.builder import build_snapshot_from_yaml
from data_ontology_graph.rpc.protocol import JsonRpcDispatcher
from data_ontology_graph.service.read import GraphReadService


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "resources" / "schema" / "akg.schema.json"
LENDING = ROOT / "tests" / "fixtures" / "lending"
VALID = ["akg-single.json", "akg-disjoint.json", "akg-data-gap.json"]
CASES = yaml.safe_load((LENDING / "akg-check-cases.yaml").read_text(encoding="utf-8"))["cases"]


def _payload(name: str) -> dict:
    return json.loads((LENDING / name).read_text(encoding="utf-8"))


def _apply(document: dict, case: dict) -> dict:
    document = copy.deepcopy(document)
    for operation in ("delete", "set", "rename"):
        if operation not in case:
            continue
        change = case[operation]
        path = change if operation == "delete" else change["path"]
        parent = document
        for key in path[:-1] if operation != "rename" else path:
            parent = parent[key]
        if operation == "delete":
            del parent[path[-1]]
        elif operation == "set":
            parent[path[-1]] = change["value"]
        else:
            parent[change["to"]] = parent.pop(change["from"])
    return document


def test_source_controlled_schema_matches_model() -> None:
    assert json.loads(SCHEMA.read_text(encoding="utf-8")) == akg_json_schema()


def test_schema_is_self_contained() -> None:
    text = json.dumps(akg_json_schema())
    assert "intermediary.schema.json" not in text
    assert set(akg_json_schema()["required"]) == {"status", "question", "edge_fields", "datasets"}


@pytest.mark.parametrize("name", VALID)
def test_valid_fixtures_have_no_findings(name: str) -> None:
    payload, findings = load_payload(LENDING / name)
    assert findings == []
    assert check_document(payload, final=True) == []


@pytest.mark.parametrize("case", CASES, ids=[case["case"] for case in CASES])
def test_each_check_case_reports_its_rule_and_severity(case: dict) -> None:
    findings = check_document(_apply(_payload(case["base"]), case), final=case.get("final", False))
    assert [(finding.rule, finding.severity) for finding in findings] == [
        (case["expected"], case["severity"])
    ]


def test_parse_error_is_one_located_error(tmp_path: Path) -> None:
    broken = tmp_path / "akg.json"
    broken.write_text('{"status": "draft",\n  "question": }', encoding="utf-8")
    payload, findings = load_payload(broken)
    assert payload is None
    assert [(finding.rule, finding.severity, finding.line) for finding in findings] == [
        ("parse_error", "error", 2)
    ]


def test_yaml_documents_load_like_json(tmp_path: Path) -> None:
    source = tmp_path / "akg.yaml"
    source.write_text(yaml.safe_dump(_payload("akg-single.json")), encoding="utf-8")
    payload, findings = load_payload(source)
    assert findings == [] and check_document(payload) == []


LOAN_EDGE = "sqlite:lending.account:account_identity:account_id__sqlite:lending.loan:account_identity:account_id"
LOAN_EDGE_AT = (
    "$.datasets['sqlite:lending.loan'].edge_groups['account_identity']"
    f".entity_definitions[['account_id']].edges[{LOAN_EDGE!r}]"
)


def _loan_definition(payload: dict) -> dict:
    return payload["datasets"][0]["edge_groups"][0]["entity_definitions"][0]


def test_disconnected_components_need_no_gap() -> None:
    disjoint = _payload("akg-disjoint.json")
    edges = [array for dataset in disjoint["datasets"] for group in dataset.get("edge_groups", [])
             for definition in group["entity_definitions"] for array in definition["edges"]]
    assert "gaps" not in disjoint and len(edges) == 2
    assert check_document(disjoint, final=True) == []


def test_an_entity_definition_holds_each_directed_edge_once() -> None:
    payload = _payload("akg-single.json")
    edges = _loan_definition(payload)["edges"]
    edges.append(copy.deepcopy(edges[0]))
    assert [(finding.location, finding.rule) for finding in check_document(payload)] == [
        (LOAN_EDGE_AT, "duplicate_edge"),
    ]


def test_a_dataset_appears_once() -> None:
    payload = _payload("akg-data-gap.json")
    payload["datasets"].append(copy.deepcopy(payload["datasets"][0]))
    assert [(finding.location, finding.rule) for finding in check_document(payload)] == [
        ("$.datasets[2]", "duplicate_dataset"),
    ]


def _service() -> ServiceSource:
    snapshot, _, _ = build_snapshot_from_yaml(LENDING / "catalog.yaml")
    return ServiceSource(dispatcher_call(JsonRpcDispatcher(GraphReadService(snapshot))))


def _sources() -> list:
    return [_service(), YamlSource.load(LENDING / "catalog.yaml")]


@pytest.mark.parametrize("name", VALID)
@pytest.mark.parametrize("source", ["service", "yaml"])
def test_valid_fixtures_resolve_against_service_and_yaml(name: str, source: str) -> None:
    graph = _service() if source == "service" else YamlSource.load(LENDING / "catalog.yaml")
    assert resolve_document(_payload(name), graph) == []


@pytest.mark.parametrize("graph", _sources(), ids=["service", "yaml"])
def test_changed_claim_is_one_mismatch_at_its_position(graph) -> None:
    findings = resolve_document(_payload("akg-changed-claim.json"), graph)
    assert [(finding.location, finding.rule) for finding in findings] == [
        (f"{LOAN_EDGE_AT}.match_existence", "graph_mismatch")
    ]
    assert "document has 'optional', graph has 'always'" in findings[0].message


def test_an_edge_from_a_non_endpoint_is_unknown() -> None:
    payload = _payload("akg-single.json")
    _loan_definition(payload)["dataset_columns"] = ["loan_id"]
    findings = resolve_document(payload, _service())
    assert [(finding.location, finding.rule) for finding in findings] == [
        (LOAN_EDGE_AT.replace("['account_id']", "['loan_id']"), "unknown_element"),
    ]


def test_unknown_dataset_column_and_changed_field_are_reported() -> None:
    payload = _payload("akg-data-gap.json")
    payload["datasets"].append({
        "node_id": "sqlite:lending.branch", "qualified_name": "lending.main.branch",
        "accessor": {"schema_id": "accessor.sqlite.v1"},
    })
    loan = payload["datasets"][0]
    loan["columns"].append({"name": "principal"})
    first = loan["columns"][0]["name"]
    loan["columns"][0]["description"] = "changed"
    loan["descriptor"]["description"] = "changed"
    loan["entity_definitions"][0]["entity_universe"] = "complete"
    locations = [(finding.location, finding.rule) for finding in resolve_document(payload, _service())]
    assert locations == [
        ("$.datasets['sqlite:lending.loan'].descriptor.description", "graph_mismatch"),
        (f"$.datasets['sqlite:lending.loan'].columns[{first!r}].description", "graph_mismatch"),
        ("$.datasets['sqlite:lending.loan'].columns['principal']", "unknown_element"),
        ("$.datasets['sqlite:lending.loan'].entity_definitions['loan_identity', ['loan_id']]"
         ".entity_universe", "graph_mismatch"),
        ("$.datasets['sqlite:lending.branch']", "unknown_element"),
    ]


def test_only_the_api_version_of_a_recorded_snapshot_is_compared() -> None:
    payload = _payload("akg-single.json")
    payload["graph"] = {"snapshot": {"api_version": "0", "version": "2000-01-01T00:00:00Z"}}
    rules = [finding.location for finding in resolve_document(payload, _service())]
    assert rules == ["$.graph.snapshot.api_version"]


def test_cli_check_and_finalize(lending_socket: Path, tmp_path: Path, capsys) -> None:
    draft = tmp_path / "akg.json"
    draft.write_text((LENDING / "akg-single.json").read_text(encoding="utf-8"), encoding="utf-8")
    catalog = str(LENDING / "catalog.yaml")
    assert main(["check", str(LENDING / "akg-changed-claim.json")]) == 0
    assert main(["check", str(LENDING / "akg-changed-claim.json"), "--yaml", catalog]) == 1
    assert main(["finalize", str(draft), "--socket", str(lending_socket)]) == 0
    assert json.loads(draft.read_text(encoding="utf-8"))["status"] == "final"
    output = capsys.readouterr().out
    assert "[graph_mismatch]" in output and f"{draft}: final" in output


def test_finalize_refuses_dangling_reference(tmp_path: Path) -> None:
    payload = _payload("akg-disjoint.json")
    payload["datasets"] = [d for d in payload["datasets"] if d["node_id"] != "sqlite:lending.region"]
    draft = tmp_path / "akg.json"
    draft.write_text(json.dumps(payload), encoding="utf-8")
    assert main(["check", str(draft)]) == 0
    assert main(["finalize", str(draft), "--yaml", str(LENDING / "catalog.yaml")]) == 1
    assert json.loads(draft.read_text(encoding="utf-8"))["status"] == "draft"


def test_finalize_defaults_to_the_service_home_socket(
    lending_socket: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("DOG_SOCKET", str(lending_socket))
    draft = tmp_path / "akg.json"
    draft.write_text((LENDING / "akg-single.json").read_text(encoding="utf-8"), encoding="utf-8")
    assert main(["finalize", str(draft)]) == 0
    assert json.loads(draft.read_text(encoding="utf-8"))["status"] == "final"
