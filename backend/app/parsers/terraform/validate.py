"""Terraform's own structural rules (what ``terraform validate`` rejects).

These need no provider schemas, so they are checked statically. Each finding
is ``TERRAFORM_SYNTAX_ERROR`` (error), with a message modelled on Terraform's
own (``Unsupported block type``, ``Missing required argument``, ...):

* top-level blocks: only known types, with the right number of labels, and
  names that are identifiers; no top-level arguments;
* ``variable``: allowed arguments, reserved names, a valid ``type``
  (an unquoted type constraint), ``validation`` blocks with ``condition`` and
  ``error_message``;
* ``output`` needs ``value``; ``module`` needs ``source``;
  ``moved``/``import``/``removed`` need their required arguments;
* ``resource``/``data``: not both ``count`` and ``for_each``; ``lifecycle``
  arguments; ``count.*`` only with ``count`` and ``each.*`` only with
  ``for_each``;
* ``terraform`` block contents; duplicate default ``provider`` blocks;
  duplicate ``locals`` names; an argument set twice in one block.

Duplicate resources, variables and so on are reported by the extractor as
DUPLICATE_NODE_ID. Provider-specific arguments are not checked: that needs
the provider's schema.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterator

from app.compiler.findings import Finding, make_finding
from app.models import DiagnosticCode, Severity, SourceLocation
from app.parsers.terraform.blocks import (
    Attribute,
    Block,
    TerraformFile,
    subtrees,
    unwrap,
)
from app.parsers.terraform.hcl_loader import Tree

# Top-level block types and their labels (Terraform 1.x language).
BLOCK_LABELS: dict[str, tuple[str, ...]] = {
    "terraform": (),
    "provider": ("name",),
    "variable": ("name",),
    "locals": (),
    "output": ("name",),
    "module": ("name",),
    "resource": ("type", "name"),
    "data": ("type", "name"),
    "ephemeral": ("type", "name"),
    "moved": (),
    "import": (),
    "removed": (),
    "check": ("name",),
}
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
VARIABLE_ARGS = frozenset(
    {"default", "type", "description", "sensitive", "nullable", "ephemeral"}
)
RESERVED_VARIABLE_NAMES = frozenset(
    {
        "source",
        "version",
        "providers",
        "count",
        "for_each",
        "lifecycle",
        "depends_on",
        "locals",
    }
)
TYPE_KEYWORDS = frozenset({"string", "number", "bool", "any"})
OUTPUT_ARGS = frozenset(
    {"value", "description", "sensitive", "depends_on", "ephemeral"}
)
LIFECYCLE_ARGS = {
    "resource": frozenset(
        {
            "create_before_destroy",
            "prevent_destroy",
            "ignore_changes",
            "replace_triggered_by",
        }
    ),
    "data": frozenset(),
    "ephemeral": frozenset(),
}
LIFECYCLE_BLOCKS = frozenset({"precondition", "postcondition", "action_trigger"})
TERRAFORM_ARGS = frozenset({"required_version", "experiments", "language"})
TERRAFORM_BLOCKS = frozenset(
    {"required_providers", "backend", "cloud", "provider_meta"}
)
REQUIRED_ARGS: dict[str, tuple[str, ...]] = {
    "output": ("value",),
    "module": ("source",),
    "moved": ("from", "to"),
    "removed": ("from",),
    "import": ("to",),
}
# The second label of resource/data/ephemeral names it; the first is its type.
LABEL_KIND = {"type": "type name", "name": "name"}


def _error(summary: str, detail: str, location: SourceLocation | None) -> Finding:
    return make_finding(
        DiagnosticCode.TERRAFORM_SYNTAX_ERROR,
        Severity.error,
        f"{summary}: {detail}",
        location,
    )


def _suggest(name: str, options: frozenset[str] | list[str]) -> str:
    close = difflib.get_close_matches(name, sorted(options), n=1, cutoff=0.75)
    return f" Did you mean '{close[0]}'?" if close else ""


def validate_file(tf: TerraformFile) -> list[Finding]:
    return list(_validate(tf))


def _validate(tf: TerraformFile) -> Iterator[Finding]:
    for attribute in tf.attributes:
        yield _error(
            "Unsupported argument",
            f"an argument named '{attribute.name}' is not expected at the top level; "
            "arguments belong inside a block.",
            attribute.location,
        )
    yield from _duplicate_attributes(tf.attributes)

    default_providers: dict[str, SourceLocation | None] = {}
    locals_seen: dict[str, SourceLocation | None] = {}
    for block in tf.blocks:
        if block.type not in BLOCK_LABELS:
            yield _error(
                "Unsupported block type",
                f"blocks of type '{block.type}' are not expected here."
                + _suggest(block.type, frozenset(BLOCK_LABELS)),
                block.location,
            )
            continue
        expected = BLOCK_LABELS[block.type]
        if block.label_error is None and len(block.labels) != len(expected):
            if len(block.labels) < len(expected):
                missing = ", ".join(expected[len(block.labels) :])
                yield _error(
                    f"Missing {missing} for {block.type}",
                    f"all {block.type} blocks must have {len(expected)} label(s) "
                    f"({', '.join(expected)}).",
                    block.location,
                )
            else:
                yield _error(
                    f"Extraneous label for {block.type}",
                    f"{block.type} blocks take {len(expected) or 'no'} label(s), "
                    f"not {len(block.labels)}.",
                    block.location,
                )
            continue
        for label, kind in zip(block.labels, expected, strict=False):
            if not IDENTIFIER.match(label):
                yield _error(
                    f"Invalid {block.type} {LABEL_KIND.get(kind, kind)}",
                    f"'{label}' must start with a letter or underscore and contain only "
                    "letters, digits, underscores and dashes.",
                    block.location,
                )
        yield from _duplicate_attributes(block.attributes)
        for name in REQUIRED_ARGS.get(block.type, ()):
            if block.attribute(name) is None:
                yield _error(
                    "Missing required argument",
                    f"the argument '{name}' is required in a {block.type} block, but no "
                    "definition was found.",
                    block.location,
                )
        if block.type == "variable":
            yield from _variable(block)
        elif block.type == "output":
            for attribute in block.attributes:
                if attribute.name not in OUTPUT_ARGS:
                    yield _unsupported(attribute, "an output block", OUTPUT_ARGS)
        elif block.type in ("resource", "data", "ephemeral"):
            yield from _resource(block)
        elif block.type == "module":
            if block.attribute("count") and block.attribute("for_each"):
                yield _count_and_for_each(block)
            yield from _counted_context(block)
        elif block.type == "terraform":
            yield from _terraform(block)
        elif block.type == "provider":
            if block.attribute("alias") is None and block.labels:
                name = block.labels[0]
                if name in default_providers:
                    yield _error(
                        "Duplicate provider configuration",
                        f"a default (non-aliased) provider configuration for '{name}' was "
                        "already given. Add an alias to the second one.",
                        block.location,
                    )
                default_providers.setdefault(name, block.location)
        elif block.type == "locals":
            for attribute in block.attributes:
                if attribute.name in locals_seen:
                    yield _error(
                        "Duplicate local value definition",
                        f"a local value named '{attribute.name}' was already defined"
                        + (
                            f" on line {locals_seen[attribute.name].start_line}"  # type: ignore[union-attr]
                            if locals_seen[attribute.name]
                            else ""
                        )
                        + ". Local value names must be unique within a module.",
                        attribute.location,
                    )
                locals_seen.setdefault(attribute.name, attribute.location)


def _unsupported(attribute: Attribute, where: str, allowed: frozenset[str]) -> Finding:
    return _error(
        "Unsupported argument",
        f"an argument named '{attribute.name}' is not expected in {where}."
        + _suggest(attribute.name, allowed),
        attribute.location,
    )


def _duplicate_attributes(attributes: tuple[Attribute, ...]) -> Iterator[Finding]:
    seen: dict[str, Attribute] = {}
    for attribute in attributes:
        first = seen.get(attribute.name)
        if first is not None:
            line = first.location.start_line if first.location else None
            yield _error(
                "Attribute redefined",
                f"the argument '{attribute.name}' was already set"
                + (f" on line {line}" if line else "")
                + ". Each argument may be set only once.",
                attribute.location,
            )
        else:
            seen[attribute.name] = attribute


def _variable(block: Block) -> Iterator[Finding]:
    name = block.labels[0] if block.labels else ""
    if name in RESERVED_VARIABLE_NAMES:
        yield _error(
            "Invalid variable name",
            f"the variable name '{name}' is reserved due to its special meaning inside "
            "module blocks.",
            block.location,
        )
    for attribute in block.attributes:
        if attribute.name not in VARIABLE_ARGS:
            yield _unsupported(attribute, "a variable block", VARIABLE_ARGS)
    type_attr = block.attribute("type")
    if type_attr is not None:
        node = unwrap(type_attr.expr)
        if node.data == "string":
            yield _error(
                "Invalid quoted type constraints",
                "type constraints are keywords, not strings: write type = string, "
                'not type = "string".',
                type_attr.location,
            )
        elif node.data == "identifier":
            keyword = str(node.children[0].value)
            if keyword not in TYPE_KEYWORDS:
                yield _error(
                    "Invalid type specification",
                    f"the keyword '{keyword}' is not a valid type constraint."
                    + _suggest(keyword, TYPE_KEYWORDS),
                    type_attr.location,
                )
    for nested in block.blocks:
        if nested.type != "validation":
            yield _error(
                "Unsupported block type",
                f"blocks of type '{nested.type}' are not expected in a variable block.",
                nested.location,
            )
            continue
        for required in ("condition", "error_message"):
            if nested.attribute(required) is None:
                yield _error(
                    "Missing required argument",
                    f"a validation block needs '{required}'.",
                    nested.location,
                )


def _count_and_for_each(block: Block) -> Finding:
    attribute = block.attribute("for_each")
    return _error(
        'Invalid combination of "count" and "for_each"',
        "the count and for_each meta-arguments are mutually exclusive; only one may "
        "be used to be explicit about the number of instances.",
        attribute.location if attribute else block.location,
    )


def _resource(block: Block) -> Iterator[Finding]:
    if block.attribute("count") and block.attribute("for_each"):
        yield _count_and_for_each(block)
    allowed = LIFECYCLE_ARGS[block.type]
    for lifecycle in block.nested("lifecycle"):
        for attribute in lifecycle.attributes:
            if attribute.name not in allowed:
                yield _unsupported(
                    attribute, f"the lifecycle block of a {block.type}", allowed
                )
        for nested in lifecycle.blocks:
            if nested.type not in LIFECYCLE_BLOCKS:
                yield _error(
                    "Unsupported block type",
                    f"blocks of type '{nested.type}' are not expected in a lifecycle block.",
                    nested.location,
                )
    yield from _counted_context(block)


def _traversal_roots(tree: Tree) -> Iterator[tuple[str, Tree]]:
    """(root name, node) for every traversal such as count.index or each.key."""
    if tree.data == "get_attr_expr_term":
        first = subtrees(tree)[0]
        inner = (
            subtrees(first)[0]
            if first.data == "expr_term" and subtrees(first)
            else first
        )
        if inner.data == "identifier":
            yield str(inner.children[0].value), tree
    for child in subtrees(tree):
        yield from _traversal_roots(child)


def _counted_context(block: Block) -> Iterator[Finding]:
    """count.* needs count, each.* needs for_each (in the same block)."""
    has_count = block.attribute("count") is not None
    has_for_each = block.attribute("for_each") is not None
    reported: set[str] = set()

    def walk(container: Block) -> Iterator[Finding]:
        for attribute in container.attributes:
            if container is block and attribute.name in ("count", "for_each"):
                continue
            for root, _ in _traversal_roots(attribute.expr):
                if root == "count" and not has_count and "count" not in reported:
                    reported.add("count")
                    yield _error(
                        'Reference to "count" in non-counted context',
                        "count.index can only be used in blocks that set count.",
                        attribute.location,
                    )
                elif root == "each" and not has_for_each and "each" not in reported:
                    reported.add("each")
                    yield _error(
                        'Reference to "each" in context without for_each',
                        "each.key and each.value can only be used in blocks that set "
                        "for_each.",
                        attribute.location,
                    )
        for nested in container.blocks:
            # dynamic blocks have their own iterator; each.* there still refers
            # to the resource's for_each.
            yield from walk(nested)

    yield from walk(block)


def _terraform(block: Block) -> Iterator[Finding]:
    for attribute in block.attributes:
        if attribute.name not in TERRAFORM_ARGS:
            yield _unsupported(attribute, "the terraform block", TERRAFORM_ARGS)
    for nested in block.blocks:
        if nested.type not in TERRAFORM_BLOCKS:
            yield _error(
                "Unsupported block type",
                f"blocks of type '{nested.type}' are not expected in the terraform block."
                + _suggest(nested.type, TERRAFORM_BLOCKS),
                nested.location,
            )
