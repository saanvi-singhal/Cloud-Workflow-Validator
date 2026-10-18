"""Helpers for building hand-made IR fixtures in tests.

These stand in for parser output, so the compiler core can be tested without
the YAML/Dockerfile parsers.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.compiler.graph import DependencyGraph
from app.compiler.ir import IRGraph
from app.models import Edge, EdgeType, Node, NodeType, SourceFormat, SourceLocation

DEFAULT_EDGE_TYPE = {
    SourceFormat.yaml: EdgeType.workflow_dependency,
    SourceFormat.dockerfile: EdgeType.docker_stage_base,
    SourceFormat.terraform: EdgeType.terraform_reference,
}
DEFAULT_NODE_TYPE = {
    SourceFormat.yaml: NodeType.task,
    SourceFormat.dockerfile: NodeType.stage,
    SourceFormat.terraform: NodeType.resource,
}


def loc(line: int, column: int = 1, file: str | None = "test.src") -> SourceLocation:
    return SourceLocation(file=file, start_line=line, start_column=column)


def build_ir(
    edges: Iterable[tuple[str, str]] = (),
    nodes: Iterable[str] = (),
    fmt: SourceFormat = SourceFormat.yaml,
) -> IRGraph:
    """Build IR from ``(source, target)`` pairs; endpoints become nodes.

    ``nodes`` adds extra (possibly isolated) nodes. Nodes get a fake location
    whose line is their position in sorted order, so locations are stable.
    """
    edge_list = list(edges)
    ids = set(nodes)
    for source, target in edge_list:
        ids.update((source, target))
    ordered = sorted(ids)
    return IRGraph(
        format=fmt,
        nodes=[
            Node(
                id=node_id,
                label=node_id,
                type=DEFAULT_NODE_TYPE[fmt],
                source_location=loc(index + 1),
            )
            for index, node_id in enumerate(ordered)
        ],
        edges=[
            Edge(source=s, target=t, type=DEFAULT_EDGE_TYPE[fmt]) for s, t in edge_list
        ],
    )


def build_graph(
    edges: Iterable[tuple[str, str]] = (), nodes: Iterable[str] = ()
) -> DependencyGraph:
    return DependencyGraph.from_ir(build_ir(edges, nodes))
