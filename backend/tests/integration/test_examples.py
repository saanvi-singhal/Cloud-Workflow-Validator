"""Keep examples/terraform honest: every example must analyse as documented."""

from pathlib import Path

import pytest

from app.compiler.pipeline import compile_source
from app.models import DiagnosticCode, SourceFormat

pytestmark = [pytest.mark.integration]

EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "terraform"

# example file -> (expected `valid`, diagnostic code that must be present or None)
EXPECTED = {
    "valid_network.tf": (True, None),
    "cyclic.tf": (False, DiagnosticCode.DEPENDENCY_CYCLE),
    "unresolved_reference.tf": (False, DiagnosticCode.UNRESOLVED_DEPENDENCY),
    "depends_on.tf": (True, None),
    "dynamic_blocks.tf": (True, None),
    "unsupported_expression.tf": (True, DiagnosticCode.UNSUPPORTED_CONSTRUCT),
    "security_findings.tf": (True, DiagnosticCode.SECURITY_RULE_VIOLATION),
}


def test_every_example_is_listed():
    assert sorted(p.name for p in EXAMPLES.glob("*.tf")) == sorted(EXPECTED)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_example_analyses_as_documented(name):
    valid, code = EXPECTED[name]
    result = compile_source(
        (EXAMPLES / name).read_text(), SourceFormat.terraform, filename=name
    )
    assert result.valid is valid
    if code is not None:
        assert code in {d.code for d in result.diagnostics}
    else:
        assert result.diagnostics == []
