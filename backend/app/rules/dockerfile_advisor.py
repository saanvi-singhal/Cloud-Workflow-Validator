"""Docker layer and cache advisor: build speed and image size (spec 6.3).

Every ``RUN``, ``COPY`` and ``ADD`` adds a layer, and Docker reuses a cached
layer only while that instruction and everything before it are unchanged. The
rules here read the instruction order and text (nothing is built) and point
out where that model costs time or space. All are ``info``: the image still
builds and runs, it is just slower to rebuild or larger than it needs to be.

==========================  ===================================================
rule_id                     fires when
==========================  ===================================================
**Cache-busting order**
DF_VOLATILE_ARG_EARLY       an ``ARG`` whose value changes every build
                            (``BUILD_DATE``, ``GIT_SHA``, ``CACHEBUST``, ...)
                            is declared before a dependency or package install
                            in the same stage: every later ``RUN`` sees it as
                            an environment variable, so all of them rerun
DF_PACKAGES_AFTER_SOURCE    OS packages (apt/apk/dnf/yum) are installed after
                            the build context or a source directory was copied:
                            every source change reinstalls them
**Image size**
DF_APT_NO_RECOMMENDS        ``apt-get install`` without
                            ``--no-install-recommends`` (often doubles the
                            packages installed)
DF_APT_LISTS_NOT_REMOVED    a ``RUN`` runs ``apt-get update`` and installs, but
                            does not ``rm -rf /var/lib/apt/lists/*``: the
                            package index (tens of MB) stays in that layer
DF_PIP_NO_CACHE_DIR         ``pip install`` without ``--no-cache-dir``: pip's
                            download cache stays in the layer
DF_CLEANUP_IN_SEPARATE_LAYER  a ``RUN`` that only deletes files or cleans
                            caches, after another ``RUN``: the files still take
                            space in the earlier layer
**Multi-stage builds**
DF_MULTI_STAGE_OPPORTUNITY  a single-stage Dockerfile that runs a build step
                            (``go build``, ``make``, ``npm run build``, ...):
                            the final image ships the toolchain. A builder
                            stage plus a small runtime stage keeps only the
                            artifact. Installing a toolchain without building
                            (a CI or cross-compile image) is not reported
DF_FINAL_STAGE_SDK_IMAGE    the final stage of a multi-stage build is based on
                            a full SDK image (golang, rust, maven, gradle,
                            dotnet/sdk) although a builder stage exists
==========================  ===================================================

Cache mounts (``RUN --mount=type=cache``) keep caches out of the image, so the
size rules skip a ``RUN`` that uses one. Values with ``$`` are never guessed.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence

from app.compiler.findings import Finding
from app.models import Severity
from app.rules.dockerfile_rules import (
    _FROM,
    _INSTALL_COMMAND,
    DockerInstruction,
    _finding,
    _shell_commands,
    _words,
)

RULE_VOLATILE_ARG_EARLY = "DF_VOLATILE_ARG_EARLY"
RULE_PACKAGES_AFTER_SOURCE = "DF_PACKAGES_AFTER_SOURCE"
RULE_APT_NO_RECOMMENDS = "DF_APT_NO_RECOMMENDS"
RULE_APT_LISTS_NOT_REMOVED = "DF_APT_LISTS_NOT_REMOVED"
RULE_PIP_NO_CACHE_DIR = "DF_PIP_NO_CACHE_DIR"
RULE_CLEANUP_IN_SEPARATE_LAYER = "DF_CLEANUP_IN_SEPARATE_LAYER"
RULE_MULTI_STAGE_OPPORTUNITY = "DF_MULTI_STAGE_OPPORTUNITY"
RULE_FINAL_STAGE_SDK_IMAGE = "DF_FINAL_STAGE_SDK_IMAGE"

_VOLATILE_ARG = re.compile(
    r"(DATE|TIME|TIMESTAMP|SHA|COMMIT|REVISION|BUILD_ID|BUILD_NUMBER|CACHE_?BUST|NOCACHE)",
    re.IGNORECASE,
)
_OS_PACKAGES = re.compile(
    r"\b(apt-get|apt|dnf|yum|microdnf)\s+(?:-\S+\s+)*install\b|\bapk\s+(?:-\S+\s+)*add\b"
)
_APT_INSTALL = re.compile(r"\b(apt-get|apt)\s+(?:-\S+\s+)*install\b")
_APT_UPDATE = re.compile(r"\b(apt-get|apt)\s+(?:-\S+\s+)*update\b")
_PIP_INSTALL = re.compile(r"\bpip3?\s+install\b")
_CACHE_MOUNT = re.compile(r"--mount=\S*type=cache")
_CLEANUP_COMMANDS = frozenset(
    {"rm", "apt-get", "apt", "apk", "yum", "dnf", "npm", "pip"}
)
_CLEANUP_SUBCOMMANDS = frozenset({"clean", "autoremove", "autoclean", "cache", "purge"})
# Evidence that a stage compiles or builds something.
_TOOLCHAIN_PACKAGES = re.compile(
    r"(?<![\w-])(build-essential|gcc|g\+\+|clang|make|cmake|golang(?:-go)?|"
    r"default-jdk|openjdk-\d+-jdk|maven|gradle|rustc|cargo|musl-dev|"
    r"python3?-dev|libpq-dev|alpine-sdk)(?![\w+-])"
)
_BUILD_COMMAND = re.compile(
    r"\b(go build|cargo build|mvn (?:\S+ )*(?:package|install)|gradle (?:\S+ )*build|"
    r"\./gradlew (?:\S+ )*build|dotnet publish|npm run build|yarn build|"
    r"pnpm (?:run )?build|make(?:\s|$)|cmake --build|tsc\b)"
)
_SDK_IMAGES = re.compile(
    r"^(?:docker\.io/)?(?:library/)?(golang|rust|maven|gradle|openjdk)(?::|$)"
    r"|^mcr\.microsoft\.com/dotnet/sdk(?::|$)",
    re.IGNORECASE,
)


def _run_text(instruction: DockerInstruction) -> str:
    return " ".join(" ".join(words) for words in _shell_commands(instruction.value))


def _stages(
    instructions: Sequence[DockerInstruction],
) -> dict[int, list[DockerInstruction]]:
    stages: dict[int, list[DockerInstruction]] = {}
    for instruction in instructions:
        if instruction.stage_index is not None:
            stages.setdefault(instruction.stage_index, []).append(instruction)
    return stages


def _copies_source(instruction: DockerInstruction) -> bool:
    """COPY/ADD of the whole context or a directory (not one manifest file)."""
    if instruction.keyword not in ("COPY", "ADD"):
        return False
    words = [w for w in _words(instruction.value) if not w.startswith("--")]
    if any(w.lower().startswith("--from") for w in _words(instruction.value)):
        return False
    return any(
        s in (".", "./") or s.endswith("/") or "." not in s.rsplit("/", 1)[-1]
        for s in words[:-1]
    )


# --- cache-busting order ---------------------------------------------------------


def check_volatile_arg_early(
    instructions: Sequence[DockerInstruction],
) -> Iterator[Finding]:
    for stage in _stages(instructions).values():
        for i, instruction in enumerate(stage):
            if instruction.keyword != "ARG":
                continue
            name = instruction.value.split("=", 1)[0].strip()
            if not name or not _VOLATILE_ARG.search(name):
                continue
            later = [
                x
                for x in stage[i + 1 :]
                if x.keyword == "RUN"
                and (
                    _INSTALL_COMMAND.search(_run_text(x))
                    or _OS_PACKAGES.search(_run_text(x))
                )
            ]
            if later:
                yield _finding(
                    RULE_VOLATILE_ARG_EARLY,
                    Severity.info,
                    f"ARG {name} changes on every build, and every RUN after it "
                    f"sees it as an environment variable, so the "
                    f"{len(later)} install step(s) below never come from the cache. "
                    "Declare it after the installs, just before it is used.",
                    instruction,
                    name=name,
                    installs=len(later),
                )


def check_packages_after_source(
    instructions: Sequence[DockerInstruction],
) -> Iterator[Finding]:
    for stage in _stages(instructions).values():
        copied = next((x for x in stage if _copies_source(x)), None)
        if copied is None:
            continue
        after = stage[stage.index(copied) + 1 :]
        install = next(
            (
                x
                for x in after
                if x.keyword == "RUN" and _OS_PACKAGES.search(_run_text(x))
            ),
            None,
        )
        if install is not None:
            line = copied.location.start_line if copied.location else None
            yield _finding(
                RULE_PACKAGES_AFTER_SOURCE,
                Severity.info,
                "OS packages are installed after the source was copied"
                + (f" (line {line})" if line else "")
                + ", so every source change reinstalls them. Install system "
                "packages first; they change far less often than your code.",
                install,
                copy_line=line,
            )


# --- image size --------------------------------------------------------------------


def check_apt_size(instruction: DockerInstruction) -> Iterator[Finding]:
    if instruction.keyword != "RUN" or _CACHE_MOUNT.search(instruction.value):
        return
    text = _run_text(instruction)
    if not _APT_INSTALL.search(text):
        return
    if "--no-install-recommends" not in text and "no-install-recommends" not in text:
        yield _finding(
            RULE_APT_NO_RECOMMENDS,
            Severity.info,
            "apt-get install also installs 'recommended' packages, which are "
            "rarely needed in a container. Add --no-install-recommends to keep "
            "the image smaller.",
            instruction,
        )
    # The index is written by `apt-get update`; deleting it only shrinks the
    # image in the same RUN (an earlier RUN's layer keeps it anyway, which
    # DF_APT_UPDATE_ALONE reports).
    if _APT_UPDATE.search(text) and "/var/lib/apt/lists" not in instruction.value:
        yield _finding(
            RULE_APT_LISTS_NOT_REMOVED,
            Severity.info,
            "This RUN installs apt packages but leaves the package index in "
            "/var/lib/apt/lists (often tens of MB) in the layer. End the same "
            "RUN with '&& rm -rf /var/lib/apt/lists/*'.",
            instruction,
        )


def check_pip_cache(instruction: DockerInstruction) -> Iterator[Finding]:
    if instruction.keyword != "RUN" or _CACHE_MOUNT.search(instruction.value):
        return
    text = _run_text(instruction)
    if _PIP_INSTALL.search(text) and "--no-cache-dir" not in text:
        yield _finding(
            RULE_PIP_NO_CACHE_DIR,
            Severity.info,
            "pip keeps downloaded packages in its cache, which stays in the "
            "layer. Add --no-cache-dir (or set ENV PIP_NO_CACHE_DIR=1).",
            instruction,
        )


def check_cleanup_layer(instructions: Sequence[DockerInstruction]) -> Iterator[Finding]:
    for stage in _stages(instructions).values():
        runs = [x for x in stage if x.keyword == "RUN"]
        for run in runs[1:]:
            commands = _shell_commands(run.value)
            if commands and all(_is_cleanup(words) for words in commands):
                yield _finding(
                    RULE_CLEANUP_IN_SEPARATE_LAYER,
                    Severity.info,
                    "This RUN only deletes files or cleans caches. Layers are "
                    "stacked, so the files still take space in the earlier layer "
                    "that created them. Do the cleanup in that same RUN.",
                    run,
                )


def _is_cleanup(words: list[str]) -> bool:
    if not words or words[0] not in _CLEANUP_COMMANDS:
        return False
    if words[0] == "rm":
        return True
    sub = next((w for w in words[1:] if not w.startswith("-")), "")
    return sub in _CLEANUP_SUBCOMMANDS


# --- multi-stage builds --------------------------------------------------------------


def check_multi_stage(instructions: Sequence[DockerInstruction]) -> Iterator[Finding]:
    stages = _stages(instructions)
    if not stages:
        return
    final_index = max(stages)
    final = stages[final_index]
    base = _FROM.match(final[0].value.strip()) if final[0].keyword == "FROM" else None
    image = base.group(1) if base else ""

    if len(stages) == 1:
        # A build step is required: an image that only installs a toolchain
        # (a CI or cross-compile image) is meant to ship it.
        builds: list[str] = []
        tools: list[str] = []
        for x in final:
            if x.keyword != "RUN":
                continue
            text = _run_text(x)
            builds += [m.group(1).strip() for m in _BUILD_COMMAND.finditer(text)]
            if _OS_PACKAGES.search(text):
                tools += [m.group(1) for m in _TOOLCHAIN_PACKAGES.finditer(text)]
        sdk = [f"base image {image}"] if _SDK_IMAGES.search(image) else []
        unique = list(dict.fromkeys([*sdk, *builds, *tools])) if builds else []
        if unique:
            yield _finding(
                RULE_MULTI_STAGE_OPPORTUNITY,
                Severity.info,
                "This image builds its own code ("
                + ", ".join(unique[:4])
                + ") and ships the whole toolchain with it. Build in a first "
                "stage, then COPY --from that stage only the artifact into a "
                "small runtime image.",
                final[0],
                evidence=unique,
                image=image,
            )
    elif _SDK_IMAGES.search(image) and "$" not in image:
        yield _finding(
            RULE_FINAL_STAGE_SDK_IMAGE,
            Severity.info,
            f"The final stage is based on the SDK image '{image}', although "
            "an earlier stage already builds. Base the final stage on a runtime "
            "image (e.g. distroless, alpine, a JRE or the dotnet runtime) and copy "
            "only the build output into it.",
            final[0],
            image=image,
        )


ADVISOR_INSTRUCTION_RULES = (check_apt_size, check_pip_cache)
ADVISOR_FILE_RULES = (
    check_volatile_arg_early,
    check_packages_after_source,
    check_cleanup_layer,
    check_multi_stage,
)


def run_dockerfile_advisor(instructions: Sequence[DockerInstruction]) -> list[Finding]:
    """Run every advisor rule; the pipeline sorts the findings by location."""
    findings: list[Finding] = []
    for instruction in instructions:
        for rule in ADVISOR_INSTRUCTION_RULES:
            findings.extend(rule(instruction))
    for file_rule in ADVISOR_FILE_RULES:
        findings.extend(file_rule(instructions))
    return findings
