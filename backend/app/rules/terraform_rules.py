"""A small, documented set of deterministic Terraform security rules.

This is **not** a comprehensive security scanner (spec 4.3, 6.3). Each rule:

* inspects only *literal* values. If the value is a variable, reference or
  function call, the rule stays silent rather than guess what it evaluates to;
* emits ``SECURITY_RULE_VIOLATION`` at ``warning`` severity (decision D11),
  with a stable ``rule_id`` on the internal finding for recommendations.

Rules:

=========================  ==================================================
rule_id                    fires when
=========================  ==================================================
TF_S3_PUBLIC_ACL           aws_s3_bucket / aws_s3_bucket_acl ``acl`` is
                           ``public-read`` or ``public-read-write``
TF_SG_OPEN_INGRESS         ingress open to ``0.0.0.0/0`` or ``::/0``
                           (aws_security_group ``ingress`` blocks,
                           aws_security_group_rule with type ``ingress``,
                           aws_vpc_security_group_ingress_rule)
TF_HARDCODED_SECRET        a secret-like attribute (password, secret_key,
                           access_key, token, ...) is a non-empty string
                           literal, in a resource/data/module/provider block,
                           or a secret-named variable has a literal default
TF_DB_PUBLICLY_ACCESSIBLE  aws_db_instance / aws_rds_cluster_instance has
                           ``publicly_accessible = true``
=========================  ==================================================
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from app.compiler.findings import Finding, make_finding
from app.models import DiagnosticCode, Severity, SourceLocation
from app.parsers.terraform.blocks import NOT_LITERAL, Block, literal_value

RULE_S3_PUBLIC_ACL = "TF_S3_PUBLIC_ACL"
RULE_SG_OPEN_INGRESS = "TF_SG_OPEN_INGRESS"
RULE_HARDCODED_SECRET = "TF_HARDCODED_SECRET"
RULE_DB_PUBLICLY_ACCESSIBLE = "TF_DB_PUBLICLY_ACCESSIBLE"

PUBLIC_ACLS = frozenset({"public-read", "public-read-write"})
OPEN_CIDRS = frozenset({"0.0.0.0/0", "::/0"})
SECRET_ATTRIBUTES = frozenset(
    {
        "password",
        "master_password",
        "admin_password",
        "secret_key",
        "access_key",
        "secret",
        "client_secret",
        "token",
        "api_key",
    }
)
SECRET_VARIABLE_WORDS = ("password", "secret", "token", "api_key", "access_key")


def _attr_literal(block: Block, name: str) -> Any:
    attribute = block.attribute(name)
    return NOT_LITERAL if attribute is None else literal_value(attribute.expr)


def _attr_location(block: Block, name: str) -> SourceLocation | None:
    attribute = block.attribute(name)
    return attribute.location if attribute is not None else block.location


def _finding(
    rule_id: str,
    message: str,
    location: SourceLocation | None,
    node_id: str | None,
    **details: Any,
) -> Finding:
    return make_finding(
        DiagnosticCode.SECURITY_RULE_VIOLATION,
        Severity.warning,
        f"[{rule_id}] {message}",
        location,
        rule_id=rule_id,
        node_ids=(node_id,) if node_id else (),
        details=details,
    )


def _resource_type(block: Block) -> str | None:
    return block.labels[0] if block.type == "resource" and block.labels else None


def check_s3_public_acl(block: Block, node_id: str | None) -> Iterator[Finding]:
    if _resource_type(block) not in ("aws_s3_bucket", "aws_s3_bucket_acl"):
        return
    acl = _attr_literal(block, "acl")
    if isinstance(acl, str) and acl in PUBLIC_ACLS:
        yield _finding(
            RULE_S3_PUBLIC_ACL,
            f"S3 ACL '{acl}' makes objects publicly readable.",
            _attr_location(block, "acl"),
            node_id,
            attribute="acl",
            value=acl,
        )


def _open_cidrs(block: Block, *names: str) -> list[str]:
    found: list[str] = []
    for name in names:
        value = _attr_literal(block, name)
        if isinstance(value, str):
            value = [value]
        if isinstance(value, list):
            found.extend(v for v in value if isinstance(v, str) and v in OPEN_CIDRS)
    return found


def check_open_ingress(block: Block, node_id: str | None) -> Iterator[Finding]:
    resource_type = _resource_type(block)
    candidates: list[Block] = []
    if resource_type == "aws_security_group":
        candidates = block.nested("ingress")
    elif resource_type == "aws_security_group_rule":
        if _attr_literal(block, "type") == "ingress":
            candidates = [block]
    elif resource_type == "aws_vpc_security_group_ingress_rule":
        candidates = [block]

    for rule_block in candidates:
        cidrs = _open_cidrs(
            rule_block, "cidr_blocks", "ipv6_cidr_blocks", "cidr_ipv4", "cidr_ipv6"
        )
        if not cidrs:
            continue
        from_port = _attr_literal(rule_block, "from_port")
        to_port = _attr_literal(rule_block, "to_port")
        ports = ""
        if isinstance(from_port, int) and isinstance(to_port, int):
            ports = f" on port(s) {from_port}-{to_port}"
        yield _finding(
            RULE_SG_OPEN_INGRESS,
            f"Ingress{ports} is open to {', '.join(sorted(set(cidrs)))} "
            "(any address on the internet).",
            rule_block.location,
            node_id,
            cidrs=sorted(set(cidrs)),
        )


def _secret_attributes(block: Block) -> Iterator[tuple[str, SourceLocation | None]]:
    for attribute in block.attributes:
        if attribute.name in SECRET_ATTRIBUTES:
            value = literal_value(attribute.expr)
            if isinstance(value, str) and value:
                yield attribute.name, attribute.location
    for nested in block.blocks:
        yield from _secret_attributes(nested)


def check_hardcoded_secret(block: Block, node_id: str | None) -> Iterator[Finding]:
    if block.type == "variable":
        name = block.labels[0] if block.labels else ""
        default = _attr_literal(block, "default")
        secret_like = any(word in name.lower() for word in SECRET_VARIABLE_WORDS)
        if secret_like and isinstance(default, str) and default:
            yield _finding(
                RULE_HARDCODED_SECRET,
                f"Variable '{name}' has a hardcoded default secret value.",
                _attr_location(block, "default"),
                node_id,
                attribute="default",
            )
        return
    if block.type not in ("resource", "data", "module", "provider"):
        return
    for attribute_name, location in _secret_attributes(block):
        yield _finding(
            RULE_HARDCODED_SECRET,
            f"'{attribute_name}' is a hardcoded string literal; secrets in "
            "source are visible to anyone with repository access.",
            location,
            node_id,
            attribute=attribute_name,
        )


def check_db_publicly_accessible(
    block: Block, node_id: str | None
) -> Iterator[Finding]:
    if _resource_type(block) not in ("aws_db_instance", "aws_rds_cluster_instance"):
        return
    if _attr_literal(block, "publicly_accessible") is True:
        yield _finding(
            RULE_DB_PUBLICLY_ACCESSIBLE,
            "Database instance is publicly accessible from the internet.",
            _attr_location(block, "publicly_accessible"),
            node_id,
            attribute="publicly_accessible",
        )


RULES: tuple[Callable[[Block, str | None], Iterator[Finding]], ...] = (
    check_s3_public_acl,
    check_open_ingress,
    check_hardcoded_secret,
    check_db_publicly_accessible,
)


def run_terraform_rules(blocks: list[tuple[Block, str | None]]) -> list[Finding]:
    """Run every rule over ``(block, node_id)`` pairs, in source order."""
    findings: list[Finding] = []
    for block, node_id in blocks:
        for rule in RULES:
            findings.extend(rule(block, node_id))
    return findings
