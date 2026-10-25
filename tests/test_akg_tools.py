import ast
import io
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from data_ontology_graph.akg import check_document, project_dataset, project_edge
from data_ontology_graph.akg.resolve import ServiceSource, resolve_document, socket_call
from data_ontology_graph.builder.intermediary import load_intermediary_yaml
from data_ontology_graph.model.derivation import derive_relationships


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "query-graph-api" / "scripts" / "akg.py"
LENDING = ROOT / "tests" / "fixtures" / "lending"
LOAN = "sqlite:lending.loan"
ACCOUNT = "sqlite:lending.account"
REGION = "sqlite:lending.region"
LOAN_ACCOUNT = (
    "sqlite:lending.account:account_identity:account_id__sqlite:lending.loan:account_identity:account_id"
)
ACCOUNT_REGION = (
    "sqlite:lending.account:region_identity:region_id__sqlite:lending.region:region_identity:region_id"
)


def _tool():
    spec = importlib.util.spec_from_file_location("akg_tool", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def run(lending_socket: Path, capsys):
    tool = _tool()

    def invoke(*args: str) -> tuple[int, object]:
        code = tool.main([*args, "--socket", str(lending_socket)])
        out = capsys.readouterr().out
        try:
            return code, json.loads(out)
        except json.JSONDecodeError:
            return code, out

    return invoke


@pytest.fixture
def akg(tmp_path: Path, run) -> Path:
    path = tmp_path / "akg.json"
    code, output = run("init", str(path), "--question", "How many loans per region?")
    assert code == 0 and output["snapshot"]["version"]
    return path


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("script", ["akg.py", "service.py"])
def test_scripts_import_only_the_standard_library(script: str) -> None:
    tree = ast.parse((SCRIPT.parent / script).read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0
    }
    assert imported - {"__future__", "graph_call"} <= set(sys.stdlib_module_names)


@pytest.mark.parametrize("detail", ["essential", "standard", "full"])
def test_projection_agrees_with_the_graph_core(detail: str) -> None:
    tool = _tool()
    definition = load_intermediary_yaml(LENDING / "catalog.yaml")
    for node in definition.nodes:
        dump = node.model_dump(mode="json")
        columns = [column.name for column in node.columns][:2]
        assert tool.project_dataset(dump, detail, columns) == project_dataset(dump, detail, columns)
    descriptions = {("sqlite:lending.loan", ("account_id",)): "the account that repays the loan"}
    for edge in derive_relationships(node.to_runtime() for node in definition.nodes):
        dump = edge.model_dump(mode="json")
        for side in ("endpoint_a", "endpoint_b"):
            start = (dump[side]["node_id"], dump[side]["dataset_columns"])
            assert tool.project_edge(dump, *start, descriptions) == project_edge(
                dump, *start, descriptions
            )


def test_init_refuses_an_existing_file(akg: Path, run) -> None:
    code, output = run("init", str(akg), "--question", "again")
    assert code == 1 and "already exists" in output["error"]


def test_adding_is_idempotent_and_only_fills_missing_fields(akg: Path, run) -> None:
    assert run("add-dataset", str(akg), LOAN, "--columns", "amount")[1]["added"] == [LOAN]
    before = akg.read_text(encoding="utf-8")
    assert run("add-dataset", str(akg), LOAN, "--columns", "amount")[1]["unchanged"] == [LOAN]
    assert akg.read_text(encoding="utf-8") == before

    loan = _read(akg)["datasets"][LOAN]
    loan["columns"]["amount"]["description"] = "kept as written"
    akg.write_text(json.dumps(_read(akg) | {"datasets": {LOAN: loan}}), encoding="utf-8")
    assert run("add-dataset", str(akg), LOAN, "--detail", "standard")[1]["extended"] == [LOAN]
    loan = _read(akg)["datasets"][LOAN]
    assert loan["columns"]["amount"]["description"] == "kept as written"
    assert set(loan["columns"]) == {"loan_id", "account_id", "amount", "term"}
    assert "entity_definitions" in loan and "description" in loan
    assert list(loan)[:3] == ["name", "source", "grain"]


def _edges(document: dict) -> list[tuple[str, str]]:
    return [(node_id, edge["edge_id"]) for node_id, dataset in document["datasets"].items()
            for edge in dataset.get("edges", [])]


def test_adding_an_edge_stores_it_in_its_start_dataset_with_its_ends(akg: Path, run) -> None:
    code, output = run("add-edge", str(akg), LOAN, LOAN_ACCOUNT)
    assert code == 0
    assert output["added"] == [LOAN_ACCOUNT]
    assert output["datasets_added"] == [LOAN, ACCOUNT]
    document = _read(akg)
    assert set(document["datasets"][LOAN]["columns"]) == {"account_id"}
    assert document["datasets"][LOAN]["edges"] == [{
        "edge_id": LOAN_ACCOUNT, "identity_id": "account_identity",
        "from_dataset_columns": ["account_id"], "to_node_id": ACCOUNT,
        "to_dataset_columns": ["account_id"], "multiplicity": "many:1",
        "match_existence": "always", "reverse_multiplicity": "1:many",
        "reverse_match_existence": "optional",
        "from_description": "the account that repays the loan",
        "to_description": "the id of the account",
    }]
    assert "edges" not in document["datasets"][ACCOUNT]
    assert run("add-edge", str(akg), LOAN, LOAN_ACCOUNT)[1]["unchanged"] == [LOAN_ACCOUNT]
    # The same relationship read from its other end is a second directed edge.
    assert run("add-edge", str(akg), ACCOUNT, LOAN_ACCOUNT)[1]["added"] == [LOAN_ACCOUNT]
    assert _edges(_read(akg)) == [(LOAN, LOAN_ACCOUNT), (ACCOUNT, LOAN_ACCOUNT)]
    code, output = run("add-edge", str(akg), REGION, LOAN_ACCOUNT)
    assert code == 1 and "is not an endpoint" in output["error"]


def test_edge_without_endpoints_needs_its_start_dataset(akg: Path, run) -> None:
    code, output = run("add-edge", str(akg), ACCOUNT, ACCOUNT_REGION, "--no-endpoints")
    assert code == 1 and "add it first" in output["error"]
    run("add-dataset", str(akg), ACCOUNT)
    run("add-edge", str(akg), ACCOUNT, ACCOUNT_REGION, "--no-endpoints")
    findings = check_document(_read(akg))
    assert {(finding.rule, finding.severity) for finding in findings} == {
        ("dangling_reference", "warning")
    }


def test_remove_refuses_referenced_elements_unless_cascaded(akg: Path, run) -> None:
    run("add-edge", str(akg), LOAN, LOAN_ACCOUNT)
    run("add-edge", str(akg), ACCOUNT, ACCOUNT_REGION)
    run("gap", str(akg), "region-match", json.dumps({"description": "x", "datasets": [REGION]}))
    code, output = run("remove", str(akg), REGION)
    assert code == 1 and "edges[" in output["error"] and "gaps[region-match]" in output["error"]
    assert REGION in _read(akg)["datasets"]

    code, output = run("remove", str(akg), REGION, "--cascade")
    assert code == 0 and output["removed"] == [ACCOUNT_REGION, REGION]
    document = _read(akg)
    assert document["gaps"]["region-match"]["datasets"] == []
    assert _edges(document) == [(LOAN, LOAN_ACCOUNT)]
    assert run("exists", str(akg), REGION, LOAN, LOAN_ACCOUNT)[1] == {
        REGION: "absent", LOAN: "present", LOAN_ACCOUNT: "present",
    }
    assert run("remove", str(akg), LOAN_ACCOUNT)[1] == {"removed": [LOAN_ACCOUNT]}
    assert _edges(_read(akg)) == []


def test_annotate_writes_usage_only(akg: Path, run) -> None:
    run("add-edge", str(akg), LOAN, LOAN_ACCOUNT)
    run("annotate", str(akg), LOAN, json.dumps({"role": "anchor", "columns": {"account_id": {"as": "join_only"}}}))
    run("annotate", str(akg), LOAN_ACCOUNT, json.dumps({"keep": [ACCOUNT]}))
    run("annotate", str(akg), LOAN, json.dumps({"columns": None, "multiplicity": "x"}))
    document = _read(akg)
    assert document["datasets"][LOAN]["usage"] == {"role": "anchor", "multiplicity": "x"}
    [edge] = document["datasets"][LOAN]["edges"]
    assert edge["multiplicity"] == "many:1" and edge["usage"] == {"keep": [ACCOUNT]}
    code, output = run("annotate", str(akg), REGION, json.dumps({"role": "grouping"}))
    assert code == 1 and "add it first" in output["error"]

    run("add-edge", str(akg), ACCOUNT, LOAN_ACCOUNT)
    code, output = run("annotate", str(akg), LOAN_ACCOUNT, json.dumps({"note": "n"}))
    assert code == 1 and "--from" in output["error"]
    run("annotate", str(akg), LOAN_ACCOUNT, json.dumps({"note": "n"}), "--from", ACCOUNT)
    assert _read(akg)["datasets"][ACCOUNT]["edges"][0]["usage"] == {"note": "n"}


def test_migrate_moves_relationships_into_their_start_datasets(akg: Path, run) -> None:
    run("add-dataset", str(akg), LOAN, ACCOUNT, "--columns", "account_id")
    earlier = _read(akg)
    del earlier["format_version"]
    earlier["relationships"] = {LOAN_ACCOUNT: {
        "endpoint_a": {"node_id": ACCOUNT, "identity_id": "account_identity",
                       "dataset_columns": ["account_id"]},
        "endpoint_b": {"node_id": LOAN, "identity_id": "account_identity",
                       "dataset_columns": ["account_id"]},
        "a_to_b": {"multiplicity": "1:many", "match_existence": "always"},
        "b_to_a": {"multiplicity": "many:1", "match_existence": "always"},
        "usage": {"from": LOAN, "keep": [ACCOUNT]},
    }}
    earlier["gaps"] = {"g": {"description": "x", "relationships": [LOAN_ACCOUNT]}}
    akg.write_text(json.dumps(earlier), encoding="utf-8")
    code, output = run("add-dataset", str(akg), REGION)
    assert code == 1 and "migrate" in output["error"]

    assert run("migrate", str(akg)) == (0, {"migrated": [{"edge_id": LOAN_ACCOUNT, "node_id": LOAN}]})
    document = _read(akg)
    assert list(document)[0] == "format_version" and "relationships" not in document
    [edge] = document["datasets"][LOAN]["edges"]
    # The claims are kept as written; descriptions the earlier format lacked are fetched.
    assert (edge["multiplicity"], edge["match_existence"]) == ("many:1", "always")
    assert edge["reverse_match_existence"] == "always"
    assert edge["from_description"] == "the account that repays the loan"
    assert edge["usage"] == {"keep": [ACCOUNT]}
    assert document["gaps"]["g"]["edges"] == [{"node_id": LOAN, "edge_id": LOAN_ACCOUNT}]
    assert check_document(document) == []


def test_gap_and_comparison_entries_merge_and_delete(akg: Path, run) -> None:
    run("gap", str(akg), "g1", json.dumps({"description": "first"}))
    run("gap", str(akg), "g1", json.dumps({"datasets": [LOAN]}))
    assert _read(akg)["gaps"]["g1"] == {"description": "first", "datasets": [LOAN]}
    run("gap", str(akg), "g1", "null")
    assert "gaps" not in _read(akg)
    code, output = run("comparison", str(akg), "c1", '"not an object"')
    assert code == 1 and output["file_unchanged"] is True


def test_any_write_resets_final_status(akg: Path, run) -> None:
    document = _read(akg) | {"status": "final"}
    akg.write_text(json.dumps(document), encoding="utf-8")
    run("gap", str(akg), "g1", json.dumps({"description": "late finding"}))
    assert _read(akg)["status"] == "draft"


def test_service_error_leaves_the_file_unchanged(akg: Path, run) -> None:
    before = akg.read_text(encoding="utf-8")
    code, output = run("add-dataset", str(akg), LOAN, "sqlite:lending.nope")
    assert code == 1 and output == {"error": "unknown dataset sqlite:lending.nope", "file_unchanged": True}
    assert akg.read_text(encoding="utf-8") == before


def test_show_lists_each_directed_edge_under_its_start_dataset(akg: Path, run) -> None:
    run("add-edge", str(akg), LOAN, LOAN_ACCOUNT)
    code, output = run("show", str(akg))
    assert code == 0
    assert output.splitlines()[0] == "status draft | 2 datasets | 1 edges | 1 component(s)"
    assert f"  {LOAN}[account_id] -> {ACCOUNT}[account_id] many:1/always | reverse 1:many/optional" in output


def test_a_tool_built_file_resolves_and_matches_the_fixture(
    akg: Path, run, lending_socket: Path
) -> None:
    run("add-dataset", str(akg), LOAN, "--columns", "loan_id")
    run("add-edge", str(akg), LOAN, LOAN_ACCOUNT)
    run("add-edge", str(akg), ACCOUNT, ACCOUNT_REGION)
    run("add-dataset", str(akg), REGION, "--columns", "region_name")
    document = _read(akg)
    assert [finding for finding in check_document(document, final=True)] == []
    assert resolve_document(document, ServiceSource(socket_call(lending_socket))) == []
    fixture = json.loads((LENDING / "akg-single.json").read_text(encoding="utf-8"))
    for node_id, dataset in fixture["datasets"].items():
        expected = {key: value for key, value in dataset.items() if key != "usage"}
        if "edges" in expected:
            expected["edges"] = [
                {key: value for key, value in edge.items() if key != "usage"}
                for edge in expected["edges"]
            ]
        assert document["datasets"][node_id] == expected


def test_patch_can_come_from_a_file_or_standard_input(
    akg: Path, run, tmp_path: Path, monkeypatch
) -> None:
    patch = tmp_path / "gap.json"
    patch.write_text(json.dumps({"description": "from a file", "datasets": [LOAN]}))
    assert run("gap", str(akg), "g1", f"@{patch}")[0] == 0
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"description": "from stdin"}'))
    assert run("gap", str(akg), "g2", "-")[0] == 0
    gaps = _read(akg)["gaps"]
    assert gaps["g1"]["datasets"] == [LOAN]
    assert gaps["g2"] == {"description": "from stdin"}
