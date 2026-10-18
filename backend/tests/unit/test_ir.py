"""Tests for the IR container, stable IDs and deterministic sorting."""

import pytest

from app.compiler.graph import DependencyGraph
from app.compiler.ir import (
    IRGraph,
    make_node_id,
    sort_diagnostics,
    unique_id,
)
from app.models import (
    Diagnostic,
    DiagnosticCode,
    Edge,
    EdgeType,
    Severity,
    SourceFormat,
    SourceLocation,
)
from tests.graph_builders import build_graph, build_ir

pytestmark = [pytest.mark.unit, pytest.mark.compiler]


def test_make_node_id_is_readable_and_deterministic():
    assert (
        make_node_id("tf", "resource", "aws_vpc", "main") == "tf:resource:aws_vpc.main"
    )
    assert make_node_id("gha", "job", "build") == make_node_id("gha", "job", "build")


@pytest.mark.parametrize(
    "args", [("", "k", "x"), ("p", "", "x"), ("p", "k"), ("p", "k", "")]
)
def test_make_node_id_rejects_empty_parts(args):
    with pytest.raises(ValueError):
        make_node_id(*args)


def test_unique_id_appends_deterministic_suffix():
    taken: set[str] = set()
    assert unique_id("a", taken) == "a"
    assert unique_id("a", taken) == "a#2"
    assert unique_id("a", taken) == "a#3"
    assert taken == {"a", "a#2", "a#3"}


def test_canonical_sorts_nodes_and_edges():
    ir = build_ir([("c", "a"), ("a", "b"), ("a", "a")])
    canonical = ir.canonical()
    assert [n.id for n in canonical.nodes] == ["a", "b", "c"]
    assert [(e.source, e.target) for e in canonical.edges] == [
        ("a", "a"),
        ("a", "b"),
        ("c", "a"),
    ]


def test_to_payload_is_canonical():
    payload = build_ir([("b", "a")]).to_payload()
    assert [n.id for n in payload.nodes] == ["a", "b"]


def test_sort_diagnostics_location_first_then_severity_and_code():
    def diag(code, sev, line=None, file="f"):
        location = None if line is None else SourceLocation(file=file, start_line=line)
        return Diagnostic(
            code=code, severity=sev, message="m", source_location=location
        )

    no_loc = diag(DiagnosticCode.DISCONNECTED_COMPONENT, Severity.info)
    line9 = diag(DiagnosticCode.DEPENDENCY_CYCLE, Severity.error, 9)
    line2_warn = diag(DiagnosticCode.UNSUPPORTED_CONSTRUCT, Severity.warning, 2)
    line2_err = diag(DiagnosticCode.UNRESOLVED_DEPENDENCY, Severity.error, 2)
    ordered = sort_diagnostics([no_loc, line9, line2_warn, line2_err])
    assert ordered == [line2_err, line2_warn, line9, no_loc]


def test_dependency_graph_adjacency_is_sorted_and_deduplicated():
    ir = IRGraph(
        format=SourceFormat.terraform,
        nodes=build_ir(nodes=["a", "b", "c"], fmt=SourceFormat.terraform).nodes,
        edges=[
            Edge(source="a", target="c", type=EdgeType.terraform_reference),
            Edge(source="a", target="b", type=EdgeType.terraform_reference),
            Edge(source="a", target="b", type=EdgeType.terraform_explicit_dependency),
        ],
    )
    g = DependencyGraph.from_ir(ir)
    assert g.nodes == ("a", "b", "c")
    assert g.successors("a") == ("b", "c")
    assert g.predecessors("b") == ("a",)
    assert len(g.edges_between("a", "b")) == 2
    assert g.edges_between("b", "a") == []
    assert len(g) == 3


def test_dependency_graph_detects_self_loop():
    g = build_graph([("a", "a"), ("a", "b")])
    assert g.has_self_loop("a")
    assert not g.has_self_loop("b")


def test_dependency_graph_rejects_unvalidated_edges():
    ir = build_ir(nodes=["a"])
    ir.edges.append(Edge(source="a", target="ghost", type=EdgeType.workflow_dependency))
    with pytest.raises(ValueError):
        DependencyGraph.from_ir(ir)
