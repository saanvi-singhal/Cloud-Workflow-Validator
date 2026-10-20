"""Keep examples/ honest: every example must analyse as documented."""

from pathlib import Path

import pytest

from app.compiler.pipeline import compile_source
from app.models import DiagnosticCode, SourceFormat

pytestmark = [pytest.mark.integration]

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"
FORMATS = {
    "terraform": SourceFormat.terraform,
    "yaml": SourceFormat.yaml,
    "dockerfile": SourceFormat.dockerfile,
}

# example path -> (expected `valid`, diagnostic code that must be present or None)
EXPECTED = {
    "terraform/valid_network.tf": (True, None),
    "terraform/cyclic.tf": (False, DiagnosticCode.DEPENDENCY_CYCLE),
    "terraform/unresolved_reference.tf": (False, DiagnosticCode.UNRESOLVED_DEPENDENCY),
    "terraform/depends_on.tf": (True, None),
    "terraform/dynamic_blocks.tf": (True, None),
    "terraform/unsupported_expression.tf": (True, DiagnosticCode.UNSUPPORTED_CONSTRUCT),
    "terraform/security_findings.tf": (True, DiagnosticCode.SECURITY_RULE_VIOLATION),
    "yaml/valid_pipeline.yml": (True, None),
    "yaml/unresolved_needs.yml": (False, DiagnosticCode.UNRESOLVED_DEPENDENCY),
    "yaml/cyclic_needs.yml": (False, DiagnosticCode.DEPENDENCY_CYCLE),
    "yaml/schema_errors.yml": (False, DiagnosticCode.YAML_SYNTAX_ERROR),
    "yaml/script_injection.yml": (True, DiagnosticCode.SECURITY_RULE_VIOLATION),
    "dockerfile/multi_stage.Dockerfile": (True, None),
    "dockerfile/unused_stage.Dockerfile": (True, DiagnosticCode.UNREACHABLE_NODE),
    "dockerfile/copy_from_typo.Dockerfile": (
        True,
        DiagnosticCode.UNRESOLVED_DEPENDENCY,
    ),
    "dockerfile/best_practices.Dockerfile": (
        False,
        DiagnosticCode.SECURITY_RULE_VIOLATION,
    ),
    "dockerfile/syntax_errors.Dockerfile": (
        False,
        DiagnosticCode.DOCKERFILE_SYNTAX_ERROR,
    ),
}


def test_every_example_is_listed():
    found = sorted(
        str(path.relative_to(EXAMPLES))
        for folder in FORMATS
        for path in (EXAMPLES / folder).iterdir()
    )
    assert found == sorted(EXPECTED)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_example_analyses_as_documented(name):
    valid, code = EXPECTED[name]
    path = EXAMPLES / name
    result = compile_source(
        path.read_text(), FORMATS[path.parent.name], filename=path.name
    )
    assert result.valid is valid
    if code is not None:
        assert code in {d.code for d in result.diagnostics}
    else:
        assert result.diagnostics == []


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_example_output_is_deterministic(name):
    path = EXAMPLES / name
    runs = {
        compile_source(
            path.read_text(), FORMATS[path.parent.name], path.name
        ).model_dump_json()
        for _ in range(3)
    }
    assert len(runs) == 1
