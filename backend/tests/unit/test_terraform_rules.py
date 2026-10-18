"""Tests for the documented Terraform security rule set."""

import pytest

from app.models import DiagnosticCode, Severity
from app.parsers.terraform import ADAPTER

pytestmark = [pytest.mark.unit]


def rule_ids(source: str) -> list[str]:
    result = ADAPTER.parse(source, "main.tf")
    findings = [
        f for f in result.findings if f.code is DiagnosticCode.SECURITY_RULE_VIOLATION
    ]
    assert all(f.severity is Severity.warning for f in findings)
    return [f.rule_id for f in findings]


@pytest.mark.parametrize("acl", ["public-read", "public-read-write"])
def test_s3_public_acl(acl):
    assert rule_ids(f'resource "aws_s3_bucket" "b" {{\n  acl = "{acl}"\n}}\n') == [
        "TF_S3_PUBLIC_ACL"
    ]


@pytest.mark.parametrize("acl", ['"private"', "var.acl"])
def test_s3_private_or_non_literal_acl_is_silent(acl):
    source = (
        f'variable "acl" {{}}\nresource "aws_s3_bucket_acl" "b" {{ acl = {acl} }}\n'
    )
    assert rule_ids(source) == []


def test_security_group_open_ingress_block():
    source = (
        'resource "aws_security_group" "sg" {\n'
        "  ingress {\n"
        "    from_port   = 22\n"
        "    to_port     = 22\n"
        '    cidr_blocks = ["0.0.0.0/0"]\n'
        "  }\n"
        "  egress {\n"
        '    cidr_blocks = ["0.0.0.0/0"]\n'
        "  }\n"
        "}\n"
    )
    result = ADAPTER.parse(source, "main.tf")
    (finding,) = result.findings
    assert finding.rule_id == "TF_SG_OPEN_INGRESS"
    assert "22-22" in finding.diagnostic.message
    assert finding.diagnostic.source_location.start_line == 2  # the ingress block
    assert finding.node_ids == ("tf:resource:aws_security_group.sg",)


def test_security_group_rule_and_vpc_ingress_rule():
    source = (
        'resource "aws_security_group_rule" "r" {\n'
        '  type             = "ingress"\n'
        '  ipv6_cidr_blocks = ["::/0"]\n'
        "}\n"
        'resource "aws_security_group_rule" "egress" {\n'
        '  type        = "egress"\n'
        '  cidr_blocks = ["0.0.0.0/0"]\n'
        "}\n"
        'resource "aws_vpc_security_group_ingress_rule" "i" {\n'
        '  cidr_ipv4 = "0.0.0.0/0"\n'
        "}\n"
    )
    assert rule_ids(source) == ["TF_SG_OPEN_INGRESS", "TF_SG_OPEN_INGRESS"]


def test_private_cidr_is_silent():
    source = (
        'resource "aws_security_group" "sg" {\n'
        '  ingress { cidr_blocks = ["10.0.0.0/8"] }\n'
        "}\n"
    )
    assert rule_ids(source) == []


def test_hardcoded_secrets():
    source = (
        'provider "aws" {\n  secret_key = "abc"\n}\n'
        'resource "aws_db_instance" "db" {\n  password = "p@ss"\n}\n'
        'resource "aws_db_instance" "ok" {\n  password = var.pw\n}\n'
        'variable "pw" {}\n'
        'variable "api_token" {\n  default = "t0ken"\n}\n'
        'variable "region" {\n  default = "eu-west-1"\n}\n'
        'resource "x" "empty" {\n  token = ""\n}\n'
    )
    assert rule_ids(source) == ["TF_HARDCODED_SECRET"] * 3


def test_db_publicly_accessible():
    source = (
        'resource "aws_db_instance" "a" { publicly_accessible = true }\n'
        'resource "aws_db_instance" "b" { publicly_accessible = false }\n'
        'resource "aws_db_instance" "c" { publicly_accessible = var.p }\n'
        'variable "p" {}\n'
    )
    assert rule_ids(source) == ["TF_DB_PUBLICLY_ACCESSIBLE"]
