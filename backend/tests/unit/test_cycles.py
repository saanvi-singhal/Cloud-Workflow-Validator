"""Tests for Tarjan SCC, DFS cycle paths and cycle diagnostics."""

import random

import pytest

from app.analysis.cycles import (
    cycle_findings,
    detect_cycles,
    find_cycle_path,
    strongly_connected_components,
)
from app.compiler.graph import DependencyGraph
from app.models import DiagnosticCode, Edge, EdgeType, Severity
from tests.graph_builders import build_graph, build_ir, loc

pytestmark = [pytest.mark.unit, pytest.mark.compiler]


def assert_is_cycle(graph: DependencyGraph, path: list[str]) -> None:
    """A path is a valid closed cycle if it returns to its start along real edges."""
    assert len(path) >= 2 and path[0] == path[-1]
    for source, target in zip(path, path[1:], strict=False):
        assert target in graph.successors(source)


# --- Tarjan -----------------------------------------------------------------


def test_scc_of_acyclic_graph_is_all_singletons():
    g = build_graph([("a", "b"), ("b", "c"), ("a", "c")])
    assert strongly_connected_components(g) == [["a"], ["b"], ["c"]]


def test_scc_groups_simple_cycle():
    g = build_graph([("a", "b"), ("b", "c"), ("c", "a"), ("c", "d")])
    assert strongly_connected_components(g) == [["a", "b", "c"], ["d"]]


def test_scc_finds_multiple_separate_cyclic_regions():
    g = build_graph([("a", "b"), ("b", "a"), ("b", "x"), ("x", "y"), ("y", "x")])
    assert strongly_connected_components(g) == [["a", "b"], ["x", "y"]]


def test_scc_merges_overlapping_cycles():
    # a<->b and b<->c share b: one region, so one diagnostic later.
    g = build_graph([("a", "b"), ("b", "a"), ("b", "c"), ("c", "b")])
    assert strongly_connected_components(g) == [["a", "b", "c"]]


def test_scc_of_empty_graph():
    assert strongly_connected_components(build_graph()) == []


# --- DFS path reconstruction --------------------------------------------------


def test_self_loop_path():
    g = build_graph([("a", "a")])
    assert find_cycle_path(g, ["a"]) == ["a", "a"]


def test_simple_cycle_path_is_readable_and_deterministic():
    g = build_graph([("c", "a"), ("a", "b"), ("b", "c")])
    assert find_cycle_path(g, ["a", "b", "c"]) == ["a", "b", "c", "a"]


def test_path_in_complex_component_is_a_real_cycle():
    edges = [("a", "b"), ("b", "c"), ("c", "b"), ("c", "d"), ("d", "a")]
    g = build_graph(edges)
    (component,) = strongly_connected_components(g)
    path = find_cycle_path(g, component)
    assert_is_cycle(g, path)


def test_find_cycle_path_returns_none_when_acyclic():
    g = build_graph([("a", "b"), ("b", "c"), ("a", "c")])
    assert find_cycle_path(g) is None
    assert find_cycle_path(g, ["a"]) is None
    assert find_cycle_path(build_graph()) is None


def test_dfs_backtracks_past_finished_nodes_to_find_a_later_cycle():
    # a -> b -> c is a dead end (b, c become BLACK); the cycle d <-> e is only
    # found after backtracking to a and exploring its next successor.
    g = build_graph([("a", "b"), ("b", "c"), ("a", "d"), ("d", "e"), ("e", "d")])
    assert find_cycle_path(g) == ["d", "e", "d"]


def test_dfs_reaching_black_node_is_not_a_cycle():
    # Diamond: c is reached twice (second time it is BLACK), still acyclic.
    g = build_graph([("a", "b"), ("a", "c"), ("b", "c")])
    assert find_cycle_path(g) is None


def test_dfs_ignores_edges_leaving_the_node_set():
    g = build_graph([("a", "b"), ("b", "a"), ("b", "x")])
    assert find_cycle_path(g, ["a", "b"]) == ["a", "b", "a"]
    assert find_cycle_path(g, ["b", "x"]) is None


# --- detect_cycles + findings -------------------------------------------------


def test_acyclic_graph_has_no_cycles():
    report = detect_cycles(build_graph([("a", "b"), ("b", "c")], nodes=["z"]))
    assert not report.has_cycles
    assert report.components == [] and report.paths == []


def test_self_loop_is_a_cycle():
    ir = build_ir([("a", "a"), ("a", "b")])
    g = DependencyGraph.from_ir(ir)
    report = detect_cycles(g)
    assert report.components == [["a"]]
    findings = cycle_findings(report, ir, g)
    assert [f.code for f in findings] == [DiagnosticCode.DEPENDENCY_CYCLE]
    assert "depends on itself" in findings[0].diagnostic.message


def test_one_diagnostic_per_cyclic_region():
    edges = [("a", "b"), ("b", "a"), ("b", "c"), ("c", "b"), ("x", "y"), ("y", "x")]
    ir = build_ir(edges)
    g = DependencyGraph.from_ir(ir)
    findings = cycle_findings(detect_cycles(g), ir, g)
    assert len(findings) == 2
    assert all(f.severity is Severity.error for f in findings)
    assert findings[0].node_ids == ("a", "b", "c")
    assert findings[1].node_ids == ("x", "y")
    # Overlapping region: the path covers part of it; the rest is named.
    assert "also contains" in findings[0].diagnostic.message


def test_cycle_location_is_closing_edge_declaration():
    ir = build_ir(nodes=["a", "b"])
    ir.edges = [
        Edge(source="a", target="b", type=EdgeType.workflow_dependency),
        Edge(
            source="b",
            target="a",
            type=EdgeType.workflow_dependency,
            source_location=loc(42),
        ),
    ]
    g = DependencyGraph.from_ir(ir)
    (finding,) = cycle_findings(detect_cycles(g), ir, g)
    assert finding.details["path"] == ["a", "b", "a"]
    assert finding.diagnostic.source_location.start_line == 42
    assert set(finding.edge_keys) == {
        ("a", "b", "workflow_dependency"),
        ("b", "a", "workflow_dependency"),
    }


def test_cycle_location_falls_back_to_dependent_node():
    ir = build_ir([("a", "b"), ("b", "a")])  # edges have no location
    g = DependencyGraph.from_ir(ir)
    (finding,) = cycle_findings(detect_cycles(g), ir, g)
    # Closing edge b -> a; node "a" (line 1 in the builder) is the dependent.
    assert finding.diagnostic.source_location.start_line == 1


def test_cycle_detection_is_deterministic_under_input_shuffling():
    edges = [("a", "b"), ("b", "c"), ("c", "a"), ("c", "d"), ("d", "e"), ("e", "d")]
    expected = detect_cycles(build_graph(edges))
    rng = random.Random(1234)
    for _ in range(20):
        shuffled = edges[:]
        rng.shuffle(shuffled)
        assert detect_cycles(build_graph(shuffled)) == expected


def test_long_chain_does_not_hit_recursion_limit():
    n = 5000
    edges = [(f"n{i:05d}", f"n{i + 1:05d}") for i in range(n)]
    edges.append((f"n{n:05d}", "n00000"))  # close one giant cycle
    report = detect_cycles(build_graph(edges))
    assert len(report.components) == 1
    assert len(report.components[0]) == n + 1
    assert len(report.paths[0]) == n + 2
