"""Terraform's own structural rules (app/parsers/terraform/validate.py)."""

import pytest

from app.compiler.pipeline import compile_source
from app.models import SourceFormat

CASES = {
    "unknown block": ('resorce "aws_vpc" "a" {}\n', "Unsupported block type"),
    "missing label": ('resource "aws_vpc" {}\n', "Missing name for resource"),
    "extra label": ('variable "a" "b" {}\n', "Extraneous label for variable"),
    "bad name": ('resource "aws_vpc" "1main" {}\n', "Invalid resource name"),
    "variable arg": (
        'variable "env" {\n  defualt = "x"\n}\n',
        "Did you mean 'default'?",
    ),
    "output value": ('output "id" {\n  description = "x"\n}\n', "'value' is required"),
    "module source": ('module "net" {\n  version = "1"\n}\n', "'source' is required"),
    "count and for_each": (
        'resource "a" "b" {\n  count = 2\n  for_each = toset([])\n}\n',
        "Invalid combination",
    ),
    "count.index": (
        'resource "a" "b" {\n  n = count.index\n}\n',
        "non-counted context",
    ),
    "each.key": ('resource "a" "b" {\n  n = each.key\n}\n', "without for_each"),
    "reserved var": ('variable "count" {}\n', "is reserved"),
    "lifecycle": (
        'resource "a" "b" {\n  lifecycle {\n    prevent_destroi = true\n  }\n}\n',
        "Did you mean 'prevent_destroy'?",
    ),
    "validation": (
        'variable "a" {\n  validation {\n    condition = true\n  }\n}\n',
        "needs 'error_message'",
    ),
    "duplicate attribute": (
        'resource "a" "b" {\n  x = 1\n  x = 2\n}\n',
        "Attribute redefined",
    ),
    "bad type": ('variable "a" {\n  type = strng\n}\n', "Did you mean 'string'?"),
    "quoted type": ('variable "a" {\n  type = "string"\n}\n', "Invalid quoted type"),
    "terraform block": (
        'terraform {\n  bakend "s3" {}\n}\n',
        "Did you mean 'backend'?",
    ),
}


@pytest.mark.parametrize(("source", "expected"), CASES.values(), ids=CASES.keys())
def test_terraform_rule(source, expected):
    errors = [
        d.message
        for d in compile_source(source, SourceFormat.terraform, "main.tf").diagnostics
        if d.severity.value == "error"
    ]
    assert any(expected in m for m in errors), errors


def test_valid_module_has_no_errors():
    source = (
        'terraform {\n  required_version = ">= 1.6"\n  backend "s3" {}\n}\n'
        'variable "names" {\n  type = list(string)\n  default = []\n'
        '  validation {\n    condition = true\n    error_message = "x"\n  }\n}\n'
        'resource "aws_s3_bucket" "b" {\n  for_each = toset(var.names)\n'
        "  bucket = each.key\n  lifecycle {\n    prevent_destroy = true\n  }\n}\n"
        'ephemeral "random_password" "p" {\n  length = 16\n}\n'
    )
    errors = [
        d.message
        for d in compile_source(source, SourceFormat.terraform, "main.tf").diagnostics
        if d.severity.value == "error"
    ]
    assert errors == []
