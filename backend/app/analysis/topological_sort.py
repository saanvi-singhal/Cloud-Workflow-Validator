"""Deterministic topological ordering with Kahn's algorithm (spec 5.3).

Kahn's algorithm:

1. Count each node's in-degree (number of unmet prerequisites).
2. Every node with in-degree 0 is *ready*.
3. Repeatedly take a ready node, append it to the order, and "remove" its
   outgoing edges. A successor whose in-degree drops to 0 becomes ready.

When several nodes are ready at the same time, any choice is valid. To make
the output identical for identical input we always take the
**lexicographically smallest node id**, using a min-heap (``heapq``).

If the graph has a cycle, the nodes on it never reach in-degree 0, so fewer
than V nodes are emitted. We then return ``None`` rather than a partial order
that might look complete.
"""

from __future__ import annotations

import heapq

from app.compiler.graph import DependencyGraph


def topological_order(graph: DependencyGraph) -> list[str] | None:
    """Return all node ids in dependency order, or ``None`` if the graph is cyclic."""
    in_degree = {node: len(graph.predecessors(node)) for node in graph.nodes}
    ready = [node for node in graph.nodes if in_degree[node] == 0]
    heapq.heapify(ready)

    order: list[str] = []
    while ready:
        node = heapq.heappop(ready)
        order.append(node)
        for succ in graph.successors(node):
            in_degree[succ] -= 1
            if in_degree[succ] == 0:
                heapq.heappush(ready, succ)

    if len(order) != len(graph.nodes):
        return None
    return order
