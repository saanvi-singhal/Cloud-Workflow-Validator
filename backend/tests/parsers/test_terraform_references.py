"""Structural reference extraction from real python-hcl2 expression trees."""

import pytest

from app.parsers.terraform.blocks import read_file
from app.parsers.terraform.hcl_loader import parse_hcl
from app.parsers.terraform.references import (
    analyze_expression,
    explicit_dependencies,
)

pytestmark = [pytest.mark.parser]


def expr_of(expression: str):
    """Parse ``x = <expression>`` inside a resource and return the expr tree."""
    source = f'resource "t" "n" {{\n  x = {expression}\n}}\n'
    (block,) = read_file(parse_hcl(source), "main.tf").blocks
    return block.attributes[0].expr


def addresses(expression: str) -> list[str]:
    result = analyze_expression(expr_of(expression), "main.tf")
    assert result.unsupported == [], result.unsupported
    return [r.address for r in result.references]


def unsupported(expression: str) -> list[str]:
    return [
        u.construct for u in analyze_expression(expr_of(expression), None).unsupported
    ]


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("aws_vpc.main.id", ["aws_vpc.main"]),
        ("aws_vpc.main", ["aws_vpc.main"]),
        ("data.aws_ami.ubuntu.id", ["data.aws_ami.ubuntu"]),
        ("module.net.vpc_id", ["module.net"]),
        ("var.env", ["var.env"]),
        ("aws_subnet.a[0].id", ["aws_subnet.a"]),
        ('aws_subnet.a["k"].id', ["aws_subnet.a"]),
        ("aws_instance.web[*].id", ["aws_instance.web"]),
        ("aws_instance.web.*.id", ["aws_instance.web"]),
        ("aws_subnet.a[var.i].id", ["aws_subnet.a", "var.i"]),
        ("var.f ? aws_vpc.a.id : aws_vpc.b.id", ["var.f", "aws_vpc.a", "aws_vpc.b"]),
        ('lookup(var.m, "k", aws_vpc.main.id)', ["var.m", "aws_vpc.main"]),
        ("element(aws_subnet.a, 0).id", ["aws_subnet.a"]),
        ('"vpc-${aws_vpc.main.id}-${var.env}"', ["aws_vpc.main", "var.env"]),
        ("[aws_vpc.a.id, aws_vpc.b.id]", ["aws_vpc.a", "aws_vpc.b"]),
        ("{ name = aws_vpc.a.id }", ["aws_vpc.a"]),
        ("{ (var.key) = 1 }", ["var.key"]),
        ("!var.x && (1 + var.n) > -var.m", ["var.x", "var.n", "var.m"]),
        ('"plain"', []),
        ("42", []),
        ("3.5", []),
        ("true", []),
        ("null", []),
        ("count.index", []),
        ("each.value", []),
        ("self.id", []),
        ("path.module", []),
        ("terraform.workspace", []),
        ('file("init.sh")', []),
        ("<<EOT\nno interpolation\nEOT\n", []),
    ],
)
def test_reference_extraction(expression, expected):
    assert addresses(expression) == expected


def test_object_keys_are_not_references():
    # "Name" is a key, not a reference to a resource or variable.
    assert addresses('{ Name = "x" }') == []


def test_reference_location_is_the_expression_span():
    (ref,) = analyze_expression(expr_of("aws_vpc.main.id"), "main.tf").references
    location = ref.location
    assert (location.file, location.start_line, location.start_column) == (
        "main.tf",
        2,
        7,
    )
    assert location.end_column == 7 + len("aws_vpc.main.id")  # exclusive end


@pytest.mark.parametrize(
    ("expression", "construct"),
    [
        ("local.tags", "local.tags"),
        ("[for s in var.list : s.id]", "for expression"),
        ("{for k, v in var.m : k => v}", "for expression"),
        ('"%{ if var.x }yes%{ endif }"', "template directive"),
        ("<<EOT\nhello ${aws_vpc.main.id}\nEOT\n", "heredoc template"),
        ("tags", "tags"),
        ("data.aws_ami", "data.aws_ami"),
        ("module", "module"),
        ("var", "var"),
    ],
)
def test_unsupported_forms_are_reported_not_guessed(expression, construct):
    result = analyze_expression(expr_of(expression), None)
    assert construct in [u.construct for u in result.unsupported]
    assert result.references == []


def test_for_expression_hides_inner_references():
    # Conservative: nothing inside the for expression becomes a dependency.
    assert unsupported("[for s in aws_subnet.all : s.id]") == ["for expression"]


def deps(expression: str):
    return explicit_dependencies(expr_of(expression), "main.tf")


def test_depends_on_accepts_whole_block_references():
    result = deps("[aws_vpc.main, data.aws_ami.u, module.net]")
    assert [r.address for r in result.references] == [
        "aws_vpc.main",
        "data.aws_ami.u",
        "module.net",
    ]
    assert result.unsupported == []


@pytest.mark.parametrize(
    "expression",
    [
        "[aws_vpc.main.id]",  # attribute, not a whole block
        "[aws_vpc.main[0]]",  # index
        "[var.env]",  # variables are not valid depends_on targets
        '["aws_vpc.main"]',  # a string, not a reference
        "[local.x]",
        "aws_vpc.main",  # not a list
    ],
)
def test_depends_on_rejects_other_forms(expression):
    result = deps(expression)
    assert result.references == []
    assert len(result.unsupported) == 1
