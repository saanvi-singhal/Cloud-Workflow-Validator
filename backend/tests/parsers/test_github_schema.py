"""GitHub's workflow rules: one invalid workflow per rule, plus valid edge cases.

The invalid cases cover GitHub's own schema (app/parsers/yaml/schema.py) and
the rules it enforces in code (workflow_rules.py). Each must produce an error
with the expected text on the expected line. The valid cases are things
GitHub accepts that a stricter checker would wrongly reject.
"""

import pytest

from app.compiler.pipeline import compile_source
from app.models import SourceFormat


def workflow(
    on: str = "push", job: str = "", steps: str = "      - run: echo\n", top: str = ""
):
    trigger = on if on.startswith("\n") else " " + on
    return (
        f"{top}on:{trigger}\n"
        "jobs:\n"
        "  build:\n"
        "    runs-on: ubuntu-latest\n"
        f"{job}"
        "    steps:\n"
        f"{steps}"
    )


def errors(source: str):
    result = compile_source(source, SourceFormat.yaml, "ci.yml")
    return [d for d in result.diagnostics if d.severity.value == "error"]


def warnings(source: str):
    result = compile_source(source, SourceFormat.yaml, "ci.yml")
    return [d for d in result.diagnostics if d.severity.value == "warning"]


INVALID = {
    # --- triggers ---------------------------------------------------------------
    "filter pair branches": (
        workflow("\n  push:\n    branches: [main]\n    branches-ignore: [dev]"),
        "has both 'branches' and 'branches-ignore'",
        4,
    ),
    "filter pair paths": (
        workflow("\n  pull_request:\n    paths: [src]\n    paths-ignore: [docs]"),
        "has both 'paths' and 'paths-ignore'",
        4,
    ),
    "unknown event": (workflow("pushh"), "'pushh' is not a GitHub Actions event", 1),
    "schedule without cron": (
        workflow("\n  schedule:\n    - crn: '0 0 * * *'"),
        "'crn' is not a valid key",
        3,
    ),
    "cron with six fields": (
        workflow("\n  schedule:\n    - cron: '0 0 * * * *'"),
        "has 6 field(s); a schedule needs five",
        3,
    ),
    "cron out of range": (
        workflow("\n  schedule:\n    - cron: '61 0 * * *'"),
        "minute '61', outside 0-59",
        3,
    ),
    "cron backwards range": (
        workflow("\n  schedule:\n    - cron: '0 0 * 5-2 *'"),
        "backwards range '5-2'",
        3,
    ),
    "dispatch input type": (
        workflow("\n  workflow_dispatch:\n    inputs:\n      env:\n        type: text"),
        "'text' is not valid for on.workflow_dispatch.inputs.env.type",
        5,
    ),
    "choice without options": (
        workflow(
            "\n  workflow_dispatch:\n    inputs:\n      env:\n        type: choice"
        ),
        "type 'choice' but no options",
        4,
    ),
    "choice default not an option": (
        workflow(
            "\n  workflow_dispatch:\n    inputs:\n      env:\n        type: choice\n"
            "        options: [dev, prod]\n        default: staging"
        ),
        "default 'staging', which is not one of its options",
        7,
    ),
    "call input without type": (
        workflow("\n  workflow_call:\n    inputs:\n      env:\n        required: true"),
        "missing the required key 'type'",
        4,
    ),
    "call output without value": (
        workflow(
            "\n  workflow_call:\n    outputs:\n      url:\n        description: x"
        ),
        "missing the required key 'value'",
        4,
    ),
    # --- workflow level ------------------------------------------------------------
    "permissions unknown scope": (
        workflow(top="permissions:\n  content: read\n"),
        "'content' is not a valid key in permissions. Did you mean 'contents'?",
        2,
    ),
    "permissions bad level": (
        workflow(top="permissions:\n  contents: reed\n"),
        "'reed' is not valid for permissions.contents. Did you mean 'read'?",
        2,
    ),
    "id-token cannot be read": (
        workflow(top="permissions:\n  id-token: read\n"),
        "'read' is not valid for permissions.id-token",
        2,
    ),
    "permissions bad shorthand": (
        workflow(top="permissions: read\n"),
        "'read' is not valid for permissions",
        1,
    ),
    "concurrency without group": (
        workflow(top="concurrency:\n  cancel-in-progress: true\n"),
        "concurrency is missing the required key 'group'",
        1,
    ),
    "concurrency queue value": (
        workflow(top="concurrency:\n  group: ci\n  queue: all\n"),
        "'all' is not valid for concurrency.queue",
        3,
    ),
    "matrix in workflow env": (
        workflow(top="env:\n  OS: ${{ matrix.os }}\n"),
        "env.OS uses 'matrix', which is not available there",
        2,
    ),
    "unclosed expression": (
        workflow(top="run-name: Deploy ${{ github.ref\n"),
        "has a '${{' that is never closed",
        1,
    ),
    # --- jobs -----------------------------------------------------------------------
    "job id format": (
        "on: push\njobs:\n  1build:\n    runs-on: x\n    steps:\n      - run: echo\n",
        "Job id '1build' is invalid",
        3,
    ),
    "timeout not a number": (
        workflow(job="    timeout-minutes: ten\n"),
        "must be a number",
        5,
    ),
    "continue-on-error not boolean": (
        workflow(job="    continue-on-error: yes\n"),
        "must be true or false, not 'yes'",
        5,
    ),
    "needs as mapping": (
        workflow(job="    needs: {a: 1}\n"),
        "jobs.build.needs must be",
        5,
    ),
    "strategy unknown key": (
        workflow(job="    strategy:\n      fail_fast: false\n"),
        "'fail_fast' is not a valid key in jobs.build.strategy. Did you mean 'fail-fast'?",
        6,
    ),
    "max-parallel not a number": (
        workflow(job="    strategy:\n      max-parallel: two\n"),
        "jobs.build.strategy.max-parallel must be a number",
        6,
    ),
    "matrix include not a list": (
        workflow(job="    strategy:\n      matrix:\n        include: {os: x}\n"),
        "jobs.build.strategy.matrix.include must be a list",
        7,
    ),
    "container unknown key": (
        workflow(job="    container:\n      image: node:20\n      port: [80]\n"),
        "'port' is not a valid key in jobs.build.container. Did you mean 'ports'?",
        7,
    ),
    "service ports not a list": (
        workflow(
            job="    services:\n      db:\n        image: postgres\n        ports: 5432\n"
        ),
        "jobs.build.services.db.ports must be a list",
        8,
    ),
    "defaults unknown key": (
        workflow(job="    defaults:\n      run:\n        shel: bash\n"),
        "'shel' is not a valid key in jobs.build.defaults.run. Did you mean 'shell'?",
        7,
    ),
    "environment without name": (
        workflow(job="    environment:\n      url: https://example.com\n"),
        "jobs.build.environment is missing the required key 'name'",
        5,
    ),
    "runs-on mapping key": (
        "on: push\njobs:\n  build:\n    runs-on:\n      label: x\n    steps:\n      - run: echo\n",
        "'label' is not a valid key in jobs.build.runs-on. Did you mean 'labels'?",
        5,
    ),
    "runs-on empty": (
        "on: push\njobs:\n  build:\n    runs-on: ''\n    steps:\n      - run: echo\n",
        "jobs.build.runs-on must be",
        4,
    ),
    "secrets in job if": (
        workflow(job="    if: secrets.TOKEN != ''\n"),
        "uses the secrets context",
        5,
    ),
    "env in job if": (
        workflow(job="    if: env.DEPLOY == 'yes'\n"),
        "jobs.build.if uses 'env', which is not available there",
        5,
    ),
    "hashFiles in job if": (
        workflow(job="    if: hashFiles('a') != ''\n"),
        "calls 'hashFiles()', which is not available there",
        5,
    ),
    "unknown function": (
        workflow(job="    if: ${{ startsWithh(github.ref, 'refs/tags') }}\n"),
        "calls 'startsWithh()'",
        5,
    ),
    "reusable workflow reference": (
        "on: push\njobs:\n  call:\n    uses: org/repo/deploy.yml@v1\n",
        "is not a reusable workflow reference",
        4,
    ),
    # --- steps ----------------------------------------------------------------------
    "shell on a uses step": (
        workflow(steps="      - uses: actions/checkout@v4\n        shell: bash\n"),
        "'shell' is not a valid key in jobs.build.steps[0]",
        7,
    ),
    "with on a run step": (
        workflow(steps="      - run: echo\n        with:\n          a: b\n"),
        "'with' is not a valid key in jobs.build.steps[0]",
        7,
    ),
    "step unknown key": (
        workflow(steps="      - run: echo\n        workdir: src\n"),
        "'workdir' is not a key of step 1",
        7,
    ),
    "step id format": (
        workflow(steps="      - id: my step\n        run: echo\n"),
        "Step id 'my step' is invalid",
        6,
    ),
    "duplicate step id": (
        workflow(
            steps="      - id: a\n        run: echo\n      - id: a\n        run: echo\n"
        ),
        "Step id 'a' is used more than once",
        8,
    ),
    "uses without ref": (
        workflow(steps="      - uses: actions/checkout\n"),
        "the @ref is required",
        6,
    ),
    "uses malformed": (
        workflow(steps="      - uses: checkout@v4\n"),
        "an action is {owner}/{repo}[/{path}]@{ref}",
        6,
    ),
    "step timeout not a number": (
        workflow(steps="      - run: echo\n        timeout-minutes: soon\n"),
        "jobs.build.steps[0].timeout-minutes must be a number",
        7,
    ),
    "step env not a mapping": (
        workflow(steps="      - run: echo\n        env: [A=1]\n"),
        "jobs.build.steps[0].env must be a mapping",
        7,
    ),
    "steps context in job env": (
        workflow(job="    env:\n      V: ${{ steps.x.outputs.v }}\n"),
        "uses 'steps', which is not available there",
        6,
    ),
}


@pytest.mark.parametrize(
    ("source", "expected", "line"), INVALID.values(), ids=INVALID.keys()
)
def test_rule_is_enforced(source, expected, line):
    found = errors(source)
    matching = [d for d in found if expected in d.message]
    assert matching, f"expected '{expected}', got {[d.message for d in found]}"
    assert matching[0].source_location.start_line == line, matching[0].message


VALID = {
    "newer step kinds": workflow(
        steps="      - run: echo\n        id: one\n        background: true\n"
        "      - wait: one\n      - wait-all: true\n      - cancel: one\n"
        "      - parallel:\n          - run: echo a\n          - run: echo b\n"
    ),
    "workflow description and cancel timeout": workflow(
        top="description: Builds the project\n", job="    cancel-timeout-minutes: 5\n"
    ),
    "expressions in typed fields": workflow(
        top="concurrency:\n  group: ci-${{ github.ref }}\n"
        "  cancel-in-progress: ${{ github.event_name == 'pull_request' }}\n",
        job="    timeout-minutes: ${{ fromJSON(vars.TIMEOUT) }}\n"
        "    strategy:\n      matrix:\n        os: ${{ fromJSON(vars.OSES) }}\n",
    ),
    "env values may be numbers and booleans": workflow(
        top="env:\n  DEBUG: true\n  PORT: 8080\n"
    ),
    "permissions shorthands and none": workflow(top="permissions: read-all\n")
    + "  other:\n    runs-on: x\n    permissions:\n      contents: none\n"
    "      id-token: write\n    steps:\n      - run: echo\n",
    "local, docker and pinned actions": workflow(
        steps="      - uses: ./.github/actions/setup\n"
        "      - uses: docker://alpine:3.20\n"
        "      - uses: actions/setup-node@v4\n"
        "      - uses: github/codeql-action/init@v3\n"
    ),
    "cron names and Sunday as 7": workflow(
        "\n  schedule:\n    - cron: '*/15 0-6 1,15 JAN-MAR MON-FRI'\n    - cron: '0 0 * * 7'"
    ),
    "status functions in step if": workflow(
        steps="      - run: echo\n        if: ${{ failure() && hashFiles('a') != '' }}\n"
    ),
    "job outputs, environment string and runs-on group": workflow(
        job="    environment: production\n    outputs:\n      v: ${{ steps.x.outputs.v }}\n"
    )
    + "  grouped:\n    runs-on:\n      group: big\n      labels: [linux]\n"
    "    steps:\n      - run: echo\n",
    "reusable workflow call": "on: push\njobs:\n  call:\n"
    "    uses: org/repo/.github/workflows/deploy.yml@v1\n"
    "    with:\n      env: prod\n    secrets: inherit\n"
    "  local:\n    uses: ./.github/workflows/test.yaml\n",
    "dispatch with choice": workflow(
        "\n  workflow_dispatch:\n    inputs:\n      env:\n        type: choice\n"
        "        options: [dev, prod]\n        default: dev\n      dry:\n"
        "        type: boolean\n        default: false"
    ),
}


@pytest.mark.parametrize("source", VALID.values(), ids=VALID.keys())
def test_valid_workflow_has_no_errors(source):
    assert [d.message for d in errors(source)] == []


def test_trigger_filter_schema_problems_are_warnings():
    # Real repositories run with these, so GitHub is evidently lenient here.
    source = workflow(
        "\n  merge_group:\n    paths-ignore: ['**.md']\n  push:\n    tags:"
    )
    assert errors(source) == []
    assert any("paths-ignore" in d.message for d in warnings(source))
