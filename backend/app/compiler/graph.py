"""Adjacency-list view of an ``IRGraph`` used by the graph algorithms.

The IR is a flat list of nodes and edges, which is convenient for parsers and
serialization but slow to query. ``DependencyGraph`` indexes it once:

* ``successors(n)``   -> nodes that depend on ``n``   (edges ``n -> x``)
* ``predecessors(n)`` -> prerequisites of ``n``       (edges ``x -> n``)

All tuples are sorted and de-duplicated, so every algorithm that iterates over
them is deterministic regardless of the order the parser produced edges in.

It must be built from an IR that already passed ``validate_graph`` (unique
node ids, every edge endpoint exists).
"""

from __future__ import annotations

from collections import defaultdict

from app.compiler.ir import IRGraph
from app.models import Edge


class DependencyGraph:
    """Immutable, sorted adjacency index over validated IR."""

    def __init__(self, node_ids: list[str], edges: list[Edge]) -> None:
        known = set(node_ids)
        succ: dict[str, set[str]] = defaultdict(set)
        pred: dict[str, set[str]] = defaultdict(set)
        between: dict[tuple[str, str], list[Edge]] = defaultdict(list)
        for edge in sorted(edges, key=lambda e: e.key):
            if edge.source not in known or edge.target not in known:
                raise ValueError(
                    f"edge {edge.source} -> {edge.target} has an unknown endpoint; "
                    "run validate_graph first"
                )
            succ[edge.source].add(edge.target)
            pred[edge.target].add(edge.source)
            between[(edge.source, edge.target)].append(edge)

        self.nodes: tuple[str, ...] = tuple(sorted(known))
        self._succ = {n: tuple(sorted(succ[n])) for n in self.nodes}
        self._pred = {n: tuple(sorted(pred[n])) for n in self.nodes}
        self._between = dict(between)

    @classmethod
    def from_ir(cls, ir: IRGraph) -> DependencyGraph:
        return cls([n.id for n in ir.nodes], ir.edges)

    def successors(self, node: str) -> tuple[str, ...]:
        return self._succ[node]

    def predecessors(self, node: str) -> tuple[str, ...]:
        return self._pred[node]

    def has_self_loop(self, node: str) -> bool:
        return node in self._succ[node]

    def edges_between(self, source: str, target: str) -> list[Edge]:
        """All IR edges ``source -> target`` (several types may coexist)."""
        return list(self._between.get((source, target), []))

    def __len__(self) -> int:
        return len(self.nodes)
