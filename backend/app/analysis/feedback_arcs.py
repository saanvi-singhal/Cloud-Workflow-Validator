"""Minimum edge removal to break a dependency cycle (minimum feedback arc set).

Given the edges of one cyclic strongly connected component, find a set of
edges whose removal leaves the component acyclic, with the smallest total
cost. The cost says how disruptive a removal is: dropping an explicit
dependency (``depends_on``, ``needs``) only removes an ordering constraint,
while dropping an attribute reference changes a value, so references cost
more and are chosen only when no cheaper removal exists.

Minimum feedback arc set is NP-hard, but the cyclic components of real
configurations are small:

* up to ``EXACT_LIMIT`` edges, every subset is tried in order of increasing
  cost, then size, then edge keys, so the answer is optimal and
  deterministic;
* above it, the Eades-Lin-Smyth heuristic orders the nodes (repeatedly
  peeling sinks and sources, otherwise taking the node with the largest
  out-minus-in weight) and removes every edge that points backwards in that
  order. The result is always acyclic but not necessarily minimal, and
  ``optimal`` says so.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import combinations

from app.compiler.findings import EdgeKey

EXACT_LIMIT = 16


@dataclass(frozen=True)
class FeedbackArcs:
    edges: tuple[EdgeKey, ...]  # sorted
    cost: int
    optimal: bool


def _acyclic(nodes: Iterable[str], edges: Iterable[EdgeKey]) -> bool:
    """Kahn's algorithm: every node is emitted iff there is no cycle."""
    indegree = {n: 0 for n in nodes}
    successors: dict[str, list[str]] = {n: [] for n in indegree}
    for source, target, _ in edges:
        successors[source].append(target)
        indegree[target] += 1
    ready = [n for n, d in indegree.items() if d == 0]
    emitted = 0
    while ready:
        node = ready.pop()
        emitted += 1
        for nxt in successors[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
    return emitted == len(indegree)


def _exact(
    nodes: set[str], edges: list[EdgeKey], cost: Mapping[EdgeKey, int]
) -> FeedbackArcs:
    best: tuple[int, int, tuple[EdgeKey, ...]] | None = None
    for size in range(1, len(edges) + 1):
        for subset in combinations(edges, size):
            total = sum(cost[e] for e in subset)
            key = (total, size, subset)
            if best is not None and key >= best:
                continue
            removed = set(subset)
            if _acyclic(nodes, (e for e in edges if e not in removed)):
                best = key
        # A larger subset can still be cheaper when costs differ; stop once
        # even the cheapest subset of the next size cannot beat the best.
        if best is not None and (size + 1) * min(cost.values()) >= best[0]:
            break
    assert best is not None  # removing every edge is always acyclic
    return FeedbackArcs(edges=best[2], cost=best[0], optimal=True)


def _eades(
    nodes: set[str], edges: list[EdgeKey], cost: Mapping[EdgeKey, int]
) -> FeedbackArcs:
    remaining = set(nodes)
    head: list[str] = []
    tail: list[str] = []

    def weight(node: str, outgoing: bool) -> int:
        return sum(
            cost[e]
            for e in edges
            if (e[0] if outgoing else e[1]) == node
            and e[0] in remaining
            and e[1] in remaining
        )

    while remaining:
        changed = True
        while changed:
            changed = False
            for node in sorted(remaining):
                if weight(node, outgoing=True) == 0:  # sink
                    tail.insert(0, node)
                    remaining.discard(node)
                    changed = True
                elif weight(node, outgoing=False) == 0:  # source
                    head.append(node)
                    remaining.discard(node)
                    changed = True
        if remaining:
            node = max(
                sorted(remaining),
                key=lambda n: weight(n, outgoing=True) - weight(n, outgoing=False),
            )
            head.append(node)
            remaining.discard(node)

    position = {n: i for i, n in enumerate(head + tail)}
    backward = tuple(sorted(e for e in edges if position[e[0]] >= position[e[1]]))
    return FeedbackArcs(
        edges=backward, cost=sum(cost[e] for e in backward), optimal=False
    )


def minimum_feedback_arcs(
    edges: Iterable[EdgeKey], cost: Mapping[EdgeKey, int] | None = None
) -> FeedbackArcs:
    """Cheapest set of ``edges`` whose removal leaves them acyclic.

    ``cost`` defaults to 1 per edge. Self-loops are always in the result.
    """
    unique = sorted(set(edges))
    costs = {e: (cost or {}).get(e, 1) for e in unique}
    loops = [e for e in unique if e[0] == e[1]]
    rest = [e for e in unique if e[0] != e[1]]
    nodes = {n for e in rest for n in e[:2]}
    if _acyclic(nodes, rest):
        found = FeedbackArcs(edges=(), cost=0, optimal=True)
    elif len(rest) <= EXACT_LIMIT:
        found = _exact(nodes, rest, costs)
    else:
        found = _eades(nodes, rest, costs)
    chosen = tuple(sorted([*loops, *found.edges]))
    return FeedbackArcs(
        edges=chosen,
        cost=found.cost + sum(costs[e] for e in loops),
        optimal=found.optimal,
    )
