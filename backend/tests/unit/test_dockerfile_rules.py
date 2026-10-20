"""Tests for the deterministic Dockerfile rule set (app/rules/dockerfile_rules.py)."""

import pytest

from app.compiler.pipeline import compile_source
from app.models import DiagnosticCode, SourceFormat

# Runs as a non-root user with a pinned base, so only the rule under test fires.
PREFIX = "FROM debian:12-slim\n"
SUFFIX = "USER app\n"


def rules(source: str) -> list[tuple[str, int]]:
    result = compile_source(source, SourceFormat.dockerfile)
    return [
        (d.message.split("]")[0].lstrip("["), d.source_location.start_line)
        for d in result.diagnostics
        if d.code == DiagnosticCode.SECURITY_RULE_VIOLATION
    ]


def fired(source: str) -> set[str]:
    return {rule for rule, _ in rules(source)}


BAD_DOCKERFILE = """\
# Violation 1: Unpinned base image version
FROM node:latest

# Violation 2: Running as root
WORKDIR /app

# Violation 3: Cache invalidation trap
COPY . .

# Violation 4: Orphaned apt-get update
RUN apt-get update

# Violation 5: Missing -y flag and unpinned package version
RUN apt-get install curl

# Violation 6: Multiple consecutive RUN instructions instead of chaining
RUN apt-get install -y python3
RUN rm -rf /var/lib/apt/lists/*

# Violation 7: Using ADD instead of COPY for local files
ADD package.json /app/

RUN npm install

# Violation 8: Executing raw apt-get upgrade
RUN apt-get upgrade -y

CMD ["npm", "start"]
"""


def test_every_violation_in_the_example_is_reported():
    # Sorted by line, then severity (error, warning, info), then message.
    assert rules(BAD_DOCKERFILE) == [
        ("DF_RUNS_AS_ROOT", 2),
        ("DF_UNPINNED_BASE_IMAGE", 2),
        ("DF_COPY_ALL_BEFORE_INSTALL", 8),
        ("DF_APT_UPDATE_ALONE", 11),
        ("DF_CONSECUTIVE_RUN", 11),
        ("DF_APT_MISSING_YES", 14),
        ("DF_APT_UNPINNED_PACKAGES", 14),
        ("DF_APT_UNPINNED_PACKAGES", 17),
        ("DF_ADD_LOCAL_FILE", 21),
        ("DF_CONSECUTIVE_RUN", 23),
        ("DF_APT_UPGRADE", 26),
    ]


def test_missing_yes_breaks_the_build_so_the_file_is_invalid():
    result = compile_source(BAD_DOCKERFILE, SourceFormat.dockerfile)
    assert result.valid is False
    errors = [d for d in result.diagnostics if d.severity.value == "error"]
    assert [d.message.split("]")[0] for d in errors] == ["[DF_APT_MISSING_YES"]


def test_a_clean_dockerfile_has_no_findings():
    source = (
        "FROM node:22-slim AS build\n"
        "WORKDIR /app\n"
        "COPY package.json package-lock.json ./\n"
        "RUN npm ci\n"
        "COPY . .\n"
        "RUN npm run build\n"
        "\n"
        "FROM node:22-slim\n"
        "RUN apt-get update && apt-get install -y --no-install-recommends "
        "curl=7.88.1-10 && rm -rf /var/lib/apt/lists/*\n"
        "COPY --from=build /app/dist /app\n"
        "USER node\n"
        'CMD ["node", "/app/index.js"]\n'
    )
    assert rules(source) == []


@pytest.mark.parametrize(
    "image",
    [
        "node:22",
        "python:3.12-slim",
        "registry.example.com:5000/team/app:1.4",
        "scratch",
        "alpine@sha256:" + "a" * 64,
        "$BASE",
        "${BASE_IMAGE}",
    ],
)
def test_pinned_or_unknowable_base_images_are_accepted(image):
    assert "DF_UNPINNED_BASE_IMAGE" not in fired(f"FROM {image}\n{SUFFIX}")


@pytest.mark.parametrize(
    "image", ["node", "node:latest", "registry.example.com:5000/app"]
)
def test_unpinned_base_images_are_reported(image):
    assert "DF_UNPINNED_BASE_IMAGE" in fired(f"FROM {image}\n{SUFFIX}")


def test_from_an_earlier_stage_is_not_an_unpinned_image():
    source = f"FROM node:22 AS base\nFROM base\n{SUFFIX}"
    assert "DF_UNPINNED_BASE_IMAGE" not in fired(source)


def test_root_user_is_judged_on_the_final_stage_only():
    # A non-root USER in the build stage does not help the final image.
    assert "DF_RUNS_AS_ROOT" in fired("FROM node:22 AS b\nUSER node\nFROM node:22\n")
    assert "DF_RUNS_AS_ROOT" not in fired(
        "FROM node:22 AS b\nFROM node:22\nUSER node\n"
    )
    assert rules("FROM node:22\nUSER node\nUSER root\n") == [("DF_RUNS_AS_ROOT", 3)]
    assert "DF_RUNS_AS_ROOT" in fired("FROM node:22\nUSER 0:0\n")


@pytest.mark.parametrize(
    "run",
    [
        "apt-get install -y curl=1",
        "apt-get -y install curl=1",
        "apt-get install -qy curl=1",
        "apt-get install --yes curl=1",
        "apt-get install --assume-yes curl=1",
        "apt-get install -qq curl=1",
        "DEBIAN_FRONTEND=noninteractive apt-get install -y curl=1",
        '["apt-get", "install", "-y", "curl=1"]',
    ],
)
def test_apt_with_yes_is_accepted(run):
    assert "DF_APT_MISSING_YES" not in fired(f"{PREFIX}RUN {run}\n{SUFFIX}")


@pytest.mark.parametrize(
    "run",
    [
        "apt-get install curl",
        "sudo apt install curl",
        "apt-get remove curl",
        "apt-get upgrade",
    ],
)
def test_apt_without_yes_is_reported(run):
    assert "DF_APT_MISSING_YES" in fired(
        f"{PREFIX}RUN apt-get update && {run}\n{SUFFIX}"
    )


def test_apt_update_with_install_in_the_same_run_is_fine():
    source = f"{PREFIX}RUN apt-get update && apt-get install -y curl=1\n{SUFFIX}"
    assert fired(source) == set()


def test_unpinned_packages_are_listed():
    result = compile_source(
        f"{PREFIX}RUN apt-get update && apt-get install -y curl git=1 $EXTRA\n{SUFFIX}",
        SourceFormat.dockerfile,
    )
    [diagnostic] = result.diagnostics
    assert "without a version: curl." in diagnostic.message


@pytest.mark.parametrize(
    ("add", "expected"),
    [
        ("ADD package.json /app/", True),
        ("ADD --chown=app src/ /app/", True),
        ("ADD https://example.com/tool.tar.gz /opt/", False),
        ("ADD vendor.tar.gz /opt/", False),
        ("ADD git@github.com:org/repo.git /src", False),
        ("COPY package.json /app/", False),
    ],
)
def test_add_for_local_files(add, expected):
    assert ("DF_ADD_LOCAL_FILE" in fired(f"{PREFIX}{add}\n{SUFFIX}")) is expected


def test_copy_all_before_install_only_fires_when_an_install_follows():
    before = f"{PREFIX}COPY . .\nRUN pip install -r requirements.txt\n{SUFFIX}"
    after = (
        f"{PREFIX}COPY requirements.txt .\n"
        f"RUN pip install -r requirements.txt\nCOPY . .\n{SUFFIX}"
    )
    no_install = f"{PREFIX}COPY . .\nRUN make\n{SUFFIX}"
    assert "DF_COPY_ALL_BEFORE_INSTALL" in fired(before)
    assert "DF_COPY_ALL_BEFORE_INSTALL" not in fired(after)
    assert "DF_COPY_ALL_BEFORE_INSTALL" not in fired(no_install)


def test_consecutive_runs_are_grouped_per_stage():
    source = (
        "FROM debian:12-slim AS a\nRUN echo 1\nRUN echo 2\nRUN echo 3\n"
        "FROM debian:12-slim\nRUN echo 4\nUSER app\nRUN echo 5\n"
    )
    # Only the three RUNs of stage `a` form a group (stage `a` is also
    # reported as UNREACHABLE_NODE, which is not a rule finding).
    assert rules(source) == [("DF_CONSECUTIVE_RUN", 2)]


def test_rule_findings_are_linked_to_their_stage_and_have_specific_fixes():
    result = compile_source(BAD_DOCKERFILE, SourceFormat.dockerfile)
    by_rule = {r.rule_id: r for r in result.recommendations}
    assert set(by_rule) == {
        "DF_RUNS_AS_ROOT",
        "DF_UNPINNED_BASE_IMAGE",
        "DF_COPY_ALL_BEFORE_INSTALL",
        "DF_APT_UPDATE_ALONE",
        "DF_CONSECUTIVE_RUN",
        "DF_APT_MISSING_YES",
        "DF_APT_UNPINNED_PACKAGES",
        "DF_ADD_LOCAL_FILE",
        "DF_APT_UPGRADE",
    }
    assert all(r.related_node_ids == ["docker:stage:0"] for r in result.recommendations)
    yes = by_rule["DF_APT_MISSING_YES"].proposed_change
    assert yes.preview == "- apt-get install curl\n+ apt-get install -y curl"
    add = by_rule["DF_ADD_LOCAL_FILE"].proposed_change
    assert add.preview == "- ADD package.json /app/\n+ COPY package.json /app/"


@pytest.mark.parametrize(
    "line",
    [
        "CMD ['nginx', '-g', 'daemon off;']",
        "ENTRYPOINT [\"a\", 'b']",
        'RUN ["echo", "x",]',
        "SHELL ['/bin/bash', '-c']",
        "HEALTHCHECK --interval=5m CMD ['curl', '-f', 'http://localhost/']",
    ],
)
def test_exec_form_that_is_not_json_is_an_error(line):
    result = compile_source(f"{PREFIX}{line}\n{SUFFIX}", SourceFormat.dockerfile)
    assert result.valid is False
    assert fired(f"{PREFIX}{line}\n{SUFFIX}") == {"DF_EXEC_FORM_NOT_JSON"}


@pytest.mark.parametrize(
    "line",
    [
        'CMD ["nginx", "-g", "daemon off;"]',
        "CMD nginx -g 'daemon off;'",
        'HEALTHCHECK CMD ["curl", "-f", "http://localhost/"]',
        "HEALTHCHECK CMD curl -f http://localhost/ || exit 1",
        "RUN echo '[not exec form]'",
    ],
)
def test_valid_exec_and_shell_forms_are_accepted(line):
    assert "DF_EXEC_FORM_NOT_JSON" not in fired(f"{PREFIX}{line}\n{SUFFIX}")


def test_single_quoted_exec_form_fix_preview():
    result = compile_source(
        f"{PREFIX}CMD ['nginx', '-g', 'daemon off;']\n{SUFFIX}", SourceFormat.dockerfile
    )
    [fix] = result.recommendations
    assert fix.proposed_change.preview == (
        "- ['nginx', '-g', 'daemon off;']\n+ [\"nginx\", \"-g\", \"daemon off;\"]"
    )
