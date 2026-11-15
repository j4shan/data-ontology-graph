"""Deterministic Mehlhorn approximation for unit-cost dataset links.

Directed edges are followed in either direction for connectivity; their claims remain
directional. No path alternatives or semantic decisions are enumerated here.
"""

from dataclasses import dataclass
from collections.abc import Iterable, Mapping
from typing import Literal

from data_ontology_graph.model import ids
from data_ontology_graph.query.neighbourhood import DirectedEdge


class DisjointSets:
    def __init__(self, nodes):
        self.parent = {node: node for node in nodes}
        self.rank = dict.fromkeys(self.parent, 0)

    def root(self, node):
        while self.parent[node] != node:
            self.parent[node] = self.parent[self.parent[node]]
            node = self.parent[node]
        return node

    def join(self, left, right) -> bool:
        left, right = self.root(left), self.root(right)
        if left == right:
            return False
        if self.rank[left] < self.rank[right]:
            left, right = right, left
        self.parent[right] = left
        if self.rank[left] == self.rank[right]:
            self.rank[left] += 1
        return True


@dataclass
class ConnectingTree:
    status: Literal["completed", "disconnected"]
    node_ids: list[str]
    edge_ids: list[str]


Candidate = tuple[int, tuple[int, int], str, str, DirectedEdge]


def connecting_tree(
    edges: Mapping[str, Iterable[DirectedEdge]],
    terminals: list[str],
) -> ConnectingTree:
    # Level-synchronous multi-source BFS builds Voronoi regions and collects the
    # cheapest boundary edge between each pair of regions as it goes.
    owner = {node: node for node in terminals}
    distance = dict.fromkeys(terminals, 0)
    predecessor: dict[str, tuple[str, DirectedEdge]] = {}
    candidates: dict[tuple[str, str], Candidate] = {}
    frontier = list(terminals)
    level = 0
    boundaries = None
    while frontier:
        following = []
        for current in frontier:
            # Edge-ID order keeps region growth and boundary choice deterministic.
            for edge in sorted(edges.get(current, ()), key=lambda item: ids.order(item.edge_id)):
                other = edge.target.node_id
                if other not in owner:
                    owner[other] = owner[current]
                    distance[other] = level + 1
                    predecessor[other] = (current, edge)
                    following.append(other)
                elif owner[other] != owner[current]:
                    left, right = sorted((current, other))
                    pair = tuple(sorted((owner[current], owner[other])))
                    candidate = (distance[current] + 1 + distance[other],
                                 ids.order(edge.edge_id), left, right, edge)
                    previous = candidates.get(pair)
                    if previous is None or candidate[:4] < previous[:4]:
                        candidates[pair] = candidate
        # Every unseen edge now has both endpoints beyond this level, so it
        # costs at least 2 * level + 3. Candidates below that are final, and
        # if they already span the terminals the full run would pick the same tree.
        boundaries = _spanning_boundaries(candidates, terminals, 2 * level + 2)
        if boundaries is not None:
            break
        frontier = following
        level += 1
    if boundaries is None:
        boundaries = _spanning_boundaries(candidates, terminals, None)
    if boundaries is None:
        return ConnectingTree("disconnected", terminals, [])

    # Each boundary edge joins two region trees; with its predecessor chains back
    # to both terminals, the union is already a tree with only terminal leaves.
    nodes = set(terminals)
    edge_ids = set()
    for _, _, left, right, boundary in boundaries:
        edge_ids.add(boundary.edge_id)
        for current in (left, right):
            while current not in nodes:
                nodes.add(current)
                current, parent_edge = predecessor[current]
                edge_ids.add(parent_edge.edge_id)
    return ConnectingTree("completed", sorted(nodes), sorted(edge_ids, key=ids.order))


def _spanning_boundaries(
    candidates: dict[tuple[str, str], Candidate],
    terminals: list[str],
    max_cost: int | None,
) -> list[Candidate] | None:
    """Kruskal over final candidates; None until they connect every terminal."""
    sets = DisjointSets(terminals)
    boundaries = []
    for pair, candidate in sorted(candidates.items(), key=lambda item: item[1][:4]):
        if max_cost is not None and candidate[0] > max_cost:
            break
        if sets.join(*pair):
            boundaries.append(candidate)
            if len(boundaries) == len(terminals) - 1:
                return boundaries
    return None
