"""GitHub Actions YAML workflow parser adapter.

Uses ruamel.yaml in round-trip mode to preserve line and column coordinates.
Normalizes jobs and their 'needs' dependencies into the shared IRGraph model.
"""

from __future__ import annotations

import io
import re
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.constructor import DuplicateKeyError
from ruamel.yaml.error import MarkedYAMLError

from app.compiler.adapters import ParseResult
from app.compiler.findings import Finding, make_finding
from app.compiler.ir import FORMAT_ID_PREFIX, IRGraph, make_node_id, unique_id
from app.models import (
    DiagnosticCode,
    Edge,
    EdgeType,
    Node,
    NodeType,
    Severity,
    SourceFormat,
    SourceLocation,
)
from app.rules.github_actions_rules import run_github_actions_rules

ID_PREFIX = FORMAT_ID_PREFIX[SourceFormat.yaml]

_DUPLICATE_KEY = re.compile(r'duplicate key "(.*?)"')
# `secrets.X` or `secrets['X']` used as a context in an expression.
_SECRETS_CONTEXT = re.compile(r"(?<![\w.'\"])secrets\s*[.\[]")

# Keys GitHub allows; any other key makes it reject the workflow
# (https://docs.github.com/actions/reference/workflow-syntax-for-github-actions).
# Unlike Docker Compose, there are no `x-` extension keys.
WORKFLOW_KEYS = frozenset(
    {"name", "run-name", "on", "permissions", "env", "defaults", "concurrency", "jobs"}
)
JOB_KEYS = frozenset(
    {
        "name",
        "permissions",
        "needs",
        "if",
        "runs-on",
        "snapshot",
        "environment",
        "concurrency",
        "outputs",
        "env",
        "defaults",
        "steps",
        "timeout-minutes",
        "strategy",
        "continue-on-error",
        "container",
        "services",
        "uses",
        "with",
        "secrets",
    }
)
# The only keys a job that calls a reusable workflow (`uses:`) may have.
REUSABLE_CALL_KEYS = frozenset(
    {
        "name",
        "uses",
        "with",
        "secrets",
        "strategy",
        "needs",
        "if",
        "concurrency",
        "permissions",
    }
)
STEP_KEYS = frozenset(
    {
        "id",
        "if",
        "name",
        "uses",
        "run",
        "working-directory",
        "shell",
        "with",
        "env",
        "continue-on-error",
        "timeout-minutes",
    }
)

# Events that can trigger a workflow
# (https://docs.github.com/actions/reference/events-that-trigger-workflows).
# GitHub refuses a workflow whose `on` names anything else.
KNOWN_EVENTS = frozenset(
    {
        "branch_protection_rule",
        "check_run",
        "check_suite",
        "create",
        "delete",
        "deployment",
        "deployment_status",
        "discussion",
        "discussion_comment",
        "fork",
        "gollum",
        "image_version",
        "issue_comment",
        "issues",
        "label",
        "merge_group",
        "milestone",
        "page_build",
        "project",
        "project_card",
        "project_column",
        "public",
        "pull_request",
        "pull_request_review",
        "pull_request_review_comment",
        "pull_request_target",
        "push",
        "registry_package",
        "release",
        "repository_dispatch",
        "schedule",
        "status",
        "watch",
        "workflow_call",
        "workflow_dispatch",
        "workflow_run",
    }
)


def _position(
    line_col: tuple[int, int] | None, filename: str | None, length: int | None = None
) -> SourceLocation | None:
    """Turn a 0-based ruamel (line, col) into a 1-based SourceLocation."""
    if line_col is None:
        return None
    line, col = line_col
    return SourceLocation(
        file=filename,
        start_line=line + 1,
        start_column=col + 1,
        end_line=line + 1 if length else None,
        end_column=col + 1 + length if length else None,
    )


def _key_position(mapping: Any, key: Any) -> tuple[int, int] | None:
    try:
        return mapping.lc.key(key)
    except Exception:
        return None


def _value_position(mapping: Any, key: Any) -> tuple[int, int] | None:
    try:
        return mapping.lc.value(key)
    except Exception:
        return None


def _item_position(sequence: Any, index: int) -> tuple[int, int] | None:
    try:
        return sequence.lc.item(index)
    except Exception:
        return None


def _extract_location(
    node: Any, key: Any = None, filename: str | None = None
) -> SourceLocation | None:
    """Extract 1-based SourceLocation from ruamel.yaml comment/line-col data."""
    if not hasattr(node, "lc"):
        return None
    try:
        if key is not None:
            line, col = node.lc.key(key)
        else:
            line, col = node.lc.line, node.lc.col
        return SourceLocation(
            file=filename,
            start_line=line + 1,
            start_column=col + 1,
        )
    except Exception:
        return None


class _YamlExtractor:
    """Extracts nodes and edges from parsed YAML structure."""

    def __init__(self, filename: str | None, source: str = "") -> None:
        self.filename = filename
        self.lines = source.split("\n")
        self.findings: list[Finding] = []
        self.complete = True
        self.nodes: list[Node] = []
        self.taken_ids: set[str] = set()
        self.job_to_id: dict[str, str] = {}
        self.edges: list[Edge] = []

    def _not_a_workflow(self, data: Any) -> IRGraph:
        """A file without `jobs` is not a GitHub Actions workflow (spec 4.1).

        This is an error, not info: reporting it as valid would suggest the
        file was checked when nothing in it was analysed.
        """
        message = (
            "Not a GitHub Actions workflow: there is no top-level 'jobs' "
            "mapping. Only GitHub Actions workflow YAML is supported."
        )
        if isinstance(data, dict) and "services" in data:
            message += " This looks like a Docker Compose file, which is not supported."
        self.findings.append(
            make_finding(
                DiagnosticCode.YAML_SYNTAX_ERROR,
                Severity.error,
                message,
                SourceLocation(file=self.filename, start_line=1, start_column=1),
            )
        )
        return IRGraph(format=SourceFormat.yaml, nodes=[], edges=[])

    def extract(self, data: Any) -> IRGraph:
        if not isinstance(data, dict) or data.get("jobs") is None:
            return self._not_a_workflow(data)

        jobs = data["jobs"]

        if not isinstance(jobs, dict):
            self.findings.append(
                make_finding(
                    DiagnosticCode.YAML_SYNTAX_ERROR,
                    Severity.error,
                    "'jobs' section must be a dictionary/mapping of jobs.",
                    location=_extract_location(data, "jobs", self.filename),
                )
            )
            return IRGraph(format=SourceFormat.yaml, nodes=[], edges=[])

        # Pass 1: Declare all job nodes
        for job_key, job_val in jobs.items():
            if not isinstance(job_key, str):
                job_key_str = str(job_key)
            else:
                job_key_str = job_key

            loc = _extract_location(jobs, job_key, self.filename)
            base_id = make_node_id(ID_PREFIX, "job", job_key_str)
            node_id = unique_id(base_id, self.taken_ids)

            if node_id != base_id:
                self.findings.append(
                    make_finding(
                        DiagnosticCode.DUPLICATE_NODE_ID,
                        Severity.error,
                        f"Duplicate job '{job_key_str}'; references "
                        "resolve to the first declaration.",
                        loc,
                        node_ids=(base_id, node_id),
                        details={"job": job_key_str},
                    )
                )
            else:
                self.job_to_id[job_key_str] = node_id

            metadata: dict[str, Any] = {"job_key": job_key_str}
            if isinstance(job_val, dict):
                if "name" in job_val and isinstance(job_val["name"], str):
                    metadata["name"] = job_val["name"]
                if "runs-on" in job_val and isinstance(job_val["runs-on"], (str, list)):
                    metadata["runs_on"] = job_val["runs-on"]

            self.nodes.append(
                Node(
                    id=node_id,
                    label=job_key_str,
                    type=NodeType.task,
                    source_location=loc,
                    metadata=metadata,
                )
            )

        # Pass 2: Connect dependencies via `needs`
        for job_key, job_val in jobs.items():
            job_key_str = str(job_key)
            target_id = self.job_to_id.get(job_key_str)
            if target_id is None:
                # Duplicate or undeclared; skipped for edge target
                continue

            if not isinstance(job_val, dict):
                continue

            if "needs" not in job_val:
                continue

            needs_raw = job_val["needs"]
            needs_loc = _extract_location(job_val, "needs", self.filename)

            if isinstance(needs_raw, (str, int)):
                needs_list = [str(needs_raw)]
            elif isinstance(needs_raw, list):
                needs_list = [str(item) for item in needs_raw]
            else:
                self.findings.append(
                    make_finding(
                        DiagnosticCode.UNSUPPORTED_CONSTRUCT,
                        Severity.warning,
                        f"Unsupported 'needs' specification for '{job_key_str}': "
                        f"{needs_raw!r}.",
                        needs_loc,
                        node_ids=(target_id,),
                    )
                )
                self.complete = False
                continue

            for needed_job in needs_list:
                source_id = self.job_to_id.get(needed_job)
                if source_id is None:
                    # CRUCIAL RULE: Do NOT create an edge to a non-existent node.
                    # DO emit UNRESOLVED_DEPENDENCY finding.
                    known = sorted(self.job_to_id.keys())
                    self.findings.append(
                        make_finding(
                            DiagnosticCode.UNRESOLVED_DEPENDENCY,
                            Severity.error,
                            f"Job '{job_key_str}' has unresolved dependency "
                            f"'{needed_job}'.",
                            needs_loc,
                            node_ids=(target_id,),
                            details={
                                "job": job_key_str,
                                "address": needed_job,
                                "known_addresses": known,
                            },
                        )
                    )
                else:
                    self.edges.append(
                        Edge(
                            source=source_id,
                            target=target_id,
                            type=EdgeType.workflow_dependency,
                            label="needs",
                            source_location=needs_loc,
                        )
                    )

        self._check_triggers(data)
        self._check_unknown_keys(data, WORKFLOW_KEYS, "a top-level workflow key")
        for job_key, job_val in jobs.items():
            node_id = self.job_to_id.get(str(job_key))
            if node_id is not None and isinstance(job_val, dict):
                self._check_job(str(job_key), node_id, job_val, jobs)

        return IRGraph(format=SourceFormat.yaml, nodes=self.nodes, edges=self.edges)

    # --- schema checks (spec 4.1) --------------------------------------------
    # Only rules GitHub itself enforces when it loads a workflow. They are
    # YAML_SYNTAX_ERROR errors: the workflow would be rejected before running.

    def _schema_error(
        self,
        message: str,
        location: SourceLocation | None,
        node_id: str | None = None,
    ) -> None:
        self.findings.append(
            make_finding(
                DiagnosticCode.YAML_SYNTAX_ERROR,
                Severity.error,
                message,
                location,
                node_ids=(node_id,) if node_id else (),
            )
        )

    def _check_unknown_keys(
        self,
        mapping: Any,
        allowed: frozenset[str],
        what: str,
        node_id: str | None = None,
    ) -> None:
        for key in mapping:
            if str(key) not in allowed:
                hint = (
                    " GitHub Actions has no 'x-' extension keys (that is a "
                    "Docker Compose feature). To share a value, put the anchor "
                    "on a valid key, e.g. under the top-level env."
                    if str(key).startswith("x-")
                    else ""
                )
                self._schema_error(
                    f"'{key}' is not {what}, so GitHub will reject this "
                    f"workflow.{hint}",
                    _position(
                        _key_position(mapping, key), self.filename, len(str(key))
                    ),
                    node_id,
                )

    def _check_reusable_call(self, job_key: str, node_id: str, job: Any) -> None:
        """A job with ``uses:`` runs another workflow; it has no runner or steps."""
        for key in job:
            if str(key) in JOB_KEYS and str(key) not in REUSABLE_CALL_KEYS:
                self._schema_error(
                    f"'{key}' is not allowed in job '{job_key}', which calls a "
                    "reusable workflow with 'uses'; such a job only takes name, "
                    "uses, with, secrets, strategy, needs, if, concurrency and "
                    "permissions. GitHub will reject this workflow.",
                    _position(_key_position(job, key), self.filename, len(str(key))),
                    node_id,
                )
        inputs = job.get("with")
        if isinstance(inputs, dict):
            for name, value in inputs.items():
                if isinstance(value, str) and _SECRETS_CONTEXT.search(value):
                    self._schema_error(
                        f"Input '{name}' of job '{job_key}' uses the secrets "
                        "context, which is not available in 'with'. Pass secrets "
                        "under 'secrets:' (or use 'secrets: inherit').",
                        self._secrets_location(inputs, name),
                        node_id,
                    )

    def _secrets_location(self, mapping: Any, key: Any) -> SourceLocation | None:
        """The ``secrets`` word in ``mapping[key]``, or the value's start."""
        position = _value_position(mapping, key)
        if position is not None and position[0] < len(self.lines):
            line, col = position
            found = _SECRETS_CONTEXT.search(self.lines[line], col)
            if found:
                return _position((line, found.start()), self.filename, len("secrets"))
        return _position(position, self.filename)

    def _check_if_secrets(self, mapping: Any, where: str, node_id: str) -> None:
        """GitHub rejects ``if:`` conditions that use the ``secrets`` context."""
        condition = mapping.get("if")
        if not isinstance(condition, str) or not _SECRETS_CONTEXT.search(condition):
            return
        location = self._secrets_location(mapping, "if")
        self._schema_error(
            f"The 'if' of {where} uses the secrets context, which is not "
            "available in conditions, so GitHub will reject this workflow. Map "
            "the secret to an env variable and test env.NAME instead.",
            location,
            node_id,
        )

    def _check_triggers(self, data: Any) -> None:
        """`on` must exist and name only real events."""
        if "on" not in data:
            self._schema_error(
                "Missing 'on': a workflow must say which events trigger it.",
                SourceLocation(file=self.filename, start_line=1, start_column=1),
            )
            return

        on = data["on"]
        # `on: push`, `on: [push, fork]` or `on: {push: {...}}`
        if isinstance(on, str):
            events = [(on, _value_position(data, "on"))]
        elif isinstance(on, list):
            events = [(e, _item_position(on, i)) for i, e in enumerate(on)]
        elif isinstance(on, dict):
            events = [(e, _key_position(on, e)) for e in on]
        else:
            self._schema_error(
                "'on' must be an event name, a list of events or a mapping of events.",
                _value_position(data, "on"),
            )
            return

        for event, position in events:
            if str(event) not in KNOWN_EVENTS:
                self._schema_error(
                    f"'{event}' is not a GitHub Actions event, so GitHub will "
                    "reject this workflow. Did you mean 'push'?"
                    if str(event) == "commit"
                    else f"'{event}' is not a GitHub Actions event, so GitHub "
                    "will reject this workflow.",
                    _position(position, self.filename, len(str(event))),
                )

    def _check_job(
        self, job_key: str, node_id: str, job: dict[str, Any], jobs: Any
    ) -> None:
        """A job needs `runs-on`, and each step exactly one of `uses` or `run`."""
        job_position = _key_position(jobs, job_key)
        self._check_unknown_keys(job, JOB_KEYS, f"a key of job '{job_key}'", node_id)
        self._check_if_secrets(job, f"job '{job_key}'", node_id)
        # A job that calls a reusable workflow (`uses:` on the job) has no
        # runner and no steps of its own.
        if "uses" in job:
            self._check_reusable_call(job_key, node_id, job)
            return

        if "runs-on" not in job:
            self._schema_error(
                f"Job '{job_key}' is missing 'runs-on', so GitHub does not know "
                "which runner to use.",
                _position(job_position, self.filename, len(job_key)),
                node_id,
            )

        steps = job.get("steps")
        if steps is None:
            return
        if not isinstance(steps, list):
            self._schema_error(
                f"'steps' in job '{job_key}' must be a list of steps.",
                _value_position(job, "steps"),
                node_id,
            )
            return

        for index, step in enumerate(steps):
            position = _position(_item_position(steps, index), self.filename)
            label = f"Step {index + 1} of job '{job_key}'"
            if isinstance(step, dict) and step.get("name"):
                label += f" ('{step['name']}')"
            if not isinstance(step, dict):
                self._schema_error(f"{label} must be a mapping.", position, node_id)
            elif "uses" in step and "run" in step:
                self._schema_error(
                    f"{label} has both 'uses' and 'run'; a step must have exactly one.",
                    position,
                    node_id,
                )
            elif "uses" not in step and "run" not in step:
                self._schema_error(
                    f"{label} has neither 'uses' nor 'run', so it does nothing. "
                    "A step must have exactly one of them.",
                    position,
                    node_id,
                )
            if isinstance(step, dict):
                self._check_if_secrets(step, f"{label[0].lower()}{label[1:]}", node_id)
                self._check_unknown_keys(
                    step, STEP_KEYS, f"a key of {label[0].lower()}{label[1:]}", node_id
                )


def _duplicate_key_finding(
    exc: DuplicateKeyError, parsed: Any, filename: str | None
) -> Finding:
    """Report a repeated key: a duplicate job ID, or invalid YAML elsewhere.

    YAML requires keys in a mapping to be unique, and most tools silently keep
    only one value. Only a repeated key directly under `jobs` is a duplicate
    graph node; anywhere else it is a YAML error.
    """
    match = _DUPLICATE_KEY.search(exc.problem or "")
    key = match.group(1) if match else "?"
    problem, context = exc.problem_mark, exc.context_mark
    loc = None
    if problem is not None:
        loc = SourceLocation(
            file=filename,
            start_line=problem.line + 1,
            start_column=problem.column + 1,
            end_line=problem.line + 1,
            end_column=problem.column + 1 + len(key) if match else None,
        )

    jobs = parsed.get("jobs") if isinstance(parsed, dict) else None
    under_jobs = (
        context is not None
        and hasattr(jobs, "lc")
        and (jobs.lc.line, jobs.lc.col) == (context.line, context.column)
    )
    if under_jobs:
        base_id = make_node_id(ID_PREFIX, "job", key)
        return make_finding(
            DiagnosticCode.DUPLICATE_NODE_ID,
            Severity.error,
            f"Duplicate job ID '{key}'; only the first definition is analysed.",
            loc,
            node_ids=(base_id,),
            details={"job": key},
        )
    where = f" in the mapping starting on line {context.line + 1}" if context else ""
    return make_finding(
        DiagnosticCode.YAML_SYNTAX_ERROR,
        Severity.error,
        f"Duplicate key '{key}'{where}. YAML keys must be unique; most tools "
        "silently keep only one of the values. Check the indentation too: a "
        "mis-indented block can merge two mappings.",
        loc,
    )


class YamlAdapter:
    """SourceAdapter implementation for GitHub Actions / YAML workflows."""

    format = SourceFormat.yaml

    def parse(self, source: str, filename: str | None) -> ParseResult:
        yaml = YAML(typ="rt")
        duplicate_findings: list[Finding] = []
        try:
            parsed = yaml.load(io.StringIO(source))
        except DuplicateKeyError as exc:
            # Re-parse allowing duplicate keys so graph extraction can continue
            yaml_dup = YAML(typ="rt")
            yaml_dup.allow_duplicate_keys = True
            try:
                parsed = yaml_dup.load(io.StringIO(source))
            except Exception:
                parsed = None
            duplicate_findings.append(_duplicate_key_finding(exc, parsed, filename))
            if parsed is None:
                return ParseResult(ir=None, findings=duplicate_findings)
        except MarkedYAMLError as exc:
            loc: SourceLocation | None = None
            if exc.problem_mark is not None:
                loc = SourceLocation(
                    file=filename,
                    start_line=exc.problem_mark.line + 1,
                    start_column=exc.problem_mark.column + 1,
                )
            finding = make_finding(
                DiagnosticCode.YAML_SYNTAX_ERROR,
                Severity.error,
                f"YAML syntax error: {exc.problem or str(exc)}",
                loc,
            )
            return ParseResult(ir=None, findings=[finding])
        except Exception as exc:
            finding = make_finding(
                DiagnosticCode.YAML_SYNTAX_ERROR,
                Severity.error,
                f"YAML syntax error: {exc}",
                SourceLocation(file=filename, start_line=1, start_column=1),
            )
            return ParseResult(ir=None, findings=[finding])

        extractor = _YamlExtractor(filename, source)
        ir = extractor.extract(parsed)
        jobs = parsed.get("jobs") if isinstance(parsed, dict) else None
        rule_findings = (
            run_github_actions_rules(jobs, source, filename, extractor.job_to_id)
            if isinstance(jobs, dict)
            else []
        )
        return ParseResult(
            ir=ir,
            findings=[*duplicate_findings, *extractor.findings, *rule_findings],
            dependency_analysis_complete=extractor.complete,
        )


ADAPTER = YamlAdapter()
