"""Workflow rules GitHub enforces in its parser code rather than in its schema.

``schema.py`` checks structure against GitHub's own schema file. These are
the other checks GitHub runs when it loads a workflow and rejects it with
"Invalid workflow file":

==========================  ===================================================
rule                        GitHub's message / behaviour
==========================  ===================================================
filter pairs                "you may only define one of branches and
                            branches-ignore for a single event" (also tags,
                            paths)
id format                   job and step ids "may only contain alphanumeric
                            characters, '_', and '-'" and "must start with a
                            letter or '_'"
duplicate step id           "The identifier 'x' may not be used more than once
                            within the same scope"
cron                        a schedule's cron must be five valid fields
step ``uses``               ``{owner}/{repo}[/{path}]@{ref}``, ``./{path}`` or
                            ``docker://{image}``
job ``uses``                ``{owner}/{repo}/.github/workflows/{file}@{ref}`` or
                            ``./.github/workflows/{file}`` (a .yml/.yaml file)
choice input                a ``workflow_dispatch`` input of type ``choice``
                            needs ``options``
==========================  ===================================================
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from typing import Any

from app.parsers.yaml.schema import Position, Problem

FILTER_PAIRS = (
    ("branches", "branches-ignore"),
    ("tags", "tags-ignore"),
    ("paths", "paths-ignore"),
)
ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
STEP_USES = re.compile(r"^(docker://\S+|\./\S*|[^\s/@]+/[^\s/@]+(/[^\s@]+)?@\S+)$")
JOB_USES = re.compile(
    r"^(\./\.github/workflows/[^\s@]+\.ya?ml"
    r"|[^\s/@]+/[^\s/@]+/\.github/workflows/[^\s@]+\.ya?ml@\S+)$"
)

# cron fields: (name, lowest, highest, names allowed)
_MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()
_DAYS = "sun mon tue wed thu fri sat".split()
CRON_FIELDS = (
    ("minute", 0, 59, None),
    ("hour", 0, 23, None),
    ("day of month", 1, 31, None),
    ("month", 1, 12, _MONTHS),
    ("day of week", 0, 6, _DAYS),
)


def _pos(mapping: Any, key: Any, value: bool = True) -> Position:
    try:
        return tuple(mapping.lc.value(key) if value else mapping.lc.key(key))  # type: ignore[return-value]
    except Exception:
        return None


def _item_pos(sequence: Any, index: int) -> Position:
    try:
        return tuple(sequence.lc.item(index))  # type: ignore[return-value]
    except Exception:
        return None


def _cron_value(text: str, names: list[str] | None) -> int | None:
    if text.isdigit():
        return int(text)
    if names and text.lower() in names:
        return names.index(text.lower()) + (1 if names is _MONTHS else 0)
    return None


def cron_problem(cron: str) -> str | None:
    """Why a cron expression is invalid, or None (POSIX five-field syntax)."""
    fields = cron.split()
    if len(fields) != 5:
        return f"has {len(fields)} field(s); a schedule needs five (minute hour day month weekday)"
    for text, (name, low, high, names) in zip(fields, CRON_FIELDS, strict=True):
        for part in text.split(","):
            base, _, step = part.partition("/")
            if step and (not step.isdigit() or int(step) == 0):
                return f"has an invalid step '/{step}' in the {name} field"
            if base == "*":
                continue
            ends = base.split("-")
            if len(ends) > 2 or not all(ends):
                return f"has an invalid {name} '{part}'"
            values = [_cron_value(e, names) for e in ends]
            # GitHub accepts 7 as Sunday in the weekday field.
            top = 7 if name == "day of week" else high
            if any(v is None or not low <= v <= top for v in values):
                return f"has {name} '{part}', outside {low}-{high}"
            if len(values) == 2 and values[0] > values[1]:  # type: ignore[operator]
                return f"has a backwards range '{part}' in the {name} field"
    return None


def check(data: Any) -> list[Problem]:
    """Problems GitHub reports from code, in a parsed workflow."""
    return list(_check(data))


def _check(data: Any) -> Iterator[Problem]:
    if not isinstance(data, Mapping):
        return
    on = data.get("on")
    if isinstance(on, Mapping):
        for event, spec in on.items():
            if not isinstance(spec, Mapping):
                continue
            for first, second in FILTER_PAIRS:
                if first in spec and second in spec:
                    yield Problem(
                        f"on.{event} has both '{first}' and '{second}'; GitHub only "
                        f"allows one of them for a single event.",
                        _pos(spec, second, value=False),
                        f"on.{event}",
                    )
        schedule = on.get("schedule")
        if isinstance(schedule, list):
            for i, item in enumerate(schedule):
                cron = item.get("cron") if isinstance(item, Mapping) else None
                if isinstance(cron, str) and (problem := cron_problem(cron)):
                    yield Problem(
                        f"The schedule cron '{cron}' {problem}.",
                        _pos(item, "cron") or _item_pos(schedule, i),
                        f"on.schedule[{i}]",
                    )
        dispatch = on.get("workflow_dispatch")
        inputs = dispatch.get("inputs") if isinstance(dispatch, Mapping) else None
        if isinstance(inputs, Mapping):
            for name, spec in inputs.items():
                if isinstance(spec, Mapping) and spec.get("type") == "choice":
                    if not spec.get("options"):
                        yield Problem(
                            f"Input '{name}' has type 'choice' but no options to choose from.",
                            _pos(inputs, name, value=False),
                            f"on.workflow_dispatch.inputs.{name}",
                        )
                    elif "default" in spec and spec["default"] not in spec["options"]:
                        yield Problem(
                            f"Input '{name}' has default '{spec['default']}', which is not "
                            "one of its options.",
                            _pos(spec, "default"),
                            f"on.workflow_dispatch.inputs.{name}",
                        )

    jobs = data.get("jobs")
    if not isinstance(jobs, Mapping):
        return
    for job_id, job in jobs.items():
        job_text = str(job_id)
        if not ID.match(job_text):
            yield Problem(
                f"Job id '{job_text}' is invalid: ids may only contain letters, digits, "
                "'_' and '-', and must start with a letter or '_'.",
                _pos(jobs, job_id, value=False),
                f"jobs.{job_text}",
            )
        if not isinstance(job, Mapping):
            continue
        uses = job.get("uses")
        if isinstance(uses, str) and "${{" not in uses and not JOB_USES.match(uses):
            yield Problem(
                f"Job '{job_text}' uses '{uses}', which is not a reusable workflow "
                "reference: use {owner}/{repo}/.github/workflows/{file}.yml@{ref} or "
                "./.github/workflows/{file}.yml.",
                _pos(job, "uses"),
                f"jobs.{job_text}.uses",
            )
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        seen: dict[str, int] = {}
        for i, step in enumerate(steps):
            if not isinstance(step, Mapping):
                continue
            step_id = step.get("id")
            if isinstance(step_id, str) and "${{" not in step_id:
                where = f"jobs.{job_text}.steps[{i}]"
                if not ID.match(step_id):
                    yield Problem(
                        f"Step id '{step_id}' is invalid: ids may only contain letters, "
                        "digits, '_' and '-', and must start with a letter or '_'.",
                        _pos(step, "id"),
                        where,
                    )
                elif step_id in seen:
                    yield Problem(
                        f"Step id '{step_id}' is used more than once in job '{job_text}' "
                        f"(first by step {seen[step_id] + 1}); step ids must be unique.",
                        _pos(step, "id"),
                        where,
                    )
                else:
                    seen[step_id] = i
            step_uses = step.get("uses")
            if (
                isinstance(step_uses, str)
                and "${{" not in step_uses
                and not STEP_USES.match(step_uses)
            ):
                yield Problem(
                    f"Step {i + 1} of job '{job_text}' uses '{step_uses}': an action "
                    "is {owner}/{repo}[/{path}]@{ref}, ./{path} or docker://{image}"
                    + (" (the @ref is required)." if "@" not in step_uses else "."),
                    _pos(step, "uses"),
                    f"jobs.{job_text}.steps[{i}]",
                )
