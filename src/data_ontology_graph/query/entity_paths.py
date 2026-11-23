"""Path search between logical entities (system design 2.3.6).

The search returns every path, or participant subgraph, that exists within the bounds under the
caller's filters; it never judges which existing results are wanted. An entity link joins two logical
entities that have entity definitions on a common dataset or a stated cross-entity relationship.
Each way to make an entity link is a pivot: one definition of each logical entity on a common dataset,
read in the direction of travel, or the stated cross-entity relationship with its claims. A
realisation picks one pivot per entity link; two consecutive dataset pivots on one definition of the
middle logical entity meet on the same records, so they restate the shorter path. A stated
pivot never restates.
"""
from __future__ import annotations

import itertools
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace

from data_ontology_graph.model.derivation import MembershipIndex, step_match_existence, step_multiplicity
from data_ontology_graph.model.entity_relationship import EntityRelationshipIndex
from data_ontology_graph.model.enums import MatchExistence, Multiplicity

SCAN_CAP = 20_000
"""Paths enumerated per search before a count is reported as a lower bound."""
RELAXATION_CAP = 1_000
"""Paths enumerated per relaxation count; a relaxation only needs to show that more exist."""
LEG_COMBINATION_LEGS = 10
"""Legs per participant combined into independent-leg subgraphs, shortest first."""
THROUGH_LIMIT = 10
TO_ONE = frozenset({Multiplicity.MANY_TO_ONE, Multiplicity.ONE_TO_ONE})
CONVERGING = TO_ONE | {Multiplicity.ONE_TO_MANY}

Chain = tuple[str, ...]
Cancelled = Callable[[], bool]


@dataclass(frozen=True)
class Pivot:
    node_id: str | None
    """The common dataset; None for the stated cross-entity relationship."""
    source_columns: tuple[str, ...]
    target_columns: tuple[str, ...]
    multiplicity: Multiplicity
    match_existence: MatchExistence


@dataclass(frozen=True)
class PathQuery:
    source: str
    target: str
    max_links: int = 2
    stated_only: bool = False
    multiplicity: frozenset[Multiplicity] | None = None
    converging: bool = False
    match_existence: frozenset[MatchExistence] | None = None
    avoid: frozenset[str] = frozenset()
    participants: tuple[str, ...] = ()
    closed: bool = False
    shape: str = "both"
    k_unnamed: int = 0
    exclude_restatements: bool = True
    self_links: bool = False

    @property
    def claim_filtered(self) -> bool:
        return self.multiplicity is not None or self.match_existence is not None or self.converging


@dataclass
class Found:
    """One result: its logical entities, its entity links (pairs in the direction read), and its rank key."""

    entities: Chain
    links: tuple[tuple[str, str], ...]
    shape: str
    key: tuple
    order: tuple
    legs: dict[str, Chain] | None = None
    unnamed: Chain | None = None


@dataclass
class SearchResult:
    found: list[Found]
    lower_bound: bool
    leg_counts: dict[str, int] | None = None


class EntityLinks:
    """Entity links between logical entities, derived on demand from the membership index.

    Neighbours come from a membership lookup: a logical entity's definitions give its datasets,
    whose definitions give the linked logical entities, deduplicated once. A logical entity links
    to itself when a dataset holds two of its definitions. Results are cached per snapshot.
    """

    def __init__(self, memberships: MembershipIndex, stated: EntityRelationshipIndex) -> None:
        self.memberships = memberships
        self.stated = stated
        self._neighbours: dict[str, tuple[str, ...]] = {}
        self._pivots: dict[tuple[str, str], tuple[Pivot, ...]] = {}
        self._options: dict[tuple[str, str], tuple[Pivot, ...]] = {}
        self.dataset_count = {
            identity: len({key.node_id for key in keys})
            for identity, keys in memberships.by_identity.items()
        }

    def neighbours(self, identity: str) -> tuple[str, ...]:
        hit = self._neighbours.get(identity)
        if hit is None:
            keys = self.memberships.by_identity.get(identity, ())
            node_ids = {key.node_id for key in keys}
            linked = {
                definition.identity_id
                for node_id in node_ids
                for definition in self.memberships.nodes[node_id].entity_definitions
            }
            if len(keys) == len(node_ids):
                linked.discard(identity)
            linked.update(self.stated.related(identity))
            hit = tuple(sorted(linked))
            self._neighbours[identity] = hit
        return hit

    def options(self, source: str, target: str) -> tuple[Pivot, ...]:
        """Every way to make the entity link: its dataset pivots, then the stated relationship."""
        hit = self._options.get((source, target))
        if hit is None:
            relationship = self.stated.between(source, target)
            stated = ()
            if relationship is not None:
                claims = relationship.read_from(source)
                stated = (Pivot(None, (), (), claims.multiplicity, claims.match_existence),)
            hit = self.pivots(source, target) + stated
            self._options[(source, target)] = hit
        return hit

    def pivots(self, source: str, target: str) -> tuple[Pivot, ...]:
        """The entity link's pivots on common datasets."""
        hit = self._pivots.get((source, target))
        if hit is None:
            by_node: dict[str, list] = {}
            for key in self.memberships.by_identity.get(target, ()):
                by_node.setdefault(key.node_id, []).append(key)
            out = []
            for a in self.memberships.by_identity.get(source, ()):
                for b in by_node.get(a.node_id, ()):
                    if a == b:
                        continue
                    left, right = self.memberships.definitions[a], self.memberships.definitions[b]
                    out.append(Pivot(a.node_id, a.dataset_columns, b.dataset_columns,
                                     step_multiplicity(left, right), step_match_existence(right)))
            hit = tuple(out)
            self._pivots[(source, target)] = hit
        return hit

    def is_stated(self, left: str, right: str) -> bool:
        return self.stated.between(left, right) is not None


# ---- filtered entity link graph -----------------------------------------------------------------

def _pivot_passes(pivot: Pivot, query: PathQuery) -> bool:
    if query.multiplicity is not None and pivot.multiplicity not in query.multiplicity:
        return False
    return query.match_existence is None or pivot.match_existence in query.match_existence


def _phase(phase: int, multiplicity: Multiplicity, converging: bool) -> int | None:
    """Converging order: ``many:1`` entity links, then ``1:many`` entity links; ``1:1`` fits either."""
    if not converging:
        return 0
    if multiplicity is Multiplicity.ONE_TO_ONE:
        return phase
    if multiplicity is Multiplicity.MANY_TO_ONE:
        return 0 if phase == 0 else None
    if multiplicity is Multiplicity.ONE_TO_MANY:
        return 1
    return None


class _Links:
    """The entity link graph under one query: stated-only, avoided entities, and per-link claim filters
    (an entity link is usable when one of its pivots passes them, in the direction travelled)."""

    def __init__(self, links: EntityLinks, query: PathQuery) -> None:
        self.links, self.query = links, query
        self._out: dict[str, tuple[str, ...]] = {}
        self._in: dict[str, tuple[str, ...]] = {}

    def usable(self, source: str, target: str) -> bool:
        if self.query.stated_only and not self.links.is_stated(source, target):
            return False
        if self.query.multiplicity is None and self.query.match_existence is None:
            return True
        return any(_pivot_passes(p, self.query) for p in self.links.options(source, target))

    def out(self, u: str) -> tuple[str, ...]:
        hit = self._out.get(u)
        if hit is None:
            hit = tuple(v for v in self.links.neighbours(u)
                        if v not in self.query.avoid and self.usable(u, v))
            self._out[u] = hit
        return hit

    def into(self, u: str) -> tuple[str, ...]:
        hit = self._in.get(u)
        if hit is None:
            hit = tuple(v for v in self.links.neighbours(u)
                        if v not in self.query.avoid and self.usable(v, u))
            self._in[u] = hit
        return hit

    def distances_to(self, target: str, bound: int, blocked: str) -> dict[str, int]:
        """The number of usable entity links from each logical entity to ``target``, within ``bound``."""
        dist, frontier = {target: 0}, [target]
        for depth in range(1, bound + 1):
            nxt = []
            for u in frontier:
                for v in self.into(u):
                    if v not in dist and v != blocked:
                        dist[v] = depth
                        nxt.append(v)
            frontier = nxt
        return dist


def realisable(links: EntityLinks, chain: Chain, query: PathQuery) -> bool:
    """Whether one pivot per entity link passes the claim filters and the order, with no two consecutive
    pivots on one definition when restatements are excluded.

    Kept per entity link and order phase: the number of reachable pivots and their count per ending
    definition, so a pivot is reachable when some predecessor ends on another definition.
    """
    previous: dict[int, tuple[int, Counter]] | None = None
    for source, target in zip(chain, chain[1:]):
        reached: dict[int, list[Pivot]] = {}
        for pivot in links.options(source, target):
            if not _pivot_passes(pivot, query):
                continue
            if previous is None:
                phase = _phase(0, pivot.multiplicity, query.converging)
                if phase is not None:
                    reached.setdefault(phase, []).append(pivot)
                continue
            for prior, (count, ends) in previous.items():
                phase = _phase(prior, pivot.multiplicity, query.converging)
                if phase is None:
                    continue
                blocked = (ends.get((pivot.node_id, pivot.source_columns), 0)
                           if query.exclude_restatements and pivot.node_id is not None else 0)
                if count > blocked:
                    reached.setdefault(phase, []).append(pivot)
        if not reached:
            return False
        previous = {
            phase: (len(pivots), Counter((p.node_id, p.target_columns) for p in pivots if p.node_id is not None))
            for phase, pivots in reached.items()
        }
    return True


def enumerate_paths(links: EntityLinks, query: PathQuery, cancelled: Cancelled,
                    cap: int = SCAN_CAP) -> tuple[list[Chain], bool]:
    """Every path from source to target within the bound under the query, and whether the
    enumeration stopped early (scan cap or cancellation). No logical entity repeats, except that
    with ``self_links`` a logical entity may take one self link (two of its definitions on one
    dataset, or a stated self relationship) before the path moves on."""
    graph = _Links(links, query)
    source, target = query.source, query.target
    if source in query.avoid or target in query.avoid:
        return [], False
    if source == target:
        if source in graph.out(source) and realisable(links, (source, source), query):
            return [(source, source)], False
        return [], False
    dist = graph.distances_to(target, query.max_links, source)
    if query.self_links:
        # The pass above never routes through the source; a self link there needs its distance.
        through = [dist[v] + 1 for v in graph.out(source) if v in dist and v != source]
        if through:
            dist[source] = min(through)
    raw: list[Chain] = []
    chain, on = [source], {source}
    stopped = False

    def visit(u: str) -> None:
        nonlocal stopped
        if cancelled():
            stopped = True
            return
        for v in graph.out(u):
            if stopped:
                return
            self_step = v == u
            if self_step:
                if not query.self_links or (len(chain) > 1 and chain[-2] == u):
                    continue
            elif v in on:
                continue
            remaining = dist.get(v)
            if remaining is None or len(chain) + remaining > query.max_links:
                continue
            if v == target:
                raw.append((*chain, v))
                if len(raw) >= cap:
                    stopped = True
                continue
            chain.append(v)
            on.add(v)
            visit(v)
            chain.pop()
            if not self_step:
                on.discard(v)

    visit(source)
    kept = []
    for c in raw:
        if cancelled():
            return kept, True
        if realisable(links, c, query):
            kept.append(c)
    return kept, stopped


def linked_entities(links: EntityLinks, query: PathQuery) -> list[str]:
    """The logical entities one entity link from ``query.source`` under its link kind, avoided
    logical entities and claim filters (read from the source), in ID order."""
    return list(_Links(links, query).out(query.source))


# ---- results --------------------------------------------------------------------------------------

def _unknown_links(links: EntityLinks, pairs) -> int:
    return sum(
        all(p.multiplicity is Multiplicity.UNKNOWN for p in links.options(a, b)) for a, b in pairs
    )


def _pairs(chain: Chain) -> tuple[tuple[str, str], ...]:
    return tuple(zip(chain, chain[1:]))


def _path_found(links: EntityLinks, chain: Chain, shape: str, legs=None) -> Found:
    pairs = _pairs(chain)
    return Found(chain, pairs, shape, (len(pairs), _unknown_links(links, pairs)), chain, legs=legs)


def _legs(links: EntityLinks, query: PathQuery, cancelled: Cancelled, cap: int = SCAN_CAP) -> SearchResult:
    chains, lower = enumerate_paths(links, replace(query, participants=()), cancelled, cap)
    parts = set(query.participants)
    per = {p: [c for c in chains if p in c[1:-1]] for p in query.participants}
    counts = {p: len(v) for p, v in per.items()}
    if any(not v for v in per.values()):
        return SearchResult([], lower, counts)
    found: list[Found] = []
    if query.shape in ("shared_chain", "both"):
        for c in chains:
            if parts <= set(c[1:-1]):
                found.append(_path_found(links, c, "shared_chain", {p: c for p in query.participants}))
    if query.shape in ("independent", "both") and len(parts) > 1:
        independent = {p: [c for c in v if not (parts - {p}) & set(c)] for p, v in per.items()}
        if all(independent.values()):
            top = {p: sorted(v, key=lambda c: (len(c), c))[:LEG_COMBINATION_LEGS] for p, v in independent.items()}
            lower = lower or any(len(v) > LEG_COMBINATION_LEGS for v in independent.values())
            for combo in itertools.product(*(top[p] for p in query.participants)):
                oriented = _orient({tuple(sorted(e)) for c in combo for e in _pairs(c)}, query.source)
                entities = tuple(sorted({e for c in combo for e in c}))
                found.append(Found(entities, oriented, "independent",
                                   (len(oriented), _unknown_links(links, oriented)),
                                   tuple(x for c in combo for x in c),
                                   legs=dict(zip(query.participants, combo))))
    return SearchResult(found, lower, counts)


def _orient(edges, source: str) -> tuple[tuple[str, str], ...]:
    """Entity links of a subgraph read away from ``source`` (breadth first, then by ID)."""
    adjacent: dict[str, set[str]] = {}
    for a, b in edges:
        adjacent.setdefault(a, set()).add(b)
        adjacent.setdefault(b, set()).add(a)
    out, seen, frontier = [], {source}, [source]
    done: set[tuple[str, str]] = set()
    while frontier:
        nxt = []
        for u in sorted(frontier):
            for v in sorted(adjacent.get(u, ())):
                pair = tuple(sorted((u, v)))
                if pair in done:
                    continue
                done.add(pair)
                out.append((u, v))
                if v not in seen:
                    seen.add(v)
                    nxt.append(v)
        frontier = nxt
    return tuple(out)


def _on_path(adjacent: dict[str, list[str]], source: str, target: str, member: str) -> bool:
    """Whether ``member`` lies on a path from source to target inside a small subgraph."""
    stack = [(source, (source,))]
    while stack:
        u, path = stack.pop()
        for v in adjacent.get(u, ()):
            if v in path:
                continue
            if v == target:
                if member in path:
                    return True
                continue
            stack.append((v, (*path, v)))
    return False


def _closed(links: EntityLinks, query: PathQuery, cancelled: Cancelled, cap: int = SCAN_CAP) -> SearchResult:
    """Subgraphs of the two logical entities, the participants and up to ``k_unnamed`` other
    logical entities with every entity link among them; each participant and other logical entity lies
    on a path from source to target inside it."""
    graph = _Links(links, query)
    terms = (query.source, query.target, *query.participants)
    if any(t in query.avoid for t in terms):
        return SearchResult([], False)
    named = set(terms)
    candidates = sorted({
        v for t in terms for v in graph.out(t)
        if v not in named and sum(1 for u in terms if u in graph.out(v)) >= 2
    })
    found: list[Found] = []
    for k in range(query.k_unnamed + 1):
        for extra in itertools.combinations(candidates, k):
            if cancelled() or len(found) >= cap:
                return SearchResult(found, True)
            members = named | set(extra)
            adjacent = {u: [v for v in graph.out(u) if v in members and v != u] for u in members}
            if all(_on_path(adjacent, query.source, query.target, m) for m in (*query.participants, *extra)):
                edges = {tuple(sorted((u, v))) for u in members for v in adjacent[u]}
                oriented = _orient(edges, query.source)
                found.append(Found(tuple(sorted(members)), oriented, "closed",
                                   (k, len(oriented), _unknown_links(links, oriented)),
                                   tuple(sorted(members)), unnamed=extra))
    return SearchResult(found, False)


def search(links: EntityLinks, query: PathQuery, cancelled: Cancelled = lambda: False,
           cap: int = SCAN_CAP) -> SearchResult:
    if not query.participants:
        chains, lower = enumerate_paths(links, query, cancelled, cap)
        return SearchResult([_path_found(links, c, "path") for c in chains], lower)
    if query.closed:
        return _closed(links, query, cancelled, cap)
    return _legs(links, query, cancelled, cap)


def ranked(found: list[Found]) -> list[tuple[int, Found]]:
    """Results by rank key, then logical entity IDs, each with its tie group."""
    out, group, last = [], -1, None
    for item in sorted(found, key=lambda f: (f.key, f.shape, f.order)):
        if item.key != last:
            group += 1
            last = item.key
        out.append((group, item))
    return out


# ---- filter report and relaxations --------------------------------------------------------------------

@dataclass(frozen=True)
class Count:
    total: int
    lower_bound: bool


@dataclass(frozen=True)
class FilterReport:
    unfiltered: Count
    by_links: dict[int, int]
    fewer_links_total: int
    unknown_multiplicity_total: int
    to_one: Count
    from_one: Count
    converging: Count
    always_match: Count
    through: list[tuple[str, int]]
    leg_counts: dict[str, int] | None


FROM_ONE = frozenset({Multiplicity.ONE_TO_MANY, Multiplicity.ONE_TO_ONE})


def filter_report(links: EntityLinks, query: PathQuery, cancelled: Cancelled) -> FilterReport:
    """Paths between the two logical entities with the claim filters removed, and what each claim
    setting would keep; same bound, link kinds, avoided logical entities and self links.

    ``to_one`` keeps paths whose every entity link is ``many:1`` or ``1:1`` (each source instance reaches
    one target instance), ``from_one`` the reverse (``1:many`` or ``1:1``), and ``converging``
    ``many:1`` entity links then ``1:many`` entity links, and ``always_match`` paths whose every
    entity link has ``always`` match existence.
    """
    base = replace(query, participants=(), closed=False, multiplicity=None, match_existence=None,
                   converging=False, k_unnamed=0)
    every, every_lower = enumerate_paths(links, base, cancelled)

    def count(**changes) -> Count:
        found, lower = enumerate_paths(links, replace(base, **changes), cancelled)
        return Count(len(found), lower)

    through = Counter(e for c in every for e in set(c[1:-1]))
    return FilterReport(
        unfiltered=Count(len(every), every_lower),
        by_links=dict(sorted(Counter(len(c) - 1 for c in every).items())),
        fewer_links_total=sum(len(c) - 1 < query.max_links for c in every),
        unknown_multiplicity_total=sum(_unknown_links(links, _pairs(c)) > 0 for c in every),
        to_one=count(multiplicity=TO_ONE),
        from_one=count(multiplicity=FROM_ONE),
        converging=count(multiplicity=CONVERGING, converging=True),
        always_match=count(match_existence=frozenset({MatchExistence.ALWAYS})),
        through=sorted(through.items(), key=lambda item: (-item[1], item[0]))[:THROUGH_LIMIT],
        leg_counts=({p: sum(p in c[1:-1] for c in every) for p in query.participants}
                    if query.participants and not query.closed else None),
    )


def relaxation_candidates(query: PathQuery, max_links_limit: int) -> list[tuple[dict, PathQuery]]:
    """Single filter changes that can widen the result, as request changes and queries."""
    out: list[tuple[dict, PathQuery]] = []
    if query.multiplicity is not None:
        if not query.converging and query.multiplicity <= TO_ONE:
            widened = query.multiplicity | {Multiplicity.ONE_TO_MANY}
            out.append(({"multiplicity": sorted(m.value for m in widened), "order": "converging"},
                        replace(query, multiplicity=widened, converging=True)))
        out.append(({"multiplicity": None, "order": "any"}, replace(query, multiplicity=None, converging=False)))
    elif query.converging:
        out.append(({"order": "any"}, replace(query, converging=False)))
    if query.match_existence is not None:
        out.append(({"match_existence": None}, replace(query, match_existence=None)))
    for avoided in sorted(query.avoid):
        rest = query.avoid - {avoided}
        out.append(({"avoid_identity_ids": sorted(rest)}, replace(query, avoid=rest)))
    if query.stated_only:
        out.append(({"link_kinds": "all"}, replace(query, stated_only=False)))
    if query.participants and query.closed:
        if query.k_unnamed < 2:
            out.append(({"k_unnamed": query.k_unnamed + 1}, replace(query, k_unnamed=query.k_unnamed + 1)))
        out.append(({"participation": "legs", "k_unnamed": 0}, replace(query, closed=False, k_unnamed=0)))
    elif query.participants:
        cleared = {"participation": "closed", "multiplicity": None, "order": "any", "match_existence": None}
        closed = replace(query, closed=True, multiplicity=None, converging=False, match_existence=None)
        out.append(({**cleared, "k_unnamed": 0}, closed))
        out.append(({**cleared, "k_unnamed": 1}, replace(closed, k_unnamed=1)))
    if not query.closed:
        if not query.self_links:
            out.append(({"self_links": True}, replace(query, self_links=True)))
        if query.exclude_restatements:
            out.append(({"exclude_restatements": False}, replace(query, exclude_restatements=False)))
        if query.max_links < max_links_limit:
            out.append(({"max_links": query.max_links + 1}, replace(query, max_links=query.max_links + 1)))
    return out
