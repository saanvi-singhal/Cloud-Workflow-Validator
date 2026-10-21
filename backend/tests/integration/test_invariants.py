"""Invariants that must hold for every analysis result, on real and mutated input.

The corpus is every example, fixture and frontend sample; each is also run
after seeded random mutations (deleted/duplicated/shuffled lines, truncation,
inserted garbage). A larger version of this run (about 50,000 inputs) found
crashes and out-of-range spans that the hand-written tests missed.
"""

import random
from pathlib import Path

import pytest

from app.compiler.pipeline import compile_source
from app.models import SourceFormat
from app.recommendations.catalog import SECURITY_RECOMMENDATIONS

pytestmark = [pytest.mark.integration]

REPO = Path(__file__).resolve().parents[3]
MUTATIONS_PER_FILE = 30
FORMAT_OF = {
    ".tf": SourceFormat.terraform,
    ".yml": SourceFormat.yaml,
    ".yaml": SourceFormat.yaml,
}


def _format_for(path: Path) -> SourceFormat | None:
    if path.suffix in FORMAT_OF:
        return FORMAT_OF[path.suffix]
    if "dockerfile" in path.name.lower():
        return SourceFormat.dockerfile
    return None


CORPUS = sorted(
    (path, fmt)
    for root in ("examples", "backend/tests/fixtures", "frontend/src/samples")
    for path in (REPO / root).rglob("*")
    if path.is_file() and (fmt := _format_for(path)) is not None
)


def check(source: str, fmt) -> list[str]:
    """Return every broken invariant for ``source`` (empty when all hold)."""
    problems = []
    result = compile_source(source, fmt, "f")
    lines = source.split("\n")
    nodes = {n.id for n in result.graph.nodes}
    if len(nodes) != len(result.graph.nodes):
        problems.append("duplicate node ids")
    errors = [d for d in result.diagnostics if d.severity.value == "error"]
    if result.valid != (not errors):
        problems.append(f"valid={result.valid} but {len(errors)} errors")
    for d in result.diagnostics:
        loc = d.source_location
        if loc is None or loc.start_line is None:
            continue
        if not 1 <= loc.start_line <= len(lines) + 1:
            problems.append(
                f"{d.code.value} start_line {loc.start_line} outside 1..{len(lines)}"
            )
            continue
        if loc.end_line is not None:
            if loc.end_line < loc.start_line:
                problems.append(f"{d.code.value} end_line before start")
            elif loc.end_line > len(lines) + 1:
                problems.append(
                    f"{d.code.value} end_line {loc.end_line} > {len(lines)}"
                )
            if (
                loc.end_column is not None
                and loc.start_column is not None
                and loc.end_line == loc.start_line
                and loc.end_column < loc.start_column
            ):
                problems.append(f"{d.code.value} end_column before start_column")
            if (
                loc.end_column is not None
                and loc.end_line is not None
                and loc.end_line <= len(lines)
                and loc.end_column > len(lines[loc.end_line - 1]) + 2
            ):
                problems.append(
                    f"{d.code.value} end_column {loc.end_column} past line "
                    f"{loc.end_line} (len {len(lines[loc.end_line - 1])}): "
                    f"{d.message[:60]}"
                )
        if (
            loc.start_column is not None
            and loc.start_line <= len(lines)
            and loc.start_column > len(lines[loc.start_line - 1]) + 1
        ):
            problems.append(
                f"{d.code.value} start_column {loc.start_column} past line len "
                f"{len(lines[loc.start_line - 1])}: {d.message[:60]}"
            )
        if d.code.value == "SECURITY_RULE_VIOLATION":
            rule = d.message.split("]")[0].lstrip("[")
            if rule not in SECURITY_RECOMMENDATIONS:
                problems.append(f"rule {rule} has no specific recommendation")
    for e in result.graph.edges:
        if e.source not in nodes or e.target not in nodes:
            problems.append(f"dangling edge {e.source}->{e.target}")
    ids = [r.id for r in result.recommendations]
    if len(ids) != len(set(ids)):
        problems.append("duplicate recommendation ids")
    for r in result.recommendations:
        if not 0 <= r.diagnostic_index < len(result.diagnostics):
            problems.append(f"rec {r.id} index out of range")
        elif result.diagnostics[r.diagnostic_index].code != r.diagnostic_code:
            problems.append(f"rec {r.id} code mismatch")
        if not set(r.related_node_ids) <= nodes:
            problems.append(
                f"rec {r.id} links unknown nodes {set(r.related_node_ids) - nodes}"
            )
        if r.rule_id == "SECURITY_REVIEW":
            problems.append("generic security recommendation used")
    order = result.execution_order
    if order is not None:
        if sorted(order) != sorted(nodes):
            problems.append("execution_order is not a permutation of nodes")
        pos = {n: i for i, n in enumerate(order)}
        for e in result.graph.edges:
            if e.source in pos and e.target in pos and pos[e.source] >= pos[e.target]:
                problems.append(f"order violates edge {e.source}->{e.target}")
        if errors:
            problems.append("execution_order set despite errors")
    if fmt is SourceFormat.dockerfile and order is not None:
        problems.append("dockerfile has an execution order")
    again = compile_source(source, fmt, "f")
    if again.model_dump_json() != result.model_dump_json():
        problems.append("non-deterministic output")
    return problems


GARBAGE = [
    "",
    " ",
    "\n",
    "\t",
    "{",
    "}",
    "[",
    "]",
    ":",
    "- ",
    "${{",
    "}}",
    "\\",
    '"',
    "'",
    "#",
    "&a",
    "*a",
    "!!",
    "\x00",
    "é",
    "🙂",
    "\r\n",
    "FROM",
    "RUN",
    "resource",
    "=",
    "COPY --from=",
    "needs:",
    "jobs:",
    "dynamic",
    "${",
    "%{",
    "<<EOF",
    "<<-EOT",
    "0.0",
    " ",
    "ONBUILD",
    "HEALTHCHECK",
    "uses:",
    "with:",
]


def mutate(text: str, rng: random.Random) -> str:
    lines = text.split("\n")
    op = rng.randrange(9)
    if op == 0 and lines:
        del lines[rng.randrange(len(lines))]
    elif op == 1 and lines:
        i = rng.randrange(len(lines))
        lines.insert(i, lines[i])
    elif op == 2:
        rng.shuffle(lines)
    elif op == 3:
        return text[: rng.randrange(len(text) + 1)]
    elif op == 4 and text:
        i = rng.randrange(len(text))
        return text[:i] + rng.choice(GARBAGE) + text[i:]
    elif op == 5 and text:
        i, j = sorted(rng.randrange(len(text)) for _ in range(2))
        return text[:i] + text[j:]
    elif op == 6 and lines:
        i = rng.randrange(len(lines))
        lines[i] = " " * rng.randrange(6) + lines[i].lstrip()
    elif op == 7:
        return "".join(rng.choice(GARBAGE) for _ in range(rng.randrange(1, 40)))
    else:
        for _ in range(rng.randrange(1, 4)):
            text = mutate(text, rng)
        return text
    return "\n".join(lines)


def test_corpus_was_found():
    formats = {fmt for _, fmt in CORPUS}
    assert formats == set(SourceFormat)
    assert len(CORPUS) >= 30


@pytest.mark.parametrize(
    ("path", "fmt"), CORPUS, ids=[str(p.relative_to(REPO)) for p, _ in CORPUS]
)
def test_invariants_hold_on_file_and_mutations(path, fmt):
    rng = random.Random(path.name)
    text = path.read_text()
    inputs = [text] + [mutate(text, rng) for _ in range(MUTATIONS_PER_FILE)]
    for source in inputs:
        assert check(source, fmt) == [], source
