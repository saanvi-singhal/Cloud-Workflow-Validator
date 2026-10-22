"""Tests for the Docker layer and cache advisor (app/rules/dockerfile_advisor.py)."""

import pytest

from app.compiler.pipeline import compile_source
from app.models import SourceFormat
from tests.unit.test_dockerfile_rules import ADVISOR_RULES

USER = "USER app\n"


def advice(source: str) -> list[tuple[str, int]]:
    result = compile_source(source, SourceFormat.dockerfile)
    found = [
        (d.message.split("]")[0].lstrip("["), d.source_location.start_line)
        for d in result.diagnostics
        if d.message.startswith("[")
    ]
    return [(rule, line) for rule, line in found if rule in ADVISOR_RULES]


def fired(source: str) -> set[str]:
    return {rule for rule, _ in advice(source)}


GOOD_APT = (
    "RUN apt-get update && apt-get install -y --no-install-recommends curl=8.5.0-2 "
    "&& rm -rf /var/lib/apt/lists/*\n"
)


def test_a_well_built_image_gets_no_advice():
    source = (
        "FROM python:3.12-slim\n" + GOOD_APT + "COPY requirements.txt .\n"
        "RUN pip install --no-cache-dir -r requirements.txt\n"
        "COPY . .\n"
        "ARG GIT_SHA\n"
        "LABEL revision=$GIT_SHA\n" + USER
    )
    assert fired(source) == set()


# --- cache-busting order -----------------------------------------------------------


def test_volatile_arg_before_installs():
    source = (
        "FROM node:20-slim\nARG BUILD_DATE\nCOPY package.json package-lock.json ./\n"
        "RUN npm ci\n" + USER
    )
    assert advice(source) == [("DF_VOLATILE_ARG_EARLY", 2)]


@pytest.mark.parametrize("name", ["NODE_ENV", "APP_PORT", "VERSIONED"])
def test_stable_args_are_fine(name):
    source = f"FROM node:20-slim\nARG {name}\nRUN npm ci\n{USER}"
    assert fired(source) == set()


def test_packages_after_source_copy():
    source = "FROM debian:12-slim\nCOPY . /app\n" + GOOD_APT + USER
    assert advice(source) == [("DF_PACKAGES_AFTER_SOURCE", 3)]


def test_packages_after_copying_one_manifest_are_fine():
    source = "FROM debian:12-slim\nCOPY requirements.txt /app/\n" + GOOD_APT + USER
    assert fired(source) == set()


# --- image size -----------------------------------------------------------------------


def test_apt_size_rules():
    source = (
        "FROM debian:12-slim\nRUN apt-get update && apt-get install -y curl=8\n" + USER
    )
    assert fired(source) == {"DF_APT_NO_RECOMMENDS", "DF_APT_LISTS_NOT_REMOVED"}


def test_lists_cleanup_only_where_the_index_is_downloaded():
    # update ran in an earlier layer: removing the lists here saves nothing.
    source = (
        "FROM debian:12-slim\nRUN apt-get update\n"
        "RUN apt-get install -y --no-install-recommends curl=8\n" + USER
    )
    assert fired(source) == set()


def test_cache_mounts_are_respected():
    source = (
        "FROM debian:12-slim\n"
        "RUN --mount=type=cache,target=/var/cache/apt apt-get update "
        "&& apt-get install -y curl=8\n"
        "RUN --mount=type=cache,target=/root/.cache/pip pip install flask==3.0.0\n"
        + USER
    )
    assert fired(source) == set()


def test_pip_cache():
    source = "FROM python:3.12-slim\nRUN pip install flask==3.0.0\n" + USER
    assert advice(source) == [("DF_PIP_NO_CACHE_DIR", 2)]


def test_cleanup_in_a_separate_layer():
    source = (
        "FROM debian:12-slim\n"
        + GOOD_APT
        + "RUN rm -rf /tmp/* && apt-get clean\n"
        + USER
    )
    assert advice(source) == [("DF_CLEANUP_IN_SEPARATE_LAYER", 3)]


def test_cleanup_in_the_first_run_is_fine():
    assert fired("FROM debian:12-slim\nRUN rm -rf /tmp/*\n" + USER) == set()


# --- multi-stage builds -----------------------------------------------------------


def test_single_stage_build_with_toolchain():
    source = (
        "FROM golang:1.22\nWORKDIR /src\nCOPY go.mod go.sum ./\nRUN go mod download\n"
        "COPY . .\nRUN go build -o /app ./cmd/server\n" + USER
    )
    result = compile_source(source, SourceFormat.dockerfile)
    [diagnostic] = [d for d in result.diagnostics if "MULTI_STAGE" in d.message]
    assert diagnostic.source_location.start_line == 1
    assert "base image golang:1.22" in diagnostic.message
    assert "go build" in diagnostic.message
    [rec] = [
        r for r in result.recommendations if r.rule_id == "DF_MULTI_STAGE_OPPORTUNITY"
    ]
    assert "COPY --from=build" in rec.proposed_change.preview


def test_single_stage_apt_toolchain():
    source = (
        "FROM debian:12-slim\nRUN apt-get update && apt-get install -y "
        "--no-install-recommends build-essential=12.9 && rm -rf /var/lib/apt/lists/*\n"
        "RUN make\n" + USER
    )
    assert "DF_MULTI_STAGE_OPPORTUNITY" in fired(source)


def test_single_stage_runtime_image_is_fine():
    assert fired("FROM nginx:1.27\nCOPY site/ /usr/share/nginx/html/\n" + USER) == set()


def test_final_stage_on_sdk_image():
    source = (
        "FROM golang:1.22 AS build\nRUN go build -o /app .\n"
        "FROM golang:1.22\nCOPY --from=build /app /app\n" + USER
    )
    assert advice(source) == [("DF_FINAL_STAGE_SDK_IMAGE", 3)]


def test_proper_multi_stage_build_is_fine():
    source = (
        "FROM golang:1.22 AS build\nRUN go build -o /app .\n"
        "FROM gcr.io/distroless/static-debian12:nonroot\nCOPY --from=build /app /app\n"
    )
    assert fired(source) == set()


def test_toolchain_image_that_builds_nothing_is_fine():
    # A CI / cross-compile image ships its compilers on purpose.
    source = (
        "FROM debian:12-slim\nRUN apt-get update && apt-get install -y "
        "--no-install-recommends gcc=4:12 && rm -rf /var/lib/apt/lists/*\n" + USER
    )
    assert fired(source) == set()
