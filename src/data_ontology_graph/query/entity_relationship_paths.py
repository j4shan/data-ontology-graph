"""Ranked simple paths over cross-entity relationships (system design 2.3.13)."""

from collections import deque
from collections.abc import Callable

from data_ontology_graph.model.entity_relationship import EntityRelationshipIndex


def ranked_paths(
    index: EntityRelationshipIndex,
    source: str,
    target: str,
    limit: int,
    max_steps: int,
    cancelled: Callable[[], bool] = lambda: False,
) -> tuple[list[list[str]], bool]:
    """Up to ``limit`` simple paths from ``source`` to ``target``, and whether more exist.

    Paths are logical entity ID sequences ranked by step count, then lexicographically. The
    search enumerates each length in neighbour order and extends a prefix only toward logical
    entities that can still reach ``target`` within the remaining steps, so it searches for
    ``limit + 1`` paths without listing every simple path.
    """
    distance = _distances_to(index, target, max_steps)
    if source not in distance:
        return [], False
    found: list[list[str]] = []
    wanted = limit + 1
    for length in range(distance[source], max_steps + 1):
        path = [source]
        on_path = {source}

        def extend(remaining: int) -> bool:
            """Extend ``path`` by exactly ``remaining`` steps; True once enough paths are found."""
            if cancelled():
                return True
            current = path[-1]
            if remaining == 0:
                if current == target:
                    found.append(list(path))
                return len(found) >= wanted
            for neighbour in index.related(current):
                if neighbour in on_path or distance.get(neighbour, max_steps + 1) > remaining - 1:
                    continue
                if neighbour == target and remaining > 1:
                    continue
                path.append(neighbour)
                on_path.add(neighbour)
                done = extend(remaining - 1)
                path.pop()
                on_path.discard(neighbour)
                if done:
                    return True
            return False

        if extend(length):
            break
    return found[:limit], len(found) > limit


def _distances_to(index: EntityRelationshipIndex, target: str, max_steps: int) -> dict[str, int]:
    distance = {target: 0}
    queue = deque([target])
    while queue:
        current = queue.popleft()
        if distance[current] == max_steps:
            continue
        for neighbour in index.related(current):
            if neighbour not in distance:
                distance[neighbour] = distance[current] + 1
                queue.append(neighbour)
    return distance
