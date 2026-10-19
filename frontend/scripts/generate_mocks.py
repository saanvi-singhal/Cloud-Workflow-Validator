"""Regenerate frontend/src/mocks/*.json from the real compiler core.

Run from the repository root with the backend venv:

    .venv/bin/python frontend/scripts/generate_mocks.py

* terraform.json, terraform-cycle.json, terraform-partial.json: real
  ``compile_source`` output for ``frontend/src/samples/main.tf``,
  ``examples/terraform/cyclic.tf`` and
  ``examples/terraform/unsupported_expression.tf``.
* yaml.json, dockerfile.json: the GitHub Actions and Dockerfile parsers do not
  exist yet, so this script builds the IR those parsers are specified to
  produce (PROJECT_SPEC 3, 4.1, 4.2) for ``samples/ci.yml`` and
  ``samples/Dockerfile`` and runs it through the real analysis pipeline
  (``analyze_ir``). Replace these with ``compile_source`` once the parsers exist.

Mocks are only used when ``VITE_USE_MOCK=true``.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from app.compiler.adapters import ParseResult  # noqa: E402
from app.compiler.ir import IRGraph, make_node_id  # noqa: E402
from app.compiler.pipeline import analyze_ir, compile_source  # noqa: E402
from app.models import (  # noqa: E402
    Edge,
    EdgeType,
    Node,
    NodeType,
    SourceFormat,
    SourceLocation,
)

SAMPLES = REPO / "frontend" / "src" / "samples"
MOCKS = REPO / "frontend" / "src" / "mocks"


def span(file: str, lines: list[str], first: int, last: int) -> SourceLocation:
    """1-based span from the start of line ``first`` to the end of ``last``.

    end_column is exclusive (PROJECT_SPEC 3.3).
    """
    return SourceLocation(
        file=file,
        start_line=first,
        start_column=1,
        end_line=last,
        end_column=len(lines[last - 1]) + 1,
    )


def word(file: str, lines: list[str], line: int, text: str) -> SourceLocation:
    """Span of ``text`` on 1-based ``line``."""
    column = lines[line - 1].index(text) + 1
    return SourceLocation(
        file=file,
        start_line=line,
        start_column=column,
        end_line=line,
        end_column=column + len(text),
    )


def github_actions_ir(file: str, text: str) -> IRGraph:
    """IR a GitHub Actions parser must produce: one task per job, needs -> edges."""
    lines = text.splitlines()
    starts = [
        (i + 1, m.group(1))
        for i, line in enumerate(lines)
        if (m := re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line))
    ]
    nodes, edges = [], []
    for k, (start, job) in enumerate(starts):
        end = starts[k + 1][0] - 1 if k + 1 < len(starts) else len(lines)
        body = lines[start:end]
        runs_on = next(
            (b.split(":", 1)[1].strip() for b in body if "runs-on:" in b), None
        )
        needs: list[str] = []
        for offset, b in enumerate(body):
            m = re.search(r"needs:\s*\[(.*)\]", b)
            if m:
                needs = [n.strip() for n in m.group(1).split(",") if n.strip()]
                needs_line = start + 1 + offset
        nodes.append(
            Node(
                id=make_node_id("gha", "job", job),
                label=job,
                type=NodeType.task,
                source_location=span(file, lines, start, end),
                metadata={"job_id": job, "runs_on": runs_on, "needs": needs},
            )
        )
        for need in needs:
            edges.append(
                Edge(
                    source=make_node_id("gha", "job", need),
                    target=make_node_id("gha", "job", job),
                    type=EdgeType.workflow_dependency,
                    label="needs",
                    source_location=word(file, lines, needs_line, need),
                )
            )
    return IRGraph(format=SourceFormat.yaml, nodes=nodes, edges=edges)


def dockerfile_ir(file: str, text: str) -> IRGraph:
    """IR a Dockerfile parser must produce: one stage node per FROM (spec 4.2)."""
    lines = text.splitlines()
    froms = [
        (i + 1, m.group(1), m.group(2))
        for i, line in enumerate(lines)
        if (m := re.match(r"^FROM\s+(\S+)(?:\s+AS\s+(\S+))?", line, re.IGNORECASE))
    ]
    aliases = {alias: index for index, (_, _, alias) in enumerate(froms) if alias}
    nodes, edges = [], []
    for index, (start, base, alias) in enumerate(froms):
        end = froms[index + 1][0] - 1 if index + 1 < len(froms) else len(lines)
        while end > start and not lines[end - 1].strip():
            end -= 1
        node_id = make_node_id("docker", "stage", str(index))
        instructions = [
            {
                "line": n,
                "instruction": lines[n - 1].split()[0].upper(),
                "text": lines[n - 1],
            }
            for n in range(start, end + 1)
            if lines[n - 1].strip()
        ]
        nodes.append(
            Node(
                id=node_id,
                label=alias or f"stage {index}",
                type=NodeType.stage,
                source_location=span(file, lines, start, end),
                metadata={
                    "stage_index": index,
                    "is_final_stage": index == len(froms) - 1,
                    "alias": alias,
                    "base": base,
                    "instructions": instructions,
                },
            )
        )
        if base in aliases:
            edges.append(
                Edge(
                    source=make_node_id("docker", "stage", str(aliases[base])),
                    target=node_id,
                    type=EdgeType.docker_stage_base,
                    label=f"FROM {base}",
                    source_location=word(file, lines, start, base),
                )
            )
    return IRGraph(format=SourceFormat.dockerfile, nodes=nodes, edges=edges)


def write(name: str, result) -> None:
    path = MOCKS / name
    path.write_text(json.dumps(result.model_dump(mode="json"), indent=2) + "\n")
    print(f"wrote {path.relative_to(REPO)}")


def main() -> None:
    MOCKS.mkdir(exist_ok=True)
    tf = (SAMPLES / "main.tf").read_text()
    write("terraform.json", compile_source(tf, SourceFormat.terraform, "main.tf"))
    cyclic = (REPO / "examples" / "terraform" / "cyclic.tf").read_text()
    write(
        "terraform-cycle.json",
        compile_source(cyclic, SourceFormat.terraform, "cyclic.tf"),
    )
    partial = (REPO / "examples/terraform/unsupported_expression.tf").read_text()
    write(
        "terraform-partial.json",
        compile_source(partial, SourceFormat.terraform, "unsupported_expression.tf"),
    )
    yml = (SAMPLES / "ci.yml").read_text()
    write(
        "yaml.json",
        analyze_ir(ParseResult(github_actions_ir("ci.yml", yml)), SourceFormat.yaml),
    )
    docker = (SAMPLES / "Dockerfile").read_text()
    write(
        "dockerfile.json",
        analyze_ir(
            ParseResult(dockerfile_ir("Dockerfile", docker)), SourceFormat.dockerfile
        ),
    )


if __name__ == "__main__":
    main()
