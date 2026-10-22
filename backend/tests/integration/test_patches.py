"""Every generated patch applies with ``git apply`` and fixes its diagnostic.

For each recommendation that carries a patch, the submitted files are written
to a temporary directory, the patch is checked and applied with ``git apply``
(the way a user would apply it), and the patched files are analysed again:
the diagnostic the patch targets must be gone and no new error may appear.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.compiler.pipeline import compile_files
from app.models import AnalysisResult, Recommendation, SourceFormat

REPO = Path(__file__).resolve().parents[3]
FORMATS = {
    "yaml": SourceFormat.yaml,
    "dockerfile": SourceFormat.dockerfile,
    "terraform": SourceFormat.terraform,
}

CRAFTED: dict[str, tuple[SourceFormat, list[tuple[str, str]]]] = {
    "dockerfile_shell_fixes": (
        SourceFormat.dockerfile,
        [
            (
                "Dockerfile",
                "FROM debian:12-slim\n"
                "RUN apt-get update && apt-get install curl\n"
                "RUN apk add jq=1.7.1-r0\n"
                "ADD app.py /app/\n"
                "USER app\n"
                "CMD ['python', '/app/app.py']\n",
            )
        ],
    ),
    "dockerfile_no_trailing_newline": (
        SourceFormat.dockerfile,
        [("Dockerfile", "FROM debian:12-slim\nUSER app\nCMD ['sleep', '1']")],
    ),
    "dockerfile_with_script": (
        SourceFormat.dockerfile,
        [
            (
                "Dockerfile",
                "FROM debian:12-slim\nCOPY build.sh .\nRUN sh build.sh\nUSER app\n",
            ),
            (
                "build.sh",
                "#!/bin/sh\nset -e\n"
                "apt-get install --no-install-recommends make=4.3-4.1\n",
            ),
        ],
    ),
    "dockerfile_copy_typo": (
        SourceFormat.dockerfile,
        [
            ("Dockerfile", "FROM debian:12-slim\nCOPY requirments.txt .\nUSER app\n"),
            ("requirements.txt", "flask==3.0.0\n"),
        ],
    ),
    "yaml_number_and_typo": (
        SourceFormat.yaml,
        [
            (
                "ci.yml",
                "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
                "    strategy:\n      matrix:\n        python: [3.10, '3.12']\n"
                "    steps:\n      - run: echo\n"
                "  test:\n    needs: [biuld]\n    runs-on: ubuntu-latest\n"
                "    steps:\n      - run: echo\n",
            )
        ],
    ),
    "yaml_cycle_block_list": (
        SourceFormat.yaml,
        [
            (
                "ci.yml",
                "on: push\njobs:\n  a:\n    needs:\n      - b\n    runs-on: x\n"
                "    steps:\n      - run: echo\n"
                "  b:\n    needs: a\n    runs-on: x\n    steps:\n      - run: echo\n",
            )
        ],
    ),
    "terraform_cycle_two_depends_on": (
        SourceFormat.terraform,
        [
            (
                "main.tf",
                'resource "aws_a" "x" {\n  depends_on = [aws_b.y, aws_c.z]\n}\n'
                'resource "aws_b" "y" {\n  depends_on = [\n    aws_a.x,\n  ]\n}\n'
                'resource "aws_c" "z" {}\n',
            )
        ],
    ),
}


def _corpus() -> list[tuple[str, SourceFormat, list[tuple[str, str]]]]:
    cases = []
    for path in sorted((REPO / "examples").glob("*/*")):
        if path.parent.name in FORMATS:
            cases.append(
                (
                    str(path.relative_to(REPO)),
                    FORMATS[path.parent.name],
                    [(path.name, path.read_text())],
                )
            )
    for path in sorted((REPO / "frontend/src/samples").glob("*")):
        if path.is_file():
            fmt = (
                SourceFormat.terraform
                if path.suffix == ".tf"
                else SourceFormat.yaml
                if path.suffix == ".yml"
                else SourceFormat.dockerfile
            )
            cases.append((f"samples/{path.name}", fmt, [(path.name, path.read_text())]))
    mixed = REPO / "frontend/src/samples/mixed"
    cases.append(
        (
            "samples/mixed",
            SourceFormat.mixed,
            [(p.name, p.read_text()) for p in sorted(mixed.iterdir())],
        )
    )
    cases.extend((name, fmt, files) for name, (fmt, files) in CRAFTED.items())
    return cases


CORPUS = _corpus()
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _target_count(result: AnalysisResult, rec: Recommendation) -> int:
    """How many diagnostics of the kind ``rec`` fixes, in ``rec``'s file."""
    file = rec.source_location.file if rec.source_location else None
    if rec.rule_id == "BREAK_DEPENDENCY_CYCLE":
        match = lambda d: d.code.value == "DEPENDENCY_CYCLE"  # noqa: E731
    elif rec.rule_id == "RESOLVE_MISSING_DEPENDENCY":
        match = lambda d: d.code.value == "UNRESOLVED_DEPENDENCY"  # noqa: E731
    else:
        match = lambda d: d.message.startswith(f"[{rec.rule_id}]")  # noqa: E731
    return sum(
        1
        for d in result.diagnostics
        if match(d) and (d.source_location.file if d.source_location else None) == file
    )


def _errors(result: AnalysisResult) -> set[str]:
    return {d.message for d in result.diagnostics if d.severity.value == "error"}


@needs_git
@pytest.mark.parametrize(("name", "fmt", "files"), CORPUS, ids=[c[0] for c in CORPUS])
def test_patches_apply_and_fix_their_diagnostic(tmp_path, name, fmt, files):
    result = compile_files(files, fmt)
    patched = [
        r
        for r in result.recommendations
        if r.proposed_change and r.proposed_change.patch
    ]
    for rec in patched:
        work = tmp_path / rec.id.replace(":", "_")
        work.mkdir()
        for filename, text in files:
            (work / filename).write_text(text)
        (work / "fix.patch").write_text(rec.proposed_change.patch)
        applied = subprocess.run(
            ["git", "apply", "--verbose", "fix.patch"],
            cwd=work,
            capture_output=True,
            text=True,
        )
        assert applied.returncode == 0, (
            f"{rec.id}: {applied.stderr}\n{rec.proposed_change.patch}"
        )

        after = compile_files([(f, (work / f).read_text()) for f, _ in files], fmt)
        assert _target_count(after, rec) < _target_count(result, rec), rec.id
        assert _errors(after) <= _errors(result), (
            rec.id,
            _errors(after) - _errors(result),
        )


def test_every_patch_kind_is_exercised():
    kinds = {
        r.rule_id
        for _, fmt, files in CORPUS
        for r in compile_files(files, fmt).recommendations
        if r.proposed_change and r.proposed_change.patch
    }
    assert kinds >= {
        "RESOLVE_MISSING_DEPENDENCY",
        "BREAK_DEPENDENCY_CYCLE",
        "DF_APT_MISSING_YES",
        "DF_APK_NO_CACHE",
        "DF_ADD_LOCAL_FILE",
        "DF_EXEC_FORM_NOT_JSON",
        "GHA_NUMBER_LOSES_ZERO",
        "TF_S3_PUBLIC_ACL",
        "TF_DB_PUBLICLY_ACCESSIBLE",
        "TF_HARDCODED_SECRET",
    }


def test_patch_points_at_the_scripts_own_file():
    _, files = CRAFTED["dockerfile_with_script"]
    result = compile_files(files, SourceFormat.dockerfile)
    [rec] = [r for r in result.recommendations if r.rule_id == "DF_APT_MISSING_YES"]
    assert rec.proposed_change.patch.startswith("--- a/build.sh\n+++ b/build.sh\n")
    assert (
        "+apt-get install -y --no-install-recommends make=4.3-4.1"
        in rec.proposed_change.patch
    )


def test_no_patch_when_the_edit_is_uncertain():
    # A secret in a variable's own default is fixed by removing it, which
    # needs a decision about where the value comes from: no patch.
    files = [("v.tf", 'variable "token" {\n  default = "hunter2-hunter2"\n}\n')]
    [rec] = compile_files(files, SourceFormat.terraform).recommendations
    assert rec.rule_id == "TF_HARDCODED_SECRET"
    assert rec.proposed_change is None or rec.proposed_change.patch is None
