"""Adapter boundary to python-hcl2: the only module that imports parser libraries.

We use ``hcl2.parses_to_tree`` (the Lark parse tree) rather than
``hcl2.loads`` (a dict). The dict form turns every expression into an opaque
string such as ``"${aws_vpc.main.id}"`` and drops source positions, so
dependency analysis would have to regex-scan strings, which the spec forbids.
The parse tree is fully structural (``get_attr_expr_term``, ``conditional``,
``function_call``...) and every subtree carries 1-based line/column metadata
with an exclusive end column.

Verified against python-hcl2 8.1.4 / lark 1.3.1. The rest of the Terraform
package depends on the 8.x grammar's rule names, which is why the dependency
is pinned to ``python-hcl2>=8.1,<9``.
"""

from __future__ import annotations

from dataclasses import dataclass

import hcl2
from lark import Token, Tree
from lark.exceptions import (
    LarkError,
    UnexpectedCharacters,
    UnexpectedEOF,
    UnexpectedInput,
    UnexpectedToken,
)

__all__ = ["HclSyntaxError", "Token", "Tree", "parse_hcl"]


@dataclass(frozen=True)
class HclSyntaxError(Exception):
    """A syntax error with the parser's (1-based) position when known."""

    message: str
    line: int | None = None
    column: int | None = None

    def __str__(self) -> str:
        return self.message


def parse_hcl(source: str) -> Tree:
    """Parse HCL text into a Lark tree, or raise ``HclSyntaxError``.

    The source is only parsed, never evaluated or executed.
    """
    try:
        return hcl2.parses_to_tree(source)
    except UnexpectedInput as exc:
        line = exc.line if isinstance(exc.line, int) and exc.line >= 1 else None
        column = exc.column if isinstance(exc.column, int) and exc.column >= 1 else None
        raise HclSyntaxError(_describe(exc), line, column) from exc
    except LarkError as exc:
        raise HclSyntaxError("invalid HCL syntax") from exc


def _describe(exc: UnexpectedInput) -> str:
    """User-facing description of a Lark error, without grammar internals."""
    if isinstance(exc, UnexpectedEOF):
        return "unexpected end of file"
    if isinstance(exc, UnexpectedToken):
        if exc.token.type == "$END":
            return "unexpected end of file"
        text = str(exc.token.value)
        shown = text if len(text) <= 20 else text[:20] + "…"
        return f"unexpected input {shown!r}"
    if isinstance(exc, UnexpectedCharacters):
        return f"unexpected character {exc.char!r}"
    return "invalid HCL syntax"
