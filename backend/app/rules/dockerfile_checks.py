"""Docker's own rules: parse errors and the official build checks.

Two groups, both from Docker's documentation:

**Parse errors** (``DOCKERFILE_SYNTAX_ERROR``, error): what BuildKit refuses
before building (https://docs.docker.com/reference/dockerfile/): wrong
argument counts, unknown ``--flags``, invalid ``RUN --network`` /
``--mount type``, a ``SHELL`` that is not JSON, an invalid stage name,
``FROM ... AS`` without a name or with extra words, an invalid port, and bad
``HEALTHCHECK`` durations.

**Build checks** (``SECURITY_RULE_VIOLATION``, warning), named after Docker's
checks (https://docs.docker.com/reference/build-checks/). Docker shows these
as warnings by default. Every check that can be decided from the file alone
is implemented; three cannot: CopyIgnoredFile (needs .dockerignore and the
context), UndefinedVar (needs the base image's environment) and
InvalidDefinitionDescription (experimental).

=================================  ===========================================
rule_id                            Docker check
=================================  ===========================================
DF_CONSISTENT_INSTRUCTION_CASING   ConsistentInstructionCasing
DF_FROM_AS_CASING                  FromAsCasing
DF_STAGE_NAME_CASING               StageNameCasing
DF_RESERVED_STAGE_NAME             ReservedStageName
DF_FROM_PLATFORM_FLAG_CONST        FromPlatformFlagConstDisallowed
DF_REDUNDANT_TARGET_PLATFORM       RedundantTargetPlatform
DF_UNDEFINED_ARG_IN_FROM           UndefinedArgInFrom
DF_INVALID_DEFAULT_ARG_IN_FROM     InvalidDefaultArgInFrom
DF_JSON_ARGS_RECOMMENDED           JSONArgsRecommended
DF_LEGACY_KEY_VALUE_FORMAT         LegacyKeyValueFormat
DF_MAINTAINER_DEPRECATED           MaintainerDeprecated
DF_MULTIPLE_INSTRUCTIONS           MultipleInstructionsDisallowed
DF_NO_EMPTY_CONTINUATION           NoEmptyContinuation
DF_SECRETS_IN_ARG_OR_ENV           SecretsUsedInArgOrEnv
DF_WORKDIR_RELATIVE_PATH           WorkdirRelativePath
DF_EXPOSE_PROTO_CASING             ExposeProtoCasing
DF_EXPOSE_INVALID_FORMAT           ExposeInvalidFormat
=================================  ===========================================

(DuplicateStageName is reported by the parser as DUPLICATE_NODE_ID.)
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Sequence
from typing import Any

from app.compiler.findings import Finding, make_finding
from app.models import DiagnosticCode, Severity, SourceLocation
from app.rules.dockerfile_rules import DockerInstruction, _finding, _words

# Flags each instruction accepts (Dockerfile reference); any other is an error.
FLAGS: dict[str, frozenset[str]] = {
    "FROM": frozenset({"platform"}),
    "RUN": frozenset({"mount", "network", "security", "device"}),
    "COPY": frozenset({"from", "chown", "chmod", "link", "parents", "exclude"}),
    "ADD": frozenset(
        {"chown", "chmod", "link", "checksum", "keep-git-dir", "exclude", "unpack"}
    ),
    "HEALTHCHECK": frozenset(
        {"interval", "timeout", "start-period", "start-interval", "retries"}
    ),
}
NETWORK_MODES = frozenset({"default", "none", "host"})
MOUNT_TYPES = frozenset({"bind", "cache", "tmpfs", "secret", "ssh"})
STAGE_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]*$")
DURATION = re.compile(r"^(\d+(\.\d+)?(ns|us|µs|ms|s|m|h))+$")
PORT = re.compile(r"^\d+(-\d+)?(/[A-Za-z]+)?$")
PREDEFINED_ARGS = frozenset(
    {
        "TARGETPLATFORM",
        "TARGETOS",
        "TARGETARCH",
        "TARGETVARIANT",
        "BUILDPLATFORM",
        "BUILDOS",
        "BUILDARCH",
        "BUILDVARIANT",
    }
)
# Docker's own patterns for SecretsUsedInArgOrEnv.
SECRET_DENY = re.compile(
    r"(?i)(?:_|^)(?:apikey|auth|credential|credentials|key|password|pword|passwd|secret|token)(?:_|$)"
)
SECRET_ALLOW = re.compile(r"(?i)(?:_|^)public(?:_|$)")
_VAR = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)(:?[-+][^}]*)?\}?")


def _loc(entry: dict[str, Any], filename: str | None) -> SourceLocation:
    return SourceLocation(
        file=filename,
        start_line=entry["startline"] + 1,
        start_column=1,
        end_line=entry["endline"] + 1,
    )


def _flags(words: list[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """Leading --name[=value] flags, and the remaining arguments."""
    flags = []
    i = 0
    while i < len(words) and words[i].startswith("--"):
        name, _, value = words[i][2:].partition("=")
        flags.append((name, value))
        i += 1
    return flags, words[i:]


# --- parse errors --------------------------------------------------------------------


def parse_errors(
    structure: Sequence[dict[str, Any]], filename: str | None
) -> list[Finding]:
    findings: list[Finding] = []

    def error(entry: dict[str, Any], message: str) -> None:
        findings.append(
            make_finding(
                DiagnosticCode.DOCKERFILE_SYNTAX_ERROR,
                Severity.error,
                f"{message} Docker will refuse to build this file.",
                _loc(entry, filename),
            )
        )

    for entry in structure:
        keyword = entry["instruction"].upper()
        value = entry.get("value", "").strip()
        if keyword == "COMMENT":
            continue
        words = _words(value)
        flags, args = _flags(words) if keyword in FLAGS else ([], words)

        for name, flag_value in flags:
            if name not in FLAGS[keyword]:
                allowed = ", ".join(f"--{f}" for f in sorted(FLAGS[keyword]))
                error(
                    entry, f"{keyword} has no flag '--{name}' (it accepts {allowed})."
                )
            elif keyword == "RUN" and name == "network" and "$" not in flag_value:
                if flag_value not in NETWORK_MODES:
                    error(
                        entry,
                        f"RUN --network={flag_value} is invalid: use default, none or host.",
                    )
            elif keyword == "RUN" and name == "mount" and "$" not in flag_value:
                options = dict(
                    part.partition("=")[::2] for part in flag_value.split(",") if part
                )
                mount_type = options.get("type", "bind")
                if mount_type not in MOUNT_TYPES:
                    error(
                        entry,
                        f"RUN --mount type '{mount_type}' is invalid: use bind, cache, "
                        "tmpfs, secret or ssh.",
                    )
            elif keyword == "HEALTHCHECK" and "$" not in flag_value:
                if name == "retries" and not flag_value.isdigit():
                    error(
                        entry,
                        f"HEALTHCHECK --retries must be a whole number, not '{flag_value}'.",
                    )
                elif name != "retries" and not DURATION.match(flag_value):
                    error(
                        entry,
                        f"HEALTHCHECK --{name}={flag_value} is not a duration "
                        "(for example 30s, 1m30s).",
                    )

        if keyword in ("COPY", "ADD") and len(args) < 2 and not args[:1] == ["<<"]:
            if not any(a.startswith("<<") for a in args):
                error(entry, f"{keyword} needs at least a source and a destination.")
        elif keyword == "FROM":
            if not args:
                error(entry, "FROM needs an image.")
            elif (
                len(args) == 2
                or (len(args) >= 3 and args[1].lower() != "as")
                or len(args) > 3
            ):
                error(
                    entry, f"'FROM {value}' is malformed: use FROM <image> [AS <name>]."
                )
            elif (
                len(args) == 3 and "$" not in args[2] and not STAGE_NAME.match(args[2])
            ):
                error(
                    entry,
                    f"'{args[2]}' is not a valid stage name: it must start with a letter "
                    "and contain only letters, digits, '-', '_' and '.'.",
                )
        elif keyword in ("WORKDIR", "USER", "STOPSIGNAL", "MAINTAINER") and not value:
            # BuildKit reads the whole rest of the line as the one argument
            # (parseString), so only an empty value is a parse error.
            error(entry, f"{keyword} needs a value.")
        elif keyword == "ENV" and (
            not words or ("=" not in words[0] and len(words) < 2)
        ):
            error(entry, "ENV needs a name and a value (ENV NAME=value).")
        elif keyword == "LABEL" and (
            not words or ("=" not in words[0] and len(words) < 2)
        ):
            error(entry, "LABEL needs a key and a value (LABEL key=value).")
        elif keyword == "ARG" and not words:
            error(entry, "ARG needs a name.")
        elif keyword == "SHELL":
            try:
                parsed = json.loads(value)
            except ValueError:
                parsed = None
            if not (
                isinstance(parsed, list)
                and parsed
                and all(isinstance(p, str) for p in parsed)
            ):
                error(
                    entry,
                    'SHELL must be a JSON array, for example SHELL ["/bin/bash", "-c"].',
                )
        elif keyword == "EXPOSE":
            for port in words:
                if "$" in port or ":" in port:  # ':' is the ExposeInvalidFormat check
                    continue
                if not PORT.match(port):
                    error(
                        entry,
                        f"EXPOSE {port} is not a port: use 80, 80/tcp or 8000-8010/udp.",
                    )
                elif "/" in port and port.split("/")[1].lower() not in (
                    "tcp",
                    "udp",
                    "sctp",
                ):
                    error(
                        entry,
                        f"EXPOSE {port} has an unknown protocol: use tcp, udp or sctp.",
                    )
    return findings


# --- build checks --------------------------------------------------------------------


def build_checks(
    structure: Sequence[dict[str, Any]],
    instructions: Sequence[DockerInstruction],
    empty_continuations: Sequence[int],
    filename: str | None,
) -> list[Finding]:
    entries = [e for e in structure if e["instruction"].upper() != "COMMENT"]
    pairs = list(zip(entries, instructions, strict=False))
    return [
        *_casing(pairs),
        *_from_checks(pairs),
        *_per_instruction(pairs),
        *_multiple(pairs),
        *_workdir(pairs),
        *_empty_continuation(empty_continuations, instructions, filename),
    ]


def _raw_keyword(entry: dict[str, Any]) -> str:
    content = entry.get("content", "").lstrip()
    return content.split(None, 1)[0] if content else ""


def _casing(pairs: list[tuple[dict[str, Any], DockerInstruction]]) -> Iterator[Finding]:
    raw = [(_raw_keyword(e), i) for e, i in pairs]
    upper = sum(1 for k, _ in raw if k.isupper())
    lower = sum(1 for k, _ in raw if k.islower())
    majority_upper = upper >= lower
    for keyword, instruction in raw:
        if (majority_upper and not keyword.isupper()) or (
            not majority_upper and not keyword.islower()
        ):
            yield _finding(
                "DF_CONSISTENT_INSTRUCTION_CASING",
                Severity.warning,
                f"'{keyword}' is not in the {'upper' if majority_upper else 'lower'} case "
                "the rest of the file uses. Use one casing for all instructions.",
                instruction,
            )


def _from_checks(
    pairs: list[tuple[dict[str, Any], DockerInstruction]],
) -> Iterator[Finding]:
    global_args: dict[str, str | None] = {}
    seen_from = False
    for entry, instruction in pairs:
        keyword = entry["instruction"].upper()
        words = _words(entry.get("value", ""))
        if keyword == "ARG" and not seen_from:
            for word in words:
                name, eq, default = word.partition("=")
                global_args[name] = default if eq else None
            continue
        if keyword != "FROM":
            continue
        seen_from = True
        flags, args = _flags(words)
        raw_from = _raw_keyword(entry)
        if len(args) == 3 and args[1].lower() == "as":
            as_word, alias = args[1], args[2]
            if (raw_from.isupper() and not as_word.isupper()) or (
                raw_from.islower() and not as_word.islower()
            ):
                yield _finding(
                    "DF_FROM_AS_CASING",
                    Severity.warning,
                    f"'{raw_from}' and '{as_word}' use different casing; write them the same way.",
                    instruction,
                )
            if alias.lower() in ("scratch", "context"):
                yield _finding(
                    "DF_RESERVED_STAGE_NAME",
                    Severity.warning,
                    f"'{alias}' is a reserved name and cannot be used as a stage name.",
                    instruction,
                )
            elif alias != alias.lower() and "$" not in alias:
                yield _finding(
                    "DF_STAGE_NAME_CASING",
                    Severity.warning,
                    f"Stage name '{alias}' has capitals; Docker treats stage names as lower case. "
                    f"Use '{alias.lower()}'.",
                    instruction,
                )
        for name, value in flags:
            if name != "platform":
                continue
            if value.strip("${}") == "TARGETPLATFORM":
                yield _finding(
                    "DF_REDUNDANT_TARGET_PLATFORM",
                    Severity.warning,
                    "--platform=$TARGETPLATFORM is the default already; remove it.",
                    instruction,
                )
            elif "$" not in value:
                yield _finding(
                    "DF_FROM_PLATFORM_FLAG_CONST",
                    Severity.warning,
                    f"--platform={value} is fixed, so the image cannot be built for other "
                    "platforms. Use a build argument such as $BUILDPLATFORM.",
                    instruction,
                )
        image = args[0] if args else ""
        for match in _VAR.finditer(image):
            var, modifier = match.group(1), match.group(2)
            if var in PREDEFINED_ARGS:
                continue
            if var not in global_args:
                yield _finding(
                    "DF_UNDEFINED_ARG_IN_FROM",
                    Severity.warning,
                    f"FROM uses ${var}, which no ARG before the first FROM declares, so it "
                    "is empty.",
                    instruction,
                    var=var,
                )
            elif global_args[var] is None and not modifier:
                yield _finding(
                    "DF_INVALID_DEFAULT_ARG_IN_FROM",
                    Severity.warning,
                    f"ARG {var} has no default, so without --build-arg {var}=... the image "
                    f"'{image}' is invalid. Give the ARG a default.",
                    instruction,
                    var=var,
                )


def _per_instruction(
    pairs: list[tuple[dict[str, Any], DockerInstruction]],
) -> Iterator[Finding]:
    for entry, instruction in pairs:
        keyword = entry["instruction"].upper()
        value = entry.get("value", "").strip()
        words = _words(value)
        if keyword in ("CMD", "ENTRYPOINT") and value and not value.startswith("["):
            yield _finding(
                "DF_JSON_ARGS_RECOMMENDED",
                Severity.warning,
                f"{keyword} uses the shell form, so signals such as SIGTERM go to the "
                "shell, not your process. Use the JSON form: "
                f'{keyword} ["executable", "arg"].',
                instruction,
            )
        elif keyword in ("ENV", "LABEL") and len(words) >= 2 and "=" not in words[0]:
            yield _finding(
                "DF_LEGACY_KEY_VALUE_FORMAT",
                Severity.warning,
                f"'{keyword} {words[0]} {' '.join(words[1:])}' uses the legacy space form. "
                f"Write {keyword} {words[0]}={' '.join(words[1:])}.",
                instruction,
            )
        elif keyword == "MAINTAINER":
            yield _finding(
                "DF_MAINTAINER_DEPRECATED",
                Severity.warning,
                'MAINTAINER is deprecated. Use LABEL org.opencontainers.image.authors="...".',
                instruction,
            )
        elif keyword == "EXPOSE":
            for port in words:
                if ":" in port:
                    yield _finding(
                        "DF_EXPOSE_INVALID_FORMAT",
                        Severity.warning,
                        f"EXPOSE {port} includes an address or host port; EXPOSE takes only "
                        "the container port. Map ports with docker run -p.",
                        instruction,
                    )
                elif "/" in port and port.split("/")[1] != port.split("/")[1].lower():
                    yield _finding(
                        "DF_EXPOSE_PROTO_CASING",
                        Severity.warning,
                        f"EXPOSE {port}: write the protocol in lower case "
                        f"({port.split('/')[0]}/{port.split('/')[1].lower()}).",
                        instruction,
                    )
        if keyword in ("ARG", "ENV"):
            names = (
                [w.partition("=")[0] for w in words]
                if keyword == "ARG" or "=" in (words[0] if words else "")
                else words[:1]
            )
            for name in names:
                if SECRET_DENY.search(name) and not SECRET_ALLOW.search(name):
                    yield _finding(
                        "DF_SECRETS_IN_ARG_OR_ENV",
                        Severity.warning,
                        f"{keyword} {name} looks like a secret; ARG and ENV values are stored in "
                        "the image and its history. Use a secret mount (RUN --mount=type=secret).",
                        instruction,
                        name=name,
                    )


def _multiple(
    pairs: list[tuple[dict[str, Any], DockerInstruction]],
) -> Iterator[Finding]:
    seen: dict[tuple[int | None, str], int] = {}
    for entry, instruction in pairs:
        keyword = entry["instruction"].upper()
        if keyword not in ("CMD", "ENTRYPOINT", "HEALTHCHECK"):
            continue
        key = (instruction.stage_index, keyword)
        if key in seen:
            yield _finding(
                "DF_MULTIPLE_INSTRUCTIONS",
                Severity.warning,
                f"This stage has more than one {keyword}; only the last one (line "
                f"{instruction.location.start_line if instruction.location else '?'}) takes "
                f"effect, so the one on line {seen[key]} is ignored.",
                instruction,
            )
        seen[key] = instruction.location.start_line if instruction.location else 0


def _workdir(
    pairs: list[tuple[dict[str, Any], DockerInstruction]],
) -> Iterator[Finding]:
    absolute: set[int | None] = set()
    for entry, instruction in pairs:
        if entry["instruction"].upper() != "WORKDIR":
            continue
        path = entry.get("value", "").strip().strip("\"'")
        is_absolute = path.startswith(("/", "$")) or re.match(r"^[A-Za-z]:[\\/]", path)
        if is_absolute:
            absolute.add(instruction.stage_index)
        elif instruction.stage_index not in absolute:
            yield _finding(
                "DF_WORKDIR_RELATIVE_PATH",
                Severity.warning,
                f"WORKDIR {path} is relative and no absolute WORKDIR comes before it in this "
                "stage, so it depends on the base image's directory. Use an absolute path.",
                instruction,
            )


def _empty_continuation(
    lines: Sequence[int],
    instructions: Sequence[DockerInstruction],
    filename: str | None,
) -> Iterator[Finding]:
    for line in lines:
        owner = next(
            (
                i
                for i in instructions
                if i.location
                and i.location.start_line
                <= line
                <= (i.location.end_line or i.location.start_line)
            ),
            None,
        )
        yield make_finding(
            DiagnosticCode.SECURITY_RULE_VIOLATION,
            Severity.warning,
            "[DF_NO_EMPTY_CONTINUATION] An empty line inside a continued instruction. "
            "Docker skips it today, but this will become an error; remove the empty line.",
            SourceLocation(file=filename, start_line=line, start_column=1),
            rule_id="DF_NO_EMPTY_CONTINUATION",
            node_ids=(owner.node_id,) if owner and owner.node_id else (),
        )
