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
======================  ========  ============================================
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from typing import Any

from app.compiler.findings import Finding, make_finding
from app.models import DiagnosticCode, Severity, SourceLocation

RULE_NUMBER_LOSES_ZERO = "GHA_NUMBER_LOSES_ZERO"

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


def run_github_actions_rules(
    jobs: Mapping[str, Any],
    source: str,
    filename: str | None,
    job_ids: Mapping[str, str],
) -> list[Finding]:
    """Run every rule over the parsed ``jobs`` mapping."""
    lines = source.splitlines()
    return list(check_numbers_losing_zero(jobs, lines, filename, job_ids))
