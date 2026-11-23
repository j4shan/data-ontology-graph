"""The server runs navigation outside the request loop, in bounded slots, and cancels it on
shutdown (system design non-functional 1.3)."""
import asyncio
from threading import Event

from data_ontology_graph.rpc.server import GraphUnixServer
from testkit.builders import topology_service
from testkit.rpc import rpc_call, temporary_socket_path


def test_navigation_does_not_block_lookup_and_shutdown_cancels_workers():
    async def exercise():
        service = topology_service(["a", "b"], [("a", "b")])
        started, stopped, second_started = Event(), Event(), Event()
        original = service.find_paths
        def slow(request, cancel_event=None):
            if request.max_links == 1:
                started.set()
            else:
                second_started.set()
            assert cancel_event.wait(3), "server did not cancel navigation"
            stopped.set()
            return original(request, cancel_event)
        service.find_paths = slow
        with temporary_socket_path() as path:
            server = GraphUnixServer(service, path,
                                     max_concurrent_navigation=1)
            await server.start()
            pending = asyncio.create_task(rpc_call(server.socket_path, 1,
                "graph.find_paths", {"source_identity_id": "a~b", "target_identity_id": "a~b", "max_links": 1}))
            second_pending = None
            try:
                assert await asyncio.to_thread(started.wait, 1)
                second_pending = asyncio.create_task(rpc_call(server.socket_path, 3,
                    "graph.find_paths", {"source_identity_id": "a~b", "target_identity_id": "a~b", "max_links": 2}))
                response = await asyncio.wait_for(rpc_call(server.socket_path, 2,
                    "graph.snapshot_info", {}), timeout=1)
                assert response["result"]["node_count"] == 2
                assert not second_started.is_set()
                await asyncio.wait_for(server.close(), timeout=1)
                assert stopped.is_set()
                assert not second_started.is_set()
            finally:
                await server.close()
                await asyncio.gather(pending, return_exceptions=True)
                if second_pending is not None:
                    await asyncio.gather(second_pending, return_exceptions=True)
    asyncio.run(exercise())
