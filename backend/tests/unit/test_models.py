"""Contract tests for the public Pydantic models."""

import pytest
from pydantic import ValidationError

from app.models import (
    AnalysisResult,
    Diagnostic,
    DiagnosticCode,
    Edge,
    EdgeType,
    FixKind,
    Node,
    NodeType,
    Recommendation,
    Severity,
    SourceFormat,
    SourceLocation,
)

pytestmark = [pytest.mark.unit, pytest.mark.compiler]


def test_node_serializes_with_exact_contract_fields():
    node = Node(id="tf:resource:a.b", label="a.b", type=NodeType.resource)
    assert node.model_dump(mode="json") == {
        "id": "tf:resource:a.b",
        "label": "a.b",
        "type": "resource",
        "source_location": None,
        "metadata": {},
    }


def test_edge_serializes_with_exact_contract_fields():
    edge = Edge(source="a", target="b", type=EdgeType.workflow_dependency)
    assert set(edge.model_dump(mode="json")) == {
        "source",
        "target",
        "type",
        "label",
        "source_location",
        "metadata",
    }
    assert edge.key == ("a", "b", "workflow_dependency")


def test_source_location_is_one_based_and_nullable():
    assert SourceLocation().model_dump() == {
        "file": None,
        "start_line": None,
        "start_column": None,
        "end_line": None,
        "end_column": None,
    }
    with pytest.raises(ValidationError):
        SourceLocation(start_line=0)
    with pytest.raises(ValidationError):
        SourceLocation(start_column=0)


def test_unknown_fields_and_types_are_rejected():
    with pytest.raises(ValidationError):
        Node(id="x", label="x", type="job")  # old docs' "kind": not a NodeType
    with pytest.raises(ValidationError):
        Edge(source="a", target="b", type="explicit_needs")
    with pytest.raises(ValidationError):
        Node(id="x", label="x", type=NodeType.task, kind="job")


def test_diagnostic_requires_code_severity_message():
    d = Diagnostic(
        code=DiagnosticCode.DEPENDENCY_CYCLE, severity=Severity.error, message="m"
    )
    assert d.model_dump(mode="json") == {
        "code": "DEPENDENCY_CYCLE",
        "severity": "error",
        "message": "m",
        "source_location": None,
    }
    with pytest.raises(ValidationError):
        Diagnostic(code="ERR_CYCLE_DETECTED", severity="error", message="m")
    with pytest.raises(ValidationError):
        Diagnostic(code=DiagnosticCode.DEPENDENCY_CYCLE, severity="ERROR", message="m")


def test_analysis_result_matches_spec_response_shape():
    result = AnalysisResult(valid=True, format=SourceFormat.yaml)
    assert result.model_dump(mode="json") == {
        "valid": True,
        "format": "yaml",
        "diagnostics": [],
        "graph": {"nodes": [], "edges": []},
        "execution_order": None,
        "recommendations": [],
    }


def test_recommendation_fields():
    rec = Recommendation(
        id="R:0",
        rule_id="R",
        title="t",
        explanation="e",
        diagnostic_code=DiagnosticCode.DEPENDENCY_CYCLE,
        diagnostic_index=0,
        fix_kind=FixKind.judgment,
    )
    dumped = rec.model_dump(mode="json")
    assert dumped["fix_kind"] == "judgment"
    assert dumped["proposed_change"] is None
    assert dumped["related_node_ids"] == []
