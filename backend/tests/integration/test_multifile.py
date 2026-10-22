"""Integration tests for multi-file validation and cross-file variable analysis."""

from fastapi.testclient import TestClient

from app.compiler.pipeline import compile_files
from app.main import app
from app.models import DiagnosticCode, SourceFormat

client = TestClient(app)


def test_multifile_terraform_interfile_dependencies():
    variables_tf = """
variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "environment" {
  type    = string
  default = "production"
}

variable "unused_token" {
  type    = string
  default = "secret"
}
"""
    main_tf = """
resource "aws_vpc" "main" {
  cidr_block = var.vpc_cidr

  tags = {
    Env = var.environment
  }
}

resource "aws_subnet" "public" {
  vpc_id     = aws_vpc.main.id
  cidr_block = "10.0.1.0/24"
}
"""
    outputs_tf = """
output "vpc_id" {
  value = aws_vpc.main.id
}
"""
    files = [
        ("variables.tf", variables_tf),
        ("main.tf", main_tf),
        ("outputs.tf", outputs_tf),
    ]

    result = compile_files(files, SourceFormat.terraform)
    assert result.valid is True
    assert result.multifile is not None
    assert set(result.multifile.files) == {"variables.tf", "main.tf", "outputs.tf"}

    # Check inter-file dependencies
    inter_deps = result.multifile.interfile_dependencies
    assert len(inter_deps) > 0

    # variables.tf -> main.tf dependency (var.vpc_cidr or var.environment)
    var_to_main = [
        d
        for d in inter_deps
        if d.source_file == "variables.tf" and d.target_file == "main.tf"
    ]
    assert len(var_to_main) >= 2
    symbols_to_main = {d.symbol for d in var_to_main}
    assert "var.vpc_cidr" in symbols_to_main
    assert "var.environment" in symbols_to_main

    # main.tf -> outputs.tf dependency (aws_vpc.main)
    main_to_out = [
        d
        for d in inter_deps
        if d.source_file == "main.tf" and d.target_file == "outputs.tf"
    ]
    assert len(main_to_out) == 1
    assert main_to_out[0].symbol == "aws_vpc.main"

    # Check variable occurrences
    vars_by_name = {v.name: v for v in result.multifile.variable_occurrences}
    assert "vpc_cidr" in vars_by_name
    assert "environment" in vars_by_name
    assert "unused_token" in vars_by_name

    vpc_cidr_var = vars_by_name["vpc_cidr"]
    assert vpc_cidr_var.declared_files == ["variables.tf"]
    assert vpc_cidr_var.referenced_files == ["main.tf"]
    assert vpc_cidr_var.is_duplicate is False
    assert vpc_cidr_var.is_unused is False

    unused_var = vars_by_name["unused_token"]
    assert unused_var.declared_files == ["variables.tf"]
    assert unused_var.referenced_files == []
    assert unused_var.is_unused is True
    assert "unused_token" in result.multifile.unused_variables


def test_multifile_terraform_duplicate_variable_across_files():
    vars_a = """
variable "db_port" {
  type    = number
  default = 5432
}
"""
    vars_b = """
variable "db_port" {
  type    = number
  default = 3306
}
"""
    files = [
        ("vars_a.tf", vars_a),
        ("vars_b.tf", vars_b),
    ]

    result = compile_files(files, SourceFormat.terraform)
    assert result.valid is False
    assert any(d.code == DiagnosticCode.DUPLICATE_NODE_ID for d in result.diagnostics)

    dup_diag = next(
        d for d in result.diagnostics if d.code == DiagnosticCode.DUPLICATE_NODE_ID
    )
    assert "vars_a.tf" in dup_diag.message and "vars_b.tf" in dup_diag.message

    assert result.multifile is not None
    assert "db_port" in result.multifile.duplicate_variables
    var_occ = next(
        v for v in result.multifile.variable_occurrences if v.name == "db_port"
    )
    assert var_occ.is_duplicate is True
    assert set(var_occ.declared_files) == {"vars_a.tf", "vars_b.tf"}


def test_multifile_terraform_cross_file_cycle():
    file_a = """
resource "aws_security_group" "a" {
  name        = "sg-a"
  description = aws_security_group.b.id
}
"""
    file_b = """
resource "aws_security_group" "b" {
  name        = "sg-b"
  description = aws_security_group.a.id
}
"""
    files = [
        ("sg_a.tf", file_a),
        ("sg_b.tf", file_b),
    ]

    result = compile_files(files, SourceFormat.terraform)
    assert result.valid is False
    assert any(d.code == DiagnosticCode.DEPENDENCY_CYCLE for d in result.diagnostics)


def test_multifile_api_endpoint():
    payload = {
        "format": "terraform",
        "files": [
            {
                "filename": "variables.tf",
                "content": 'variable "bucket" { default = "my-bucket" }\n',
            },
            {
                "filename": "main.tf",
                "content": 'resource "aws_s3_bucket" "b" { bucket = var.bucket }\n',
            },
        ],
    }
    response = client.post("/api/v1/validate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["multifile"] is not None
    assert "variables.tf" in data["multifile"]["files"]
    assert "main.tf" in data["multifile"]["files"]
    assert len(data["multifile"]["interfile_dependencies"]) == 1
    assert (
        data["multifile"]["interfile_dependencies"][0]["source_file"] == "variables.tf"
    )
    assert data["multifile"]["interfile_dependencies"][0]["target_file"] == "main.tf"


def test_multifile_empty_files_rejected():
    payload = {
        "format": "terraform",
        "files": [],
    }
    response = client.post("/api/v1/validate", json=payload)
    assert response.status_code == 422


def test_multifile_yaml_multiple_workflows():
    ci_yml = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
"""
    deploy_yml = """
on: workflow_dispatch
jobs:
  deploy:
    runs-on: ubuntu-latest
"""
    files = [("ci.yml", ci_yml), ("deploy.yml", deploy_yml)]
    result = compile_files(files, SourceFormat.yaml)
    assert result.valid is True
    assert result.multifile is not None
    assert set(result.multifile.files) == {"ci.yml", "deploy.yml"}
    assert len(result.graph.nodes) == 2


def test_multifile_yaml_same_job_in_two_workflows_is_not_a_duplicate():
    # GitHub runs each workflow on its own; `needs` only sees its own file.
    workflow = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo a
  test:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - run: echo b
"""
    files = [("ci.yml", workflow), ("release.yml", workflow)]
    result = compile_files(files, SourceFormat.yaml)
    assert result.valid is True
    assert result.diagnostics == []
    assert sorted(n.id for n in result.graph.nodes) == [
        "gha:job:ci.yml:build",
        "gha:job:ci.yml:test",
        "gha:job:release.yml:build",
        "gha:job:release.yml:test",
    ]
    assert {(e.source, e.target) for e in result.graph.edges} == {
        ("gha:job:ci.yml:build", "gha:job:ci.yml:test"),
        ("gha:job:release.yml:build", "gha:job:release.yml:test"),
    }


def test_multifile_yaml_findings_point_at_their_own_file():
    ok = "on: push\njobs:\n  a:\n    runs-on: x\n    steps:\n      - run: echo\n"
    broken = "on: push\njobs:\n  b:\n    needs: missing\n    runs-on: x\n"
    broken += "    steps:\n      - run: echo\n"
    result = compile_files([("ok.yml", ok), ("broken.yml", broken)], SourceFormat.yaml)
    [diagnostic] = result.diagnostics
    assert diagnostic.code == DiagnosticCode.UNRESOLVED_DEPENDENCY
    assert diagnostic.source_location.file == "broken.yml"
    [rec] = result.recommendations
    assert rec.related_node_ids == ["gha:job:broken.yml:b"]


def test_multifile_yaml_separate_workflows_are_not_disconnected():
    chain = "on: push\njobs:\n  a:\n    runs-on: x\n    steps:\n      - run: echo\n"
    chain += "  b:\n    needs: a\n    runs-on: x\n    steps:\n      - run: echo\n"
    result = compile_files([("one.yml", chain), ("two.yml", chain)], SourceFormat.yaml)
    codes = [d.code for d in result.diagnostics]
    assert DiagnosticCode.DISCONNECTED_COMPONENT not in codes


DOCKERFILE = """FROM node:20 AS build
COPY build.sh package.json ./
COPY src ./src
COPY buld.txt .
RUN ./build.sh

FROM nginx:1.27
COPY --from=build /app /usr/share/nginx/html
USER nginx
"""
BUILD_SH = """#!/bin/sh
set -e
apt-get update
apt-get install \\
   curl
npm ci
"""


def test_multifile_dockerfile_scripts_are_build_context_not_dockerfiles():
    files = [("Dockerfile", DOCKERFILE), ("build.sh", BUILD_SH), ("build.txt", "x")]
    result = compile_files(files, SourceFormat.dockerfile)
    codes = [d.code for d in result.diagnostics]
    # The script's lines are not read as Dockerfile instructions.
    assert DiagnosticCode.DOCKERFILE_SYNTAX_ERROR not in codes
    assert [n.id for n in result.graph.nodes] == [
        "docker:stage:Dockerfile:0",
        "docker:stage:Dockerfile:1",
    ]
    assert result.graph.nodes[0].metadata["context_files"] == ["build.sh"]

    by_message = {d.message.split(":")[0]: d for d in result.diagnostics}
    # apt rules run on the script a RUN executes, located in the script.
    missing_yes = next(
        d for d in result.diagnostics if "DF_APT_MISSING_YES" in d.message
    )
    assert missing_yes.severity.value == "error"
    assert missing_yes.source_location.file == "build.sh"
    assert missing_yes.source_location.start_line == 4
    assert "run by RUN on line 5" in missing_yes.message
    # update and install on separate script lines run in one layer: no warning.
    assert not any("DF_APT_UPDATE_ALONE" in d.message for d in result.diagnostics)
    # A near-miss COPY source is a likely typo; an unknown one is only info.
    assert by_message["COPY buld.txt"].severity.value == "warning"
    assert "Did you mean 'build.txt'" in by_message["COPY buld.txt"].message
    assert by_message["COPY package.json"].severity.value == "info"
    # Directories (no extension) are not reported.
    assert "COPY src" not in by_message

    assert result.multifile is not None
    [link] = result.multifile.interfile_dependencies
    assert (link.source_file, link.target_file) == ("build.sh", "Dockerfile")
    assert link.edge_type == "docker_build_context"


def test_multifile_two_dockerfiles_are_separate_builds():
    api = "FROM python:3.12 AS base\nFROM python:3.12\nUSER app\n"
    web = "FROM node:20\nUSER node\n"
    files = [("Dockerfile.api", api), ("web.dockerfile", web)]
    result = compile_files(files, SourceFormat.dockerfile)
    assert {n.id: n.source_location.file for n in result.graph.nodes} == {
        "docker:stage:Dockerfile.api:0": "Dockerfile.api",
        "docker:stage:Dockerfile.api:1": "Dockerfile.api",
        "docker:stage:web.dockerfile:0": "web.dockerfile",
    }
    # Each file has its own final stage: only 'base' is unused.
    [unused] = result.diagnostics
    assert unused.code == DiagnosticCode.UNREACHABLE_NODE
    assert unused.message.startswith("'base' is not needed by the final build stage")
    assert "('stage-1')" in unused.message


def test_multifile_dockerfile_without_any_dockerfile():
    files = [("a.sh", "echo a"), ("b.sh", "echo b")]
    result = compile_files(files, SourceFormat.dockerfile)
    [diagnostic] = result.diagnostics
    assert diagnostic.code == DiagnosticCode.DOCKERFILE_SYNTAX_ERROR
    assert "None of the uploaded files is a Dockerfile" in diagnostic.message
    assert result.graph.nodes == []


def test_multifile_dockerfile_detected_by_content():
    # An unusual name still counts when the file starts with FROM.
    files = [("api.docker", "FROM alpine:3.20\nUSER app\n"), ("run.sh", "echo")]
    result = compile_files(files, SourceFormat.dockerfile)
    assert [n.id for n in result.graph.nodes] == ["docker:stage:api.docker:0"]


WORKFLOW = """on: push
jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aquasecurity/trivy-action@master
"""
SCANNER_DOCKERFILE = """FROM alpine:3.20
RUN apk add --no-cache curl=8.9.1-r0
COPY scan.sh /usr/local/bin/scan.sh
USER app
ENTRYPOINT ["/usr/local/bin/scan.sh"]
"""
MAIN_TF = 'resource "aws_s3_bucket" "logs" {\n  bucket = "logs"\n}\n'


def test_mixed_formats_are_analysed_together():
    files = [
        ("ci.yml", WORKFLOW),
        ("Dockerfile", SCANNER_DOCKERFILE),
        ("scan.sh", "#!/bin/sh\ntrivy fs .\n"),
        ("main.tf", MAIN_TF),
    ]
    result = compile_files(files, SourceFormat.mixed)
    assert result.format == SourceFormat.mixed
    assert result.valid is True
    assert [n.id for n in result.graph.nodes] == [
        "docker:stage:Dockerfile:0",
        "gha:job:scan",
        "tf:resource:aws_s3_bucket.logs",
    ]
    # Each group keeps its own rules and policy.
    [diagnostic] = result.diagnostics
    assert diagnostic.message.startswith("[GHA_UNPINNED_ACTION]")
    assert diagnostic.source_location.file == "ci.yml"
    # Different kinds of order are never mixed into one list.
    assert result.execution_order is None
    assert result.multifile is not None
    assert result.multifile.file_formats == {
        "ci.yml": "yaml",
        "Dockerfile": "dockerfile",
        "scan.sh": "build_context",
        "main.tf": "terraform",
    }
    assert [
        (d.source_file, d.target_file) for d in result.multifile.interfile_dependencies
    ] == [("scan.sh", "Dockerfile")]


def test_mixed_matches_each_format_analysed_alone():
    files = [("ci.yml", WORKFLOW), ("Dockerfile", "FROM node:latest\n")]
    mixed = compile_files(files, SourceFormat.mixed)
    alone = [
        *compile_files([files[0]], SourceFormat.yaml).diagnostics,
        *compile_files([files[1]], SourceFormat.dockerfile).diagnostics,
    ]
    assert sorted(d.message for d in mixed.diagnostics) == sorted(
        d.message for d in alone
    )


def test_mixed_reports_files_it_cannot_analyse():
    files = [("ci.yml", WORKFLOW), ("notes.txt", "hello")]
    result = compile_files(files, SourceFormat.mixed)
    notes = [d for d in result.diagnostics if d.source_location.file == "notes.txt"]
    [note] = notes
    assert note.code == DiagnosticCode.UNSUPPORTED_CONSTRUCT
    assert note.severity.value == "info"
    assert result.multifile.file_formats["notes.txt"] == "unknown"


def test_mixed_over_http_and_single_source_rejected():
    files = [
        {"filename": "ci.yml", "content": WORKFLOW},
        {"filename": "Dockerfile", "content": SCANNER_DOCKERFILE},
    ]
    response = client.post("/api/v1/validate", json={"format": "mixed", "files": files})
    assert response.status_code == 200
    assert response.json()["format"] == "mixed"

    response = client.post("/api/v1/validate", json={"format": "mixed", "source": "x"})
    assert response.status_code == 422
    assert "needs 'files'" in response.json()["detail"]["message"]
