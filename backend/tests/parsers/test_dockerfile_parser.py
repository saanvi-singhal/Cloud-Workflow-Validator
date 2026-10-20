"""Unit and integration tests for the Dockerfile parser adapter."""

from pathlib import Path

import pytest

from app.compiler.pipeline import compile_source
from app.models import DiagnosticCode, EdgeType, NodeType, SourceFormat
from app.parsers.dockerfile import DockerfileAdapter

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "dockerfile"


def parser_diagnostics(result):
    """Diagnostics from parsing, without the best-practice rule findings."""
    return [
        d
        for d in result.diagnostics
        if d.code != DiagnosticCode.SECURITY_RULE_VIOLATION
    ]


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
    assert parser_diagnostics(result) == []
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
    assert parser_diagnostics(result) == []
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


def test_parse_does_not_touch_the_filesystem(adapter, tmp_path, monkeypatch):
    # dockerfile-parse reads and writes ./Dockerfile unless given a file object.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "Dockerfile").write_text("FROM keep-me\n")

    result = adapter.parse("FROM alpine AS base\nRUN echo hi\n", None)

    assert sorted(p.name for p in tmp_path.iterdir()) == ["Dockerfile"]
    assert (tmp_path / "Dockerfile").read_text() == "FROM keep-me\n"
    assert result.ir is not None
    assert result.ir.nodes[0].metadata["base_image"] == "alpine"


def test_stage_ids_use_the_stage_index(adapter):
    source = "FROM alpine AS base\nRUN echo\n\nFROM base\nRUN echo\n"
    result = adapter.parse(source, None)

    assert result.ir is not None
    assert [(n.id, n.label) for n in result.ir.nodes] == [
        ("docker:stage:0", "base"),
        ("docker:stage:1", "stage-1"),
    ]
    assert result.ir.nodes[0].metadata["alias"] == "base"


def _errors(result):
    return [
        (d.code, d.message.split(".")[0], d.source_location.start_line)
        for d in result.diagnostics
        if d.severity.value == "error"
    ]


def test_file_without_from_and_unknown_instruction_is_invalid(adapter):
    source = (
        "WORKDIR /app\n"
        "COPY requirements.txt .\n"
        "EXPOSE 8000\n"
        'START ["uvicorn", "main:app"]\n'
    )
    result = compile_source(source, SourceFormat.dockerfile, adapter=adapter)

    assert result.valid is False
    assert _errors(result) == [
        (DiagnosticCode.DOCKERFILE_SYNTAX_ERROR, "No FROM instruction found", 1),
        (DiagnosticCode.DOCKERFILE_SYNTAX_ERROR, "Unknown instruction 'START'", 4),
    ]
    start = result.diagnostics[-1].source_location
    assert (start.start_column, start.end_column) == (1, 6)  # end is exclusive


def test_unknown_instruction_after_from_is_reported(adapter):
    result = compile_source(
        "FROM python:3.12\n  RUNN pip install x\n",
        SourceFormat.dockerfile,
        adapter=adapter,
    )
    assert result.valid is False
    [diagnostic] = parser_diagnostics(result)
    assert diagnostic.message.startswith("Unknown instruction 'RUNN'")
    loc = diagnostic.source_location
    assert (loc.start_line, loc.start_column, loc.end_column) == (2, 3, 7)


def test_instruction_before_from_is_reported(adapter):
    result = compile_source(
        "WORKDIR /app\nFROM alpine\n", SourceFormat.dockerfile, adapter=adapter
    )
    assert _errors(result) == [
        (
            DiagnosticCode.DOCKERFILE_SYNTAX_ERROR,
            "'WORKDIR' appears before the first FROM",
            1,
        ),
    ]


def test_arg_and_comments_before_from_are_allowed(adapter):
    source = "# syntax=docker/dockerfile:1\nARG VERSION=3.12\nFROM python:${VERSION}\n"
    result = compile_source(source, SourceFormat.dockerfile, adapter=adapter)
    assert result.valid is True
    assert parser_diagnostics(result) == []


def test_empty_dockerfile_is_invalid(adapter):
    result = compile_source("", SourceFormat.dockerfile, adapter=adapter)
    assert result.valid is False
    assert [d.message.split(".")[0] for d in result.diagnostics] == [
        "No FROM instruction found"
    ]


@pytest.mark.parametrize(
    ("line", "message"),
    [
        (
            "HEALTHCHECK --interval=5m --timeout=3s \\\n  curl -f http://localhost/",
            "HEALTHCHECK needs the CMD keyword before the command (found 'curl')",
        ),
        ("HEALTHCHECK --interval=5m", "HEALTHCHECK needs CMD <command> or NONE."),
        ("HEALTHCHECK CMD", "HEALTHCHECK CMD needs a command."),
        ("HEALTHCHECK NONE curl", "HEALTHCHECK NONE takes no command."),
        (
            'ONBUILD ONBUILD RUN echo "x"',
            "ONBUILD ONBUILD is not allowed: ONBUILD triggers cannot be chained.",
        ),
        ("ONBUILD FROM alpine", "ONBUILD FROM is not allowed."),
        ("ONBUILD RUNN x", "ONBUILD runs an unknown instruction 'RUNN'."),
    ],
)
def test_healthcheck_and_onbuild_forms_docker_rejects(adapter, line, message):
    result = compile_source(
        f"FROM alpine:3.20\n{line}\n", SourceFormat.dockerfile, adapter=adapter
    )
    [diagnostic] = parser_diagnostics(result)
    assert diagnostic.code == DiagnosticCode.DOCKERFILE_SYNTAX_ERROR
    assert diagnostic.message.startswith(message)
    assert diagnostic.source_location.start_line == 2


@pytest.mark.parametrize(
    "line",
    [
        "HEALTHCHECK --interval=5m --timeout=3s CMD curl -f http://localhost/",
        "HEALTHCHECK NONE",
        "ONBUILD RUN echo ok",
        "ONBUILD COPY . /app",
    ],
)
def test_valid_healthcheck_and_onbuild_are_accepted(adapter, line):
    result = compile_source(
        f"FROM alpine:3.20\n{line}\n", SourceFormat.dockerfile, adapter=adapter
    )
    assert parser_diagnostics(result) == []
