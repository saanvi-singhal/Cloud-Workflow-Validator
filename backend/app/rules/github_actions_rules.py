"""Deterministic GitHub Actions workflow rules (spec 6.3).

Schema violations that make GitHub reject a workflow are checked by the YAML
parser itself. The rules here flag workflows GitHub *accepts* but that very
likely do not do what the author meant. Each finding is
``SECURITY_RULE_VIOLATION`` with a stable ``rule_id``, linked to the job node.

======================  ========  ============================================
rule_id                 severity  fires when
======================  ========  ============================================
GHA_NUMBER_LOSES_ZERO   warning   an unquoted number with a trailing zero in
                                  its fraction (``3.10``, ``18.0``). YAML reads
                                  it as a number, so GitHub passes ``3.1`` or
                                  ``18``: a matrix of ``[3.10]`` tests Python 3.1
GHA_SCRIPT_INJECTION    warning   ``${{ ... }}`` with attacker-controlled
                                  event data (issue/PR title or body, comment
                                  body, branch name, commit message, ...)
                                  inside ``run`` or ``actions/github-script``'s
                                  ``script``. GitHub pastes the value into the
                                  script before it runs, so it can inject
                                  commands
GHA_UNPINNED_ACTION     warning   a step or job ``uses`` an action or reusable
                                  workflow by a branch (``@main``,
                                  ``@master``) or with no ref. Whoever can push
                                  to that branch changes what your workflow
                                  runs; a version tag or commit SHA does not
                                  move silently
======================  ========  ============================================
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from typing import Any

from app.compiler.findings import Finding, make_finding
from app.models import DiagnosticCode, Severity, SourceLocation

RULE_NUMBER_LOSES_ZERO = "GHA_NUMBER_LOSES_ZERO"
RULE_SCRIPT_INJECTION = "GHA_SCRIPT_INJECTION"
RULE_UNPINNED_ACTION = "GHA_UNPINNED_ACTION"

# Refs that do not move on their own: a full commit SHA or a version tag
# (v4, v4.1.2, 1.0.0-beta). Anything else is treated as a branch.
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_VERSION_TAG = re.compile(r"^v?\d+(?:\.\d+)*(?:[-+.][0-9A-Za-z.]+)?$")

_EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
_ITEM = r"(?:\.\*|\[[^\]]*\]|\.\w+)"  # commits.*  commits[0]
# Event fields anyone who can open an issue, comment or push a branch controls
# (https://docs.github.com/actions/security-for-github-actions/security-guides/
# security-hardening-for-github-actions#understanding-the-risk-of-script-injections).
_UNTRUSTED = re.compile(
    r"\bgithub\.(?:head_ref\b|event\.(?:"
    r"issue\.(?:title|body)"
    r"|pull_request\.(?:title|body|head\.(?:ref|label|repo\.default_branch))"
    r"|(?:comment|review|review_comment)\.body"
    r"|discussion\.(?:title|body)"
    rf"|pages{_ITEM}\.page_name"
    rf"|commits{_ITEM}\.(?:message|author\.(?:email|name))"
    r"|head_commit\.(?:message|author\.(?:email|name))"
    r"|workflow_run\.(?:head_branch|head_commit\.(?:message|author\.(?:email|name)))"
    r")\b)"
)

# A plain YAML scalar ends at whitespace, a flow separator or a comment.
_PLAIN_SCALAR = re.compile(r"[^\s,\]\}#]+")
_TRAILING_ZERO = re.compile(r"^[-+]?\d*\.\d*0$")


def _positioned_values(node: Any) -> Iterator[tuple[Any, tuple[int, int] | None]]:
    """Yield every scalar under ``node`` with its 0-based (line, col)."""
    if isinstance(node, Mapping):
        for key, value in node.items():
            if isinstance(value, (Mapping, list)):
                yield from _positioned_values(value)
            else:
                try:
                    yield value, node.lc.value(key)
                except Exception:
                    yield value, None
    elif isinstance(node, list):
        for index, value in enumerate(node):
            if isinstance(value, (Mapping, list)):
                yield from _positioned_values(value)
            else:
                try:
                    yield value, node.lc.item(index)
                except Exception:
                    yield value, None


def check_numbers_losing_zero(
    jobs: Mapping[str, Any],
    lines: list[str],
    filename: str | None,
    job_ids: Mapping[str, str],
) -> Iterator[Finding]:
    for job_key, job in jobs.items():
        if not isinstance(job, Mapping):
            continue
        for value, position in _positioned_values(job):
            # bool is an int subclass, never a float; only floats lose digits.
            if not isinstance(value, float) or position is None:
                continue
            line, col = position
            if line >= len(lines):
                continue
            match = _PLAIN_SCALAR.match(lines[line], col)
            text = match.group(0) if match else ""
            if not _TRAILING_ZERO.match(text):
                continue
            seen = f"{value:g}"
            node_id = job_ids.get(str(job_key))
            yield make_finding(
                DiagnosticCode.SECURITY_RULE_VIOLATION,
                Severity.warning,
                f"[{RULE_NUMBER_LOSES_ZERO}] '{text}' is not quoted, so YAML "
                f"reads it as a number and GitHub passes '{seen}', not '{text}'. "
                f'Quote it ("{text}") if it is a version.',
                SourceLocation(
                    file=filename,
                    start_line=line + 1,
                    start_column=col + 1,
                    end_line=line + 1,
                    end_column=col + 1 + len(text),
                ),
                rule_id=RULE_NUMBER_LOSES_ZERO,
                node_ids=(node_id,) if node_id else (),
                details={"text": text, "seen": seen},
            )


def _offset(lines: list[str], line: int, col: int) -> int:
    return sum(len(text) + 1 for text in lines[:line]) + col


def _line_col(source: str, offset: int) -> tuple[int, int]:
    line = source.count("\n", 0, offset)
    return line, offset - (source.rfind("\n", 0, offset) + 1)


def _scripts(job: Mapping[str, Any]) -> Iterator[tuple[Mapping[str, Any], str]]:
    """(mapping, key) for every script GitHub runs: ``run`` and github-script."""
    steps = job.get("steps")
    if not isinstance(steps, list):
        return
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        if isinstance(step.get("run"), str):
            yield step, "run"
        uses = step.get("uses")
        inputs = step.get("with")
        if (
            isinstance(uses, str)
            and uses.startswith("actions/github-script")
            and isinstance(inputs, Mapping)
            and isinstance(inputs.get("script"), str)
        ):
            yield inputs, "script"


def check_script_injection(
    jobs: Mapping[str, Any],
    source: str,
    lines: list[str],
    filename: str | None,
    job_ids: Mapping[str, str],
) -> Iterator[Finding]:
    for job_key, job in jobs.items():
        if not isinstance(job, Mapping):
            continue
        node_id = job_ids.get(str(job_key))
        for mapping, key in _scripts(job):
            try:
                line, col = mapping.lc.value(key)
            except Exception:
                continue
            search_from = _offset(lines, line, col)
            for match in _EXPRESSION.finditer(mapping[key]):
                untrusted = _UNTRUSTED.search(match.group(1))
                if untrusted is None:
                    continue
                text = match.group(0)
                # Locate the expression in the source (block scalars start at `|`).
                found = source.find(text, search_from)
                location = None
                if found != -1:
                    search_from = found + len(text)
                    start = _line_col(source, found)
                    end = _line_col(source, found + len(text))
                    location = SourceLocation(
                        file=filename,
                        start_line=start[0] + 1,
                        start_column=start[1] + 1,
                        end_line=end[0] + 1,
                        end_column=end[1] + 1,
                    )
                field = untrusted.group(0)
                yield make_finding(
                    DiagnosticCode.SECURITY_RULE_VIOLATION,
                    Severity.warning,
                    f"[{RULE_SCRIPT_INJECTION}] '{field}' is controlled by whoever "
                    f"triggers the workflow, and GitHub pastes it into the "
                    f"{key} script before it runs, so it can inject shell "
                    "commands. Pass it through an env variable instead.",
                    location,
                    rule_id=RULE_SCRIPT_INJECTION,
                    node_ids=(node_id,) if node_id else (),
                    details={"expression": text, "field": field, "key": key},
                )


def _uses(job: Mapping[str, Any]) -> Iterator[tuple[Mapping[str, Any], str]]:
    """(mapping, value) for a reusable-workflow call and every step's ``uses``."""
    if isinstance(job.get("uses"), str):
        yield job, job["uses"]
    steps = job.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, Mapping) and isinstance(step.get("uses"), str):
                yield step, step["uses"]


def check_unpinned_actions(
    jobs: Mapping[str, Any],
    lines: list[str],
    filename: str | None,
    job_ids: Mapping[str, str],
) -> Iterator[Finding]:
    for job_key, job in jobs.items():
        if not isinstance(job, Mapping):
            continue
        node_id = job_ids.get(str(job_key))
        for mapping, uses in _uses(job):
            # Local actions are part of the repository; docker:// images are
            # covered by image pinning, not by this rule.
            if uses.startswith(("./", "docker://")):
                continue
            action, _, ref = uses.partition("@")
            if ref and (_FULL_SHA.match(ref) or _VERSION_TAG.match(ref)):
                continue
            location = None
            try:
                line, col = mapping.lc.value("uses")
                if line < len(lines) and lines[line].startswith(uses, col):
                    location = SourceLocation(
                        file=filename,
                        start_line=line + 1,
                        start_column=col + 1,
                        end_line=line + 1,
                        end_column=col + 1 + len(uses),
                    )
                else:
                    location = SourceLocation(
                        file=filename, start_line=line + 1, start_column=col + 1
                    )
            except Exception:
                pass
            problem = f"the branch '{ref}'" if ref else "no version"
            yield make_finding(
                DiagnosticCode.SECURITY_RULE_VIOLATION,
                Severity.warning,
                f"[{RULE_UNPINNED_ACTION}] '{uses}' uses {problem}, so whoever "
                "can push to it changes the code this workflow runs, with your "
                "repository's token and secrets. Pin a release tag or, safest, a "
                "full commit SHA.",
                location,
                rule_id=RULE_UNPINNED_ACTION,
                node_ids=(node_id,) if node_id else (),
                details={"uses": uses, "action": action, "ref": ref},
            )


def run_github_actions_rules(
    jobs: Mapping[str, Any],
    source: str,
    filename: str | None,
    job_ids: Mapping[str, str],
) -> list[Finding]:
    """Run every rule over the parsed ``jobs`` mapping."""
    lines = source.split("\n")
    return [
        *check_numbers_losing_zero(jobs, lines, filename, job_ids),
        *check_script_injection(jobs, source, lines, filename, job_ids),
        *check_unpinned_actions(jobs, lines, filename, job_ids),
    ]
