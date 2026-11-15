import asyncio
from itertools import combinations
import random
from threading import Event

import pytest
from pydantic import ValidationError

from data_ontology_graph.model import ids
from data_ontology_graph.query.connecting import connecting_tree
from data_ontology_graph.rpc.protocol import INVALID_PARAMS
from data_ontology_graph.rpc.server import GraphUnixServer
from data_ontology_graph.service.contracts import ConnectingSubgraphRequest, PathsRequest
from testkit.records import by_id, edges, paths
from testkit.builders import topology_service
from testkit.rpc import dispatch, rpc_call, temporary_socket_path


def find(service, source, target, **kwargs):
    return service.find_paths(PathsRequest(from_node_id=source, to_node_id=target, **kwargs))


def test_filter_prunes_calendar_fanout_and_keeps_process_path():
    service = topology_service(
        ["confirmation", "day", "fact", "operation", "order", "plant"],
        [("confirmation", "day", "many:1", "1:many"),
         ("day", "fact", "1:many", "many:1"),
         ("fact", "plant", "many:1", "1:many"),
         ("confirmation", "operation", "many:1", "1:many"),
         ("operation", "order", "many:1", "1:many"),
         ("order", "plant", "many:1", "1:many")],
    )
    assert find(service, "confirmation", "plant", max_edges=3).path_count == 2
    filtered = find(service, "confirmation", "plant", max_edges=3,
                    allowed_multiplicities=["many:1", "1:1"])
    assert filtered.path_count == 1
    assert [edge["to_node_id"] for edge in paths(filtered)[0]] == [
        "operation", "order", "plant",
    ]
    assert find(service, "plant", "confirmation", max_edges=3,
                allowed_multiplicities=["many:1"]).path_count == 0
    assert find(service, "plant", "confirmation", max_edges=3,
                allowed_multiplicities=["1:many"]).path_count


def _all_paths(service, source, target, max_edges, allowed):
    """Reference: every path that never reuses a definition, as edge-ID lists.

    A path arrives at a dataset on one definition and leaves on another, so it may revisit a
    dataset, and it ends on first reaching the target.
    """
    found = []

    def walk(current, arrived_on, edges, used):
        if len(edges) == max_edges:
            return
        for edge in service.index.directed_edges.get(current, ()):
            leaving, arriving = edge.source, edge.target
            if leaving.identity_key() == arrived_on:
                continue
            if allowed is not None and edge.outgoing.multiplicity not in allowed:
                continue
            keys = {leaving.identity_key(), arriving.identity_key()}
            if keys & used:
                continue
            path = [*edges, edge.edge_id]
            if arriving.node_id == target:
                found.append(path)
            else:
                walk(arriving.node_id, arriving.identity_key(), path, used | keys)

    walk(source, None, [], set())
    return found


def test_k_shortest_paths_match_exhaustive_enumeration():
    rnd = random.Random(7)
    mults = ["1:1", "1:many", "many:1", "many:many"]
    for _ in range(8):
        names = [f"n{i}" for i in range(9)]
        links = rnd.sample(list(combinations(names, 2)), 16)
        service = topology_service(
            names, [(a, b, rnd.choice(mults)) for a, b in links]
        )
        for source, target in rnd.sample(list(combinations(names, 2)), 6):
            for max_edges in (1, 3, 5):
                for allowed in (None, ["1:1", "many:1"]):
                    expected = sorted(
                        _all_paths(service, source, target, max_edges, allowed),
                        key=lambda path: (len(path), tuple(path)),
                    )
                    valid = {tuple(path) for path in expected}
                    for limit in (1, 2, 5, len(expected) or 1, 100):
                        response = find(service, source, target, max_edges=max_edges,
                                        limit=limit, allowed_multiplicities=allowed)
                        found = [tuple(edge["edge_id"] for edge in path) for path in paths(response)]
                        # The k shortest: every path exists, lengths are the k smallest, and no
                        # path repeats. Which of several equal-length paths is a tie-break.
                        assert set(found) <= valid and len(set(found)) == len(found)
                        assert [len(path) for path in found] == [
                            len(path) for path in expected[:limit]
                        ]
                        assert response.truncated is (len(expected) > limit)
                        if limit >= len(expected):
                            assert sorted(found) == sorted(map(tuple, expected))


def test_path_search_cost_does_not_follow_the_number_of_paths(monkeypatch):
    from data_ontology_graph.query import paths as path_module

    names = [f"n{i}" for i in range(10)]
    service = topology_service(names, list(combinations(names, 2)))
    searches = []
    original = path_module._Search.shortest

    def counting(self, *args):
        searches.append(args)
        return original(self, *args)

    monkeypatch.setattr(path_module._Search, "shortest", counting)
    response = find(service, "n0", "n9", max_edges=8, limit=1)
    assert [len(path) for path in paths(response)] == [1]
    assert response.truncated is True
    # Enumerating every path here would expand on the order of 10^5 partial paths; the k
    # shortest search runs about one shortest search per state of each path found.
    assert len(searches) < 20


def test_paths_list_each_dataset_once_and_orient_every_directed_edge():
    service = topology_service(["a", "b", "c", "d"], [("a", "b"), ("b", "c"), ("b", "d"), ("c", "d")])
    response = find(service, "a", "c", max_edges=3)
    assert [[(edge["from_node_id"], edge["to_node_id"]) for edge in path]
            for path in paths(response)] == [[("a", "b"), ("b", "c")],
                                            [("a", "b"), ("b", "d"), ("d", "c")]]
    assert list(by_id(response.datasets, "node_id")) == ["a", "b", "c", "d"]
    # The c-d edge is stored canonically with c first and traversed from d.
    last = paths(response)[1][-1]
    assert service.get_relationship(last["edge_id"]).endpoint_a["node_id"] == "c"
    assert last["from_node_id"] == "d"

def test_unknown_multiplicity_requires_explicit_opt_in():
    service = topology_service(["a", "b"], [("a", "b", "unknown", "unknown")])
    assert find(service, "a", "b").path_count
    assert not find(service, "a", "b", allowed_multiplicities=["1:1"]).path_count
    assert find(service, "a", "b", allowed_multiplicities=["unknown"]).path_count
    with pytest.raises(ValidationError):
        PathsRequest(from_node_id="a", to_node_id="b", allowed_multiplicities=[])
    with pytest.raises(ValidationError):
        PathsRequest(from_node_id="a", to_node_id="b", allowed_multiplicities=["invalid"])


def test_connecting_tree_uses_shared_intermediate_and_preserves_evidence():
    service = topology_service(["a", "b", "c", "hub", "unused"],
                          [("a", "hub", "many:1", "1:many"),
                           ("b", "hub"), ("c", "hub"), ("hub", "unused")])
    response = service.find_connecting_subgraph(ConnectingSubgraphRequest(node_ids=["c", "a", "b"]))
    assert response.status == "completed"
    assert list(by_id(response.datasets, "node_id")) == ["a", "b", "c", "hub"]
    tree_edges = edges(response)
    # Each tree relationship is a edge from each of its two datasets.
    assert len({edge["edge_id"] for edge in tree_edges}) == 3 and len(tree_edges) == 6
    from_a = next(edge for edge in tree_edges if edge["from_node_id"] == "a")
    assert from_a["multiplicity"] == "many:1"
    back = next(edge for edge in tree_edges
                if edge["from_node_id"] == "hub" and edge["to_node_id"] == "a")
    assert back["multiplicity"] == "1:many"
    reverse = service.find_connecting_subgraph(ConnectingSubgraphRequest(node_ids=["b", "a", "c"]))
    assert response == reverse


def test_disconnected_endpoints_return_no_tree():
    service = topology_service(["a", "b", "c"], [("a", "b")])
    response = service.find_connecting_subgraph(ConnectingSubgraphRequest(node_ids=["a", "c"]))
    assert response.status == "disconnected"
    assert list(by_id(response.datasets, "node_id")) == ["a", "c"]
    assert not edges(response)


def test_endpoint_cap_is_configurable_and_defaults_to_sixteen():
    service = topology_service(["a", "b", "c"], [("a", "b"), ("b", "c")],
                               max_connecting_datasets=2)
    over_cap = dispatch(service, "graph.find_connecting_subgraph", {"node_ids": ["a", "b", "c"]})
    assert over_cap["error"]["code"] == INVALID_PARAMS
    assert dispatch(service, "graph.find_connecting_subgraph",
                    {"node_ids": ["a", "b"]})["result"]["status"] == "completed"
    assert dispatch(service, "graph.find_paths", {"from_node_id": "a", "to_node_id": "c",
                                                  "allowed_multiplicities": ["many:1"]})["result"]["path_count"] == 0
    with pytest.raises(ValueError, match="at most 16"):
        topology_service(["a", "b"], [("a", "b")]).find_connecting_subgraph(
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
        service = topology_service(names, links)
        terminals = ["a", "d", "f"]
        response = service.find_connecting_subgraph(ConnectingSubgraphRequest(node_ids=terminals))
        result = sorted({
            tuple(sorted((edge["from_node_id"], edge["to_node_id"])))
            for edge in edges(response)
        })
        datasets = by_id(response.datasets, "node_id")
        assert response.status == "completed" and is_connected(terminals, result)
        assert len(result) == len(datasets) - 1
        optimum = next(k for k in range(1, len(links) + 1)
                       if any(is_connected(terminals, subset) for subset in combinations(links, k)))
        assert len(result) <= 2 * optimum
        assert all(sum(node_id in pair for pair in result) > 1
                   for node_id in datasets if node_id not in terminals)


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
            other = edge.target.node_id
            if other not in owner:
                owner[other], distance[other] = owner[current], distance[current] + 1
                predecessor[other] = (current, edge)
                queue.append(other)
    candidates = {}
    for current in queue:
        for edge in adjacency.get(current, ()):
            other = edge.target.node_id
            if current < other and owner[current] != owner[other]:
                pair = tuple(sorted((owner[current], owner[other])))
                candidate = (distance[current] + 1 + distance[other], ids.order(edge.edge_id), current, other,
                             edge.edge_id)
                candidates[pair] = min(candidates.get(pair, candidate), candidate)
    parent = {t: t for t in terminals}
    def root(node):
        while parent[node] != node:
            node = parent[node]
        return node
    nodes, edge_ids = set(terminals), set()
    for pair, (_, _, left, right, edge_id) in sorted(candidates.items(), key=lambda item: item[1]):
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
    return sorted(nodes), sorted(edge_ids, key=ids.order)


def test_early_termination_matches_full_mehlhorn_on_random_graphs():
    rng = random.Random(7)
    for _ in range(40):
        names = [f"n{i:02}" for i in range(rng.randint(6, 30))]
        links = sorted({tuple(sorted(rng.sample(names, 2))) for _ in range(len(names) * 2)})
        service = topology_service(names, links)
        terminals = sorted(rng.sample(names, rng.randint(2, min(6, len(names)))))
        tree = connecting_tree(service.index.directed_edges, terminals)
        expected = full_mehlhorn(service.index.directed_edges, terminals)
        if expected is None:
            assert tree.status == "disconnected"
        else:
            assert (tree.status, (tree.node_ids, tree.edge_ids)) == ("completed", expected)
            assert len(tree.edge_ids) == len(tree.node_ids) - 1


def test_search_stops_at_the_terminals_neighbourhood():
    names = [f"n{i:03}" for i in range(200)]
    service = topology_service(names, list(zip(names, names[1:])))
    adjacency = CountingAdjacency(service.index.directed_edges)
    tree = connecting_tree(adjacency, ["n100", "n101"])
    [between] = [edge for edge in service.index.directed_edges["n100"] if edge.target.node_id == "n101"]
    assert tree.edge_ids == [between.edge_id]
    assert adjacency.expanded == 2
    adjacency = CountingAdjacency(service.index.directed_edges)
    assert len(connecting_tree(adjacency, [names[0], names[-1]]).edge_ids) == 199
    assert adjacency.expanded <= len(names)


def test_navigation_does_not_block_lookup_and_shutdown_cancels_workers():
    async def exercise():
        service = topology_service(["a", "b"], [("a", "b")])
        started, stopped, second_started = Event(), Event(), Event()
        original = service.find_paths
        def slow(request, cancel_event=None):
            if request.from_node_id == "a":
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
                "graph.find_paths", {"from_node_id": "a", "to_node_id": "b"}))
            second_pending = None
            try:
                assert await asyncio.to_thread(started.wait, 1)
                second_pending = asyncio.create_task(rpc_call(server.socket_path, 3,
                    "graph.find_paths", {"from_node_id": "b", "to_node_id": "a"}))
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
