"""Unit and integration tests for the Dockerfile parser adapter."""

from pathlib import Path

import pytest

from app.compiler.pipeline import compile_source
from app.models import DiagnosticCode, EdgeType, NodeType, SourceFormat
from app.parsers.dockerfile import DockerfileAdapter

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "dockerfile"


@pytest.fixture
def adapter():
    return DockerfileAdapter()


def test_single_stage_dockerfile(adapter):
    source = (FIXTURES / "single_stage.dockerfile").read_text()
    result = compile_source(
        source,
        SourceFormat.dockerfile,
        filename="single_stage.dockerfile",
        adapter=adapter,
    )

    assert result.valid is True
    assert len(result.diagnostics) == 0
    assert len(result.graph.nodes) == 1
    # Dockerfile execution_order is always None per policy
    assert result.execution_order is None

    stage_node = result.graph.nodes[0]
    assert stage_node.type == NodeType.stage
    assert stage_node.metadata["is_final_stage"] is True
    assert stage_node.metadata["stage_index"] == 0
    assert "instructions" in stage_node.metadata


def test_multi_stage_dockerfile_and_copy_from(adapter):
    source = (FIXTURES / "multi_stage.dockerfile").read_text()
    result = compile_source(
        source,
        SourceFormat.dockerfile,
        filename="multi_stage.dockerfile",
        adapter=adapter,
    )

    assert result.valid is True
    assert len(result.diagnostics) == 0
    assert len(result.graph.nodes) == 2

    # Nodes: builder (stage 0), runner (stage 1)
    nodes_by_label = {n.label: n for n in result.graph.nodes}
    assert "builder" in nodes_by_label
    assert "runner" in nodes_by_label

    builder = nodes_by_label["builder"]
    runner = nodes_by_label["runner"]

    assert builder.metadata["is_final_stage"] is False
    assert runner.metadata["is_final_stage"] is True

    # Dependency edge from COPY --from=builder: builder -> runner
    edges = [(e.source, e.target, e.type) for e in result.graph.edges]
    assert (builder.id, runner.id, EdgeType.docker_stage_base) in edges


def test_unresolved_copy_from_stage(adapter):
    """Unknown COPY --from stage emits UNRESOLVED_DEPENDENCY without an edge."""
    source = (FIXTURES / "unresolved_copy_from.dockerfile").read_text()
    result = compile_source(
        source,
        SourceFormat.dockerfile,
        filename="unresolved_copy_from.dockerfile",
        adapter=adapter,
    )

    assert result.valid is False
    assert len(result.graph.edges) == 0

    codes = [d.code for d in result.diagnostics]
    assert DiagnosticCode.UNRESOLVED_DEPENDENCY in codes


def test_unreachable_intermediate_stage(adapter):
    """An intermediate stage not used by final stage is UNREACHABLE_NODE."""
    source = """
FROM alpine AS base
RUN echo base

FROM alpine AS unused_stage
RUN echo unused

FROM alpine AS final_stage
COPY --from=base /etc/hosts /tmp/hosts
"""
    result = compile_source(
        source,
        SourceFormat.dockerfile,
        filename="unreachable.dockerfile",
        adapter=adapter,
    )
    # UNREACHABLE_NODE is severity warning, so valid stays True
    assert result.valid is True
    codes = [d.code for d in result.diagnostics]
    assert DiagnosticCode.UNREACHABLE_NODE in codes


def test_from_scratch_and_stage_base_dependency(adapter):
    source = """
FROM scratch AS empty
COPY file.txt /

FROM empty AS extended
RUN echo extended
"""
    result = compile_source(
        source, SourceFormat.dockerfile, filename="scratch.dockerfile", adapter=adapter
    )
    assert result.valid is True
    assert len(result.graph.nodes) == 2
    # FROM empty in 'extended' stage creates dependency empty -> extended
    edges = [(e.source, e.target) for e in result.graph.edges]
    nodes_by_label = {n.label: n for n in result.graph.nodes}
    assert (nodes_by_label["empty"].id, nodes_by_label["extended"].id) in edges
