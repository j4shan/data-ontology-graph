import asyncio
import stat

import pytest

from data_ontology_graph.rpc.protocol import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    RESOURCE_NOT_FOUND,
    JsonRpcDispatcher,
)
from data_ontology_graph.rpc.server import GraphUnixServer
from testkit import STATED, service_of
from testkit.builders import SEED, TENANT, fanout_service
from testkit.rpc import dispatch, rpc_call, temporary_socket_path

ACCOUNT = "sqlite:lending.account"
LOAN_ACCOUNT = (
    "D1-D8"
)
SERVICES = {"lending": service_of, "fanout": fanout_service, "stated": lambda: service_of(STATED)}


def _cases(service, method, base, code, *variants):
    return [(service, method, base | variant, code) for variant in variants or ({},)]


ERRORS = [
    # Method and request shape.
    ("lending", "graph.generate_sql", {}, METHOD_NOT_FOUND),
    ("lending", "graph.search", {"query": ""}, INVALID_PARAMS),
    ("lending", "graph.search", {"query": "customer", "kind": []}, INVALID_PARAMS),
    # Lookup.
    ("lending", "graph.get_dataset", {"node_id": "missing"}, RESOURCE_NOT_FOUND),
    ("lending", "graph.get_relationship", {"edge_id": LOAN_ACCOUNT, "from_node_id": "missing"},
     INVALID_PARAMS),
    # Directed edges: presentation, bounds, and source filters.
    *_cases("lending", "graph.get_edges", {"node_id": ACCOUNT}, INVALID_PARAMS,
            {"response_format": "xml"}, {"limit": 1001}, {"detail": "verbose"},
            {"fields": {"edge": ["nope"]}}, {"from_dataset_columns": ["account_id"]},
            {"identity_id": "loan_identity"},
            {"identity_id": "region_identity", "from_dataset_columns": ["account_id"]}),
    # Directed-edge discovery: target filters, view, and threshold.
    ("fanout", "graph.get_edges", {"node_id": SEED, "target_identity_ids": ["missing"]},
     RESOURCE_NOT_FOUND),
    *_cases("fanout", "graph.get_edges", {"node_id": SEED}, INVALID_PARAMS,
            {"target_identity_ids": [""]}, {"target_identity_ids": "tenant_identity"},
            {"view": "unknown"}, {"fan_out_threshold": 0}, {"fan_out_threshold": 10_001}),
    # Entity-definition discovery.
    ("fanout", "graph.get_entity_definitions", {"identity_id": "missing"}, RESOURCE_NOT_FOUND),
    ("fanout", "graph.get_entity_definitions",
     {"identity_id": TENANT, "target_identity_ids": ["missing"]}, RESOURCE_NOT_FOUND),
    *_cases("fanout", "graph.get_entity_definitions", {"identity_id": TENANT}, INVALID_PARAMS,
            {"identity_id": ""}, {"target_identity_ids": [""]}, {"target_identity_ids": TENANT},
            {"target_identity_ids": ["a", "b", "c", "d", "e"]}, {"target_identity_ids": None},
            {"entity_universe": []}, {"entity_universe": ["invalid"]}, {"view": "invalid"},
            {"limit": 0}, {"limit": 1001}, {"dataset_threshold": 0}, {"dataset_threshold": 10001},
            {"response_format": "invalid"}, {"unexpected": True}),
    # Connecting subgraph.
    *_cases("lending", "graph.find_connecting_subgraph", {}, INVALID_PARAMS,
            {"node_ids": [ACCOUNT]}, {"node_ids": [ACCOUNT, ACCOUNT]}, {"node_ids": [ACCOUNT, ""]},
            {"node_ids": [ACCOUNT, "sqlite:lending.loan"], "max_work": 1}),
    ("lending", "graph.find_connecting_subgraph", {"node_ids": [ACCOUNT, "missing"]},
     RESOURCE_NOT_FOUND),
    # Cross-entity relationships.
    ("stated", "graph.find_entity_relationship_paths",
     {"from_identity_id": "click_identity", "to_identity_id": "click_identity"}, INVALID_PARAMS),
    ("stated", "graph.get_entity_relationships", {"identity_id": "missing_identity"},
     RESOURCE_NOT_FOUND),
    ("stated", "graph.find_entity_relationship_paths",
     {"from_identity_id": "click_identity", "to_identity_id": "missing_identity"}, RESOURCE_NOT_FOUND),
]


@pytest.mark.parametrize(("service", "method", "params", "code"), ERRORS)
def test_errors_map_to_json_rpc_codes(service: str, method: str, params: dict, code: int) -> None:
    response = dispatch(SERVICES[service](), method, params)
    assert response.get("error", {}).get("code") == code, response
    if code == RESOURCE_NOT_FOUND and "missing_identity" in str(params):
        assert "unknown identity missing_identity" in response["error"]["message"]


def test_dispatcher_returns_results(lending_service) -> None:
    search = dispatch(lending_service, "graph.search", {"query": "customer"})
    assert any(group["match_rows"] for group in search["result"]["groups"])


def test_dispatcher_requires_request_id_and_does_not_accept_notifications(lending_service) -> None:
    dispatcher = JsonRpcDispatcher(lending_service)
    missing_id = dispatcher.dispatch(
        {
            "jsonrpc": "2.0",
            "method": "graph.search",
            "params": {"query": "client"},
        }
    )
    assert missing_id["error"]["code"] == INVALID_REQUEST
    assert missing_id["error"]["message"] == "Request id is required"


def test_unix_socket_supports_multiple_clients_and_user_only_permissions(lending_service) -> None:
    async def exercise() -> None:
        with temporary_socket_path() as socket_path:
            server = GraphUnixServer(lending_service, socket_path)
            await server.start()
            try:
                assert stat.S_IMODE(socket_path.stat().st_mode) == 0o600
                first, second = await asyncio.gather(
                    rpc_call(socket_path, 1, "graph.search", {"query": "customer"}),
                    rpc_call(socket_path, 2, "graph.search", {"query": "loan"}),
                )
                assert first["id"] == 1
                assert second["id"] == 2
                assert any(group["match_rows"] for group in first["result"]["groups"])
                assert any(group["match_rows"] for group in second["result"]["groups"])

                follow_up = await rpc_call(
                    socket_path,
                    3,
                    "graph.expand_subgraph",
                    {"seed_node_ids": ["sqlite:lending.customer"], "max_depth": 1},
                )
                assert follow_up["id"] == 3 and follow_up["result"]["datasets"]["rows"]
            finally:
                await server.close()
            assert not socket_path.exists()

    asyncio.run(exercise())


def test_server_refuses_to_replace_a_regular_file(lending_service) -> None:
    async def exercise() -> None:
        with temporary_socket_path() as socket_path:
            socket_path.write_text("do not replace", encoding="utf-8")
            server = GraphUnixServer(lending_service, socket_path)
            try:
                await server.start()
            except RuntimeError as error:
                assert "refusing to replace non-socket" in str(error)
            else:
                raise AssertionError("server replaced a non-socket path")

    asyncio.run(exercise())


def test_second_singleton_cannot_replace_active_socket(lending_service) -> None:
    async def exercise() -> None:
        with temporary_socket_path() as socket_path:
            first = GraphUnixServer(lending_service, socket_path)
            second = GraphUnixServer(lending_service, socket_path)
            await first.start()
            try:
                try:
                    await second.start()
                except RuntimeError as error:
                    assert "already listening" in str(error)
                else:
                    raise AssertionError("second singleton replaced the active socket")

                response = await rpc_call(
                    socket_path,
                    1,
                    "graph.snapshot_info",
                    {},
                )
                assert response["result"]["node_count"] == 5
            finally:
                await first.close()

    asyncio.run(exercise())
