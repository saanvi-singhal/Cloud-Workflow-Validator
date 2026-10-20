"""Structural extraction of Terraform references from HCL expression trees.

A Terraform reference is a *traversal*: a root name followed by attribute
and index steps, e.g. ``aws_subnet.a[0].id`` is::

    root "aws_subnet"  ->  .a  ->  [0]  ->  .id

In the python-hcl2 tree this is a nest of ``get_attr_expr_term`` /
``index_expr_term`` / splat nodes around an ``identifier``. ``flatten``
unwinds that nest. ``resolve`` then maps the root to what it refers to:

=================  ==========================  ======================
written as         refers to                   address
=================  ==========================  ======================
``TYPE.NAME...``   resource                    ``TYPE.NAME``
``data.T.N...``    data source                 ``data.T.N``
``module.N...``    module                      ``module.N``
``var.N``          variable                    ``var.N``
``local.N``        (unsupported in v1, D6)     -
``count/each/self/path/terraform.*``  meta-values, not dependencies
iterator name      current ``dynamic`` item    - (scoped, see below)
=================  ==========================  ======================

Inside ``dynamic "ingress" { content { ... } }``, ``ingress.value`` and
``ingress.key`` name the current element of ``for_each`` (or the name set by
``iterator = ...``). The extractor passes such names as ``scoped`` roots, which
are not dependencies.

Indexes and splats do not change the target: ``aws_subnet.a[0].id`` depends
on the whole ``aws_subnet.a`` resource, as in Terraform itself.

The walker is **conservative**. Every expression form is listed explicitly.
Anything it doesn't know (``for`` expressions, template directives, heredocs
with interpolation, or a new grammar rule) becomes an ``Unsupported`` record
instead of being guessed at or silently ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.models import SourceLocation
from app.parsers.terraform.blocks import object_key_name, span, subtrees, unwrap
from app.parsers.terraform.hcl_loader import Token, Tree

RefKind = Literal["resource", "data", "module", "variable"]

# Roots that name Terraform meta-values rather than other blocks.
META_ROOTS = frozenset({"count", "each", "self", "path", "terraform"})

_CHAIN_NODES = frozenset(
    {
        "get_attr_expr_term",
        "index_expr_term",
        "full_splat_expr_term",
        "attr_splat_expr_term",
    }
)
_LITERALS = frozenset({"int_lit", "float_lit", "literal_value"})
# Forms whose children are walked as ordinary sub-expressions.
_CONTAINERS = frozenset(
    {
        "expr_term",
        "conditional",
        "binary_op",
        "binary_term",
        "unary_op",
        "tuple",
        "arguments",
        "string",
        "string_part",
        "interpolation",
    }
)
_IGNORED = frozenset({"binary_operator", "new_line_or_comment"})
_TEMPLATE_DIRECTIVES = frozenset(
    {
        "template_if_start",
        "template_else",
        "template_endif",
        "template_for_start",
        "template_endfor",
    }
)
_HEREDOCS = frozenset({"heredoc_template", "heredoc_template_trim"})
_FOR_EXPRESSIONS = frozenset({"for_tuple_expr", "for_object_expr"})


@dataclass(frozen=True)
class Reference:
    """A resolved reference to another block."""

    kind: RefKind
    address: str  # e.g. "aws_vpc.main", "data.aws_ami.u", "module.net", "var.env"
    text: str  # how it was written, normalised: "aws_subnet.a[…].id"
    location: SourceLocation | None


@dataclass(frozen=True)
class Unsupported:
    """An expression form we refuse to interpret."""

    construct: str
    reason: str
    location: SourceLocation | None


@dataclass
class ExpressionAnalysis:
    references: list[Reference] = field(default_factory=list)
    unsupported: list[Unsupported] = field(default_factory=list)


@dataclass(frozen=True)
class Traversal:
    """A flattened ``root.attr[...]`` chain."""

    root: str
    steps: tuple[str | None, ...]  # attribute name, or None for an index/splat
    index_exprs: tuple[Tree, ...]  # expressions inside [...] (walked separately)

    @property
    def leading_attrs(self) -> list[str]:
        """Attribute names directly after the root, up to the first index."""
        names: list[str] = []
        for step in self.steps:
            if step is None:
                break
            names.append(step)
        return names

    @property
    def text(self) -> str:
        return self.root + "".join(
            f".{s}" if s is not None else "[…]" for s in self.steps
        )


def _identifier_name(tree: Tree) -> str | None:
    if tree.data not in ("identifier", "keyword"):
        return None
    token = next((c for c in tree.children if isinstance(c, Token)), None)
    return None if token is None else str(token.value)


def _get_attr_name(get_attr: Tree) -> str | None:
    for child in subtrees(get_attr):
        name = _identifier_name(child)
        if name is not None:
            return name
    return None


def flatten(expr: Tree) -> tuple[Traversal | None, Tree | None, list[Tree]]:
    """Unwind a traversal chain.

    Returns ``(traversal, base, index_exprs)``. If the innermost expression is
    a plain identifier, ``traversal`` is set. Otherwise (e.g. ``func(x).id``)
    ``traversal`` is ``None`` and ``base`` is that innermost expression,
    which the caller should walk as an ordinary expression.
    """
    node = unwrap(expr)
    steps: list[str | None] = []
    index_exprs: list[Tree] = []
    while True:
        name = _identifier_name(node)
        if name is not None:
            steps.reverse()
            index_exprs.reverse()
            return Traversal(name, tuple(steps), tuple(index_exprs)), None, index_exprs
        if node.data not in _CHAIN_NODES:
            return None, node, index_exprs
        inner, step = subtrees(node)[0], subtrees(node)[1]
        if node.data == "get_attr_expr_term":
            steps.append(_get_attr_name(step))
        else:
            # Index or splat: the target block is unchanged; keep any
            # expressions used inside brackets so their references count.
            steps.append(None)
            brackets = [step] if step.data == "braces_index" else subtrees(step)
            for part in brackets:
                if part.data == "braces_index":
                    index_exprs.extend(subtrees(part))
        node = unwrap(inner)


def resolve(
    trav: Traversal, scoped: frozenset[str] = frozenset()
) -> tuple[RefKind, str] | str | None:
    """Map a traversal to ``(kind, address)``.

    Returns ``None`` for meta-values and ``scoped`` iterator names, and a
    string describing the problem when the reference can't be resolved safely.
    """
    attrs = trav.leading_attrs
    if trav.root in META_ROOTS or trav.root in scoped:
        return None
    if trav.root == "local":
        return "references to locals are not analysed in v1"
    if trav.root == "var":
        return (
            ("variable", f"var.{attrs[0]}") if attrs else "incomplete 'var' reference"
        )
    if trav.root == "data":
        if len(attrs) >= 2:
            return "data", f"data.{attrs[0]}.{attrs[1]}"
        return "incomplete data-source reference"
    if trav.root == "module":
        return (
            ("module", f"module.{attrs[0]}") if attrs else "incomplete module reference"
        )
    if attrs:
        return "resource", f"{trav.root}.{attrs[0]}"
    return f"bare name '{trav.root}' is not a Terraform reference"


class _Walker:
    def __init__(self, filename: str | None, scoped: frozenset[str]) -> None:
        self.filename = filename
        self.scoped = scoped
        self.result = ExpressionAnalysis()

    def unsupported(self, tree: Tree, construct: str, reason: str) -> None:
        self.result.unsupported.append(
            Unsupported(construct, reason, span(tree, self.filename))
        )

    def walk(self, node: Tree | Token) -> None:
        if isinstance(node, Token):
            return  # punctuation, literal characters
        kind = node.data
        if kind in _CHAIN_NODES or kind in ("identifier", "keyword"):
            self.walk_traversal(node)
        elif kind in _LITERALS or kind in _IGNORED:
            return
        elif kind in _CONTAINERS:
            for child in node.children:
                self.walk(child)
        elif kind == "function_call":
            for child in subtrees(node):
                if child.data == "arguments":
                    self.walk(child)
        elif kind == "object":
            for elem in subtrees(node):
                key, value = subtrees(elem)
                if object_key_name(key) is None:
                    for part in subtrees(key):  # computed key like (var.k)
                        self.walk(part)
                self.walk(value)
        elif kind in _FOR_EXPRESSIONS:
            self.unsupported(node, "for expression", "iterator scoping")
        elif kind in _TEMPLATE_DIRECTIVES:
            self.unsupported(node, "template directive", "%{...} directives")
        elif kind in _HEREDOCS:
            text = "".join(str(t.value) for t in node.children if isinstance(t, Token))
            if "${" in text or "%{" in text:
                self.unsupported(node, "heredoc template", "interpolation in heredoc")
        else:
            self.unsupported(node, kind, "unrecognised expression form")

    def walk_traversal(self, node: Tree) -> None:
        trav, base, index_exprs = flatten(node)
        if trav is None:
            if base is not None:
                self.walk(base)
        else:
            resolved = resolve(trav, self.scoped)
            if isinstance(resolved, str):
                self.unsupported(node, trav.text, resolved)
            elif resolved is not None:
                ref_kind, address = resolved
                self.result.references.append(
                    Reference(ref_kind, address, trav.text, span(node, self.filename))
                )
        for index_expr in index_exprs:
            self.walk(index_expr)


def analyze_expression(
    expr: Tree, filename: str | None, scoped: frozenset[str] = frozenset()
) -> ExpressionAnalysis:
    """All references and unsupported forms inside one expression.

    ``scoped`` holds ``dynamic`` iterator names visible here; they are not
    references to other blocks.
    """
    walker = _Walker(filename, scoped)
    walker.walk(expr)
    return walker.result


def iterator_name(expr: Tree) -> str | None:
    """The name in ``iterator = NAME``, or None if it is not a plain name."""
    trav, _, _ = flatten(expr)
    if trav is None or trav.steps:
        return None
    return trav.root


def explicit_dependencies(expr: Tree, filename: str | None) -> ExpressionAnalysis:
    """Analyse a ``depends_on = [...]`` list.

    Each item must be a bare reference to a whole resource, data source or
    module (``aws_vpc.main``, ``data.x.y``, ``module.m``). Anything else is
    reported as unsupported rather than guessed at.
    """
    result = ExpressionAnalysis()
    node = unwrap(expr)
    if node.data != "tuple":
        result.unsupported.append(
            Unsupported("depends_on", "must be a list", span(node, filename))
        )
        return result
    for item in subtrees(node):
        trav, _, _ = flatten(item)
        location = span(item, filename)
        resolved = resolve(trav) if trav is not None else "not a reference"
        if not isinstance(resolved, tuple) or resolved[0] == "variable":
            reason = resolved if isinstance(resolved, str) else "not a block"
            result.unsupported.append(
                Unsupported("depends_on item", str(reason), location)
            )
            continue
        kind, address = resolved
        expected_len = {"resource": 1, "data": 2, "module": 1}[kind]
        if trav is None or len(trav.steps) != expected_len:
            result.unsupported.append(
                Unsupported(
                    "depends_on item",
                    "must name a whole block, without attributes or indexes",
                    location,
                )
            )
            continue
        result.references.append(Reference(kind, address, trav.text, location))
    return result
