# API Specification & Contracts

This document specifies the planned REST API contract exposed by the FastAPI backend service for the **Compiler-Based Cloud Workflow Validator**.

---

## 1. Base URL & Versioning

- Local Development Base URL: `http://localhost:8000`
- Deployed Vercel Base URL: `https://<backend-project>.vercel.app`
- API Prefix: `/api/v1`

---

## 2. Endpoints

### A. Health & Service Status

#### `GET /api/v1/health`
Returns the operational health and version status of the validator backend. This is the canonical health check endpoint.
*(Note: A root alias or redirect from `GET /health` to `GET /api/v1/health` may optionally be supported for infrastructure probes).*

**Response `200 OK`**:
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "supported_formats": ["yaml", "dockerfile", "terraform"]
}
```

---

### B. Validation & Analysis

#### `POST /api/v1/validate`
Main entrypoint for static compilation, dependency graph generation, cycle detection, and linting recommendations.

**Request Headers**:
- `Content-Type: application/json`

**Request Body Schema (`ValidationRequest`)**:
```json
{
  "format": "yaml", 
  "content": "name: CI\non: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps: []\n  deploy:\n    needs: build\n    runs-on: ubuntu-latest\n    steps: []",
  "filename": "workflow.yml",
  "options": {
    "detect_cycles": true,
    "detect_orphans": true,
    "generate_recommendations": true
  }
}
```

**Field Descriptions**:
| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `format` | `string` | Yes | Target parser adapter: `"yaml"`, `"dockerfile"`, or `"terraform"`. |
| `content` | `string` | Yes | Raw string contents of the configuration file. |
| `filename` | `string` | No | Optional filename for source mapping and error reporting. |
| `options` | `object` | No | Optional analysis flags toggling specific compiler passes. |

**Response `200 OK` Schema (`ValidationResponse`)**:
```json
{
  "is_valid": true,
  "summary": {
    "total_nodes": 2,
    "total_edges": 1,
    "error_count": 0,
    "warning_count": 0,
    "has_cycles": false
  },
  "graph": {
    "nodes": [
      {
        "id": "job_build",
        "label": "build",
        "kind": "job",
        "source_location": {
          "file": "workflow.yml",
          "start_line": 4,
          "end_line": 7
        },
        "metadata": {
          "runs_on": "ubuntu-latest"
        }
      },
      {
        "id": "job_deploy",
        "label": "deploy",
        "kind": "job",
        "source_location": {
          "file": "workflow.yml",
          "start_line": 8,
          "end_line": 12
        },
        "metadata": {
          "runs_on": "ubuntu-latest"
        }
      }
    ],
    "edges": [
      {
        "id": "edge_deploy_needs_build",
        "source": "job_build",
        "target": "job_deploy",
        "kind": "explicit_needs",
        "label": "needs"
      }
    ]
  },
  "diagnostics": [],
  "recommendations": []
}
```

**Response `200 OK` (With Detected Cycle or Lint Diagnostics)**:
```json
{
  "is_valid": false,
  "summary": {
    "total_nodes": 2,
    "total_edges": 2,
    "error_count": 1,
    "warning_count": 0,
    "has_cycles": true
  },
  "graph": {
    "nodes": [ ... ],
    "edges": [ ... ]
  },
  "diagnostics": [
    {
      "code": "ERR_CYCLE_DETECTED",
      "severity": "ERROR",
      "message": "Circular dependency detected along cycle: job_a -> job_b -> job_a",
      "location": {
        "file": "workflow.yml",
        "start_line": 5,
        "end_line": 10
      },
      "element_ids": ["job_a", "job_b"]
    }
  ],
  "recommendations": [
    {
      "rule_id": "RULE-CYCLE-001",
      "title": "Break Circular Dependency",
      "explanation": "Jobs 'job_a' and 'job_b' depend on each other, preventing task scheduling.",
      "suggested_fix": "Remove 'needs: job_b' from job_a or extract shared tasks into an intermediate job.",
      "diff": "- needs: job_b\n+ # removed circular prerequisite"
    }
  ]
}
```

---

## 3. Error Codes & Handling

| HTTP Status | Error Type | Description |
| :--- | :--- | :--- |
| `400 Bad Request` | `INVALID_FORMAT` | Format specified is not one of `["yaml", "dockerfile", "terraform"]`. |
| `413 Payload Too Large`| `PAYLOAD_EXCEEDS_LIMIT`| Input content exceeds maximum allowed payload size (4.5 MB). |
| `422 Unprocessable` | `SYNTAX_ERROR` | Syntax in input configuration is unparseable (e.g. malformed YAML syntax). |
| `500 Server Error` | `INTERNAL_COMPILER_ERROR`| Unhandled exception encountered during graph compilation. |
