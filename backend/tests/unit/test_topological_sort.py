"""Tests for deterministic Kahn topological sorting."""

import random

import pytest

from app.analysis.topological_sort import topological_order
from tests.graph_builders import build_graph

pytestmark = [pytest.mark.unit, pytest.mark.compiler]


def test_linear_chain():
    assert topological_order(build_graph([("a", "b"), ("b", "c")])) == ["a", "b", "c"]


def test_ties_broken_lexicographically():
    # Diamond: after "root", both "left" and "right" are ready -> "left" first.
    g = build_graph(
        [("root", "right"), ("root", "left"), ("left", "sink"), ("right", "sink")]
    )
    assert topological_order(g) == ["root", "left", "right", "sink"]


def test_order_respects_every_edge():
    edges = [("b", "a"), ("c", "a"), ("d", "b"), ("d", "c"), ("e", "d")]
    order = topological_order(build_graph(edges))
    position = {n: i for i, n in enumerate(order)}
    assert all(position[s] < position[t] for s, t in edges)


def test_disconnected_nodes_included():
    assert topological_order(build_graph([("b", "c")], nodes=["a", "z"])) == [
        "a",
        "b",
        "c",
        "z",
    ]


@pytest.mark.parametrize(
    "edges",
    [
        [("a", "a")],
        [("a", "b"), ("b", "a")],
        [("a", "b"), ("b", "c"), ("c", "a"), ("x", "y")],
    ],
)
def test_cyclic_graph_returns_none_not_partial_order(edges):
    assert topological_order(build_graph(edges)) is None


def test_empty_graph():
    assert topological_order(build_graph()) == []


def test_deterministic_across_shuffled_input():
    edges = [(f"n{i}", f"n{j}") for i in range(10) for j in range(i + 1, 10, 3)]
    expected = topological_order(build_graph(edges))
    rng = random.Random(7)
    for _ in range(20):
        shuffled = edges[:]
        rng.shuffle(shuffled)
        assert topological_order(build_graph(shuffled)) == expected


def test_large_graph():
    n = 5000
    edges = [(f"n{i:05d}", f"n{i + 1:05d}") for i in range(n)]
    order = topological_order(build_graph(edges))
    assert order is not None and len(order) == n + 1
