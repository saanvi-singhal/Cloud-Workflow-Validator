"""A small, documented set of deterministic Dockerfile rules (spec 6.3).

This is **not** a comprehensive linter or security scanner. Each rule reads
only the instruction text: nothing is built, pulled or executed, and a value
containing a ``$`` variable is skipped rather than guessed at. Every finding is
``SECURITY_RULE_VIOLATION`` with a stable ``rule_id`` (the prefix of the
message), linked to the stage node it belongs to.

Severity: ``error`` when the build itself will fail, ``warning`` for security
and reproducibility risks, ``info`` for image size and build-cache advice.

=========================  ========  =========================================
rule_id                    severity  fires when
=========================  ========  =========================================
DF_APT_MISSING_YES         error     ``apt-get``/``apt`` install, upgrade or
                                     remove without ``-y``: there is no one to
                                     answer the prompt, so the build aborts
DF_UNPINNED_BASE_IMAGE     warning   ``FROM`` an image with no tag or
                                     ``:latest`` and no ``@sha256`` digest
DF_RUNS_AS_ROOT            warning   the final stage never switches to a
                                     non-root ``USER`` (or switches to root)
DF_APT_UPDATE_ALONE        warning   a ``RUN`` with ``apt-get update`` but no
                                     install: the cached package index goes
                                     stale and later installs can fail
DF_APT_UPGRADE             warning   ``apt-get upgrade``/``dist-upgrade``:
                                     the image changes whenever it is rebuilt
DF_ADD_LOCAL_FILE          warning   ``ADD`` of a local file that is not an
                                     archive; ``COPY`` does only what it says
DF_COPY_ALL_BEFORE_INSTALL info      ``COPY . .`` before the dependency
                                     install in the same stage, so any source
                                     change re-runs the install
DF_CONSECUTIVE_RUN         info      two or more ``RUN`` in a row; each adds a
                                     layer, and cleanup in a later layer does
                                     not shrink the image
DF_APT_UNPINNED_PACKAGES   info      ``apt-get install`` packages without a
                                     ``=version``
=========================  ========  =========================================
"""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from app.compiler.findings import Finding, make_finding
from app.models import DiagnosticCode, Severity, SourceLocation

RULE_APT_MISSING_YES = "DF_APT_MISSING_YES"
RULE_UNPINNED_BASE_IMAGE = "DF_UNPINNED_BASE_IMAGE"
RULE_RUNS_AS_ROOT = "DF_RUNS_AS_ROOT"
RULE_APT_UPDATE_ALONE = "DF_APT_UPDATE_ALONE"
RULE_APT_UPGRADE = "DF_APT_UPGRADE"
RULE_ADD_LOCAL_FILE = "DF_ADD_LOCAL_FILE"
RULE_COPY_ALL_BEFORE_INSTALL = "DF_COPY_ALL_BEFORE_INSTALL"
RULE_CONSECUTIVE_RUN = "DF_CONSECUTIVE_RUN"
RULE_APT_UNPINNED_PACKAGES = "DF_APT_UNPINNED_PACKAGES"

APT_TOOLS = frozenset({"apt-get", "apt"})
# apt subcommands that ask for confirmation unless -y is given.
APT_PROMPTING = frozenset(
    {
        "install",
        "upgrade",
        "dist-upgrade",
        "full-upgrade",
        "remove",
        "purge",
        "autoremove",
    }
)
APT_UPGRADES = frozenset({"upgrade", "dist-upgrade", "full-upgrade"})
YES_LONG_FLAGS = frozenset({"--yes", "--assume-yes"})
ARCHIVE_SUFFIXES = (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")
ROOT_USERS = frozenset({"root", "0"})

# Commands that install a project's dependencies from its manifest.
_INSTALL_COMMAND = re.compile(
    r"\b(npm (install|ci)|yarn install|pnpm install|pip3? install .*-r|"
    r"poetry install|bundle install|go mod download|composer install|cargo fetch)\b"
)
_FROM = re.compile(r"^(?:--platform=\S+\s+)?(\S+)(?:\s+as\s+(\S+))?", re.IGNORECASE)
_SHELL_SEPARATORS = re.compile(r"&&|\|\||;|\|")


@dataclass(frozen=True)
class DockerInstruction:
    """One instruction, in source order, with the stage it belongs to."""

    keyword: str  # upper-case, e.g. "RUN"
    value: str  # arguments, with line continuations joined
    location: SourceLocation | None
    stage_index: int | None  # None before the first FROM
    node_id: str | None


def _finding(
    rule_id: str,
    severity: Severity,
    message: str,
    instruction: DockerInstruction,
    **details: Any,
) -> Finding:
    return make_finding(
        DiagnosticCode.SECURITY_RULE_VIOLATION,
        severity,
        f"[{rule_id}] {message}",
        instruction.location,
        rule_id=rule_id,
        node_ids=(instruction.node_id,) if instruction.node_id else (),
        details=details,
    )


# --- shell helpers ----------------------------------------------------------


def _shell_commands(value: str) -> list[list[str]]:
    """Split a RUN value into simple commands, each a list of words.

    Handles the exec form (``["a", "b"]``) and ``&&``, ``||``, ``;`` and ``|``.
    Leading ``sudo`` and ``VAR=value`` assignments are dropped. This is a
    tokenizer, not a shell: subshells and heredocs are not interpreted.
    """
    text = value.strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, list):
            text = " ".join(str(part) for part in parsed)
    commands = []
    for part in _SHELL_SEPARATORS.split(text):
        try:
            words = shlex.split(part)
        except ValueError:
            words = part.split()
        while words and (words[0] == "sudo" or re.fullmatch(r"\w+=\S*", words[0])):
            words = words[1:]
        if words:
            commands.append(words)
    return commands


def _apt_subcommand(words: list[str]) -> str | None:
    """Return the apt subcommand (``install``...) or None if not an apt call."""
    if not words or words[0] not in APT_TOOLS:
        return None
    return next((w for w in words[1:] if not w.startswith("-")), None)


def _has_yes_flag(words: list[str]) -> bool:
    for word in words[1:]:
        if word in YES_LONG_FLAGS or word == "-qq":
            return True
        if word.startswith("-") and not word.startswith("--") and "y" in word:
            return True
    return False


def _apt_packages(words: list[str]) -> list[str]:
    """Package arguments after the subcommand (flags excluded)."""
    sub = _apt_subcommand(words)
    if sub is None:
        return []
    after = words[words.index(sub) + 1 :]
    return [w for w in after if not w.startswith("-")]


# --- rules over single instructions ----------------------------------------


def check_apt(instruction: DockerInstruction) -> Iterator[Finding]:
    if instruction.keyword != "RUN":
        return
    commands = _shell_commands(instruction.value)
    subcommands = [_apt_subcommand(words) for words in commands]

    if "update" in subcommands and "install" not in subcommands:
        yield _finding(
            RULE_APT_UPDATE_ALONE,
            Severity.warning,
            "'apt-get update' runs in its own RUN. Docker caches that layer, so "
            "a later 'apt-get install' can use a stale package index and fail. "
            "Run update and install in the same RUN.",
            instruction,
        )

    for words, sub in zip(commands, subcommands, strict=True):
        if sub is None:
            continue
        command = " ".join(words)
        if sub in APT_PROMPTING and not _has_yes_flag(words):
            yield _finding(
                RULE_APT_MISSING_YES,
                Severity.error,
                f"'{command}' has no -y. A Docker build cannot answer the "
                "confirmation prompt, so apt aborts and the build fails.",
                instruction,
                command=command,
                subcommand=sub,
            )
        if sub in APT_UPGRADES:
            yield _finding(
                RULE_APT_UPGRADE,
                Severity.warning,
                f"'{command}' upgrades every package to whatever is newest when "
                "the image is built, so two builds of the same Dockerfile can "
                "differ. Use an updated base image instead.",
                instruction,
            )
        if sub == "install":
            unpinned = [
                p for p in _apt_packages(words) if "=" not in p and "$" not in p
            ]
            unpinned = [p for p in unpinned if not p.endswith(".deb")]
            if unpinned:
                yield _finding(
                    RULE_APT_UNPINNED_PACKAGES,
                    Severity.info,
                    f"Packages installed without a version: {', '.join(unpinned)}. "
                    "Rebuilds may install different versions; pin them with "
                    "name=version if you need reproducible images.",
                    instruction,
                    packages=unpinned,
                )


def check_add_local_file(instruction: DockerInstruction) -> Iterator[Finding]:
    if instruction.keyword != "ADD":
        return
    words = [w for w in _words(instruction.value) if not w.startswith("--")]
    sources = words[:-1]
    local = [
        s
        for s in sources
        if "://" not in s
        and not s.startswith("git@")
        and "$" not in s
        and not s.lower().endswith(ARCHIVE_SUFFIXES)
    ]
    if local:
        yield _finding(
            RULE_ADD_LOCAL_FILE,
            Severity.warning,
            f"ADD is used for local files ({', '.join(local)}). ADD also "
            "downloads URLs and unpacks archives; use COPY, which only copies.",
            instruction,
            sources=local,
            value=instruction.value,
        )


def _words(value: str) -> list[str]:
    text = value.strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, list):
            return [str(p) for p in parsed]
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


# --- rules over the whole file ----------------------------------------------


def check_base_images(instructions: Sequence[DockerInstruction]) -> Iterator[Finding]:
    aliases: set[str] = set()
    for instruction in instructions:
        if instruction.keyword != "FROM":
            continue
        match = _FROM.match(instruction.value.strip())
        if not match:
            continue
        image, alias = match.group(1), match.group(2)
        is_stage = image.lower() in aliases
        if alias:
            aliases.add(alias.lower())
        if is_stage or image.lower() == "scratch" or "$" in image or "@" in image:
            continue
        name = image.rsplit("/", 1)[-1]
        tag = name.split(":", 1)[1] if ":" in name else None
        if tag is None or tag == "latest":
            shown = "no tag (so 'latest')" if tag is None else "the 'latest' tag"
            yield _finding(
                RULE_UNPINNED_BASE_IMAGE,
                Severity.warning,
                f"Base image '{image}' uses {shown}, which points to a "
                "different image over time. Pin a version tag (or a digest).",
                instruction,
                image=image,
            )


def check_runs_as_root(instructions: Sequence[DockerInstruction]) -> Iterator[Finding]:
    stages = [i.stage_index for i in instructions if i.stage_index is not None]
    if not stages:
        return
    final = max(stages)
    in_final = [i for i in instructions if i.stage_index == final]
    users = [i for i in in_final if i.keyword == "USER"]
    if users:
        last = users[-1]
        user = last.value.strip().split(":", 1)[0]
        if user in ROOT_USERS:
            yield _finding(
                RULE_RUNS_AS_ROOT,
                Severity.warning,
                f"The final stage switches to USER {user}, so the container runs "
                "as root. Switch to a non-root user after the steps that need root.",
                last,
            )
        return
    yield _finding(
        RULE_RUNS_AS_ROOT,
        Severity.warning,
        "The final stage has no USER instruction, so the container runs as root "
        "unless the base image sets another user. Add a non-root USER before CMD.",
        in_final[0],
    )


def check_copy_all_before_install(
    instructions: Sequence[DockerInstruction],
) -> Iterator[Finding]:
    copied_all: dict[int | None, DockerInstruction] = {}
    reported: set[int | None] = set()
    for instruction in instructions:
        stage = instruction.stage_index
        if instruction.keyword in ("COPY", "ADD") and stage not in copied_all:
            words = [w for w in _words(instruction.value) if not w.startswith("--")]
            if any(s in (".", "./") for s in words[:-1]):
                copied_all[stage] = instruction
        elif (
            instruction.keyword == "RUN"
            and stage in copied_all
            and stage not in reported
            and _INSTALL_COMMAND.search(
                " ".join(sum(_shell_commands(instruction.value), []))
            )
        ):
            reported.add(stage)
            yield _finding(
                RULE_COPY_ALL_BEFORE_INSTALL,
                Severity.info,
                "The whole build context is copied before dependencies are "
                "installed, so any source change re-runs the install. Copy the "
                "dependency manifest first, install, then copy the rest.",
                copied_all[stage],
            )


def check_consecutive_runs(
    instructions: Sequence[DockerInstruction],
) -> Iterator[Finding]:
    group: list[DockerInstruction] = []

    def flush() -> Iterator[Finding]:
        if len(group) > 1:
            yield _finding(
                RULE_CONSECUTIVE_RUN,
                Severity.info,
                f"{len(group)} RUN instructions in a row each create a layer; "
                "files deleted in a later layer still take space in the image. "
                "Chain related commands with && in one RUN.",
                group[0],
                count=len(group),
            )

    for instruction in instructions:
        same_stage = group and group[-1].stage_index == instruction.stage_index
        if instruction.keyword == "RUN" and (not group or same_stage):
            group.append(instruction)
            continue
        yield from flush()
        group = [instruction] if instruction.keyword == "RUN" else []
    yield from flush()


INSTRUCTION_RULES: tuple[Callable[[DockerInstruction], Iterator[Finding]], ...] = (
    check_apt,
    check_add_local_file,
)
FILE_RULES: tuple[Callable[[Sequence[DockerInstruction]], Iterator[Finding]], ...] = (
    check_base_images,
    check_runs_as_root,
    check_copy_all_before_install,
    check_consecutive_runs,
)


def run_dockerfile_rules(instructions: Sequence[DockerInstruction]) -> list[Finding]:
    """Run every rule; the pipeline sorts the findings by location."""
    findings: list[Finding] = []
    for instruction in instructions:
        for rule in INSTRUCTION_RULES:
            findings.extend(rule(instruction))
    for file_rule in FILE_RULES:
        findings.extend(file_rule(instructions))
    return findings
