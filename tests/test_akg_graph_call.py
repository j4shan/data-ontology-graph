import ast
import importlib.util
import json
import sys
from pathlib import Path

from data_ontology_graph.akg.model import AkgDocument
from data_ontology_graph.akg.resolve import resolve_akg, socket_call


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "query-graph-api" / "scripts" / "graph_call.py"
LOAN = "sqlite:lending.loan"
ACCOUNT = "sqlite:lending.account"
LOAN_ACCOUNT = (
    "sqlite:lending.account:account_identity:account_id__sqlite:lending.loan:account_identity:account_id"
)


def _client():
    spec = importlib.util.spec_from_file_location("graph_call", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(socket_path: Path, capsys, *args: str) -> tuple[int, object]:
    code = _client().main([*args, "--socket", str(socket_path)])
    return code, json.loads(capsys.readouterr().out)


def test_client_imports_only_the_standard_library() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
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
    assert imported - {"__future__"} <= set(sys.stdlib_module_names)


def test_get_dataset_puts_names_first_and_drops_accessor(lending_socket: Path, capsys) -> None:
    code, output = _run(lending_socket, capsys, "get_dataset", json.dumps({"node_id": LOAN}))
    assert code == 0
    assert list(output)[:3] == ["node_id", "qualified_name", "display_name"]
    assert "accessor" not in output
    assert all("entity_metadata" not in definition for definition in output["entity_definitions"])


def test_find_paths_lists_one_line_per_path_fan_out_free_first(
    lending_socket: Path, capsys
) -> None:
    params = json.dumps({"from_node_id": LOAN, "to_node_id": "sqlite:lending.region", "max_hops": 4})
    code, output = _run(lending_socket, capsys, "find_paths", params)
    assert code == 0
    assert all(isinstance(line, str) for line in output["paths"])
    assert output["paths"][0].startswith("#0 [many:1 > many:1] fan_out=0")

    code, detailed = _run(lending_socket, capsys, "find_paths", params, "--detail")
    assert code == 0
    first_hop = detailed["paths"][0]["hops"][0]
    assert first_hop["edge_id"] == LOAN_ACCOUNT
    assert first_hop["step"].startswith(f"{LOAN}[account_id] -> {ACCOUNT}[account_id]")


def test_relationship_is_oriented_from_the_requested_endpoint(
    lending_socket: Path, capsys
) -> None:
    params = json.dumps({"edge_id": LOAN_ACCOUNT, "from_node_id": LOAN})
    code, output = _run(lending_socket, capsys, "get_relationship", params)
    assert code == 0
    assert output["direction"] == "many:1/always"
    assert output["reverse_direction"] == "1:many/optional"
    assert output["a_to_b"] == "1:many/optional"


def test_hops_carry_both_directions(lending_socket: Path, capsys) -> None:
    code, output = _run(lending_socket, capsys, "get_hops", json.dumps({"node_id": LOAN}))
    assert code == 0
    assert output["hops"] == [
        {
            "edge_id": LOAN_ACCOUNT,
            "step": f"{LOAN}[account_id] -> {ACCOUNT}[account_id] account_identity "
            "many:1/always | reverse 1:many/optional",
        }
    ]


def test_search_lists_one_line_per_subject_with_its_matches(lending_socket: Path, capsys) -> None:
    params = json.dumps({"query": "loan", "kind": ["column"]})
    code, output = _run(lending_socket, capsys, "search", params)
    assert code == 0
    hits = output["groups"][0]["hits"]
    assert (
        f"{LOAN}.loan_id <- exact:column_name='loan_id'; exact:description='the id of the loan'"
        in hits
    )


def test_cut_is_copied_verbatim_from_the_snapshot(lending_socket: Path, capsys) -> None:
    params = json.dumps({"node_ids": [LOAN, ACCOUNT], "edge_ids": [LOAN_ACCOUNT]})
    code, cut = _run(lending_socket, capsys, "cut", params)
    assert code == 0
    _, info = _run(lending_socket, capsys, "snapshot_info")
    document = AkgDocument.model_validate(
        {
            "akg_version": "1.0",
            "question": "How many loans does each account repay?",
            "snapshot": {
                "version": info["version"],
                "schema_fingerprint": info["schema_fingerprint"],
            },
            "akgs": [{"interpretation": "Count loans per account.", "cuts": [cut]}],
        }
    )
    assert list(cut["logical_identities"]) == ["account_identity"]
    assert resolve_akg(document, socket_call(lending_socket)) == []


def test_service_error_exits_non_zero(lending_socket: Path, capsys) -> None:
    code, error = _run(lending_socket, capsys, "get_dataset", json.dumps({"node_id": "nope"}))
    assert code == 1
    assert error["message"] == "unknown dataset nope"
