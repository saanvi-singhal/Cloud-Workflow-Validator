"""Regenerate frontend/src/mocks/*.json from the real backend.

Run from the repository root with the backend venv:

    .venv/bin/python frontend/scripts/generate_mocks.py

Every mock is real ``compile_source`` output:

* terraform.json, yaml.json, dockerfile.json: the samples in
  ``frontend/src/samples/`` (``main.tf``, ``ci.yml``, ``Dockerfile``);
* terraform-cycle.json: ``examples/terraform/cyclic.tf``;
* terraform-partial.json: ``examples/terraform/unsupported_expression.tf``;
* mixed.json: ``compile_files`` over ``frontend/src/samples/mixed/`` with
  ``format: mixed``.

Mocks are only used when ``VITE_USE_MOCK=true``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from app.compiler.pipeline import compile_files, compile_source  # noqa: E402
from app.models import SourceFormat  # noqa: E402

SAMPLES = REPO / "frontend" / "src" / "samples"
EXAMPLES = REPO / "examples" / "terraform"
MOCKS = REPO / "frontend" / "src" / "mocks"

# mock file -> (source file, format, filename shown in diagnostics)
SOURCES = {
    "terraform.json": (SAMPLES / "main.tf", SourceFormat.terraform, "main.tf"),
    "terraform-cycle.json": (
        EXAMPLES / "cyclic.tf",
        SourceFormat.terraform,
        "cyclic.tf",
    ),
    "terraform-partial.json": (
        EXAMPLES / "unsupported_expression.tf",
        SourceFormat.terraform,
        "unsupported_expression.tf",
    ),
    "yaml.json": (SAMPLES / "ci.yml", SourceFormat.yaml, "ci.yml"),
    "dockerfile.json": (SAMPLES / "Dockerfile", SourceFormat.dockerfile, "Dockerfile"),
}


def main() -> None:
    MOCKS.mkdir(exist_ok=True)
    for name, (source, fmt, filename) in SOURCES.items():
        result = compile_source(source.read_text(), fmt, filename)
        path = MOCKS / name
        path.write_text(json.dumps(result.model_dump(mode="json"), indent=2) + "\n")
        print(f"wrote {path.relative_to(REPO)}")

    # Same order as MIXED_SAMPLE in App.tsx.
    names = ["ci.yml", "Dockerfile", "install-tools.sh", "scan.sh"]
    files = [(n, (SAMPLES / "mixed" / n).read_text()) for n in names]
    result = compile_files(files, SourceFormat.mixed)
    path = MOCKS / "mixed.json"
    path.write_text(json.dumps(result.model_dump(mode="json"), indent=2) + "\n")
    print(f"wrote {path.relative_to(REPO)}")


if __name__ == "__main__":
    main()
