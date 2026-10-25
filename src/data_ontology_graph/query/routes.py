"""The k shortest routes between two datasets, with entity definitions as route stops.

A directed edge follows a stored relationship to its other endpoint and costs 1; a pivot moves to another
definition on the same dataset and costs 0. The searched graph holds each definition twice: as
arrived by a directed edge and as ready to leave. Pivots link the arrived copy to the ready copies of the
dataset's other definitions, and directed edges link a ready copy to the arrived copy across a
relationship, so a directed edge is always followed by a pivot or the route's end, and two
directed edges on one key never repeat a direct one. A route may revisit a dataset through a different definition but never
reuses a definition, and it ends on first reaching the target dataset.

A search is linear in the stored relationships. Yen's algorithm turns the shortest search into k
shortest simple routes.
"""

from __future__ import annotations

import heapq
from collections import defaultdict, deque
from collections.abc import Callable, Iterable

from data_ontology_graph.model.dataset import DatasetNode
from data_ontology_graph.model.enums import Multiplicity
from data_ontology_graph.model.relationship import JoinRelationship

SOURCE = -1
TARGET = -2

DefinitionKey = tuple[str, str, tuple[str, ...]]
State = int
"""``SOURCE``, ``TARGET``, ``2 * d`` (ready to leave definition d), or ``2 * d + 1`` (arrived)."""


def _ready(definition: int) -> State:
    return 2 * definition


def _arrived(definition: int) -> State:
    return 2 * definition + 1


class RouteGraph:
    def __init__(
        self, nodes: Iterable[DatasetNode], relationships: Iterable[JoinRelationship],
    ) -> None:
        self.keys: list[DefinitionKey] = []
        self.on_dataset: dict[str, list[int]] = defaultdict(list)
        for node in sorted(nodes, key=lambda item: item.node_id):
            for definition in sorted(node.entity_definitions, key=lambda item: item.key(node.node_id)):
                self.on_dataset[node.node_id].append(len(self.keys))
                self.keys.append(definition.key(node.node_id))
        index = {key: position for position, key in enumerate(self.keys)}
        self.edges: dict[int, list[tuple[int, Multiplicity, str]]] = defaultdict(list)
        """Each definition's directed edges: (target definition, outgoing multiplicity, edge ID)."""
        self._edge_by_pair: dict[tuple[int, int], str] = {}
        for relationship in sorted(relationships, key=lambda item: item.edge_id):
            a = index[relationship.endpoint_a.identity_key()]
            b = index[relationship.endpoint_b.identity_key()]
            self.edges[a].append((b, relationship.a_to_b.multiplicity, relationship.edge_id))
            self.edges[b].append((a, relationship.b_to_a.multiplicity, relationship.edge_id))
            self._edge_by_pair[(a, b)] = self._edge_by_pair[(b, a)] = relationship.edge_id

    def edge_id(self, source: int, target: int) -> str:
        return self._edge_by_pair[(source, target)]

    def k_shortest(
        self,
        source: str,
        target: str,
        k: int,
        max_edges: int,
        allowed: set[Multiplicity] | None = None,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> tuple[list[list[tuple[int, int]]], bool]:
        """Up to ``k`` routes as (source, target) definition pairs, and whether more exist.

        Routes are ordered by their number of directed edges, then by their sequence of edge IDs and
        the definitions each directed edge leaves from.
        """
        search = _Search(self, source, target, allowed)
        first = search.shortest(SOURCE, set(), set(), max_edges)
        if first is None:
            return [], False
        found = [first]
        candidates: list[tuple[int, tuple, tuple[State, ...]]] = []
        seen = {tuple(first)}
        while len(found) <= k and not cancelled():
            previous = found[-1]
            for j in range(len(previous) - 1):
                root = previous[: j + 1]
                removed = {
                    (route[j], route[j + 1]) for route in found if route[: j + 1] == root
                }
                blocked = {state // 2 for state in root[:-1] if state >= 0}
                spur = search.shortest(root[-1], blocked, removed, max_edges - _edge_count(root))
                if spur is None:
                    continue
                route = root[:-1] + spur
                if tuple(route) in seen or not _simple(route):
                    continue
                seen.add(tuple(route))
                heapq.heappush(candidates, (_edge_count(route), self._edge_ids(route), tuple(route)))
            if not candidates:
                break
            found.append(list(heapq.heappop(candidates)[2]))
        routes = sorted(found[:k], key=lambda route: (_edge_count(route), self._edge_ids(route)))
        return [_edge_pairs(route) for route in routes], len(found) > k

    def _edge_ids(self, route: list[State]) -> tuple[tuple[str, DefinitionKey], ...]:
        return tuple((self.edge_id(a, b), self.keys[a]) for a, b in _edge_pairs(route))


class _Search:
    def __init__(
        self, graph: RouteGraph, source: str, target: str, allowed: set[Multiplicity] | None,
    ) -> None:
        self.graph = graph
        self.source = source
        self.target = target
        self.allowed = allowed

    def shortest(
        self, start: State, blocked: set[int], removed: set[tuple[State, State]], budget: int,
    ) -> list[State] | None:
        """The route with the fewest directed edges from ``start`` to the target within ``budget``."""
        if budget < 0:
            return None
        graph = self.graph
        distance = {start: 0}
        previous: dict[State, State] = {}
        done: set[State] = set()
        queue: deque[State] = deque([start])
        while queue:
            state = queue.popleft()
            if state in done:
                continue
            done.add(state)
            if state == TARGET:
                route = [state]
                while route[-1] != start:
                    route.append(previous[route[-1]])
                return route[::-1]
            cost_here = distance[state]
            for following, cost in self._successors(state, blocked, removed):
                total = cost_here + cost
                if total > budget or total >= distance.get(following, budget + 1):
                    continue
                distance[following] = total
                previous[following] = state
                (queue.appendleft if cost == 0 else queue.append)(following)
        return None

    def _successors(self, state, blocked, removed):
        graph = self.graph
        if state == SOURCE:
            for definition in graph.on_dataset.get(self.source, ()):
                ready = _ready(definition)
                if definition not in blocked and (state, ready) not in removed:
                    yield ready, 0
            return
        definition, arrived = divmod(state, 2)
        node_id = graph.keys[definition][0]
        if arrived:
            if node_id == self.target:
                if (state, TARGET) not in removed:
                    yield TARGET, 0
                return
            for other in graph.on_dataset[node_id]:
                ready = _ready(other)
                if other != definition and other not in blocked and (state, ready) not in removed:
                    yield ready, 0
            return
        for target, multiplicity, _ in graph.edges[definition]:
            following = _arrived(target)
            if target in blocked or (state, following) in removed:
                continue
            if self.allowed is None or multiplicity in self.allowed:
                yield following, 1


def _edge_count(route: list[State]) -> int:
    return sum(1 for state in route if state >= 0 and state % 2 == 1)


def _simple(route: list[State]) -> bool:
    definitions = [state // 2 for state in route if state >= 0]
    return len(definitions) == len(set(definitions))


def _edge_pairs(route: list[State]) -> list[tuple[int, int]]:
    return [
        (a // 2, b // 2)
        for a, b in zip(route, route[1:])
        if a >= 0 and b >= 0 and a % 2 == 0 and b % 2 == 1
    ]
