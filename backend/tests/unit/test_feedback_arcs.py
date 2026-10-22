"""Tests for minimum edge removal (app/analysis/feedback_arcs.py)."""

import random
from itertools import combinations

from app.analysis.feedback_arcs import EXACT_LIMIT, _acyclic, minimum_feedback_arcs


def e(source, target, kind="t"):
    return (source, target, kind)


def brute_force_cost(edges, cost):
    """The cheapest acyclic removal over *all* subsets (any size)."""
    nodes = {n for x in edges for n in x[:2]}
    return min(
        sum(cost.get(x, 1) for x in subset)
        for size in range(len(edges) + 1)
        for subset in combinations(edges, size)
        if _acyclic(nodes, [x for x in edges if x not in subset])
    )


def test_acyclic_input_needs_no_removal():
    found = minimum_feedback_arcs([e("a", "b"), e("b", "c")])
    assert found.edges == () and found.cost == 0 and found.optimal


def test_two_cycle_removes_one_edge_deterministically():
    found = minimum_feedback_arcs([e("b", "a"), e("a", "b")])
    assert found.edges == (e("a", "b"),)  # ties break on the smallest key


def test_shared_edge_breaks_two_cycles_at_once():
    # a->b->c->a and b->c->d->b share b->c: removing it is the unique optimum.
    edges = [e("a", "b"), e("b", "c"), e("c", "a"), e("c", "d"), e("d", "b")]
    assert minimum_feedback_arcs(edges).edges == (e("b", "c"),)


def test_costs_prefer_cheap_edges_even_if_more_are_needed():
    # One reference (cost 3) or two explicit edges (cost 1 each): take the two.
    edges = [
        e("a", "b", "ref"),
        e("b", "a", "dep"),
        e("b", "c", "ref"),
        e("c", "a", "dep"),
    ]
    cost = {x: 3 if x[2] == "ref" else 1 for x in edges}
    found = minimum_feedback_arcs(edges, cost)
    assert found.cost == 2
    assert found.edges == (e("b", "a", "dep"), e("c", "a", "dep"))


def test_self_loops_are_always_removed():
    found = minimum_feedback_arcs([e("a", "a"), e("a", "b")])
    assert found.edges == (e("a", "a"),)


def test_exact_search_is_optimal_on_random_graphs():
    rng = random.Random(7)
    for _ in range(60):
        nodes = [f"n{i}" for i in range(rng.randint(2, 6))]
        edges = sorted(
            {e(a, b) for a in nodes for b in nodes if a != b and rng.random() < 0.4}
        )[:10]
        cost = {x: rng.choice([1, 3]) for x in edges}
        found = minimum_feedback_arcs(edges, cost)
        remaining = [x for x in edges if x not in found.edges]
        assert _acyclic(nodes, remaining)
        assert found.optimal
        assert found.cost == brute_force_cost(edges, cost)


def test_large_components_use_the_heuristic_and_stay_acyclic():
    # A complete digraph on 6 nodes has 30 edges, above the exact limit.
    nodes = [f"n{i}" for i in range(6)]
    edges = [e(a, b) for a in nodes for b in nodes if a != b]
    assert len(edges) > EXACT_LIMIT
    found = minimum_feedback_arcs(edges)
    assert not found.optimal
    assert _acyclic(nodes, [x for x in edges if x not in found.edges])
    # Any acyclic subgraph of K6 keeps at most 15 edges, so 15 must go.
    assert len(found.edges) == 15
