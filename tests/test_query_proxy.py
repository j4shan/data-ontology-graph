"""Contract tests for the installed skill's question/traversal proxy."""
import ast
import importlib.util
import json
from pathlib import Path
import re

import pytest

from data_ontology_graph.builder import build_snapshot_from_yaml
from data_ontology_graph.rpc.protocol import JsonRpcDispatcher
from data_ontology_graph.service.read import GraphReadService


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/query-graph-api/scripts/query.py"
LOAN = "sqlite:lending.loan"
REGION = "sqlite:lending.region"
LOAN_ACCOUNT = (
    "sqlite:lending.account:account_identity:account_id__sqlite:lending.loan:account_identity:account_id"
)


@pytest.fixture
def proxy():
    spec = importlib.util.spec_from_file_location("query_proxy", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def graph_transport(proxy, monkeypatch):
    snapshot, _, _ = build_snapshot_from_yaml(ROOT / "tests/fixtures/lending/catalog.yaml")
    dispatcher = JsonRpcDispatcher(GraphReadService(snapshot))
    calls = []

    def call(socket_path, method, params):
        calls.append((socket_path, method, params))
        return dispatcher.dispatch({"jsonrpc": "2.0", "id": 1,
                                    "method": method, "params": params})

    monkeypatch.setattr(proxy, "call", call)
    return calls


def run(proxy, capsys, context, method, params=None, *options):
    status = proxy.main([method, json.dumps(params or {}), "--context", str(context), *options])
    return status, json.loads(capsys.readouterr().out)


def read_traversals(context):
    markdown = context.with_suffix(".traversals.md").read_text(encoding="utf-8")
    blocks = re.findall(r"^## ([^\n]+)\n\n```python\n(.*?)\n```$", markdown, re.M | re.S)
    assert len(blocks) == markdown.count("\n```python\n")
    entries = []
    for method, source in blocks:
        assert source.count('"request": """') == 1
        assert source.count('"response": """') == 1
        entry = ast.literal_eval(source)
        assert set(entry) == {"request", "response"}
        assert all(isinstance(value, str) for value in entry.values())
        entries.append((method, {key: json.loads(value) for key, value in entry.items()}))
    return entries


def test_four_traversals_keep_service_shapes_and_accumulate_history(
    proxy, graph_transport, capsys, tmp_path
):
    context = tmp_path / "nested" / "question.json"
    methods = [
        ("get_edges", {"node_id": LOAN}),
        ("graph.expand_subgraph", {"seed_node_ids": [LOAN], "max_depth": 1,
                                   "response_format": "records"}),
        ("find_paths", {"from_node_id": LOAN, "to_node_id": REGION}),
        ("find_connecting_subgraph", {"node_ids": [LOAN, REGION]}),
    ]
    previous = b""
    for index, (method, params) in enumerate(methods):
        options = ("--question", "Which regions do loans belong to?", "--entity", "loan")
        if index:
            options = ("--entity", "region", "--entity", "loan")
        status, output = run(proxy, capsys, context, method, params, *options)
        assert status == 0, output
        stored = context.with_suffix(".traversals.md").read_bytes()
        assert stored.startswith(previous)
        previous = stored
        entries = read_traversals(context)
        assert len(entries) == index + 1
        normalized = method if method.startswith("graph.") else "graph." + method
        assert entries[-1] == (normalized, {"request": {"method": normalized, "params": params},
                                          "response": output})
    assert json.loads(context.read_text()) == {
        "question": "Which regions do loans belong to?", "logical_entities": ["loan", "region"]}
    assert len(graph_transport) == 4


@pytest.mark.parametrize("method,params", [
    ("search", {"query": "loan"}),
    ("get_dataset", {"node_id": LOAN}),
    ("get_identity", {"identity_id": "loan_identity"}),
    ("get_relationship", {"edge_id": LOAN_ACCOUNT, "from_node_id": LOAN}),
    ("snapshot_info", {}),
])
def test_discovery_and_lookup_calls_do_not_enter_traversal_file(
    proxy, graph_transport, capsys, tmp_path, method, params
):
    context = tmp_path / "question.json"
    status, output = run(proxy, capsys, context, method, params, "--question", "Find loans")
    assert status == 0, output
    assert len(graph_transport) == 1
    assert context.with_suffix(".traversals.md").read_bytes() == b""
    assert json.loads(context.read_text()) == {"question": "Find loans", "logical_entities": []}


def test_service_error_is_preserved_and_recorded_as_a_traversal(
    proxy, graph_transport, capsys, tmp_path
):
    context = tmp_path / "question.json"
    status, output = run(proxy, capsys, context, "get_edges", {"node_id": "missing"},
                         "--question", "Where does missing join?")
    assert status == 1
    assert output == {"error": {"code": -32004, "message": "unknown dataset missing"}}
    assert read_traversals(context)[0][1]["response"] == output


def test_lookup_keeps_existing_traversal_history_unchanged(
    proxy, graph_transport, capsys, tmp_path
):
    context = tmp_path / "question.json"
    status, output = run(proxy, capsys, context, "get_edges", {"node_id": LOAN},
                         "--question", "q")
    assert status == 0, output
    history = context.with_suffix(".traversals.md").read_bytes()
    status, output = run(proxy, capsys, context, "get_dataset", {"node_id": LOAN},
                         "--entity", "loan")
    assert status == 0, output
    assert context.with_suffix(".traversals.md").read_bytes() == history
    assert json.loads(context.read_text())["logical_entities"] == ["loan"]


@pytest.mark.parametrize("existing,params,options", [
    (None, "{}", []),
    (None, "{}", ["--question", "   "]),
    (None, "[]", ["--question", "q"]),
    (None, "{broken", ["--question", "q"]),
    (None, "{}", ["--question", "q", "--entity", "   "]),
    ('{"question":"q","logical_entities":[]}', "{}", ["--question", "changed"]),
    ('{"question":"q","logical_entities":"loan"}', "{}", []),
    ('{"question":"q","logical_entities":[7]}', "{}", []),
    ('{"question":"q","logical_entities":[],"extra":true}', "{}", []),
    ('{"question":"","logical_entities":[]}', "{}", []),
    ('[]', "{}", []),
    ('broken', "{}", []),
])
def test_invalid_local_input_does_not_call_service_or_overwrite_context(
    proxy, monkeypatch, capsys, tmp_path, existing, params, options
):
    def unexpected_call(*args):
        pytest.fail("invalid local input reached the service")

    monkeypatch.setattr(proxy, "call", unexpected_call)
    context = tmp_path / "question.json"
    if existing is not None:
        context.write_text(existing, encoding="utf-8")
    status = proxy.main(["get_edges", params, "--context", str(context), *options])
    assert status == 2
    assert "error" in json.loads(capsys.readouterr().out)
    assert not context.with_suffix(".traversals.md").exists()
    if existing is None:
        assert not context.exists()
    else:
        assert context.read_text(encoding="utf-8") == existing


def test_traversal_strings_round_trip_unicode_escapes_quotes_and_code_fences(
    proxy, monkeypatch, capsys, tmp_path
):
    special = 'Unicode: café 雪; quotes: """ and \'\'\'; backslash: \\; literal: \\n; newline:\n```python\nend'
    result = {"jsonrpc": "2.0", "id": 1, "result": {
        "datasets": [{"description": special, "nullable": None, "flag": True}],
        "edge_fields": ["edge", "description"], "edges": [[special, special]],
    }}
    params = {"node_id": special, "fields": {"dataset": [special]}}
    monkeypatch.setattr(proxy, "call", lambda *args: result)
    context = tmp_path / "question.json"
    status, output = run(proxy, capsys, context, "get_edges", params,
                         "--question", special, "--entity", special)
    assert status == 0
    assert output == {"result": result["result"]}
    assert read_traversals(context) == [("graph.get_edges", {
        "request": {"method": "graph.get_edges", "params": params}, "response": output})]
    assert json.loads(context.read_text()) == {"question": special, "logical_entities": [special]}


def test_socket_override_and_default_discovery(proxy, monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("DOG_HOME", str(tmp_path / "service_home"))
    monkeypatch.delenv("DOG_SOCKET", raising=False)
    calls = []
    monkeypatch.setattr(proxy, "call", lambda *args: calls.append(args) or {"result": {}})
    context = tmp_path / "question.json"
    run(proxy, capsys, context, "search", {"query": "loan"}, "--question", "q")
    assert calls[-1][0] == tmp_path / "service_home/graph.sock"
    monkeypatch.setenv("DOG_SOCKET", str(tmp_path / "environment.sock"))
    run(proxy, capsys, context, "search", {"query": "loan"})
    assert calls[-1][0] == tmp_path / "environment.sock"
    explicit = tmp_path / "explicit.sock"
    run(proxy, capsys, context, "search", {"query": "loan"}, "--socket", str(explicit))
    assert calls[-1][0] == explicit


def test_unwritable_context_fails_before_service_call(proxy, monkeypatch, capsys, tmp_path):
    context = tmp_path / "parent" / "question.json"
    context.parent.write_text("a file cannot contain the context", encoding="utf-8")

    def unexpected_call(*args):
        pytest.fail("a context write failure reached the service")

    monkeypatch.setattr(proxy, "call", unexpected_call)
    status, output = run(proxy, capsys, context, "get_edges", {"node_id": LOAN},
                         "--question", "q")
    assert status == 2
    assert "error" in output


def test_transport_failure_is_reported_without_invented_response(
    proxy, monkeypatch, capsys, tmp_path
):
    def unavailable(*args):
        raise ConnectionRefusedError("test service is unavailable")

    monkeypatch.setattr(proxy, "call", unavailable)
    context = tmp_path / "question.json"
    status, output = run(proxy, capsys, context, "get_edges", {"node_id": LOAN},
                         "--question", "q")
    assert status == 1
    assert output == {"error": {"message": "test service is unavailable"}}
    assert context.with_suffix(".traversals.md").read_bytes() == b""


def test_uncreatable_traversal_file_fails_before_service_call(
    proxy, monkeypatch, capsys, tmp_path
):
    context = tmp_path / "question.json"
    context.with_suffix(".traversals.md").mkdir()

    def unexpected_call(*args):
        pytest.fail("a traversal context creation failure reached the service")

    monkeypatch.setattr(proxy, "call", unexpected_call)
    status, output = run(proxy, capsys, context, "search", {"query": "loan"},
                         "--question", "q")
    assert status == 2
    assert "error" in output
    assert json.loads(context.read_text()) == {"question": "q", "logical_entities": []}


def test_traversal_write_failure_keeps_the_received_response_visible(
    proxy, monkeypatch, capsys, tmp_path
):
    context = tmp_path / "question.json"
    response = {"result": {"datasets": [], "edge_fields": []}}
    monkeypatch.setattr(proxy, "call", lambda *args: response)

    def cannot_append(*args):
        raise OSError("test storage failure")

    monkeypatch.setattr(proxy, "append_traversal", cannot_append)
    status = proxy.main(["get_edges", json.dumps({"node_id": LOAN}),
                         "--context", str(context), "--question", "q"])
    output = capsys.readouterr()
    assert status == 1
    assert json.loads(output.out) == response
    assert "could not save traversal context: test storage failure" in output.err
