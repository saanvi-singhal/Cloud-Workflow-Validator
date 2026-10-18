"""Terraform fixtures through the full pipeline (parse -> IR -> analysis)."""

import json
from pathlib import Path

import pytest

from app.compiler.adapters import get_adapter
from app.compiler.pipeline import compile_source
from app.models import DiagnosticCode, EdgeType, Severity, SourceFormat

pytestmark = [pytest.mark.integration, pytest.mark.compiler]

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "terraform"


def analyse(name: str):
    return compile_source(
        (FIXTURES / name).read_text(), SourceFormat.terraform, filename=name
    )


def codes(result) -> list[DiagnosticCode]:
    return [d.code for d in result.diagnostics]


def test_terraform_adapter_is_registered_lazily():
    assert get_adapter(SourceFormat.terraform).format is SourceFormat.terraform


def test_valid_fixture():
    result = analyse("valid.tf")
    assert result.valid is True
    assert result.diagnostics == []
    assert result.execution_order == [
        "tf:data:aws_ami.ubuntu",
        "tf:variable:env",
        "tf:resource:aws_vpc.main",
        "tf:resource:aws_security_group.web",
        "tf:resource:aws_subnet.app",
        "tf:resource:aws_instance.web",
        "tf:output:web_ip",
    ]
    position = {n: i for i, n in enumerate(result.execution_order)}
    for edge in result.graph.edges:
        assert position[edge.source] < position[edge.target]


def test_cyclic_fixture_reports_each_cycle_once():
    result = analyse("cyclic.tf")
    assert result.valid is False
    assert result.execution_order is None
    assert codes(result) == [DiagnosticCode.DEPENDENCY_CYCLE] * 2
    sg_cycle, self_loop = result.diagnostics
    assert "aws_security_group.app -> aws_security_group.db" in sg_cycle.message
    assert sg_cycle.source_location.start_line == 9
    assert "depends on itself" in self_loop.message


def test_unresolved_fixture():
    result = analyse("unresolved.tf")
    assert result.valid is False
    assert codes(result) == [DiagnosticCode.UNRESOLVED_DEPENDENCY]
    assert result.diagnostics[0].source_location.start_line == 7
    assert result.graph.edges == []
    assert result.execution_order is None


def test_depends_on_fixture_has_both_edge_types():
    result = analyse("depends_on.tf")
    assert result.valid is True
    types = sorted((e.source.split(":")[-1], e.type.value) for e in result.graph.edges)
    assert types == [
        ("aws_iam_role.deployer", EdgeType.terraform_explicit_dependency.value),
        ("aws_iam_role.deployer", EdgeType.terraform_reference.value),
        ("aws_s3_bucket.artifacts", EdgeType.terraform_explicit_dependency.value),
    ]
    assert result.execution_order[-1] == "tf:resource:aws_instance.builder"


def test_unsupported_fixture_is_partial_and_has_no_order():
    result = analyse("unsupported.tf")
    assert set(codes(result)) == {DiagnosticCode.UNSUPPORTED_CONSTRUCT}
    assert result.valid is True  # partial analysis is not an error...
    assert result.execution_order is None  # ...but no misleading order
    warnings = [d for d in result.diagnostics if d.severity is Severity.warning]
    assert len(warnings) == 4  # local ref, for expr, heredoc, dynamic


def test_security_fixture():
    result = analyse("security.tf")
    rules = [
        d.message.split("]")[0].lstrip("[")
        for d in result.diagnostics
        if d.code is DiagnosticCode.SECURITY_RULE_VIOLATION
    ]
    assert rules == [
        "TF_HARDCODED_SECRET",
        "TF_HARDCODED_SECRET",
        "TF_S3_PUBLIC_ACL",
        "TF_SG_OPEN_INGRESS",
        "TF_DB_PUBLICLY_ACCESSIBLE",
    ]
    assert result.valid is True


def test_syntax_error_fixture():
    result = analyse("syntax_error.tf")
    assert result.valid is False
    assert codes(result) == [DiagnosticCode.TERRAFORM_SYNTAX_ERROR]
    assert result.diagnostics[0].source_location.start_line == 2
    assert result.graph.nodes == []


@pytest.mark.parametrize("name", sorted(p.name for p in FIXTURES.glob("*.tf")))
def test_fixture_output_is_deterministic(name):
    runs = {json.dumps(analyse(name).model_dump(mode="json")) for _ in range(3)}
    assert len(runs) == 1


def test_large_generated_file_is_fast_enough():
    blocks = ['resource "null_resource" "r0" {}']
    blocks += [
        f'resource "null_resource" "r{i}" {{\n'
        f"  triggers = {{ p = null_resource.r{i - 1}.id }}\n}}"
        for i in range(1, 400)
    ]
    result = compile_source("\n".join(blocks), SourceFormat.terraform)
    assert result.valid is True
    assert len(result.execution_order) == 400
