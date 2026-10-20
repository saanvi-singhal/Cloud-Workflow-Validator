"""Terraform blocks -> IR nodes, edges and parser findings."""

import pytest

from app.models import DiagnosticCode, EdgeType, NodeType, Severity
from app.parsers.terraform import ADAPTER
from app.parsers.terraform.blocks import NOT_LITERAL, literal_value, read_file
from app.parsers.terraform.extractor import extract
from app.parsers.terraform.hcl_loader import HclSyntaxError, parse_hcl

pytestmark = [pytest.mark.parser]


def run(source: str, filename: str | None = "main.tf"):
    return extract(read_file(parse_hcl(source), filename), filename)


def codes(result) -> list[DiagnosticCode]:
    return [f.code for f in result.findings]


def edge_tuples(result):
    return sorted((e.source, e.target, e.type) for e in result.ir.edges)


BASIC = """
variable "env" {}
data "aws_ami" "u" {}
resource "aws_vpc" "main" {}
module "net" {
  source = "./net"
  vpc    = aws_vpc.main.id
}
output "vpc" {
  value = aws_vpc.main.id
}
"""


def test_node_ids_labels_types_and_metadata():
    result = run(BASIC)
    nodes = {n.id: n for n in result.ir.nodes}
    assert set(nodes) == {
        "tf:variable:env",
        "tf:data:aws_ami.u",
        "tf:resource:aws_vpc.main",
        "tf:module:net",
        "tf:output:vpc",
    }
    assert nodes["tf:resource:aws_vpc.main"].label == "aws_vpc.main"
    assert nodes["tf:data:aws_ami.u"].type is NodeType.data_source
    assert nodes["tf:data:aws_ami.u"].label == "data.aws_ami.u"
    assert nodes["tf:variable:env"].label == "var.env"
    assert nodes["tf:module:net"].metadata["source"] == "./net"
    assert nodes["tf:resource:aws_vpc.main"].metadata["resource_type"] == "aws_vpc"
    assert result.findings == [] and result.complete


def test_node_location_spans_whole_block():
    result = run('resource "aws_vpc" "main" {\n  cidr_block = "x"\n}\n')
    location = result.ir.nodes[0].source_location
    assert (location.start_line, location.start_column) == (1, 1)
    assert (location.end_line, location.end_column) == (3, 2)


def test_edge_direction_prerequisite_to_dependent():
    result = run(BASIC)
    assert edge_tuples(result) == [
        ("tf:resource:aws_vpc.main", "tf:module:net", EdgeType.terraform_reference),
        ("tf:resource:aws_vpc.main", "tf:output:vpc", EdgeType.terraform_reference),
    ]


def test_repeated_references_merge_into_one_edge():
    result = run(
        'resource "aws_vpc" "v" {}\n'
        'resource "aws_subnet" "s" {\n'
        "  vpc_id = aws_vpc.v.id\n"
        "  tags   = { Vpc = aws_vpc.v.arn }\n"
        "}\n"
    )
    (edge,) = result.ir.edges
    assert edge.label == "vpc_id"
    assert [r["attribute"] for r in edge.metadata["references"]] == ["vpc_id", "tags"]
    assert edge.source_location.start_line == 3


def test_explicit_and_inferred_edges_are_distinct_types():
    result = run(
        'resource "aws_vpc" "v" {}\n'
        'resource "aws_subnet" "s" {\n'
        "  vpc_id     = aws_vpc.v.id\n"
        "  depends_on = [aws_vpc.v]\n"
        "}\n"
    )
    assert {e.type for e in result.ir.edges} == {
        EdgeType.terraform_reference,
        EdgeType.terraform_explicit_dependency,
    }
    explicit = next(
        e for e in result.ir.edges if e.type is EdgeType.terraform_explicit_dependency
    )
    assert explicit.label == "depends_on"


def test_nested_block_references_use_dotted_path():
    result = run(
        'resource "aws_security_group" "a" {}\n'
        'resource "aws_security_group" "b" {\n'
        "  ingress {\n"
        "    security_groups = [aws_security_group.a.id]\n"
        "  }\n"
        "}\n"
    )
    assert result.ir.edges[0].label == "ingress.security_groups"


def test_unresolved_reference_creates_no_edge():
    result = run('resource "aws_subnet" "s" {\n  vpc_id = aws_vpc.missing.id\n}\n')
    assert result.ir.edges == []
    (finding,) = result.findings
    assert finding.code is DiagnosticCode.UNRESOLVED_DEPENDENCY
    assert finding.severity is Severity.error
    assert finding.diagnostic.source_location.start_line == 2
    assert finding.details["address"] == "aws_vpc.missing"


def test_unresolved_reference_lists_known_addresses_of_same_kind():
    result = run(
        'resource "aws_vpc" "main" {}\n'
        'variable "x" {}\n'
        'resource "aws_subnet" "s" { vpc_id = aws_vpc.mian.id }\n'
    )
    (finding,) = result.findings
    # Resources only (not var.x); difflib later picks the closest one.
    assert finding.details["known_addresses"] == ["aws_subnet.s", "aws_vpc.main"]


def test_duplicate_block_gets_suffixed_id_and_error():
    result = run('resource "aws_vpc" "main" {}\nresource "aws_vpc" "main" {}\n')
    assert [n.id for n in result.ir.nodes] == [
        "tf:resource:aws_vpc.main",
        "tf:resource:aws_vpc.main#2",
    ]
    assert codes(result) == [DiagnosticCode.DUPLICATE_NODE_ID]
    assert result.findings[0].diagnostic.source_location.start_line == 2


def test_unmodelled_blocks_are_info_and_do_not_mark_incomplete():
    result = run('provider "aws" {}\nterraform {}\nlocals { a = 1 }\n')
    assert codes(result) == [DiagnosticCode.UNSUPPORTED_CONSTRUCT] * 3
    assert {f.severity for f in result.findings} == {Severity.info}
    assert result.complete


def test_unknown_block_and_top_level_attribute_are_warnings():
    result = run('frobnicate "x" {}\nfoo = 1\n')
    assert codes(result) == [DiagnosticCode.UNSUPPORTED_CONSTRUCT] * 2
    assert {f.severity for f in result.findings} == {Severity.warning}
    assert not result.complete


@pytest.mark.parametrize(
    "source",
    ['resource "aws_vpc" {}\n', 'module "a" "b" {}\n', 'resource "a" "${x}" {}\n'],
)
def test_malformed_block_labels_are_reported(source):
    result = run(source)
    assert result.ir.nodes == []
    assert codes(result) == [DiagnosticCode.UNSUPPORTED_CONSTRUCT]


def test_provider_meta_argument_and_ignore_changes_are_not_dependencies():
    result = run(
        'resource "aws_vpc" "v" {\n'
        "  provider = aws.west\n"
        "  lifecycle {\n"
        "    ignore_changes = [tags]\n"
        "  }\n"
        "}\n"
    )
    assert result.ir.edges == [] and result.findings == []


def test_replace_triggered_by_is_unsupported():
    result = run(
        'resource "aws_vpc" "v" {\n'
        "  lifecycle {\n"
        "    replace_triggered_by = [aws_vpc.v]\n"
        "  }\n"
        "}\n"
    )
    constructs = [f.details["construct"] for f in result.findings]
    assert constructs == ["replace_triggered_by"]
    assert not result.complete


def _edges(result):
    return sorted((e.source, e.target, e.label) for e in result.ir.edges)


def test_dynamic_block_iterator_is_not_a_dependency():
    result = run(
        'variable "tags" {}\n'
        'resource "aws_vpc" "other" {}\n'
        'resource "aws_vpc" "v" {\n'
        '  dynamic "tag" {\n'
        "    for_each = var.tags\n"
        "    content {\n"
        "      key   = tag.key\n"
        "      value = aws_vpc.other.id\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    assert result.findings == []
    assert result.complete
    assert _edges(result) == [
        ("tf:resource:aws_vpc.other", "tf:resource:aws_vpc.v", "tag.value"),
        ("tf:variable:tags", "tf:resource:aws_vpc.v", "dynamic.tag.for_each"),
    ]


def test_dynamic_block_custom_iterator_and_nesting():
    result = run(
        'variable "groups" {}\n'
        'resource "aws_x" "x" {\n'
        '  dynamic "group" {\n'
        "    for_each = var.groups\n"
        "    iterator = g\n"
        "    content {\n"
        "      name = g.value.name\n"
        '      dynamic "member" {\n'
        "        for_each = g.value.members\n"
        "        content { id = member.value }\n"
        "      }\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    assert result.findings == []
    assert _edges(result) == [
        ("tf:variable:groups", "tf:resource:aws_x.x", "dynamic.group.for_each")
    ]


def test_iterator_name_is_scoped_to_its_content_only():
    # Outside the dynamic block `tag` is not an iterator, so it is reported.
    result = run(
        'variable "tags" {}\n'
        'resource "aws_vpc" "v" {\n'
        "  name = tag.key\n"
        '  dynamic "tag" {\n'
        "    for_each = var.tags\n"
        "    content { key = tag.key }\n"
        "  }\n"
        "}\n"
    )
    assert [f.code for f in result.findings] == [DiagnosticCode.UNRESOLVED_DEPENDENCY]


def test_dynamic_block_that_terraform_rejects_is_an_error():
    result = run(
        'resource "aws_security_group" "sg" {\n'
        '  dynamic "ingress" {\n'
        '    protocol = "tcp"\n'
        "    content {\n"
        "      from_port = ingress.value\n"
        "    }\n"
        "    content {}\n"
        "  }\n"
        '  dynamic "egress" {\n'
        "    for_each = [1]\n"
        "  }\n"
        "}\n"
    )
    assert [
        (
            f.code,
            f.severity,
            f.diagnostic.source_location.start_line,
            f.diagnostic.message.split(";")[0],
        )
        for f in result.findings
    ] == [
        (
            DiagnosticCode.TERRAFORM_SYNTAX_ERROR,
            Severity.error,
            2,
            "dynamic \"ingress\" is missing the required 'for_each' argument, so "
            "Terraform does not know what to repeat the block for.",
        ),
        (
            DiagnosticCode.TERRAFORM_SYNTAX_ERROR,
            Severity.error,
            3,
            "'protocol' is not a valid argument in dynamic \"ingress\"",
        ),
        (
            DiagnosticCode.TERRAFORM_SYNTAX_ERROR,
            Severity.error,
            7,
            'dynamic "ingress" has more than one content block.',
        ),
        (
            DiagnosticCode.TERRAFORM_SYNTAX_ERROR,
            Severity.error,
            9,
            'dynamic "egress" has no content block, so it generates nothing.',
        ),
    ]
    # `ingress.value` is still treated as the iterator, not a missing resource.
    assert all(f.code != DiagnosticCode.UNRESOLVED_DEPENDENCY for f in result.findings)
    assert all(
        f.node_ids == ("tf:resource:aws_security_group.sg",) for f in result.findings
    )


def test_variable_blocks_have_no_dependencies():
    result = run(
        'variable "v" {\n'
        "  type = list(string)\n"
        "  validation {\n"
        "    condition = length(var.v) > 0\n"
        '    error_message = "empty"\n'
        "  }\n"
        "}\n"
    )
    assert result.ir.edges == [] and result.findings == []


def test_self_reference_becomes_self_loop_edge():
    result = run('resource "aws_vpc" "v" {\n  tags = { id = aws_vpc.v.id }\n}\n')
    (edge,) = result.ir.edges
    assert edge.source == edge.target == "tf:resource:aws_vpc.v"


def test_no_filename_means_null_file_not_invented():
    result = run('resource "aws_vpc" "v" {}\n', filename=None)
    assert result.ir.nodes[0].source_location.file is None


def test_syntax_error_has_position():
    with pytest.raises(HclSyntaxError) as info:
        parse_hcl('resource "a" "b" {\n  x = \n}\n')
    assert (info.value.line, info.value.column) == (2, 7)
    assert "Token(" not in info.value.message


def test_unexpected_character_is_described():
    with pytest.raises(HclSyntaxError) as info:
        parse_hcl('resource "a" "b" {\n  x = 1 @\n}\n')
    assert info.value.line == 2
    assert str(info.value) == info.value.message
    assert "Token(" not in info.value.message


def test_adapter_reports_syntax_error_without_ir():
    result = ADAPTER.parse('resource "a" {\n', "main.tf")
    assert result.ir is None
    (finding,) = result.findings
    assert finding.code is DiagnosticCode.TERRAFORM_SYNTAX_ERROR
    assert finding.diagnostic.source_location.start_line == 2
    assert "end of file" in finding.diagnostic.message


def test_adapter_handles_empty_source():
    result = ADAPTER.parse("", None)
    assert result.ir is not None and result.ir.nodes == []
    assert result.findings == []


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ('"x"', "x"),
        ("1", 1),
        ("1.5", 1.5),
        ("true", True),
        ("false", False),
        ("null", None),
        ('["a", 1]', ["a", 1]),
        ('{ a = "b", "c" = 2 }', {"a": "b", "c": 2}),
    ],
)
def test_literal_values(expression, expected):
    (block,) = read_file(parse_hcl(f'x "y" {{\n  v = {expression}\n}}\n'), None).blocks
    assert literal_value(block.attributes[0].expr) == expected


@pytest.mark.parametrize("expression", ["var.x", '"a-${var.x}"', "f(1)", "[var.x]"])
def test_non_literals_are_not_literal(expression):
    (block,) = read_file(parse_hcl(f'x "y" {{\n  v = {expression}\n}}\n'), None).blocks
    assert literal_value(block.attributes[0].expr) is NOT_LITERAL
