"""Docker's rules: BuildKit parse errors and the official build checks.

Every parse error below is one BuildKit itself raises (messages checked
against moby/buildkit frontend/dockerfile/instructions/parse.go); every build
check is one of docs.docker.com/reference/build-checks. The valid cases are
Dockerfiles BuildKit accepts that a simpler parser gets wrong.
"""

import pytest

from app.compiler.pipeline import compile_source
from app.models import DiagnosticCode, SourceFormat

BASE = "FROM alpine:3.20\n"
USER = "USER app\n"


def diagnostics(source: str):
    return compile_source(source, SourceFormat.dockerfile, "Dockerfile").diagnostics


def syntax_errors(source: str):
    return [
        d
        for d in diagnostics(source)
        if d.code == DiagnosticCode.DOCKERFILE_SYNTAX_ERROR
    ]


def rules(source: str) -> set[str]:
    return {
        d.message.split("]")[0].lstrip("[")
        for d in diagnostics(source)
        if d.message.startswith("[")
    }


PARSE_ERRORS = {
    "unknown COPY flag": (
        BASE + "COPY --chwn=app a b\n",
        "COPY has no flag '--chwn'",
        2,
    ),
    "unknown RUN flag": (
        BASE + "RUN --mnt=type=cache true\n",
        "RUN has no flag '--mnt'",
        2,
    ),
    "RUN network mode": (
        BASE + "RUN --network=bridge true\n",
        "RUN --network=bridge is invalid",
        2,
    ),
    "RUN mount type": (
        BASE + "RUN --mount=type=volume,target=/x true\n",
        "mount type 'volume' is invalid",
        2,
    ),
    "COPY without destination": (
        BASE + "COPY app.py\n",
        "COPY needs at least a source and a destination",
        2,
    ),
    "ADD without destination": (
        BASE + "ADD app.tar\n",
        "ADD needs at least a source and a destination",
        2,
    ),
    "FROM extra words": (
        BASE.replace("\n", " # base image\n"),
        "is malformed: use FROM <image> [AS <name>]",
        1,
    ),
    "FROM AS without name": ("FROM alpine:3.20 AS\n", "is malformed", 1),
    "stage name starts with digit": (
        "FROM alpine:3.20 AS 1build\n",
        "'1build' is not a valid stage name",
        1,
    ),
    "stage name with symbol": (
        "FROM alpine:3.20 AS my@stage\n",
        "'my@stage' is not a valid stage name",
        1,
    ),
    "ENV without value": (BASE + "ENV ONLYNAME\n", "ENV needs a name and a value", 2),
    "LABEL without value": (
        BASE + "LABEL version\n",
        "LABEL needs a key and a value",
        2,
    ),
    "SHELL not JSON": (BASE + "SHELL /bin/bash -c\n", "SHELL must be a JSON array", 2),
    "EXPOSE not a port": (BASE + "EXPOSE http\n", "EXPOSE http is not a port", 2),
    "EXPOSE unknown protocol": (BASE + "EXPOSE 80/foo\n", "has an unknown protocol", 2),
    "HEALTHCHECK duration": (
        BASE + "HEALTHCHECK --interval=5 CMD true\n",
        "--interval=5 is not a duration",
        2,
    ),
    "HEALTHCHECK retries": (
        BASE + "HEALTHCHECK --retries=many CMD true\n",
        "--retries must be a whole number",
        2,
    ),
    "HEALTHCHECK unknown flag": (
        BASE + "HEALTHCHECK --every=5s CMD true\n",
        "HEALTHCHECK has no flag '--every'",
        2,
    ),
    "WORKDIR empty": (BASE + "WORKDIR\n", "WORKDIR needs a value", 2),
}


@pytest.mark.parametrize(
    ("source", "expected", "line"), PARSE_ERRORS.values(), ids=PARSE_ERRORS.keys()
)
def test_buildkit_parse_error(source, expected, line):
    found = syntax_errors(source)
    matching = [d for d in found if expected in d.message]
    assert matching, f"expected '{expected}', got {[d.message for d in found]}"
    assert matching[0].severity.value == "error"
    assert matching[0].source_location.start_line == line


BUILD_CHECKS = {
    "DF_CONSISTENT_INSTRUCTION_CASING": BASE + "run echo hi\nRUN echo ok\n" + USER,
    "DF_FROM_AS_CASING": "FROM alpine:3.20 as build\nFROM alpine:3.20\n" + USER,
    "DF_STAGE_NAME_CASING": "FROM alpine:3.20 AS Build\nFROM alpine:3.20\nCOPY --from=Build /a /a\n"
    + USER,
    "DF_RESERVED_STAGE_NAME": "FROM alpine:3.20 AS context\nFROM alpine:3.20\n" + USER,
    "DF_FROM_PLATFORM_FLAG_CONST": "FROM --platform=linux/amd64 alpine:3.20\n" + USER,
    "DF_REDUNDANT_TARGET_PLATFORM": "FROM --platform=$TARGETPLATFORM alpine:3.20\n"
    + USER,
    "DF_UNDEFINED_ARG_IN_FROM": "FROM alpine:${TAG}\n" + USER,
    "DF_INVALID_DEFAULT_ARG_IN_FROM": "ARG TAG\nFROM alpine:${TAG}\n" + USER,
    "DF_JSON_ARGS_RECOMMENDED": BASE + USER + "CMD node server.js\n",
    "DF_LEGACY_KEY_VALUE_FORMAT": BASE + "ENV MODE production\n" + USER,
    "DF_MAINTAINER_DEPRECATED": BASE + "MAINTAINER me@example.com\n" + USER,
    "DF_MULTIPLE_INSTRUCTIONS": BASE + USER + 'CMD ["a"]\nCMD ["b"]\n',
    "DF_NO_EMPTY_CONTINUATION": BASE + "RUN echo a \\\n\n  b\n" + USER,
    "DF_SECRETS_IN_ARG_OR_ENV": BASE + "ARG GITHUB_TOKEN\n" + USER,
    "DF_WORKDIR_RELATIVE_PATH": BASE + "WORKDIR app\n" + USER,
    "DF_EXPOSE_PROTO_CASING": BASE + "EXPOSE 80/TCP\n" + USER,
    "DF_EXPOSE_INVALID_FORMAT": BASE + "EXPOSE 0.0.0.0:8080:80\n" + USER,
}


@pytest.mark.parametrize(
    ("rule", "source"), BUILD_CHECKS.items(), ids=BUILD_CHECKS.keys()
)
def test_docker_build_check(rule, source):
    found = [d for d in diagnostics(source) if d.message.startswith(f"[{rule}]")]
    assert found, f"{rule} not reported; got {rules(source)}"
    assert found[0].severity.value == "warning"


VALID = {
    "heredocs": "# syntax=docker/dockerfile:1\n"
    + BASE
    + "RUN <<EOF\napk add --no-cache "
    "curl=8.9.1-r0\necho done\nEOF\nCOPY <<EOT /etc/motd\nWelcome\nEOT\n" + USER,
    "escape directive": "# escape=`\nFROM mcr.microsoft.com/windows/servercore:ltsc2022\n"
    "RUN powershell -Command `\n    Write-Host hi\nUSER ContainerUser\n",
    "comments inside a continuation": BASE + "RUN apk add --no-cache \\\n"
    "    # for health checks\n    curl=8.9.1-r0\n" + USER,
    "JSON COPY and flags": BASE + 'COPY --chown=app:app --chmod=755 ["a b", "/app/"]\n'
    "COPY --link --parents src/ /app/\n" + USER,
    "valid mounts and network": BASE + "RUN --mount=type=cache,target=/root/.cache "
    "--mount=type=secret,id=npm --network=none true\n" + USER,
    "platform from a build arg": "FROM --platform=$BUILDPLATFORM alpine:3.20 AS build\n"
    "FROM alpine:3.20\nCOPY --from=build /out /out\n" + USER,
    "global ARG with default in FROM": "ARG TAG=3.20\nFROM alpine:${TAG}\n" + USER,
    "USER with group and spaced WORKDIR": BASE + "WORKDIR /srv/my app\nUSER app:app\n",
    "healthcheck durations": BASE + USER + "HEALTHCHECK --interval=1m30s --timeout=5s "
    '--start-period=10s --retries=3 CMD ["true"]\n',
    "expose ranges": BASE + "EXPOSE 80 443/tcp 8000-8010/udp ${PORT}\n" + USER,
    "public key name": BASE + "ARG PUBLIC_KEY_URL=https://example.com/key\n" + USER,
}


@pytest.mark.parametrize("source", VALID.values(), ids=VALID.keys())
def test_valid_dockerfile_has_no_errors_or_warnings(source):
    problems = [
        d.message
        for d in diagnostics(source)
        if d.severity.value in ("error", "warning")
    ]
    assert problems == []


def test_heredoc_body_is_checked_at_its_own_lines():
    source = BASE + "RUN <<EOF\nset -e\napt-get install curl\nEOF\n" + USER
    [error] = [d for d in diagnostics(source) if "DF_APT_MISSING_YES" in d.message]
    assert error.source_location.start_line == 4
