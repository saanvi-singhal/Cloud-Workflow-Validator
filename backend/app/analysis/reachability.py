"""Connectivity and reachability analysis (spec 5.4, 5.5).

Two separate questions:

* **Disconnected components:** ignoring edge direction, does the graph fall
  apart into separate pieces? This is computed with BFS over weakly connected
  components. It is a *warning/info*, never an error, and the format policy
  decides whether it is reported at all.
* **Reachability:** only when the format defines a root (e.g. the final
  Dockerfile stage) do we ask which nodes the root actually needs. We never
  invent a universal root.

Direction reminder: an edge ``A -> B`` means A is a prerequisite of B. The
prerequisites of a root are therefore its **ancestors** (nodes with a path
*into* the root).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable

from app.compiler.findings import Finding, make_finding
from app.compiler.graph import DependencyGraph
from app.compiler.ir import IRGraph
from app.compiler.policy import FormatPolicy
from app.models import DiagnosticCode, Severity


def _bfs(starts: Iterable[str], neighbours: Callable[[str], Iterable[str]]) -> set[str]:
    """Nodes reachable from ``starts`` in one or more steps.

    A start node is only included if it is reached again (i.e. via a cycle).
    """
    seen: set[str] = set()
    queue = deque(sorted(set(starts)))
    while queue:
        node = queue.popleft()
        for nxt in neighbours(node):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def ancestors(graph: DependencyGraph, targets: Iterable[str]) -> set[str]:
    """All nodes with a path into some target (the target's prerequisites)."""
    return _bfs(targets, graph.predecessors)


def descendants(graph: DependencyGraph, sources: Iterable[str]) -> set[str]:
    """All nodes reachable from some source (everything that depends on it)."""
    return _bfs(sources, graph.successors)


def weakly_connected_components(graph: DependencyGraph) -> list[list[str]]:
    """Components when edge direction is ignored.

    Sorted largest first, ties broken by smallest node id, so ``result[0]`` is
    the deterministic "main" component. Each component is a sorted list.
    """
    seen: set[str] = set()
    components: list[list[str]] = []
    for start in graph.nodes:
        if start in seen:
            continue
        seen.add(start)
        component = [start]
        queue = deque([start])
        while queue:
            node = queue.popleft()
            for nxt in (*graph.successors(node), *graph.predecessors(node)):
                if nxt not in seen:
                    seen.add(nxt)
                    component.append(nxt)
                    queue.append(nxt)
        components.append(sorted(component))
    return sorted(components, key=lambda c: (-len(c), c[0]))


def component_findings(
    graph: DependencyGraph, ir: IRGraph, policy: FormatPolicy
) -> list[Finding]:
    """DISCONNECTED_COMPONENT for each component other than the main one.

    Isolated single nodes are skipped unless the policy asks for them; this
    is the "isolated node vs. non-trivial component" distinction of spec 5.4.
    """
    if policy.disconnected_severity is None:
        return []
    components = weakly_connected_components(graph)
    if len(components) <= 1:
        return []

    nodes = ir.node_map()
    main = components[0]
    findings: list[Finding] = []
    for component in components[1:]:
        if len(component) == 1 and not policy.report_isolated_nodes:
            continue
        labels = ", ".join(nodes[n].label for n in component)
        if len(component) == 1:
            reason = f"'{labels}' has no dependencies and nothing depends on it"
        else:
            reason = (
                f"{len(component)} nodes ({labels}) form a dependency chain "
                "with no connection"
            )
        findings.append(
            make_finding(
                DiagnosticCode.DISCONNECTED_COMPONENT,
                policy.disconnected_severity,
                f"{reason} to the main dependency graph ({len(main)} nodes). "
                "This can be intentional; check that no dependency is missing.",
                nodes[component[0]].source_location,
                node_ids=tuple(component),
            )
        )
    return findings


def reachability_findings(
    graph: DependencyGraph, ir: IRGraph, policy: FormatPolicy
) -> list[Finding]:
    """UNREACHABLE_NODE for nodes the format's root does not need.

    Returns nothing when the policy defines no root, or the root selector finds
    none in this graph: no root is ever invented (spec 5.5).
    """
    if policy.roots is None:
        return []
    known = set(graph.nodes)
    roots = [r for r in policy.roots(ir) if r in known]
    if not roots:
        return []

    nodes = ir.node_map()
    needed = set(roots) | ancestors(graph, roots)
    root_labels = ", ".join(f"'{nodes[r].label}'" for r in roots)
    findings: list[Finding] = []
    for node_id in graph.nodes:
        if node_id in needed:
            continue
        findings.append(
            make_finding(
                DiagnosticCode.UNREACHABLE_NODE,
                Severity.warning,
                f"'{nodes[node_id].label}' is not needed by "
                f"{policy.root_description} ({root_labels}). "
                f"{policy.unreachable_reason}".strip(),
                nodes[node_id].source_location,
                node_ids=(node_id,),
                details={"roots": roots},
            )
        )
    return findings
