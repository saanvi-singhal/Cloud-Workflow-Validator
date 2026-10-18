"""Cycle detection: Tarjan's SCC algorithm plus DFS cycle-path reconstruction.

Why two algorithms (spec 5.2)?

* **Tarjan's strongly connected components (SCC)** partitions the graph in
  one O(V + E) pass into groups of nodes that can all reach each other. Any
  SCC with more than one node, or a single node with a self-loop, is a
  *cyclic region*. Tarjan finds **every** cyclic region at once, including
  several unrelated ones, but it only gives a *set* of nodes, not a path.
* **Depth-first search with a recursion stack** gives a *readable path*
  ``a -> b -> c -> a`` that a user can follow in their source. Running it
  restricted to one SCC at a time guarantees it finds a cycle in that SCC.

Combining them yields exactly **one DEPENDENCY_CYCLE diagnostic per cyclic
region**. Overlapping cycles (``a<->b`` and ``b<->c``) share one SCC, so they
aren't reported twice.

Both algorithms are written iteratively with explicit stacks (approved
decision D14). A recursive version is shorter but fails beyond Python's
default ~1000-frame recursion limit on long dependency chains.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from app.compiler.findings import EdgeKey, Finding, make_finding
from app.compiler.graph import DependencyGraph
from app.compiler.ir import IRGraph
from app.models import DiagnosticCode, Severity

# DFS colours used by find_cycle_path.
WHITE = 0  # not visited yet
GRAY = 1  # on the current DFS path (the "recursion stack")
BLACK = 2  # fully explored; no cycle goes through it from the current path


@dataclass(frozen=True)
class CycleReport:
    """Result of cycle detection.

    ``components[i]`` is a cyclic SCC (sorted node ids) and ``paths[i]`` is one
    closed cycle inside it, e.g. ``["a", "b", "a"]``.
    """

    components: list[list[str]]
    paths: list[list[str]]

    @property
    def has_cycles(self) -> bool:
        return bool(self.components)


def strongly_connected_components(graph: DependencyGraph) -> list[list[str]]:
    """Tarjan's algorithm. Returns every SCC (each sorted), ordered by first id.

    For every node Tarjan records:

    * ``index[n]``: the order in which DFS first discovered ``n``;
    * ``lowlink[n]``: the smallest index reachable from ``n``'s DFS subtree
      using at most one edge back to a node still on the SCC stack.

    When DFS finishes ``n`` and ``lowlink[n] == index[n]``, ``n`` is the root
    of an SCC: everything above it on the SCC stack belongs to that SCC.

    The iterative form keeps a ``work`` stack of ``(node, successor
    iterator)`` pairs. That stack plays the role of the call stack in the
    textbook recursive version.
    """
    index: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    scc_stack: list[str] = []
    on_scc_stack: set[str] = set()
    components: list[list[str]] = []
    next_index = 0

    def discover(node: str) -> Iterator[str]:
        nonlocal next_index
        index[node] = lowlink[node] = next_index
        next_index += 1
        scc_stack.append(node)
        on_scc_stack.add(node)
        return iter(graph.successors(node))

    for root in graph.nodes:  # sorted, so discovery order is deterministic
        if root in index:
            continue
        work: list[tuple[str, Iterator[str]]] = [(root, discover(root))]
        while work:
            node, successors = work[-1]
            descended = False
            for succ in successors:
                if succ not in index:
                    # Tree edge: "recurse" into succ.
                    work.append((succ, discover(succ)))
                    descended = True
                    break
                if succ in on_scc_stack:
                    # Edge back into the current SCC candidate.
                    lowlink[node] = min(lowlink[node], index[succ])
            if descended:
                continue

            # All successors of `node` are done: "return" from it.
            work.pop()
            if work:
                parent = work[-1][0]
                lowlink[parent] = min(lowlink[parent], lowlink[node])
            if lowlink[node] == index[node]:
                component: list[str] = []
                while True:
                    member = scc_stack.pop()
                    on_scc_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                components.append(sorted(component))

    return sorted(components, key=lambda c: c[0])


def is_cyclic_component(graph: DependencyGraph, component: Sequence[str]) -> bool:
    """An SCC is cyclic if it has 2+ nodes, or 1 node with a self-loop."""
    return len(component) > 1 or graph.has_self_loop(component[0])


def find_cycle_path(graph: DependencyGraph, component: Sequence[str]) -> list[str]:
    """Return one closed cycle ``[n0, n1, ..., n0]`` inside a cyclic SCC.

    Classic three-colour DFS, restricted to the SCC's nodes:

    * WHITE: unvisited;
    * GRAY: on the current path (the recursion stack);
    * BLACK: finished.

    Reaching a GRAY node means we followed an edge back onto our own path,
    which is a cycle. The cycle is the part of the path from that GRAY node
    to the current node, closed by repeating the GRAY node. DFS starts at
    the smallest id and visits successors in sorted order, so the path is
    deterministic. A self-loop ``a -> a`` gives ``["a", "a"]``.
    """
    members = set(component)
    if not members or not is_cyclic_component(graph, sorted(members)):
        raise ValueError("find_cycle_path needs a cyclic strongly connected component")

    color = dict.fromkeys(members, WHITE)
    start = min(members)
    path = [start]
    color[start] = GRAY
    successor_iters: list[Iterator[str]] = [iter(graph.successors(start))]

    while successor_iters:
        node = path[-1]
        for succ in successor_iters[-1]:
            if succ not in members:
                continue
            if color[succ] == GRAY:
                return path[path.index(succ) :] + [succ]
            if color[succ] == WHITE:
                color[succ] = GRAY
                path.append(succ)
                successor_iters.append(iter(graph.successors(succ)))
                break
        else:
            # No unexplored successor left: backtrack.
            color[node] = BLACK
            path.pop()
            successor_iters.pop()

    # Unreachable for a genuine SCC: every SCC with an edge contains a cycle.
    raise AssertionError("no cycle found in a cyclic component")


def detect_cycles(graph: DependencyGraph) -> CycleReport:
    """Find every cyclic region (Tarjan) and one readable path in each (DFS)."""
    cyclic = [
        c for c in strongly_connected_components(graph) if is_cyclic_component(graph, c)
    ]
    return CycleReport(
        components=cyclic, paths=[find_cycle_path(graph, c) for c in cyclic]
    )


def cycle_findings(
    report: CycleReport, ir: IRGraph, graph: DependencyGraph
) -> list[Finding]:
    """One DEPENDENCY_CYCLE error per cyclic component.

    The location is the declaration of the edge that closes the cycle. That
    edge is usually written in the dependent construct (e.g. a ``needs:`` or
    a Terraform reference), so it is where a user would edit. If the edge has
    no location, the dependent node's location is used instead.
    """
    nodes = ir.node_map()
    findings: list[Finding] = []
    for component, path in zip(report.components, report.paths, strict=True):
        edge_keys: list[EdgeKey] = []
        for source, target in zip(path, path[1:], strict=False):
            edge_keys.extend(e.key for e in graph.edges_between(source, target))

        closing = graph.edges_between(path[-2], path[-1])
        location = next(
            (e.source_location for e in closing if e.source_location is not None),
            None,
        )
        if location is None:
            location = nodes[path[-1]].source_location

        if len(path) == 2:
            message = f"Self-dependency: '{nodes[path[0]].label}' depends on itself."
        else:
            readable = " -> ".join(nodes[n].label for n in path)
            message = f"Dependency cycle: {readable}."
        extra = sorted(set(component) - set(path))
        if extra:
            others = ", ".join(nodes[n].label for n in extra)
            message += (
                f" The same cyclic region also contains {others}; "
                "breaking this cycle may not remove every cycle in it."
            )

        findings.append(
            make_finding(
                DiagnosticCode.DEPENDENCY_CYCLE,
                Severity.error,
                message,
                location,
                node_ids=tuple(component),
                edge_keys=tuple(edge_keys),
                details={"path": list(path), "component": list(component)},
            )
        )
    return findings
