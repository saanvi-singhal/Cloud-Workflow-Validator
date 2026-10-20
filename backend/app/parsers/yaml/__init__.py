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

ID_PREFIX = FORMAT_ID_PREFIX[SourceFormat.yaml]

_DUPLICATE_KEY = re.compile(r'duplicate key "(.*?)"')


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

    def __init__(self, filename: str | None) -> None:
        self.filename = filename
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

        return IRGraph(format=SourceFormat.yaml, nodes=self.nodes, edges=self.edges)


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

        extractor = _YamlExtractor(filename)
        ir = extractor.extract(parsed)
        return ParseResult(
            ir=ir,
            findings=[*duplicate_findings, *extractor.findings],
            dependency_analysis_complete=extractor.complete,
        )


ADAPTER = YamlAdapter()
