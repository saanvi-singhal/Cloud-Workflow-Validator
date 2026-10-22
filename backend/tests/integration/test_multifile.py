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
        d for d in inter_deps if d.source_file == "variables.tf" and d.target_file == "main.tf"
    ]
    assert len(var_to_main) >= 2
    symbols_to_main = {d.symbol for d in var_to_main}
    assert "var.vpc_cidr" in symbols_to_main
    assert "var.environment" in symbols_to_main

    # main.tf -> outputs.tf dependency (aws_vpc.main)
    main_to_out = [
        d for d in inter_deps if d.source_file == "main.tf" and d.target_file == "outputs.tf"
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

    dup_diag = next(d for d in result.diagnostics if d.code == DiagnosticCode.DUPLICATE_NODE_ID)
    assert "vars_a.tf" in dup_diag.message and "vars_b.tf" in dup_diag.message

    assert result.multifile is not None
    assert "db_port" in result.multifile.duplicate_variables
    var_occ = next(v for v in result.multifile.variable_occurrences if v.name == "db_port")
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
    assert data["multifile"]["interfile_dependencies"][0]["source_file"] == "variables.tf"
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


def test_multifile_yaml_duplicate_jobs():
    ci_yml = """
on: push
jobs:
  test:
    runs-on: ubuntu-latest
"""
    other_yml = """
on: pull_request
jobs:
  test:
    runs-on: ubuntu-latest
"""
    files = [("ci.yml", ci_yml), ("other.yml", other_yml)]
    result = compile_files(files, SourceFormat.yaml)
    assert result.valid is False
    assert any(d.code == DiagnosticCode.DUPLICATE_NODE_ID for d in result.diagnostics)
