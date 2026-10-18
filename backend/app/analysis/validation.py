"""Graph integrity validation, run before any graph algorithm (spec 5.1).

Checks, in this order:

1. **Unique node IDs**: a repeated id is reported as ``DUPLICATE_NODE_ID``;
   the first occurrence is kept so analysis can continue.
2. **Edge endpoints exist**: an edge pointing at an unknown node is an
   internal inconsistency (parsers must report unknown user references as
   ``UNRESOLVED_DEPENDENCY`` *instead of* creating such an edge), so it is
   reported as ``INVALID_GRAPH`` and dropped.
3. **Edge type is allowed for the format**: e.g. a ``docker_stage_base`` edge
   in a Terraform graph is reported as ``INVALID_GRAPH`` and dropped.

The function never raises for bad input; it returns a cleaned IR that the
algorithms can trust, plus findings describing what was removed.
"""

from __future__ import annotations

from app.compiler.findings import Finding, make_finding
from app.compiler.ir import IRGraph
from app.models import DiagnosticCode, Edge, EdgeType, Node, Severity, SourceFormat

ALLOWED_EDGE_TYPES: dict[SourceFormat, frozenset[EdgeType]] = {
    SourceFormat.yaml: frozenset({EdgeType.workflow_dependency}),
    SourceFormat.dockerfile: frozenset(
        {EdgeType.docker_stage_base, EdgeType.docker_instruction_order}
    ),
    SourceFormat.terraform: frozenset(
        {EdgeType.terraform_reference, EdgeType.terraform_explicit_dependency}
    ),
}


def validate_graph(ir: IRGraph) -> tuple[IRGraph, list[Finding]]:
    """Return ``(clean_ir, findings)``; ``clean_ir`` satisfies all invariants."""
    findings: list[Finding] = []

    kept_nodes: list[Node] = []
    seen_ids: set[str] = set()
    for node in ir.nodes:
        if node.id in seen_ids:
            findings.append(
                make_finding(
                    DiagnosticCode.DUPLICATE_NODE_ID,
                    Severity.error,
                    f"Duplicate node id '{node.id}' ('{node.label}'); "
                    "only the first declaration is analysed.",
                    node.source_location,
                    node_ids=(node.id,),
                )
            )
            continue
        seen_ids.add(node.id)
        kept_nodes.append(node)

    allowed = ALLOWED_EDGE_TYPES[ir.format]
    kept_edges: list[Edge] = []
    for edge in ir.edges:
        missing = [e for e in (edge.source, edge.target) if e not in seen_ids]
        if missing:
            findings.append(
                make_finding(
                    DiagnosticCode.INVALID_GRAPH,
                    Severity.error,
                    f"Edge {edge.source} -> {edge.target} ({edge.type.value}) refers "
                    f"to unknown node(s) {', '.join(missing)}; edge ignored.",
                    edge.source_location,
                    edge_keys=(edge.key,),
                )
            )
            continue
        if edge.type not in allowed:
            findings.append(
                make_finding(
                    DiagnosticCode.INVALID_GRAPH,
                    Severity.error,
                    f"Edge type '{edge.type.value}' is not valid for format "
                    f"'{ir.format.value}' ({edge.source} -> {edge.target}); "
                    "edge ignored.",
                    edge.source_location,
                    edge_keys=(edge.key,),
                )
            )
            continue
        kept_edges.append(edge)

    return IRGraph(format=ir.format, nodes=kept_nodes, edges=kept_edges), findings
