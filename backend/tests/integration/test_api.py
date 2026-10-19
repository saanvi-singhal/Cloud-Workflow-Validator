"""Integration tests for FastAPI validation and health routes."""

from fastapi.testclient import TestClient

from app.main import app
from app.models import DiagnosticCode

client = TestClient(app)


def test_health_check_canonical():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_check_root_alias():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_validate_terraform_success():
    payload = {
        "source": 'resource "aws_vpc" "main" {}\n',
        "format": "terraform",
        "filename": "main.tf",
    }
    response = client.post("/api/v1/validate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["format"] == "terraform"
    assert len(data["graph"]["nodes"]) == 1
    assert data["graph"]["nodes"][0]["id"] == "tf:resource:aws_vpc.main"


def test_validate_yaml_success():
    payload = {
        "source": """
jobs:
  build:
    runs-on: ubuntu-latest
  test:
    runs-on: ubuntu-latest
    needs: build
""",
        "format": "yaml",
        "filename": "ci.yml",
    }
    response = client.post("/api/v1/validate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["format"] == "yaml"
    assert len(data["graph"]["nodes"]) == 2
    assert len(data["graph"]["edges"]) == 1
    assert data["execution_order"] == ["gha:task:build", "gha:task:test"]


def test_validate_dockerfile_success():
    payload = {
        "source": """
FROM golang:1.21 AS build
RUN go build

FROM alpine:latest
COPY --from=build /app /app
""",
        "format": "dockerfile",
        "filename": "Dockerfile",
    }
    response = client.post("/api/v1/validate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["format"] == "dockerfile"
    assert len(data["graph"]["nodes"]) == 2
    assert len(data["graph"]["edges"]) == 1


def test_validate_syntax_error_returns_200_with_diagnostics():
    """Syntax errors return HTTP 200 with diagnostics, not 500 or 4xx."""
    payload = {
        "source": 'resource "aws_vpc" { unclosed',
        "format": "terraform",
        "filename": "broken.tf",
    }
    response = client.post("/api/v1/validate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    codes = [d["code"] for d in data["diagnostics"]]
    assert DiagnosticCode.TERRAFORM_SYNTAX_ERROR.value in codes


def test_validate_unknown_format_returns_422():
    payload = {
        "source": "hello",
        "format": "unsupported_language",
    }
    response = client.post("/api/v1/validate", json=payload)
    assert response.status_code == 422


def test_validate_oversized_payload_returns_413(monkeypatch):
    import app.api.routes as routes

    monkeypatch.setattr(routes, "MAX_SOURCE_BYTES", 50)
    payload = {
        "source": "a" * 100,
        "format": "terraform",
    }
    response = client.post("/api/v1/validate", json=payload)
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "SOURCE_TOO_LARGE"
