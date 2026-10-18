"""Tests for components, ancestors/descendants and format-aware warnings."""

import pytest

from app.analysis.reachability import (
    ancestors,
    component_findings,
    descendants,
    reachability_findings,
    weakly_connected_components,
)
from app.compiler.graph import DependencyGraph
from app.compiler.ir import IRGraph
from app.compiler.policy import FormatPolicy, docker_final_stage, policy_for
from app.models import DiagnosticCode, Node, NodeType, Severity, SourceFormat
from tests.graph_builders import build_graph, build_ir

pytestmark = [pytest.mark.unit, pytest.mark.compiler]


def test_weak_components_sorted_largest_first():
    g = build_graph([("x", "y"), ("a", "b"), ("b", "c")], nodes=["solo"])
    assert weakly_connected_components(g) == [["a", "b", "c"], ["x", "y"], ["solo"]]


def test_weak_components_ignore_direction():
    g = build_graph([("a", "c"), ("b", "c")])
    assert weakly_connected_components(g) == [["a", "b", "c"]]


def test_ancestors_and_descendants_follow_edge_direction():
    g = build_graph([("a", "b"), ("b", "c"), ("x", "c"), ("c", "d")])
    assert ancestors(g, ["c"]) == {"a", "b", "x"}
    assert descendants(g, ["b"]) == {"c", "d"}
    assert ancestors(g, ["a"]) == set()


def test_ancestors_include_target_only_through_a_cycle():
    g = build_graph([("a", "b"), ("b", "a")])
    assert ancestors(g, ["a"]) == {"a", "b"}


def _findings_for(edges, nodes=(), fmt=SourceFormat.yaml, policy=None):
    ir = build_ir(edges, nodes, fmt=fmt)
    g = DependencyGraph.from_ir(ir)
    return component_findings(g, ir, policy or policy_for(fmt))


def test_connected_graph_has_no_component_warning():
    assert _findings_for([("a", "b"), ("b", "c")]) == []


def test_isolated_nodes_not_reported_for_yaml():
    # Independent GitHub Actions jobs are normal (they run in parallel).
    assert _findings_for([("a", "b")], nodes=["lint", "docs"]) == []


def test_separate_nontrivial_chain_reported_as_info():
    findings = _findings_for([("a", "b"), ("b", "c"), ("x", "y")])
    assert [f.code for f in findings] == [DiagnosticCode.DISCONNECTED_COMPONENT]
    assert findings[0].severity is Severity.info
    assert findings[0].node_ids == ("x", "y")
    assert "dependency chain" in findings[0].diagnostic.message


def test_isolated_nodes_reported_when_policy_asks():
    policy = FormatPolicy(
        execution_order_meaningful=True,
        disconnected_severity=Severity.warning,
        report_isolated_nodes=True,
    )
    findings = _findings_for([("a", "b")], nodes=["solo"], policy=policy)
    assert [f.node_ids for f in findings] == [("solo",)]
    assert findings[0].severity is Severity.warning


def test_docker_policy_disables_component_rule():
    assert _findings_for([("a", "b"), ("x", "y")], fmt=SourceFormat.dockerfile) == []


def _docker_ir(stage_edges, stages, final=None):
    ir = build_ir(stage_edges, stages, fmt=SourceFormat.dockerfile)
    nodes = []
    for index, node in enumerate(ir.nodes):
        meta = {"stage_index": index}
        if final is not None:
            meta["is_final_stage"] = node.id == final
        nodes.append(node.model_copy(update={"metadata": meta}))
    return IRGraph(format=ir.format, nodes=nodes, edges=ir.edges)


def test_docker_unused_stage_is_unreachable():
    # base -> build -> zfinal ; "test" builds on base but final doesn't need it.
    ir = _docker_ir([("base", "build"), ("build", "zfinal"), ("base", "test")], [])
    g = DependencyGraph.from_ir(ir)
    findings = reachability_findings(g, ir, policy_for(SourceFormat.dockerfile))
    assert [f.code for f in findings] == [DiagnosticCode.UNREACHABLE_NODE]
    assert findings[0].node_ids == ("test",)
    assert findings[0].severity is Severity.warning


def test_docker_final_stage_prefers_explicit_flag():
    ir = _docker_ir([], ["a", "b", "c"], final="b")
    assert docker_final_stage(ir) == ["b"]
    assert docker_final_stage(_docker_ir([], ["a", "b", "c"])) == ["c"]


def test_no_root_means_no_reachability_findings():
    # Docker nodes without stage metadata: no root is invented.
    ir = build_ir([("a", "b")], ["c"], fmt=SourceFormat.dockerfile)
    g = DependencyGraph.from_ir(ir)
    assert reachability_findings(g, ir, policy_for(SourceFormat.dockerfile)) == []
    # Formats without a defined root never run reachability.
    yaml_ir = build_ir([("a", "b")], ["c"])
    yaml_g = DependencyGraph.from_ir(yaml_ir)
    assert reachability_findings(yaml_g, yaml_ir, policy_for(SourceFormat.yaml)) == []


def test_policy_table():
    assert policy_for(SourceFormat.yaml).execution_order_meaningful
    assert policy_for(SourceFormat.terraform).execution_order_meaningful
    assert not policy_for(SourceFormat.dockerfile).execution_order_meaningful


def test_root_selector_ignores_non_bool_flag():
    node = Node(
        id="s",
        label="s",
        type=NodeType.stage,
        metadata={"is_final_stage": "yes"},
    )
    ir = IRGraph(format=SourceFormat.dockerfile, nodes=[node])
    assert docker_final_stage(ir) == []
