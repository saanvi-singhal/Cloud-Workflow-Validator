"""Unit and integration tests for the GitHub Actions YAML parser adapter."""

from pathlib import Path

import pytest

from app.compiler.pipeline import compile_source
from app.models import DiagnosticCode, SourceFormat
from app.parsers.yaml import YamlAdapter

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "yaml"


@pytest.fixture
def adapter():
    return YamlAdapter()


def test_valid_yaml_workflow_parsing(adapter):
    source = (FIXTURES / "valid_workflow.yml").read_text()
    result = compile_source(
        source, SourceFormat.yaml, filename="valid_workflow.yml", adapter=adapter
    )

    assert result.valid is True
    assert len(result.diagnostics) == 0
    assert len(result.graph.nodes) == 3

    node_ids = {n.id for n in result.graph.nodes}
    assert "gha:job:build" in node_ids
    assert "gha:job:test" in node_ids
    assert "gha:job:deploy" in node_ids

    # Check edges (prerequisites point to dependents)
    # build -> test, build -> deploy, test -> deploy
    edges = [(e.source, e.target) for e in result.graph.edges]
    assert ("gha:job:build", "gha:job:test") in edges
    assert ("gha:job:build", "gha:job:deploy") in edges
    assert ("gha:job:test", "gha:job:deploy") in edges

    # Execution order must respect dependencies
    assert result.execution_order is not None
    order = result.execution_order
    assert order.index("gha:job:build") < order.index("gha:job:test")
    assert order.index("gha:job:test") < order.index("gha:job:deploy")


def test_yaml_syntax_error(adapter):
    source = (FIXTURES / "syntax_error.yml").read_text()
    result = compile_source(
        source, SourceFormat.yaml, filename="syntax_error.yml", adapter=adapter
    )

    assert result.valid is False
    assert result.execution_order is None
    codes = [d.code for d in result.diagnostics]
    assert DiagnosticCode.YAML_SYNTAX_ERROR in codes


def test_unresolved_dependency_rule(adapter):
    """Unknown needs targets emit UNRESOLVED_DEPENDENCY without an edge."""
    source = (FIXTURES / "unresolved_needs.yml").read_text()
    result = compile_source(
        source, SourceFormat.yaml, filename="unresolved_needs.yml", adapter=adapter
    )

    assert result.valid is False
    assert result.execution_order is None
    # Must NOT have any dangling edges!
    assert len(result.graph.edges) == 0

    unresolved_diags = [
        d for d in result.diagnostics if d.code == DiagnosticCode.UNRESOLVED_DEPENDENCY
    ]
    assert len(unresolved_diags) == 1
    assert "non_existent_job" in unresolved_diags[0].message


def test_duplicate_job_id(adapter):
    source = """
jobs:
  build:
    runs-on: ubuntu-latest
  build:
    runs-on: macos-latest
"""
    result = compile_source(
        source, SourceFormat.yaml, filename="dup.yml", adapter=adapter
    )
    codes = [d.code for d in result.diagnostics]
    assert DiagnosticCode.DUPLICATE_NODE_ID in codes
    # Valid should be false because DUPLICATE_NODE_ID is an error
    assert result.valid is False


def test_empty_or_no_jobs(adapter):
    source = "name: Empty Workflow\non: push\n"
    result = compile_source(
        source, SourceFormat.yaml, filename="empty.yml", adapter=adapter
    )
    assert result.valid is False
    assert len(result.graph.nodes) == 0
    [diagnostic] = result.diagnostics
    assert diagnostic.code == DiagnosticCode.YAML_SYNTAX_ERROR
    assert diagnostic.message.startswith("Not a GitHub Actions workflow")


@pytest.mark.parametrize("source", ["", "- a\n- b\n", "just text\n"])
def test_non_mapping_yaml_is_not_a_workflow(adapter, source):
    result = compile_source(source, SourceFormat.yaml, adapter=adapter)
    assert result.valid is False
    assert result.diagnostics[0].message.startswith("Not a GitHub Actions workflow")


def test_docker_compose_file_is_named_as_unsupported(adapter):
    source = (
        'version: "3.8"\nservices:\n  api:\n    image: x\n'
        "    depends_on:\n      - cache\n  cache:\n    image: redis\n"
    )
    result = compile_source(source, SourceFormat.yaml, adapter=adapter)
    assert result.valid is False
    [diagnostic] = result.diagnostics
    assert "Docker Compose file, which is not supported" in diagnostic.message


def test_duplicate_key_outside_jobs_is_a_yaml_error(adapter):
    source = (
        "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
        "    runs-on: windows-latest\n"
    )
    result = compile_source(source, SourceFormat.yaml, adapter=adapter)
    assert result.valid is False
    [diagnostic] = result.diagnostics
    assert diagnostic.code == DiagnosticCode.YAML_SYNTAX_ERROR
    assert diagnostic.message.startswith(
        "Duplicate key 'runs-on' in the mapping starting on line 4"
    )
    loc = diagnostic.source_location
    assert (loc.start_line, loc.start_column, loc.end_column) == (5, 5, 12)
    # The graph is still built from the rest of the file.
    assert [n.id for n in result.graph.nodes] == ["gha:job:build"]


def test_duplicate_job_id_is_a_duplicate_node(adapter):
    source = "on: push\njobs:\n  a:\n    runs-on: x\n  a:\n    runs-on: y\n"
    result = compile_source(source, SourceFormat.yaml, adapter=adapter)
    [diagnostic] = result.diagnostics
    assert diagnostic.code == DiagnosticCode.DUPLICATE_NODE_ID
    assert diagnostic.message.startswith("Duplicate job ID 'a'")
    assert diagnostic.source_location.start_line == 5
    assert [r.related_node_ids for r in result.recommendations] == [["gha:job:a"]]


def test_unsupported_needs_construct(adapter):
    source = """
jobs:
  jobA:
    runs-on: ubuntu-latest
    needs:
      nested: bad_value
"""
    result = compile_source(
        source, SourceFormat.yaml, filename="bad_needs.yml", adapter=adapter
    )
    assert any(
        d.code == DiagnosticCode.UNSUPPORTED_CONSTRUCT for d in result.diagnostics
    )
    # When unsupported construct exists, execution_order is withheld
    assert result.execution_order is None
