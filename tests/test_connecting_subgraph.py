import asyncio
from itertools import combinations
from pathlib import Path
import random
from threading import Event
import tempfile

import pytest
from pydantic import ValidationError

from data_ontology_graph.builder import build_snapshot_from_yaml
from data_ontology_graph.model.relationship import JoinEndpoint, JoinRelationship, edge_id_for
from data_ontology_graph.query.connecting import connecting_tree
from data_ontology_graph.rpc.protocol import INVALID_PARAMS, RESOURCE_NOT_FOUND, JsonRpcDispatcher
from data_ontology_graph.rpc.server import GraphUnixServer
from data_ontology_graph.service.contracts import ConnectingSubgraphRequest, PathsRequest
from data_ontology_graph.service.read import GraphReadService
from test_json_rpc_service import _rpc_call


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "tests/fixtures/lending/catalog.yaml"


def service_for(names, links, **kwargs):
    """Small topology variations using the existing lending fixture's definitions."""
    snapshot, _, _ = build_snapshot_from_yaml(CATALOG)
    template = next(node for node in snapshot.nodes if node.node_id == "sqlite:lending.account")
    definition = next(d for d in template.entity_definitions if d.identity_id == "account_identity")
    nodes = []
    for name in names:
        node = template.model_copy(deep=True)
        node.node_id = name
        node.entity_definitions = [definition.model_copy(deep=True)]
        nodes.append(node)
    edges = []
    for link in links:
        left, right = link[:2]
        forward, reverse = link[2:] if len(link) == 4 else ("1:1", "1:1")
        a = JoinEndpoint(node_id=left, identity_id=definition.identity_id,
                         dataset_columns=definition.dataset_columns)
        b = JoinEndpoint(node_id=right, identity_id=definition.identity_id,
                         dataset_columns=definition.dataset_columns)
        edges.append(JoinRelationship(
            edge_id=edge_id_for(a, b), endpoint_a=a, endpoint_b=b,
            a_to_b={"multiplicity": forward, "match_existence": "always"},
            b_to_a={"multiplicity": reverse, "match_existence": "always"},
        ))
    data = snapshot.model_dump()
    data.update(nodes=nodes, edges=edges, annotations=[])
    return GraphReadService(type(snapshot).model_validate(data), **kwargs)


def test_filter_prunes_calendar_fanout_and_keeps_process_path():
    service = service_for(
        ["confirmation", "day", "fact", "operation", "order", "plant"],
        [("confirmation", "day", "many:1", "1:many"),
         ("day", "fact", "1:many", "many:1"),
         ("fact", "plant", "many:1", "1:many"),
         ("confirmation", "operation", "many:1", "1:many"),
         ("operation", "order", "many:1", "1:many"),
         ("order", "plant", "many:1", "1:many")],
    )
    assert len(service.find_paths("confirmation", "plant", max_hops=3).paths) == 2
    filtered = service.find_paths("confirmation", "plant", max_hops=3,
                                  allowed_multiplicities=["many:1", "1:1"])
    assert len(filtered.paths) == 1
    assert [hop["to_node_id"] for hop in filtered.paths[0]["hops"]] == [
        "operation", "order", "plant",
    ]
    assert service.find_paths("plant", "confirmation", max_hops=3,
                              allowed_multiplicities=["many:1"]).paths == []
    assert service.find_paths("plant", "confirmation", max_hops=3,
                              allowed_multiplicities=["1:many"]).paths


def _all_paths(service, source, target, max_hops, allowed):
    """Reference ranking: every simple path, sorted by hop count then edge IDs."""
    paths = []

    def walk(current, hops, seen):
        if len(hops) == max_hops:
            return
        for edge in service.index.adjacency.get(current, ()):
            if allowed is not None and edge.direction_from(current).multiplicity not in allowed:
                continue
            nxt = edge.opposite(current).node_id
            if nxt in seen:
                continue
            if nxt == target:
                paths.append([*hops, edge.edge_id])
            else:
                walk(nxt, [*hops, edge.edge_id], seen | {nxt})

    walk(source, [], {source})
    return sorted(paths, key=lambda path: (len(path), tuple(path)))


def test_path_ranking_and_truncation_match_exhaustive_enumeration():
    rnd = random.Random(7)
    mults = ["1:1", "1:many", "many:1", "many:many"]
    for _ in range(8):
        names = [f"n{i}" for i in range(9)]
        links = rnd.sample(list(combinations(names, 2)), 16)
        service = service_for(
            names, [(a, b, rnd.choice(mults), rnd.choice(mults)) for a, b in links]
        )
        for source, target in rnd.sample(list(combinations(names, 2)), 6):
            for max_hops in (1, 3, 5):
                for allowed in (None, ["1:1", "many:1"]):
                    expected = _all_paths(service, source, target, max_hops, allowed)
                    for limit in (1, 2, 5, len(expected) or 1, 1000):
                        response = service.find_paths(
                            source, target, max_hops=max_hops, limit=limit,
                            allowed_multiplicities=allowed,
                        )
                        assert [[hop["edge_id"] for hop in path["hops"]]
                                for path in response.paths] == expected[:limit]
                        assert response.truncated is (len(expected) > limit)


def test_path_search_stops_once_the_limit_is_filled():
    names = [f"n{i}" for i in range(10)]
    service = service_for(names, list(combinations(names, 2)))
    expanded = []

    class CountingAdjacency(dict):
        def get(self, key, default=None):
            expanded.append(key)
            return super().get(key, default)

    service.index.adjacency = CountingAdjacency(service.index.adjacency)
    response = service.find_paths("n0", "n9", max_hops=8, limit=1)
    assert [len(path["hops"]) for path in response.paths] == [1]
    assert response.truncated is True
    # Exhaustive search would expand on the order of 10^5 partial paths here.
    assert len(expanded) < 20


def test_unknown_multiplicity_requires_explicit_opt_in():
    service = service_for(["a", "b"], [("a", "b", "unknown", "1:1")])
    assert service.find_paths("a", "b").paths
    assert not service.find_paths("a", "b", allowed_multiplicities=["1:1"]).paths
    assert service.find_paths("a", "b", allowed_multiplicities=["unknown"]).paths
    with pytest.raises(ValidationError):
        PathsRequest(from_node_id="a", to_node_id="b", allowed_multiplicities=[])
    with pytest.raises(ValidationError):
        PathsRequest(from_node_id="a", to_node_id="b", allowed_multiplicities=["invalid"])


def test_connecting_tree_uses_shared_intermediate_and_preserves_evidence():
    service = service_for(["a", "b", "c", "hub", "unused"],
                          [("a", "hub", "many:1", "1:many"),
                           ("b", "hub"), ("c", "hub"), ("hub", "unused")])
    response = service.find_connecting_subgraph(ConnectingSubgraphRequest(node_ids=["c", "a", "b"]))
    assert response.status == "completed"
    assert [node.node_id for node in response.nodes] == ["a", "b", "c", "hub"]
    assert len(response.edges) == 3
    edge = next(edge for edge in response.edges if edge.endpoint_a["node_id"] == "a")
    assert edge.a_to_b["multiplicity"] == "many:1"
    assert edge.b_to_a["multiplicity"] == "1:many"
    reverse = service.find_connecting_subgraph(ConnectingSubgraphRequest(node_ids=["b", "a", "c"]))
    assert response == reverse


def test_disconnected_endpoints_return_no_tree():
    service = service_for(["a", "b", "c"], [("a", "b")])
    response = service.find_connecting_subgraph(ConnectingSubgraphRequest(node_ids=["a", "c"]))
    assert response.status == "disconnected"
    assert [node.node_id for node in response.nodes] == ["a", "c"] and not response.edges


def test_endpoint_cap_is_configurable_and_rpc_validates_inputs():
    service = service_for(["a", "b", "c"], [("a", "b"), ("b", "c")],
                          max_connecting_datasets=2)
    dispatcher = JsonRpcDispatcher(service)
    def call(method, params):
        return dispatcher.dispatch({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    for ids in [["a"], ["a", "a"], ["a", ""], ["a", "b", "c"]]:
        response = call("graph.find_connecting_subgraph", {"node_ids": ids})
        assert response["error"]["code"] == INVALID_PARAMS
    assert call("graph.find_connecting_subgraph", {"node_ids": ["a", "missing"]})["error"]["code"] == RESOURCE_NOT_FOUND
    assert call("graph.find_connecting_subgraph", {"node_ids": ["a", "b"]})["result"]["status"] == "completed"
    assert call("graph.find_paths", {"from_node_id": "a", "to_node_id": "c",
                                    "allowed_multiplicities": ["many:1"]})["result"]["paths"] == []
    assert call("graph.find_connecting_subgraph", {"node_ids": ["a", "b"], "max_work": 1})["error"]["code"] == INVALID_PARAMS


def test_default_endpoint_cap():
    service = service_for(["a", "b"], [("a", "b")])
    with pytest.raises(ValueError, match="at most 16"):
        service.find_connecting_subgraph(
            ConnectingSubgraphRequest(node_ids=[f"n{i}" for i in range(17)])
        )


def is_connected(terminals, edges):
    seen = {terminals[0]}
    while True:
        expanded = seen | {node for a, b in edges if a in seen or b in seen for node in (a, b)}
        if expanded == seen:
            return set(terminals) <= seen
        seen = expanded


def test_approximation_against_exhaustive_small_graph_optimum():
    rng = random.Random(42)
    for _ in range(20):
        names = ["a", "b", "c", "d", "e", "f"]
        links = list(zip(names, names[1:]))
        links += [pair for pair in combinations(names, 2) if pair not in links and rng.random() < .25]
        service = service_for(names, links)
        terminals = ["a", "d", "f"]
        response = service.find_connecting_subgraph(ConnectingSubgraphRequest(node_ids=terminals))
        result = [(edge.endpoint_a["node_id"], edge.endpoint_b["node_id"]) for edge in response.edges]
        assert response.status == "completed" and is_connected(terminals, result)
        assert len(result) == len(response.nodes) - 1
        optimum = next(k for k in range(1, len(links) + 1)
                       if any(is_connected(terminals, subset) for subset in combinations(links, k)))
        assert len(result) <= 2 * optimum
        assert all(sum(node.node_id in pair for pair in result) > 1
                   for node in response.nodes if node.node_id not in terminals)


class CountingAdjacency(dict):
    def __init__(self, adjacency):
        super().__init__(adjacency)
        self.expanded = 0

    def get(self, key, default=None):
        self.expanded += 1
        return super().get(key, default)


def full_mehlhorn(adjacency, terminals):
    """Reference without early termination: whole-component BFS, then Kruskal."""
    owner, distance, predecessor = {t: t for t in terminals}, dict.fromkeys(terminals, 0), {}
    queue = list(terminals)
    for current in queue:
        for edge in adjacency.get(current, ()):
            other = edge.opposite(current).node_id
            if other not in owner:
                owner[other], distance[other] = owner[current], distance[current] + 1
                predecessor[other] = (current, edge)
                queue.append(other)
    candidates = {}
    for current in queue:
        for edge in adjacency.get(current, ()):
            other = edge.opposite(current).node_id
            if current < other and owner[current] != owner[other]:
                pair = tuple(sorted((owner[current], owner[other])))
                candidate = (distance[current] + 1 + distance[other], edge.edge_id, current, other)
                candidates[pair] = min(candidates.get(pair, candidate), candidate)
    parent = {t: t for t in terminals}
    def root(node):
        while parent[node] != node:
            node = parent[node]
        return node
    nodes, edge_ids = set(terminals), set()
    for pair, (_, edge_id, left, right) in sorted(candidates.items(), key=lambda item: item[1]):
        if root(pair[0]) == root(pair[1]):
            continue
        parent[root(pair[0])] = root(pair[1])
        edge_ids.add(edge_id)
        for current in (left, right):
            while current not in nodes:
                nodes.add(current)
                current, edge = predecessor[current]
                edge_ids.add(edge.edge_id)
    if len({root(t) for t in terminals}) > 1:
        return None
    return sorted(nodes), sorted(edge_ids)


def test_early_termination_matches_full_mehlhorn_on_random_graphs():
    rng = random.Random(7)
    for _ in range(40):
        names = [f"n{i:02}" for i in range(rng.randint(6, 30))]
        links = sorted({tuple(sorted(rng.sample(names, 2))) for _ in range(len(names) * 2)})
        service = service_for(names, links)
        terminals = sorted(rng.sample(names, rng.randint(2, min(6, len(names)))))
        tree = connecting_tree(service.index.adjacency, terminals)
        expected = full_mehlhorn(service.index.adjacency, terminals)
        if expected is None:
            assert tree.status == "disconnected"
        else:
            assert (tree.status, (tree.node_ids, tree.edge_ids)) == ("completed", expected)
            assert len(tree.edge_ids) == len(tree.node_ids) - 1


def test_search_stops_at_the_terminals_neighbourhood():
    names = [f"n{i:03}" for i in range(200)]
    service = service_for(names, list(zip(names, names[1:])))
    adjacency = CountingAdjacency(service.index.adjacency)
    tree = connecting_tree(adjacency, ["n100", "n101"])
    assert tree.edge_ids == [service.index.adjacency["n100"][1].edge_id]
    assert adjacency.expanded == 2
    adjacency = CountingAdjacency(service.index.adjacency)
    assert len(connecting_tree(adjacency, [names[0], names[-1]]).edge_ids) == 199
    assert adjacency.expanded <= len(names)


def test_navigation_does_not_block_lookup_and_shutdown_cancels_workers():
    async def exercise():
        service = service_for(["a", "b"], [("a", "b")])
        started, stopped, second_started = Event(), Event(), Event()
        original = service.find_paths
        def slow(from_node_id, to_node_id, cancel_event=None, **kwargs):
            if from_node_id == "a":
                started.set()
            else:
                second_started.set()
            assert cancel_event.wait(3), "server did not cancel navigation"
            stopped.set()
            return original(from_node_id, to_node_id, cancel_event=cancel_event, **kwargs)
        service.find_paths = slow
        with tempfile.TemporaryDirectory(prefix="dog-", dir="/tmp") as directory:
            server = GraphUnixServer(service, Path(directory) / "graph.sock",
                                     max_concurrent_navigation=1)
            await server.start()
            pending = asyncio.create_task(_rpc_call(server.socket_path, 1,
                "graph.find_paths", {"from_node_id": "a", "to_node_id": "b"}))
            second_pending = None
            try:
                assert await asyncio.to_thread(started.wait, 1)
                second_pending = asyncio.create_task(_rpc_call(server.socket_path, 3,
                    "graph.find_paths", {"from_node_id": "b", "to_node_id": "a"}))
                response = await asyncio.wait_for(_rpc_call(server.socket_path, 2,
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
