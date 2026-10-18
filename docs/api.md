# API Contract

The HTTP contract for Cloud-Workflow-Validator. The authoritative definition is
[PROJECT_SPEC.md section 7](PROJECT_SPEC.md#7-public-api-contract); this page
summarises it and shows what the implemented compiler core actually returns.

## Implementation status

| Part | Owner | Status in this repository |
|---|---|---|
| Response payload (`AnalysisResult` and its nested models) | Compiler core | **Implemented**: `backend/app/models/`, produced by `app.compiler.pipeline.compile_source()` |
| Terraform analysis | Compiler core | **Implemented**: `backend/app/parsers/terraform/` |
| GitHub Actions YAML and Dockerfile parsers | Saanvi | **Not implemented yet** (`compile_source` raises `AdapterNotAvailableError` for `yaml`/`dockerfile`) |
| FastAPI app, `ValidationRequest`, routes, HTTP status handling, size limit | Saanvi | **Not implemented yet**: there is no `backend/app/main.py` and `backend/app/api/` is empty |

Nothing below is a running endpoint until the API layer exists. The response
examples are real pipeline output (see [Examples](#examples)).

## Endpoints (contract, spec 7.1-7.2)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/health` | Canonical health check. A root `/health` alias is optional and must not replace it. The response body is not fixed by the spec; the API owner defines it. |
| `POST` | `/api/v1/validate` | Parse and statically analyse one source file. |

## Request: `POST /api/v1/validate`

```json
{
  "source": "resource \"aws_vpc\" \"main\" {}\n",
  "format": "terraform",
  "filename": "main.tf"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `source` | string | yes | Source text. It is parsed, never executed. |
| `format` | `"yaml"` \| `"dockerfile"` \| `"terraform"` | yes | Unknown values are rejected with a 4xx error. |
| `filename` | string | no | Display name for diagnostics only (`source_location.file`). It is never opened on the server. If it is omitted, `file` is `null`. |

There are no other request fields. In particular, there is no `options` object.

## Response (HTTP 200)

```json
{
  "valid": true,
  "format": "terraform",
  "diagnostics": [],
  "graph": { "nodes": [], "edges": [] },
  "execution_order": [],
  "recommendations": []
}
```

| Field | Meaning |
|---|---|
| `valid` | `false` if and only if at least one diagnostic has severity `error`. Warnings and info never make it false. |
| `format` | The normalised format that was analysed. |
| `diagnostics` | Compact diagnostic objects, deterministically sorted (see below). |
| `graph.nodes` / `graph.edges` | The normalised graph. Nodes are sorted by `id`; edges by `(source, target, type)`. |
| `execution_order` | A list of node ids, or `null` (see below). |
| `recommendations` | Deterministic recommendations, each linked to one diagnostic. |

### Node

| Field | Type | Notes |
|---|---|---|
| `id` | string | Stable and deterministic, e.g. `tf:resource:aws_vpc.main`. No UUIDs. |
| `label` | string | Human-readable label, e.g. `aws_vpc.main`. |
| `type` | string | One of `task`, `stage`, `instruction`, `resource`, `data_source`, `module`, `variable`, `output`, `unknown`. |
| `source_location` | object \| null | See [Source locations](#source-locations). |
| `metadata` | object | Format-specific details; `{}` when there are none. |

### Edge

| Field | Type | Notes |
|---|---|---|
| `source` | string | Node id of the **prerequisite**. |
| `target` | string | Node id of the **dependent**. |
| `type` | string | `workflow_dependency`, `terraform_reference`, `terraform_explicit_dependency`, `docker_stage_base`, or `docker_instruction_order` (the last is not emitted by any implemented code). |
| `label` | string \| null | e.g. the Terraform attribute holding the reference (`vpc_id`, `depends_on`). |
| `source_location` | object \| null | Where the dependency is declared. |
| `metadata` | object | Terraform edges carry `references`: one entry per occurrence (`attribute`, `expression`, `location`). |

Edges have **no `id` field**. A client that needs a key can use
`${source}->${target}:${type}`.

**Edge direction (spec 3.6):** `A -> B` means A must precede B; B depends on A.
In Terraform, if resource B references resource A, the edge is `A -> B`.
Clients must not reverse edges.

### Source locations

```json
{ "file": "main.tf", "start_line": 4, "start_column": 1, "end_line": 8, "end_column": 2 }
```

- All positions are **one-based**.
- **`end_column` is exclusive**: it points one past the last character (approved decision D4; it matches the Lark parser behind python-hcl2). A block ending with `}` in column 1 has `end_column: 2`. Editor highlighting must treat the end as exclusive.
- Any field, or the whole object, may be `null`. Positions are never invented.

### Diagnostic

| Field | Type | Notes |
|---|---|---|
| `code` | string | Stable code (table below). Clients and tests should match on `code`, not on `message`. |
| `severity` | `"error"` \| `"warning"` \| `"info"` | Lowercase. |
| `message` | string | Human-readable explanation. |
| `source_location` | object \| null | Serialised as `null` when unavailable. |

There are no other diagnostic fields (no `location`, `element_ids` or category).

| Code | Severity | Produced by |
|---|---|---|
| `YAML_SYNTAX_ERROR` | error | YAML parser (not implemented yet) |
| `DOCKERFILE_SYNTAX_ERROR` | error | Dockerfile parser (not implemented yet) |
| `TERRAFORM_SYNTAX_ERROR` | error | Terraform adapter |
| `DUPLICATE_NODE_ID` | error | Terraform adapter, graph validation |
| `UNRESOLVED_DEPENDENCY` | error | Terraform adapter (undeclared reference; no edge is created) |
| `DEPENDENCY_CYCLE` | error | Cycle analysis: one per cyclic region, self-loops included |
| `DISCONNECTED_COMPONENT` | info | Connectivity analysis (YAML/Terraform policy) |
| `UNREACHABLE_NODE` | warning | Reachability analysis (Dockerfile: stage not needed by the final stage) |
| `UNSUPPORTED_CONSTRUCT` | warning or info | Parsers. A warning means dependencies may be missing (partial analysis). An info means a valid construct that is not graphed. |
| `SECURITY_RULE_VIOLATION` | warning | Terraform rules; the message starts with the rule id, e.g. `[TF_S3_PUBLIC_ACL]` |
| `INVALID_GRAPH` | error | Graph validation: internal parser inconsistency |
| `SOURCE_TOO_LARGE` | n/a | Reserved for the API size limit. The core never produces it. |

`INVALID_GRAPH` and `UNREACHABLE_NODE` were added by approved decision D2 and are
not yet in the spec's example list. Full details are in [compiler-core.md](compiler-core.md#4-diagnostic-codes).

Diagnostics are sorted by location (`file`, `start_line`, `start_column`;
diagnostics without a location go last), then severity, `code` and `message`.

### `execution_order`

A list of node ids in dependency order (Kahn's algorithm; ties broken by the
lexicographically smallest id). It is `null`, never a partial order, when any
of these hold:

- any diagnostic has severity `error` (this includes cycles, unresolved references and syntax errors);
- the graph is cyclic;
- ordering is not meaningful for the format (Dockerfiles always get `null`);
- dependency analysis is incomplete (a warning-level `UNSUPPORTED_CONSTRUCT` is present).

### Recommendation

Defined in `backend/app/models/recommendations.py`:

| Field | Type | Notes |
|---|---|---|
| `id` | string | Stable: `"<rule_id>:<diagnostic_index>"`. |
| `rule_id` | string | e.g. `BREAK_DEPENDENCY_CYCLE`, `RESOLVE_MISSING_DEPENDENCY`, `TF_S3_PUBLIC_ACL`. |
| `title` | string | Short headline. |
| `explanation` | string | Why it matters and what to consider. |
| `diagnostic_code` | string | Code of the linked diagnostic. |
| `diagnostic_index` | integer | Index into this response's `diagnostics` list. |
| `fix_kind` | `"deterministic"` \| `"judgment"` | Every v1 recommendation is `judgment`; none is claimed to be provably safe. |
| `proposed_change` | object \| null | `{description, preview, source_location}`. `preview` is a text diff only when the exact edit is known, otherwise `null`. |
| `source_location` | object \| null | Same as the linked diagnostic. |
| `related_node_ids` | string[] | Nodes to highlight. |

Recommendations never modify the source; a `preview` is text only. The full
catalogue is in [compiler-core.md](compiler-core.md#9-recommendations).

## HTTP status semantics (spec 7.4)

| Status | When |
|---|---|
| **200** | The request was processed and analysis completed, **including invalid source**. Syntax errors, cycles and unresolved references are diagnostics in a 200 response, not HTTP errors. |
| **4xx** | Malformed request body, unsupported `format` value, or source larger than the application limit. |
| **5xx** | Unexpected server failures only. |

The exact 4xx codes and error-body shape belong to the API layer and have not
been implemented yet.

### Source-size limit (spec 7.5)

The limit is a **configurable, application-level** limit. Its default value
**has not been chosen yet**. Spec 7.5 requires choosing it only after measuring
the real deployment's request limits. Exceeding it returns a clear client
error (`SOURCE_TOO_LARGE`).

## Examples

The examples below are **real output** from
`compile_source(text, SourceFormat.terraform, filename=...)` on files in
`examples/terraform/`, generated on this branch and serialised with
`model_dump(mode="json")`. They show the payload the API is expected to
return; they were not captured from a running HTTP server.

### Valid file with explicit and inferred dependencies (`examples/terraform/depends_on.tf`)

```json
{
  "valid": true,
  "format": "terraform",
  "diagnostics": [],
  "graph": {
    "nodes": [
      {
        "id": "tf:resource:aws_iam_role.deployer",
        "label": "aws_iam_role.deployer",
        "type": "resource",
        "source_location": {
          "file": "depends_on.tf",
          "start_line": 6,
          "start_column": 1,
          "end_line": 8,
          "end_column": 2
        },
        "metadata": {
          "block_type": "resource",
          "address": "aws_iam_role.deployer",
          "attributes": [
            "name"
          ],
          "resource_type": "aws_iam_role",
          "name": "deployer"
        }
      },
      {
        "id": "tf:resource:aws_instance.builder",
        "label": "aws_instance.builder",
        "type": "resource",
        "source_location": {
          "file": "depends_on.tf",
          "start_line": 10,
          "start_column": 1,
          "end_line": 19,
          "end_column": 2
        },
        "metadata": {
          "block_type": "resource",
          "address": "aws_instance.builder",
          "attributes": [
            "ami",
            "depends_on",
            "iam_instance_profile",
            "instance_type"
          ],
          "resource_type": "aws_instance",
          "name": "builder"
        }
      },
      {
        "id": "tf:resource:aws_s3_bucket.artifacts",
        "label": "aws_s3_bucket.artifacts",
        "type": "resource",
        "source_location": {
          "file": "depends_on.tf",
          "start_line": 2,
          "start_column": 1,
          "end_line": 4,
          "end_column": 2
        },
        "metadata": {
          "block_type": "resource",
          "address": "aws_s3_bucket.artifacts",
          "attributes": [
            "bucket"
          ],
          "resource_type": "aws_s3_bucket",
          "name": "artifacts"
        }
      }
    ],
    "edges": [
      {
        "source": "tf:resource:aws_iam_role.deployer",
        "target": "tf:resource:aws_instance.builder",
        "type": "terraform_explicit_dependency",
        "label": "depends_on",
        "source_location": {
          "file": "depends_on.tf",
          "start_line": 17,
          "start_column": 5,
          "end_line": 17,
          "end_column": 26
        },
        "metadata": {
          "references": [
            {
              "attribute": "depends_on",
              "expression": "aws_iam_role.deployer",
              "location": {
                "file": "depends_on.tf",
                "start_line": 17,
                "start_column": 5,
                "end_line": 17,
                "end_column": 26
              }
            }
          ]
        }
      },
      {
        "source": "tf:resource:aws_iam_role.deployer",
        "target": "tf:resource:aws_instance.builder",
        "type": "terraform_reference",
        "label": "iam_instance_profile",
        "source_location": {
          "file": "depends_on.tf",
          "start_line": 13,
          "start_column": 26,
          "end_line": 13,
          "end_column": 52
        },
        "metadata": {
          "references": [
            {
              "attribute": "iam_instance_profile",
              "expression": "aws_iam_role.deployer.name",
              "location": {
                "file": "depends_on.tf",
                "start_line": 13,
                "start_column": 26,
                "end_line": 13,
                "end_column": 52
              }
            }
          ]
        }
      },
      {
        "source": "tf:resource:aws_s3_bucket.artifacts",
        "target": "tf:resource:aws_instance.builder",
        "type": "terraform_explicit_dependency",
        "label": "depends_on",
        "source_location": {
          "file": "depends_on.tf",
          "start_line": 16,
          "start_column": 5,
          "end_line": 16,
          "end_column": 28
        },
        "metadata": {
          "references": [
            {
              "attribute": "depends_on",
              "expression": "aws_s3_bucket.artifacts",
              "location": {
                "file": "depends_on.tf",
                "start_line": 16,
                "start_column": 5,
                "end_line": 16,
                "end_column": 28
              }
            }
          ]
        }
      }
    ]
  },
  "execution_order": [
    "tf:resource:aws_iam_role.deployer",
    "tf:resource:aws_s3_bucket.artifacts",
    "tf:resource:aws_instance.builder"
  ],
  "recommendations": []
}
```

Note the two distinct edge types between `aws_iam_role.deployer` and
`aws_instance.builder`: one from `depends_on`, one from the attribute reference.

### Cyclic file (`examples/terraform/cyclic.tf`)

Fields shown: `valid`, `format`, `diagnostics`, `execution_order` (with `graph`
omitted for brevity):

```json
{
  "valid": false,
  "format": "terraform",
  "diagnostics": [
    {
      "code": "DEPENDENCY_CYCLE",
      "severity": "error",
      "message": "Dependency cycle: aws_security_group.app -> aws_security_group.db -> aws_security_group.app.",
      "source_location": {
        "file": "cyclic.tf",
        "start_line": 9,
        "start_column": 24,
        "end_line": 9,
        "end_column": 48
      }
    },
    {
      "code": "DEPENDENCY_CYCLE",
      "severity": "error",
      "message": "Self-dependency: 'aws_s3_bucket.logs' depends on itself.",
      "source_location": {
        "file": "cyclic.tf",
        "start_line": 25,
        "start_column": 20,
        "end_line": 25,
        "end_column": 41
      }
    }
  ],
  "execution_order": null
}
```

The first recommendation from the same response:

```json
{
  "id": "BREAK_DEPENDENCY_CYCLE:0",
  "rule_id": "BREAK_DEPENDENCY_CYCLE",
  "title": "Break the dependency cycle",
  "explanation": "No valid execution order exists while this cycle remains. Break it by removing or inverting one of these dependencies: 'aws_security_group.db' depends on 'aws_security_group.app' (via 'ingress.security_groups'); 'aws_security_group.app' depends on 'aws_security_group.db' (via 'egress.security_groups').",
  "diagnostic_code": "DEPENDENCY_CYCLE",
  "diagnostic_index": 0,
  "fix_kind": "judgment",
  "proposed_change": {
    "description": "Remove one dependency on the cycle; which one depends on your intent, so this is not done automatically.",
    "preview": null,
    "source_location": {
      "file": "cyclic.tf",
      "start_line": 9,
      "start_column": 24,
      "end_line": 9,
      "end_column": 48
    }
  },
  "source_location": {
    "file": "cyclic.tf",
    "start_line": 9,
    "start_column": 24,
    "end_line": 9,
    "end_column": 48
  },
  "related_node_ids": [
    "tf:resource:aws_security_group.app",
    "tf:resource:aws_security_group.db"
  ]
}
```
