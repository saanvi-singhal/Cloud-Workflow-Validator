"""Turn the python-hcl2 parse tree into simple block/attribute records.

The Lark tree has many layers of wrapper nodes. This module keeps only what
the extractor and the rules need:

* ``Block``: block type (``resource``), labels (``aws_vpc``, ``main``), its
  attributes, nested blocks and source span;
* ``Attribute``: name, the raw expression subtree and source span.

Expressions are *not* interpreted here. ``references.py`` does that, and
``literal_value`` below only recognises plain literal values for the rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models import SourceLocation
from app.parsers.terraform.hcl_loader import Token, Tree


@dataclass(frozen=True)
class Attribute:
    name: str
    expr: Tree
    location: SourceLocation | None


@dataclass(frozen=True)
class Block:
    type: str
    labels: tuple[str, ...]
    attributes: tuple[Attribute, ...]
    blocks: tuple[Block, ...]
    location: SourceLocation | None
    label_error: str | None = None  # set when a label is not a plain string

    def attribute(self, name: str) -> Attribute | None:
        return next((a for a in self.attributes if a.name == name), None)

    def nested(self, block_type: str) -> list[Block]:
        return [b for b in self.blocks if b.type == block_type]


@dataclass(frozen=True)
class TerraformFile:
    """Top level of one ``.tf`` file."""

    attributes: tuple[Attribute, ...]
    blocks: tuple[Block, ...]


def span(tree: Tree, filename: str | None) -> SourceLocation | None:
    """Source span of ``tree`` from Lark metadata, or ``None`` if unavailable."""
    meta = tree.meta
    if meta.empty:
        return None
    return SourceLocation(
        file=filename,
        start_line=meta.line,
        start_column=meta.column,
        end_line=meta.end_line,
        end_column=meta.end_column,
    )


# Layout-only subtrees (newlines and comments) carry no meaning.
LAYOUT_NODES = frozenset({"new_line_or_comment"})


def subtrees(tree: Tree) -> list[Tree]:
    """Child subtrees, skipping newline/comment layout nodes."""
    return [
        c for c in tree.children if isinstance(c, Tree) and c.data not in LAYOUT_NODES
    ]


def _name_of(tree: Tree) -> str:
    """Text of an ``identifier``/``keyword`` node (e.g. ``vpc_id``, ``for_each``)."""
    token = next(c for c in tree.children if isinstance(c, Token))
    return str(token.value)


def plain_string(tree: Tree) -> str | None:
    """Value of a quoted string without interpolations, else ``None``."""
    if tree.data != "string":
        return None
    parts: list[str] = []
    for part in subtrees(tree):
        if part.data != "string_part":
            return None
        for child in part.children:
            if isinstance(child, Token) and child.type == "STRING_CHARS":
                parts.append(str(child.value))
            else:
                return None  # interpolation or template directive
    return "".join(parts)


def _read_block(tree: Tree, filename: str | None) -> Block:
    children = subtrees(tree)
    block_type = _name_of(children[0])
    labels: list[str] = []
    label_error: str | None = None
    body: Tree | None = None
    for child in children[1:]:
        if child.data == "body":
            body = child
        elif child.data == "identifier":
            labels.append(_name_of(child))
        else:
            value = plain_string(child)
            if value is None:
                label_error = "block label is not a plain string"
            else:
                labels.append(value)
    attributes, blocks = _read_body(body, filename) if body is not None else ((), ())
    return Block(
        type=block_type,
        labels=tuple(labels),
        attributes=attributes,
        blocks=blocks,
        location=span(tree, filename),
        label_error=label_error,
    )


def _read_body(
    body: Tree, filename: str | None
) -> tuple[tuple[Attribute, ...], tuple[Block, ...]]:
    attributes: list[Attribute] = []
    blocks: list[Block] = []
    for child in subtrees(body):
        if child.data == "attribute":
            name_node, expr = subtrees(child)
            attributes.append(
                Attribute(_name_of(name_node), expr, span(child, filename))
            )
        elif child.data == "block":
            blocks.append(_read_block(child, filename))
    return tuple(attributes), tuple(blocks)


def read_file(tree: Tree, filename: str | None) -> TerraformFile:
    """Read the top level of a parsed file (``start -> body``)."""
    body = next(c for c in subtrees(tree) if c.data == "body")
    attributes, blocks = _read_body(body, filename)
    return TerraformFile(attributes=attributes, blocks=blocks)


class _NotLiteral:
    def __repr__(self) -> str:
        return "NOT_LITERAL"


NOT_LITERAL: Any = _NotLiteral()


def unwrap(expr: Tree) -> Tree:
    """Skip ``expr_term`` wrappers that hold exactly one subtree (no parens)."""
    while expr.data == "expr_term" and len(expr.children) == 1 and subtrees(expr):
        expr = subtrees(expr)[0]
    return expr


def literal_value(expr: Tree) -> Any:
    """Python value of a *literal* expression, else ``NOT_LITERAL``.

    Supports strings without interpolation, numbers, ``true``/``false``/
    ``null``, and tuples/objects made only of literals. Anything involving a
    reference, function call or operator is not a literal. Rules must then
    stay silent rather than guess.
    """
    node = unwrap(expr)
    kind = node.data
    if kind == "string":
        value = plain_string(node)
        return NOT_LITERAL if value is None else value
    if kind in ("int_lit", "float_lit"):
        text = str(node.children[0].value)
        try:
            return int(text) if kind == "int_lit" else float(text)
        except ValueError:
            return NOT_LITERAL
    if kind == "literal_value":
        return {"TRUE": True, "FALSE": False, "NULL": None}.get(
            node.children[0].type, NOT_LITERAL
        )
    if kind == "tuple":
        items = [literal_value(item) for item in subtrees(node)]
        return NOT_LITERAL if any(i is NOT_LITERAL for i in items) else items
    if kind == "object":
        result: dict[str, Any] = {}
        for elem in subtrees(node):
            key_node, value_node = subtrees(elem)
            key = object_key_name(key_node)
            value = literal_value(value_node)
            if key is None or value is NOT_LITERAL:
                return NOT_LITERAL
            result[key] = value
        return result
    return NOT_LITERAL


def object_key_name(key_node: Tree) -> str | None:
    """Name of an object key written as a bare word or plain string, else None."""
    inner = unwrap(subtrees(key_node)[0]) if subtrees(key_node) else key_node
    if inner.data == "identifier":
        return _name_of(inner)
    return plain_string(inner)
