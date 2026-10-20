"""Tests for the deterministic recommendation engine and catalogue."""

import json
from pathlib import Path

import pytest

from app.compiler.adapters import ParseResult
from app.compiler.findings import make_finding
from app.compiler.pipeline import analyze_ir, compile_source
from app.models import DiagnosticCode, FixKind, Severity, SourceFormat
from app.recommendations.engine import generate_recommendations
from tests.graph_builders import build_ir, loc

pytestmark = [pytest.mark.unit, pytest.mark.compiler]

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "terraform"


def analyse_fixture(name: str):
    return compile_source(
        (FIXTURES / name).read_text(), SourceFormat.terraform, filename=name
    )


def test_every_recommendation_links_to_its_diagnostic():
    for path in sorted(FIXTURES.glob("*.tf")):
        result = analyse_fixture(path.name)
        for rec in result.recommendations:
            diagnostic = result.diagnostics[rec.diagnostic_index]
            assert rec.diagnostic_code is diagnostic.code
            assert rec.source_location == diagnostic.source_location
            assert rec.id == f"{rec.rule_id}:{rec.diagnostic_index}"


def test_no_recommendation_claims_a_deterministic_fix_in_v1():
    for path in sorted(FIXTURES.glob("*.tf")):
        for rec in analyse_fixture(path.name).recommendations:
            assert rec.fix_kind is FixKind.judgment


def test_cycle_recommendation_lists_edges_and_related_nodes():
    result = analyse_fixture("cyclic.tf")
    cycle, self_loop = result.recommendations
    assert cycle.rule_id == "BREAK_DEPENDENCY_CYCLE"
    assert cycle.related_node_ids == [
        "tf:resource:aws_security_group.app",
        "tf:resource:aws_security_group.db",
    ]
    assert "via 'egress.security_groups'" in cycle.explanation
    assert "self-dependency" in self_loop.title


def test_cycle_recommendation_names_explicit_depends_on_first():
    source = (
        'resource "aws_vpc" "a" {\n  depends_on = [aws_vpc.b]\n}\n'
        'resource "aws_vpc" "b" {\n  tags = { a = aws_vpc.a.id }\n}\n'
    )
    (rec,) = compile_source(source, SourceFormat.terraform).recommendations
    first_step = rec.explanation.split("dependencies: ")[1].split(";")[0]
    assert "via 'depends_on'" in first_step
    assert "Explicit depends_on" in rec.explanation


def test_typo_gets_did_you_mean_with_preview():
    (rec,) = analyse_fixture("unresolved.tf").recommendations
    assert rec.title == "Did you mean 'aws_vpc.main'?"
    assert rec.proposed_change.preview == "- aws_vpc.mian\n+ aws_vpc.main"


def test_unresolved_without_close_match_has_no_preview():
    source = 'resource "aws_subnet" "s" {\n  vpc_id = aws_vpc.zzz.id\n}\n'
    (rec,) = compile_source(source, SourceFormat.terraform).recommendations
    assert rec.title == "Declare 'aws_vpc.zzz'"
    assert rec.proposed_change is None


def test_unsupported_info_gets_no_recommendation_but_warnings_do():
    result = analyse_fixture("unsupported.tf")
    linked = [result.diagnostics[r.diagnostic_index] for r in result.recommendations]
    assert linked and all(d.severity is Severity.warning for d in linked)
    assert len(result.recommendations) == 3


def test_security_recommendations_per_rule():
    result = analyse_fixture("security.tf")
    rule_ids = [
        r.rule_id
        for r in result.recommendations
        if r.diagnostic_code is DiagnosticCode.SECURITY_RULE_VIOLATION
    ]
    assert rule_ids == [
        "TF_HARDCODED_SECRET",
        "TF_HARDCODED_SECRET",
        "TF_S3_PUBLIC_ACL",
        "TF_SG_OPEN_INGRESS",
        "TF_DB_PUBLICLY_ACCESSIBLE",
    ]
    acl = next(r for r in result.recommendations if r.rule_id == "TF_S3_PUBLIC_ACL")
    assert acl.proposed_change.preview == '- acl = "public-read"\n+ acl = "private"'
    sg = next(r for r in result.recommendations if r.rule_id == "TF_SG_OPEN_INGRESS")
    assert sg.proposed_change.preview is None  # the right CIDR can't be inferred


def test_generic_findings_get_generic_recommendations():
    findings = [
        make_finding(DiagnosticCode.YAML_SYNTAX_ERROR, Severity.error, "x", loc(1)),
        make_finding(DiagnosticCode.DUPLICATE_NODE_ID, Severity.error, "x", loc(2)),
        make_finding(DiagnosticCode.INVALID_GRAPH, Severity.error, "x", loc(3)),
        make_finding(DiagnosticCode.UNRESOLVED_DEPENDENCY, Severity.error, "x"),
        make_finding(
            DiagnosticCode.SECURITY_RULE_VIOLATION,
            Severity.warning,
            "x",
            rule_id="GHA_SOMETHING",
        ),
        make_finding(DiagnosticCode.SOURCE_TOO_LARGE, Severity.error, "x"),
    ]
    recs = generate_recommendations(findings, None)
    assert [r.rule_id for r in recs] == [
        "FIX_SYNTAX_ERROR",
        "RENAME_DUPLICATE",
        "REPORT_INTERNAL_INCONSISTENCY",
        "RESOLVE_MISSING_DEPENDENCY",
        "GHA_SOMETHING",
    ]
    assert [r.diagnostic_index for r in recs] == [0, 1, 2, 3, 4]


def test_graph_level_recommendations_from_pipeline():
    ir = build_ir(
        [("base", "build"), ("build", "final"), ("base", "test")],
        fmt=SourceFormat.dockerfile,
    )
    ir.nodes = [
        n.model_copy(update={"metadata": {"is_final_stage": n.id == "final"}})
        for n in ir.nodes
    ]
    (rec,) = analyze_ir(ParseResult(ir), SourceFormat.dockerfile).recommendations
    assert rec.rule_id == "REVIEW_UNUSED_NODE"
    assert rec.related_node_ids == ["test"]

    yaml_ir = build_ir([("a", "b"), ("b", "c"), ("x", "y")])
    (rec,) = analyze_ir(ParseResult(yaml_ir), SourceFormat.yaml).recommendations
    assert rec.rule_id == "REVIEW_DISCONNECTED"
    assert rec.proposed_change is None


def test_recommendations_are_deterministic():
    runs = {
        json.dumps(
            [r.model_dump(mode="json") for r in analyse_fixture(name).recommendations]
        )
        for name in ["security.tf"] * 3
    }
    assert len(runs) == 1
