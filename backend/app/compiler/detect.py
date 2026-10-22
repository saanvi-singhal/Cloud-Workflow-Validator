"""Per-file format detection for multi-file requests.

Used by ``format: "mixed"`` (each file goes to its own parser) and by the
Dockerfile adapter (Dockerfiles vs. build-context files). Pure functions over
the name and text: no parser library is imported here.
"""

from __future__ import annotations

import posixpath

from app.models import SourceFormat

DOCKERFILE_NAMES = ("dockerfile", "containerfile")
# Extensions that are never a Dockerfile, even if the text starts with FROM.
NOT_DOCKERFILE_SUFFIXES = (
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".py",
    ".js",
    ".txt",
    ".json",
    ".md",
    ".yml",
    ".yaml",
    ".tf",
)


def base_name(filename: str) -> str:
    return posixpath.basename(filename.replace("\\", "/"))


def is_dockerfile(filename: str, source: str) -> bool:
    """Whether a file is a Dockerfile rather than a build-context file.

    By name first (``Dockerfile``, ``Dockerfile.api``, ``api.dockerfile``,
    ``Containerfile``). A file with any other name counts as a Dockerfile only
    if it has no known non-Dockerfile extension and its first instruction is
    FROM or ARG.
    """
    base = base_name(filename).lower()
    if base.startswith(DOCKERFILE_NAMES) or base.endswith(
        tuple(f".{name}" for name in DOCKERFILE_NAMES)
    ):
        return True
    if base.endswith(NOT_DOCKERFILE_SUFFIXES):
        return False
    for line in source.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped.split(None, 1)[0].upper() in ("FROM", "ARG")
    return False


def detect_format(filename: str, source: str) -> SourceFormat | None:
    """The format a file is analysed as, or None for other files.

    ``.tf`` is Terraform, ``.yml``/``.yaml`` is a GitHub Actions workflow and
    Dockerfiles are recognised by ``is_dockerfile``. Anything else (scripts,
    manifests) is not a configuration this tool analyses on its own; next to
    a Dockerfile it is build context.
    """
    base = base_name(filename).lower()
    if base.endswith(".tf"):
        return SourceFormat.terraform
    if base.endswith((".yml", ".yaml")):
        return SourceFormat.yaml
    if is_dockerfile(filename, source):
        return SourceFormat.dockerfile
    return None
