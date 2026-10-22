"""Shared intermediate representation (IR) and deterministic helpers.

Every parser converts its format-specific parse result into an ``IRGraph``
built from the public ``Node``/``Edge`` models. This module also owns:

* the stable node-ID scheme (``make_node_id`` / ``unique_id``), and
* the canonical sort orders that make output deterministic (spec 5.6).
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

from app.compiler.findings import Finding
from app.models import Diagnostic, Edge, GraphPayload, Node, Severity, SourceFormat

ID_SEPARATOR = ":"
COLLISION_MARKER = "#"

# Short, stable ID prefixes per format.
FORMAT_ID_PREFIX: dict[SourceFormat, str] = {
    SourceFormat.yaml: "gha",
    SourceFormat.dockerfile: "docker",
    SourceFormat.terraform: "tf",
}

_SEVERITY_RANK = {Severity.error: 0, Severity.warning: 1, Severity.info: 2}


def make_node_id(prefix: str, kind: str, *parts: str) -> str:
    """Build a readable, deterministic node ID such as ``tf:resource:aws_vpc.main``.

    ``prefix`` names the format, ``kind`` the construct, and ``parts`` the
    construct's own identity (joined with ``.``). No randomness or hashing is
    involved, so identical source always yields identical IDs.
    """
    if not prefix or not kind or not parts or not all(parts):
        raise ValueError("make_node_id needs a prefix, a kind and non-empty parts")
    return ID_SEPARATOR.join([prefix, kind, ".".join(parts)])


def unique_id(base: str, taken: set[str]) -> str:
    """Return ``base`` or the first free ``base#2``, ``base#3``, ... and reserve it.

    Callers process constructs in source order, so the suffix assignment is
    deterministic. The parser is responsible for also emitting a
    ``DUPLICATE_NODE_ID`` diagnostic when the *source* declares a duplicate.
    """
    candidate = base
    counter = 2
    while candidate in taken:
        candidate = f"{base}{COLLISION_MARKER}{counter}"
        counter += 1
    taken.add(candidate)
    return candidate


def scope_node_id(node_id: str, filename: str) -> str:
    """Prefix a node ID's identity with its file, for multi-file analysis.

    ``gha:job:build`` in ``release.yml`` becomes ``gha:job:release.yml:build``.
    Used only when several *independent* files (workflows, Dockerfiles) are
    analysed together, so that equal names in different files stay distinct.
    Single-file IDs are never scoped.
    """
    prefix, kind, rest = node_id.split(ID_SEPARATOR, 2)
    return ID_SEPARATOR.join([prefix, kind, filename, rest])


class IRGraph(BaseModel):
    """The normalized graph for one source file."""

    model_config = ConfigDict(extra="forbid")

    format: SourceFormat
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)

    def canonical(self) -> IRGraph:
        """Return a copy with nodes sorted by id and edges by (source, target, type).

        Python's sort is stable, so edges sharing a key keep their source order.
        """
        return IRGraph(
            format=self.format,
            nodes=sorted(self.nodes, key=lambda n: n.id),
            edges=sorted(self.edges, key=lambda e: e.key),
        )

    def node_map(self) -> dict[str, Node]:
        """Map id -> node (first occurrence wins if ids are duplicated)."""
        result: dict[str, Node] = {}
        for node in self.nodes:
            result.setdefault(node.id, node)
        return result

    def to_payload(self) -> GraphPayload:
        """Public ``{"nodes": [...], "edges": [...]}`` in canonical order."""
        canonical = self.canonical()
        return GraphPayload(nodes=canonical.nodes, edges=canonical.edges)


def _diagnostic_sort_key(d: Diagnostic) -> tuple:
    """Location first (useful for source navigation), then severity, code, text.

    Diagnostics without any location sort after all located ones.
    """
    loc = d.source_location
    unlocated = loc is None
    file = (loc.file if loc else None) or ""
    line = loc.start_line if loc and loc.start_line is not None else math.inf
    column = loc.start_column if loc and loc.start_column is not None else math.inf
    return (
        unlocated,
        file,
        line,
        column,
        _SEVERITY_RANK[d.severity],
        d.code.value,
        d.message,
    )


def sort_diagnostics(diagnostics: Iterable[Diagnostic]) -> list[Diagnostic]:
    """Deterministically order diagnostics (approved decision D16)."""
    return sorted(diagnostics, key=_diagnostic_sort_key)


def sort_findings(findings: Iterable[Finding]) -> list[Finding]:
    """Order findings with the same key as their diagnostics.

    Ties on the full key keep their insertion order (stable sort), and every
    pass emits findings in a deterministic order, so the result is stable.
    """
    return sorted(findings, key=lambda f: _diagnostic_sort_key(f.diagnostic))
