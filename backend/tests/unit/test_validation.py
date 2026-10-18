"""Tests for graph integrity validation."""

import pytest

from app.analysis.validation import validate_graph
from app.models import (
    DiagnosticCode,
    Edge,
    EdgeType,
    Node,
    NodeType,
    Severity,
    SourceFormat,
)
from tests.graph_builders import build_ir, loc

pytestmark = [pytest.mark.unit, pytest.mark.compiler]


def test_valid_graph_passes_unchanged():
    ir = build_ir([("a", "b"), ("b", "c")])
    clean, findings = validate_graph(ir)
    assert findings == []
    assert clean == ir


def test_duplicate_node_id_reported_and_first_kept():
    ir = build_ir(nodes=["a"])
    ir.nodes.append(
        Node(id="a", label="second a", type=NodeType.task, source_location=loc(7))
    )
    clean, findings = validate_graph(ir)
    assert [f.code for f in findings] == [DiagnosticCode.DUPLICATE_NODE_ID]
    assert findings[0].severity is Severity.error
    assert findings[0].diagnostic.source_location.start_line == 7
    assert len(clean.nodes) == 1 and clean.nodes[0].label == "a"


def test_dangling_edge_is_invalid_graph_and_dropped():
    ir = build_ir([("a", "b")])
    ir.edges.append(Edge(source="ghost", target="a", type=EdgeType.workflow_dependency))
    clean, findings = validate_graph(ir)
    assert [f.code for f in findings] == [DiagnosticCode.INVALID_GRAPH]
    assert "ghost" in findings[0].diagnostic.message
    assert [(e.source, e.target) for e in clean.edges] == [("a", "b")]


def test_edge_type_not_allowed_for_format_is_dropped():
    ir = build_ir([("a", "b")], fmt=SourceFormat.terraform)
    ir.edges.append(Edge(source="a", target="b", type=EdgeType.docker_stage_base))
    clean, findings = validate_graph(ir)
    assert [f.code for f in findings] == [DiagnosticCode.INVALID_GRAPH]
    assert [e.type for e in clean.edges] == [EdgeType.terraform_reference]


@pytest.mark.parametrize(
    ("fmt", "edge_type"),
    [
        (SourceFormat.yaml, EdgeType.workflow_dependency),
        (SourceFormat.dockerfile, EdgeType.docker_stage_base),
        (SourceFormat.dockerfile, EdgeType.docker_instruction_order),
        (SourceFormat.terraform, EdgeType.terraform_reference),
        (SourceFormat.terraform, EdgeType.terraform_explicit_dependency),
    ],
)
def test_each_format_accepts_its_edge_types(fmt, edge_type):
    ir = build_ir(nodes=["a", "b"], fmt=fmt)
    ir.edges.append(Edge(source="a", target="b", type=edge_type))
    _, findings = validate_graph(ir)
    assert findings == []


def test_self_loop_is_not_an_integrity_error():
    _, findings = validate_graph(build_ir([("a", "a")]))
    assert findings == []
