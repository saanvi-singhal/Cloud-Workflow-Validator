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


INVALID_CI = """\
name: Invalid CI Pipeline
on: [commit]

jobs:
  test:
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      - name: Empty Step
        env:
          MY_VAR: "value"

  publish:
    runs-on: ubuntu-latest
    needs: build
    steps:
      - name: Publish Package
        run: npm publish
"""


def _located_errors(result):
    return [
        (d.code, d.source_location.start_line, d.message.split(",")[0].split(";")[0])
        for d in result.diagnostics
        if d.severity.value == "error"
    ]


def test_schema_violations_are_reported_at_their_location(adapter):
    result = compile_source(INVALID_CI, SourceFormat.yaml, adapter=adapter)

    assert result.valid is False
    syntax = DiagnosticCode.YAML_SYNTAX_ERROR
    assert _located_errors(result) == [
        (syntax, 2, "'commit' is not a GitHub Actions event"),
        (syntax, 5, "Job 'test' is missing 'runs-on'"),
        (syntax, 9, "Step 2 of job 'test' ('Empty Step') has neither 'uses' nor 'run'"),
        (
            DiagnosticCode.UNRESOLVED_DEPENDENCY,
            15,
            "Job 'publish' has unresolved dependency 'build'.",
        ),
    ]
    event = result.diagnostics[0].source_location
    assert (event.start_column, event.end_column) == (6, 12)  # `commit`, exclusive end
    # Problems in a job colour its node.
    test_recs = [
        r for r in result.recommendations if "gha:job:test" in r.related_node_ids
    ]
    assert len(test_recs) == 2


@pytest.mark.parametrize(
    "on",
    [
        "push",
        "[push, pull_request]",
        "\n  push:\n    branches: [main]\n  workflow_dispatch:",
    ],
)
def test_valid_trigger_forms_are_accepted(adapter, on):
    source = f"on: {on}\njobs:\n  a:\n    runs-on: x\n    steps:\n      - run: echo\n"
    result = compile_source(source, SourceFormat.yaml, adapter=adapter)
    assert result.diagnostics == []
    assert result.valid is True


def test_missing_on_is_reported(adapter):
    result = compile_source(
        "jobs:\n  a:\n    runs-on: x\n", SourceFormat.yaml, adapter=adapter
    )
    [diagnostic] = result.diagnostics
    assert diagnostic.message.startswith("Missing 'on'")


def test_step_with_both_uses_and_run_is_reported(adapter):
    source = (
        "on: push\njobs:\n  a:\n    runs-on: x\n    steps:\n"
        "      - uses: actions/checkout@v4\n        run: echo\n"
    )
    result = compile_source(source, SourceFormat.yaml, adapter=adapter)
    [diagnostic] = result.diagnostics
    assert "has both 'uses' and 'run'" in diagnostic.message
    assert diagnostic.source_location.start_line == 6


def test_reusable_workflow_job_needs_no_runs_on_or_steps(adapter):
    source = "on: push\njobs:\n  call:\n    uses: org/repo/.github/workflows/w.yml@v1\n"
    result = compile_source(source, SourceFormat.yaml, adapter=adapter)
    assert result.diagnostics == []


ADVANCED = """\
name: Advanced YAML Parser Test
on:
  push:
    branches:
      - main

x-node-version: &node_version "18.x"

jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        node: [16, 18.0]
    steps:
      - uses: actions/checkout@v4
      - name: Setup Node
        uses: actions/setup-node@v3
        with:
          node-version: *node_version
      - name: Deploy
        env:
          ENABLE_DEBUG: true
          PORT: 8080
        run: npm run deploy
"""


def test_unknown_top_level_key_and_lost_zero_are_reported(adapter):
    result = compile_source(ADVANCED, SourceFormat.yaml, adapter=adapter)
    assert result.valid is False
    assert [
        (d.code, d.severity.value, d.source_location.start_line)
        for d in result.diagnostics
    ] == [
        (DiagnosticCode.YAML_SYNTAX_ERROR, "error", 7),
        (DiagnosticCode.SECURITY_RULE_VIOLATION, "warning", 14),
    ]
    key, number = result.diagnostics
    assert key.message.startswith("'x-node-version' is not a top-level workflow key")
    assert "no 'x-' extension keys" in key.message
    # `        node: [16, 18.0]`: 18.0 starts at column 20; end is exclusive.
    span = number.source_location
    assert (span.start_column, span.end_column) == (20, 24)
    assert "GitHub passes '18', not '18.0'" in number.message
    [_, fix] = result.recommendations
    assert fix.rule_id == "GHA_NUMBER_LOSES_ZERO"
    assert fix.related_node_ids == ["gha:job:build"]
    assert fix.proposed_change.preview == '- 18.0\n+ "18.0"'


def test_booleans_and_numbers_in_env_are_accepted(adapter):
    # GitHub converts these to the strings "true" and "8080".
    source = (
        ADVANCED.replace('x-node-version: &node_version "18.x"\n', "")
        .replace("*node_version", '"18.x"')
        .replace("[16, 18.0]", "[16, 18]")
    )
    result = compile_source(source, SourceFormat.yaml, adapter=adapter)
    assert result.diagnostics == []
    assert result.valid is True


@pytest.mark.parametrize(
    ("value", "fires"),
    [
        ("3.10", True),
        ("[3.9, 3.10]", True),
        ("1.20", True),
        ("3.11", False),
        ('"3.10"', False),
        ("3", False),
        ("true", False),
    ],
)
def test_only_unquoted_numbers_ending_in_zero_fire(adapter, value, fires):
    source = (
        "on: push\njobs:\n  a:\n    runs-on: x\n    strategy:\n      matrix:\n"
        f"        python: {value}\n    steps:\n      - run: echo\n"
    )
    result = compile_source(source, SourceFormat.yaml, adapter=adapter)
    codes = [d.code for d in result.diagnostics]
    assert (DiagnosticCode.SECURITY_RULE_VIOLATION in codes) is fires


def test_unknown_job_and_step_keys_are_reported(adapter):
    source = (
        "on: push\njobs:\n  a:\n    runs-on: x\n    run-on: y\n    steps:\n"
        "      - run: echo\n        working_directory: src\n"
    )
    result = compile_source(source, SourceFormat.yaml, adapter=adapter)
    assert [
        (d.source_location.start_line, d.message.split(",")[0])
        for d in result.diagnostics
    ] == [
        (5, "'run-on' is not a key of job 'a'"),
        (8, "'working_directory' is not a key of step 1 of job 'a'"),
    ]


VULNERABLE = """\
name: Vulnerable Pipeline
on:
  issues:
    types: [opened]

jobs:
  process-issue:
    runs-on: ubuntu-latest
    steps:
      - name: Print Issue Title
        run: echo "Issue title is ${{ github.event.issue.title }}"

      - name: Invalid Context
        if: ${{ secrets.MY_TOKEN != '' }}
        run: echo "Token exists"
"""


def test_script_injection_and_secrets_in_if_are_reported(adapter):
    result = compile_source(VULNERABLE, SourceFormat.yaml, adapter=adapter)
    assert result.valid is False
    found = [
        (
            d.code,
            d.severity.value,
            d.source_location.start_line,
            d.source_location.start_column,
            d.source_location.end_column,
        )
        for d in result.diagnostics
    ]
    assert found == [
        (DiagnosticCode.SECURITY_RULE_VIOLATION, "warning", 11, 35, 66),
        (DiagnosticCode.YAML_SYNTAX_ERROR, "error", 14, 17, 24),
    ]
    injection = next(
        r for r in result.recommendations if r.rule_id == "GHA_SCRIPT_INJECTION"
    )
    assert injection.related_node_ids == ["gha:job:process-issue"]
    assert "TITLE: ${{ github.event.issue.title }}" in injection.proposed_change.preview


def _workflow(step: str) -> str:
    return f"on: push\njobs:\n  a:\n    runs-on: x\n    steps:\n{step}"


def _rule_ids(adapter, source):
    result = compile_source(source, SourceFormat.yaml, adapter=adapter)
    return [r.rule_id for r in result.recommendations]


@pytest.mark.parametrize(
    "expression",
    [
        "github.event.issue.body",
        "github.event.pull_request.title",
        "github.event.pull_request.head.ref",
        "github.head_ref",
        "github.event.comment.body",
        "github.event.commits[0].message",
        "github.event.head_commit.author.name",
        "github.event.workflow_run.head_branch",
        "toJSON(github.event.issue.title)",
    ],
)
def test_untrusted_fields_in_run_are_injection(adapter, expression):
    source = _workflow(f'      - run: echo "${{{{ {expression} }}}}"\n')
    assert _rule_ids(adapter, source) == ["GHA_SCRIPT_INJECTION"]


@pytest.mark.parametrize(
    "step",
    [
        # Trusted or not attacker-controlled values.
        '      - run: echo "${{ github.sha }} ${{ github.event.issue.number }}"\n',
        '      - run: echo "${{ github.event.pull_request.base.ref }}"\n',
        # The safe pattern: untrusted data passed through env.
        "      - env:\n          TITLE: ${{ github.event.issue.title }}\n"
        '        run: echo "$TITLE"\n',
        # Inputs of ordinary actions are not scripts.
        "      - uses: actions/labeler@v5\n        with:\n"
        "          title: ${{ github.event.issue.title }}\n",
    ],
)
def test_safe_uses_are_not_injection(adapter, step):
    assert _rule_ids(adapter, _workflow(step)) == []


def test_injection_in_a_block_script_and_github_script_is_located(adapter):
    source = _workflow(
        "      - run: |\n"
        "          echo start\n"
        '          echo "${{ github.event.pull_request.head.ref }}"\n'
        "      - uses: actions/github-script@v7\n"
        "        with:\n"
        "          script: console.log('${{ github.event.comment.body }}')\n"
    )
    result = compile_source(source, SourceFormat.yaml, adapter=adapter)
    assert [
        (d.source_location.start_line, d.source_location.start_column)
        for d in result.diagnostics
    ] == [
        (8, 17),
        (11, 32),  # after `          script: console.log('`
    ]


@pytest.mark.parametrize(
    ("condition", "fires"),
    [
        ("${{ secrets.MY_TOKEN != '' }}", True),
        ("secrets.MY_TOKEN != ''", True),
        ("${{ secrets['MY_TOKEN'] }}", True),
        ("env.MY_TOKEN != ''", False),
        ("github.event_name == 'push'", False),
        ("contains(github.ref, 'secrets.')", False),
    ],
)
def test_secrets_in_step_if(adapter, condition, fires):
    source = _workflow(f"      - if: {condition}\n        run: echo\n")
    result = compile_source(source, SourceFormat.yaml, adapter=adapter)
    messages = [d.message for d in result.diagnostics]
    assert any("uses the secrets context" in m for m in messages) is fires


def test_secrets_in_job_if(adapter):
    source = (
        "on: push\njobs:\n  a:\n    if: secrets.X\n    runs-on: x\n"
        "    steps:\n      - run: echo\n"
    )
    result = compile_source(source, SourceFormat.yaml, adapter=adapter)
    [diagnostic] = result.diagnostics
    assert diagnostic.message.startswith("The 'if' of job 'a' uses the secrets context")
    assert diagnostic.source_location.start_line == 4
