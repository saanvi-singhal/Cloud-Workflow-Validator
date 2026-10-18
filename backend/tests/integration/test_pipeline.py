"""End-to-end pipeline tests using hand-built fake adapters.

These stand in for the YAML/Dockerfile parsers (owned by another team member)
and exercise IR -> validation -> analysis -> result without them.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field

import pytest

from app.compiler.adapters import (
    AdapterNotAvailableError,
    ParseResult,
    get_adapter,
    register_adapter,
    unregister_adapter,
)
from app.compiler.findings import Finding, make_finding
from app.compiler.ir import IRGraph
from app.compiler.pipeline import analyze_ir, compile_source
from app.models import (
    DiagnosticCode,
    Edge,
    EdgeType,
    Severity,
    SourceFormat,
)
from tests.graph_builders import build_ir, loc

pytestmark = [pytest.mark.integration, pytest.mark.compiler]


@dataclass
class FakeAdapter:
    """Returns a fixed ParseResult regardless of the source text."""

    result: ParseResult
    format: SourceFormat = SourceFormat.yaml
    calls: list[tuple[str, str | None]] = field(default_factory=list)

    def parse(self, source: str, filename: str | None) -> ParseResult:
        self.calls.append((source, filename))
        return self.result


def run(ir: IRGraph, findings: list[Finding] | None = None, complete: bool = True):
    return analyze_ir(ParseResult(ir, findings or [], complete), ir.format)


def test_valid_acyclic_workflow():
    result = run(build_ir([("build", "test"), ("test", "deploy"), ("build", "lint")]))
    assert result.valid is True
    assert result.diagnostics == []
    assert result.execution_order == ["build", "lint", "test", "deploy"]
    assert [n.id for n in result.graph.nodes] == ["build", "deploy", "lint", "test"]


def test_cycle_invalidates_and_nulls_execution_order():
    result = run(build_ir([("a", "b"), ("b", "c"), ("c", "a"), ("c", "d")]))
    assert result.valid is False
    assert result.execution_order is None
    assert [d.code for d in result.diagnostics] == [DiagnosticCode.DEPENDENCY_CYCLE]


def test_warnings_alone_keep_result_valid_and_ordered():
    warning = make_finding(
        DiagnosticCode.UNSUPPORTED_CONSTRUCT, Severity.warning, "w", loc(3)
    )
    result = run(build_ir([("a", "b")]), [warning])
    assert result.valid is True
    assert result.execution_order == ["a", "b"]


def test_incomplete_dependency_analysis_nulls_order_but_stays_valid():
    result = run(build_ir([("a", "b")]), complete=False)
    assert result.valid is True
    assert result.execution_order is None


def test_parser_error_nulls_order():
    error = make_finding(
        DiagnosticCode.UNRESOLVED_DEPENDENCY, Severity.error, "unknown job", loc(2)
    )
    result = run(build_ir([("a", "b")]), [error])
    assert result.valid is False
    assert result.execution_order is None


def test_syntax_error_without_ir():
    error = make_finding(
        DiagnosticCode.YAML_SYNTAX_ERROR, Severity.error, "bad yaml", loc(1)
    )
    result = analyze_ir(ParseResult(ir=None, findings=[error]), SourceFormat.yaml)
    assert result.valid is False
    assert result.graph.nodes == [] and result.graph.edges == []
    assert result.execution_order is None
    assert [d.code for d in result.diagnostics] == [DiagnosticCode.YAML_SYNTAX_ERROR]


def test_integrity_problems_reported_and_analysis_continues():
    ir = build_ir([("a", "b")])
    ir.edges.append(Edge(source="b", target="ghost", type=EdgeType.workflow_dependency))
    result = run(ir)
    assert [d.code for d in result.diagnostics] == [DiagnosticCode.INVALID_GRAPH]
    assert [(e.source, e.target) for e in result.graph.edges] == [("a", "b")]
    assert result.execution_order is None


def test_dockerfile_has_no_execution_order_and_reports_unused_stage():
    ir = build_ir(
        [("base", "build"), ("build", "final"), ("base", "test")],
        fmt=SourceFormat.dockerfile,
    )
    ir.nodes = [
        n.model_copy(update={"metadata": {"is_final_stage": n.id == "final"}})
        for n in ir.nodes
    ]
    result = run(ir)
    assert result.execution_order is None
    assert [d.code for d in result.diagnostics] == [DiagnosticCode.UNREACHABLE_NODE]
    assert result.valid is True


def test_disconnected_chain_is_info_not_error():
    result = run(build_ir([("a", "b"), ("b", "c"), ("x", "y")], nodes=["solo"]))
    assert result.valid is True
    assert [(d.code, d.severity) for d in result.diagnostics] == [
        (DiagnosticCode.DISCONNECTED_COMPONENT, Severity.info)
    ]
    assert result.execution_order == ["a", "b", "c", "solo", "x", "y"]


def test_multiple_cycles_and_self_loop_one_diagnostic_each():
    result = run(build_ir([("a", "a"), ("b", "c"), ("c", "b"), ("c", "d")]))
    cycles = [
        d for d in result.diagnostics if d.code is DiagnosticCode.DEPENDENCY_CYCLE
    ]
    assert len(cycles) == 2


def test_adapter_format_mismatch_is_a_programming_error():
    ir = build_ir([("a", "b")], fmt=SourceFormat.terraform)
    with pytest.raises(ValueError):
        analyze_ir(ParseResult(ir), SourceFormat.yaml)


def test_output_is_identical_for_repeated_and_shuffled_input():
    edges = [("a", "b"), ("b", "c"), ("c", "a"), ("x", "y"), ("p", "q"), ("q", "r")]
    baseline = json.dumps(run(build_ir(edges)).model_dump(mode="json"))
    rng = random.Random(99)
    for _ in range(10):
        shuffled = edges[:]
        rng.shuffle(shuffled)
        ir = build_ir(shuffled)
        rng.shuffle(ir.nodes)
        assert json.dumps(run(ir).model_dump(mode="json")) == baseline


def test_compile_source_uses_given_adapter_and_passes_filename():
    adapter = FakeAdapter(ParseResult(build_ir([("a", "b")])))
    result = compile_source("jobs: {}", SourceFormat.yaml, "ci.yml", adapter=adapter)
    assert adapter.calls == [("jobs: {}", "ci.yml")]
    assert result.format is SourceFormat.yaml
    assert result.execution_order == ["a", "b"]


def test_registry_round_trip():
    adapter = FakeAdapter(ParseResult(build_ir()))
    unregister_adapter(SourceFormat.yaml)
    try:
        register_adapter(adapter)
        assert get_adapter(SourceFormat.yaml) is adapter
        with pytest.raises(ValueError):
            register_adapter(adapter)
        register_adapter(adapter, replace=True)
        assert compile_source("x", SourceFormat.yaml).valid is True
    finally:
        unregister_adapter(SourceFormat.yaml)


def test_missing_adapter_raises_clear_error():
    unregister_adapter(SourceFormat.dockerfile)
    with pytest.raises(AdapterNotAvailableError):
        get_adapter(SourceFormat.dockerfile)


def test_register_rejects_non_adapter():
    with pytest.raises(TypeError):
        register_adapter(object())
