import asyncio
import json
import stat
import tempfile
from pathlib import Path

from data_ontology_graph.builder import build_snapshot_from_yaml
from data_ontology_graph.rpc.protocol import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    RESOURCE_NOT_FOUND,
    JsonRpcDispatcher,
)
from data_ontology_graph.rpc.server import GraphUnixServer
from data_ontology_graph.service.read import GraphReadService


ROOT = Path(__file__).resolve().parents[1]
FINANCIAL = ROOT / "resources" / "data" / "dev_overlays" / "financial" / "catalog.yaml"


def _service() -> GraphReadService:
    snapshot, _, _ = build_snapshot_from_yaml(FINANCIAL)
    return GraphReadService(snapshot)


def test_dispatcher_exposes_only_read_methods() -> None:
    dispatcher = JsonRpcDispatcher(_service())

    search = dispatcher.dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "graph.search",
            "params": {"query": "customer"},
        }
    )
    assert search is not None
    assert search["result"]["hits"]

    unknown = dispatcher.dispatch(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "graph.generate_sql",
            "params": {},
        }
    )
    assert unknown is not None
    assert unknown["error"]["code"] == METHOD_NOT_FOUND

    invalid = dispatcher.dispatch(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "graph.search",
            "params": {"query": ""},
        }
    )
    assert invalid is not None
    assert invalid["error"]["code"] == INVALID_PARAMS


def test_dispatcher_requires_request_id_and_does_not_accept_notifications() -> None:
    dispatcher = JsonRpcDispatcher(_service())
    missing_id = dispatcher.dispatch(
        {
            "jsonrpc": "2.0",
            "method": "graph.search",
            "params": {"query": "client"},
        }
    )
    assert missing_id["error"]["code"] == INVALID_REQUEST
    assert missing_id["error"]["message"] == "Request id is required"

    missing = dispatcher.dispatch(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "graph.get_dataset",
            "params": {"node_id": "missing"},
        }
    )
    assert missing is not None
    assert missing["error"]["code"] == RESOURCE_NOT_FOUND


def test_unix_socket_supports_multiple_clients_and_user_only_permissions() -> None:
    async def exercise() -> None:
        # macOS limits AF_UNIX paths to roughly 104 bytes; pytest's native
        # temporary path is intentionally much longer than a deployed socket.
        with tempfile.TemporaryDirectory(prefix="dog-", dir="/tmp") as directory:
            socket_path = Path(directory) / "graph.sock"
            server = GraphUnixServer(_service(), socket_path)
            await server.start()
            try:
                assert stat.S_IMODE(socket_path.stat().st_mode) == 0o600
                first, second = await asyncio.gather(
                    _rpc_call(socket_path, 1, "graph.search", {"query": "customer"}),
                    _rpc_call(socket_path, 2, "graph.search", {"query": "loan"}),
                )
                assert first["id"] == 1
                assert second["id"] == 2
                assert first["result"]["hits"]
                assert second["result"]["hits"]

                follow_up = await _rpc_call(
                    socket_path,
                    3,
                    "graph.expand_subgraph",
                    {"seed_node_ids": ["sql_db:financial.client"], "max_depth": 1},
                )
                assert follow_up["result"]["nodes"]
            finally:
                await server.close()
            assert not socket_path.exists()

    asyncio.run(exercise())


def test_server_refuses_to_replace_a_regular_file() -> None:
    async def exercise() -> None:
        with tempfile.TemporaryDirectory(prefix="dog-", dir="/tmp") as directory:
            socket_path = Path(directory) / "graph.sock"
            socket_path.write_text("do not replace", encoding="utf-8")
            server = GraphUnixServer(_service(), socket_path)
            try:
                await server.start()
            except RuntimeError as error:
                assert "refusing to replace non-socket" in str(error)
            else:
                raise AssertionError("server replaced a non-socket path")

    asyncio.run(exercise())


def test_second_singleton_cannot_replace_active_socket() -> None:
    async def exercise() -> None:
        with tempfile.TemporaryDirectory(prefix="dog-", dir="/tmp") as directory:
            socket_path = Path(directory) / "graph.sock"
            first = GraphUnixServer(_service(), socket_path)
            second = GraphUnixServer(_service(), socket_path)
            await first.start()
            try:
                try:
                    await second.start()
                except RuntimeError as error:
                    assert "already listening" in str(error)
                else:
                    raise AssertionError("second singleton replaced the active socket")

                response = await _rpc_call(
                    socket_path,
                    1,
                    "graph.snapshot_info",
                    {},
                )
                assert response["result"]["node_count"] == 8
            finally:
                await first.close()

    asyncio.run(exercise())


async def _rpc_call(
    socket_path: Path,
    request_id: int,
    method: str,
    params: dict,
) -> dict:
    reader, writer = await asyncio.open_unix_connection(socket_path)
    request = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    }
    writer.write(json.dumps(request).encode("utf-8") + b"\n")
    await writer.drain()
    response = json.loads(await reader.readline())
    writer.close()
    await writer.wait_closed()
    return response
