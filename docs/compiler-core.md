# Compiler Core Reference

Contract reference for the compiler core (owner: project lead). The shared contract is defined in `docs/PROJECT_SPEC.md`; this file documents how the implementation realises it, and the decisions approved in `docs/claude-planning.md` (D1–D17). Where this file and the spec disagree, the spec wins. Please report the conflict.

## 1. Module map

| Path | Role |
|---|---|
| `backend/app/models/` | Public wire contract (Pydantic): `SourceLocation`, `Node`, `Edge`, `GraphPayload`, `Diagnostic`, `DiagnosticCode`, `Recommendation`, `ProposedChange`, `AnalysisResult`, enums |
| `backend/app/compiler/ir.py` | `IRGraph`, stable IDs (`make_node_id`, `unique_id`), deterministic sorting |
| `backend/app/compiler/graph.py` | `DependencyGraph`: sorted adjacency index used by algorithms |
| `backend/app/compiler/findings.py` | Internal `Finding` = diagnostic + rule/node context (never serialised) |
| `backend/app/compiler/policy.py` | Per-format analysis policy |
| `backend/app/compiler/adapters.py` | `SourceAdapter` Protocol, `ParseResult`, adapter registry |
| `backend/app/compiler/pipeline.py` | `compile_source()` / `analyze_ir()`: the single entry point |
| `backend/app/analysis/` | `validation.py`, `cycles.py`, `topological_sort.py`, `reachability.py` |
| `backend/app/parsers/terraform/` | Terraform adapter (single `.tf` file) |
| `backend/app/rules/terraform_rules.py` | Terraform security rules |
| `backend/app/recommendations/` | `engine.py`, `catalog.py` |

Dependencies point one way: `api → compiler → analysis/recommendations → models`, and `parsers → compiler (adapter contract) → models`.

## 2. Contract essentials

- **Edge direction:** `source → target` means *source is a prerequisite of target*; the target depends on the source. Terraform: if B references A, the edge is `A → B`.
- **Source locations:** 1-based, and every field is nullable. **`end_column` is exclusive** (one past the last character). `file` is the request's `filename`, or `null` when none was given. Values are never invented.
- **Determinism:** nodes are sorted by `id`; edges by `(source, target, type)`; diagnostics by location (file, line, column; unlocated last), then severity, code and message; Kahn ties are broken by smallest `id`.
- **`valid`** is `false` exactly when some diagnostic has severity `error`.
- **`execution_order`** is a list of node ids only when **all** of these hold:
  - the format's policy says ordering is meaningful (not for Dockerfiles);
  - a graph exists (no syntax error);
  - there are no cycles;
  - dependency analysis is complete (no warning-level `UNSUPPORTED_CONSTRUCT`);
  - there are no error diagnostics.

  Otherwise it is `null`. It is never a partial order.

### Example response (real output for a two-resource file with a typo)

```json
{
  "valid": false,
  "format": "terraform",
  "diagnostics": [
    {
      "code": "UNRESOLVED_DEPENDENCY",
      "severity": "error",
      "message": "Reference to undeclared resource 'aws_vpc.mian' (in 'tags'). v1 analyses a single .tf file, so it must be declared in this file.",
      "source_location": {"file": "main.tf", "start_line": 5, "start_column": 21, "end_line": 5, "end_column": 36}
    }
  ],
  "graph": {
    "nodes": [
      {"id": "tf:resource:aws_subnet.app", "label": "aws_subnet.app", "type": "resource",
       "source_location": {"file": "main.tf", "start_line": 3, "start_column": 1, "end_line": 6, "end_column": 2},
       "metadata": {"block_type": "resource", "address": "aws_subnet.app", "attributes": ["tags", "vpc_id"], "resource_type": "aws_subnet", "name": "app"}},
      {"id": "tf:resource:aws_vpc.main", "label": "aws_vpc.main", "type": "resource", "source_location": {"...": "..."}, "metadata": {"...": "..."}}
    ],
    "edges": [
      {"source": "tf:resource:aws_vpc.main", "target": "tf:resource:aws_subnet.app", "type": "terraform_reference", "label": "vpc_id",
       "source_location": {"file": "main.tf", "start_line": 4, "start_column": 12, "end_line": 4, "end_column": 27},
       "metadata": {"references": [{"attribute": "vpc_id", "expression": "aws_vpc.main.id", "location": {"...": "..."}}]}}
    ]
  },
  "execution_order": null,
  "recommendations": [
    {
      "id": "RESOLVE_MISSING_DEPENDENCY:0",
      "rule_id": "RESOLVE_MISSING_DEPENDENCY",
      "title": "Did you mean 'aws_vpc.main'?",
      "explanation": "'aws_vpc.mian' is not declared, but 'aws_vpc.main' is and has a very similar name. If this is a typo, correct the reference.",
      "diagnostic_code": "UNRESOLVED_DEPENDENCY",
      "diagnostic_index": 0,
      "fix_kind": "judgment",
      "proposed_change": {"description": "Replace 'aws_vpc.mian' with 'aws_vpc.main'.", "preview": "- aws_vpc.mian\n+ aws_vpc.main", "source_location": {"...": "..."}},
      "source_location": {"...": "..."},
      "related_node_ids": ["tf:resource:aws_subnet.app"]
    }
  ]
}
```

## 3. Stable node IDs

The format is `<format prefix>:<kind>:<identity>`. No UUIDs or hashes. If the same identity is declared twice, the second gets `#2`, the third `#3`, assigned in source order, and the parser reports `DUPLICATE_NODE_ID`.

| Construct | ID |
|---|---|
| Terraform resource `aws_vpc.main` | `tf:resource:aws_vpc.main` |
| Terraform data source | `tf:data:aws_ami.ubuntu` |
| Terraform module / variable / output | `tf:module:net`, `tf:variable:env`, `tf:output:vpc_id` |
| GitHub Actions job (suggested) | `gha:job:<job_id>` |
| Docker stage (suggested) | `docker:stage:<0-based index>` |

## 4. Diagnostic codes

| Code | Severity | Emitted by | Meaning |
|---|---|---|---|
| `YAML_SYNTAX_ERROR` / `DOCKERFILE_SYNTAX_ERROR` / `TERRAFORM_SYNTAX_ERROR` | error | parsers | Source could not be parsed (`graph` is empty), or is not valid for the format: e.g. a repeated YAML key, YAML with no `jobs` (not a GitHub Actions workflow), a GitHub Actions schema violation (missing `on`, an unknown trigger event, a key GitHub does not allow at workflow, job or step level such as `x-...`, the `secrets` context in a job or step `if` or in a reusable-workflow call's `with`, a key other than `name/uses/with/secrets/strategy/needs/if/concurrency/permissions` in a job that calls a reusable workflow, a job without `runs-on`, a step without exactly one of `uses`/`run`), a Dockerfile with no `FROM` or an unknown instruction, `HEALTHCHECK` without `CMD`/`NONE`, `ONBUILD ONBUILD`/`FROM`/`MAINTAINER` |
| `DUPLICATE_NODE_ID` | error | parsers, `validation.py` | Same identity declared twice |
| `UNRESOLVED_DEPENDENCY` | error | parsers | Reference to something not declared; **no edge is created** |
| `DEPENDENCY_CYCLE` | error | `cycles.py` | One per cyclic region (Tarjan SCC), with a readable path (DFS); self-loops included |
| `DISCONNECTED_COMPONENT` | info (per policy) | `reachability.py` | A multi-node component not connected to the main one |
| `UNREACHABLE_NODE` | warning | `reachability.py` | Not needed by the format's root (Dockerfile: the final stage) |
| `UNSUPPORTED_CONSTRUCT` | warning, or info | parsers | warning = may hide dependencies (makes `execution_order` null); info = valid construct not modelled in the graph |
| `SECURITY_RULE_VIOLATION` | warning (Dockerfile rules: error, warning or info) | rules | Message is prefixed with the rule id, e.g. `[TF_S3_PUBLIC_ACL]`, `[DF_RUNS_AS_ROOT]` |
| `INVALID_GRAPH` | error | `validation.py` | IR inconsistency (dangling edge endpoint, edge type not allowed for the format): a parser bug |
| `SOURCE_TOO_LARGE` | error | API layer | Reserved for the API size limit; not produced by the core |

Tests assert on codes, not on message text.

## 5. Format policy

| Format | `execution_order` | Disconnected components | Reachability root |
|---|---|---|---|
| yaml | yes | info, multi-node components only (isolated jobs are normal) | none |
| terraform | yes | info, multi-node components only | none |
| dockerfile | `null` (spec 5.3) | disabled | final stage: node with `metadata.is_final_stage == true`, else highest `metadata.stage_index`; neither present → no check |

No universal root is invented. Formats without a root get no reachability check.

## 6. Algorithms

- **Validation** (`validate_graph`) runs first: duplicate ids (keep the first), dangling edges, and edge types not allowed for the format are reported and dropped.
- **Tarjan's SCC** (iterative) finds every cyclic region in O(V+E).
- **DFS** with WHITE/GRAY/BLACK colours, restricted to each cyclic SCC, reconstructs one closed path. The diagnostic's location is the edge that closes the cycle; if that edge has no location, the dependent node's location is used.
- **Kahn's algorithm** with a min-heap gives a deterministic order, or `None` if nodes remain (cycle).
- **Weakly connected components** come from a BFS ignoring direction. **Ancestors** come from a BFS over predecessors (a root's prerequisites).

All of these use explicit stacks or queues, with no recursion, so long chains don't hit Python's recursion limit. 5000-node chains are tested.

## 7. Terraform support (v1, single `.tf` file)

Parsing goes through `hcl2.parses_to_tree` (python-hcl2 8.x Lark tree), **not** `hcl2.loads`: the dict form has opaque `${...}` strings and no positions. Nothing is evaluated; no provider or `terraform` command is ever run.

| Construct | Handling |
|---|---|
| `resource`, `data`, `module`, `variable`, `output` blocks | Graph nodes |
| `provider`, `terraform`, `locals`, `moved`, `import`, `check`, `removed` | Not in graph; `UNSUPPORTED_CONSTRUCT` (info) |
| Unknown top-level block / top-level attribute | `UNSUPPORTED_CONSTRUCT` (warning) |
| `TYPE.NAME…`, `data.T.N…`, `module.N…`, `var.N` | `terraform_reference` edge |
| Indexes / splats (`a.b[0].id`, `a.b[*].id`, `a.b.*.id`) | Depend on the whole block; index expressions are also scanned |
| Conditionals, operators, function arguments, tuples, object values, computed object keys, `${}` interpolation | Scanned recursively |
| `depends_on = [a.b, data.x.y, module.m]` | `terraform_explicit_dependency` edge; anything else (attributes, indexes, `var.*`, strings) is reported as unsupported |
| `count.*`, `each.*`, `self.*`, `path.*`, `terraform.*` | Meta-values, not dependencies |
| `provider = …`, module `providers = {…}`, `lifecycle.ignore_changes` | Not dependencies; skipped by rule |
| `variable` block contents | No dependencies (defaults must be literal) |
| `local.*`, `for` expressions, `%{}` directives, heredocs with interpolation, `replace_triggered_by`, unknown expression forms | `UNSUPPORTED_CONSTRUCT` (warning); analysis is marked incomplete |
| `dynamic "X" { for_each = ...  iterator = ...  content { ... } }` | `for_each` is analysed in the enclosing scope; inside `content` and `labels` the iterator (`X`, or the `iterator` name) is the current element, not a dependency. Nested `dynamic` blocks are supported. Missing `for_each`, no or several `content` blocks, or another argument directly in the block is a `TERRAFORM_SYNTAX_ERROR` (Terraform rejects them) |
| Reference to an undeclared block | `UNRESOLVED_DEPENDENCY` (error), no edge |
| Repeated references A→B | Merged into one edge per type; every occurrence is listed in `metadata.references` |

## 8. Terraform security rules

These are literal-only: a value that comes from a variable or expression never triggers a rule. All are warnings. This is not a comprehensive scanner.

| rule_id | Fires when |
|---|---|
| `TF_S3_PUBLIC_ACL` | `aws_s3_bucket`/`aws_s3_bucket_acl` `acl` is `public-read` or `public-read-write` |
| `TF_SG_OPEN_INGRESS` | `0.0.0.0/0` or `::/0` in `aws_security_group` `ingress` blocks, `aws_security_group_rule` (type `ingress`), or `aws_vpc_security_group_ingress_rule` |
| `TF_HARDCODED_SECRET` | `password`, `secret_key`, `access_key`, `token`, `api_key`, … is a non-empty string literal (resource/data/module/provider), or a secret-named variable has a literal default |
| `TF_DB_PUBLICLY_ACCESSIBLE` | `aws_db_instance`/`aws_rds_cluster_instance` has `publicly_accessible = true` |

## 8a. Dockerfile rules

`app/rules/dockerfile_rules.py`, called by the Dockerfile adapter. The rules read instruction text only. Nothing is built, pulled or executed, and a value containing a `$` variable is skipped rather than guessed. Severity: **error** when the build itself will fail, **warning** for security and reproducibility risks, **info** for image size and build-cache advice. Every finding is linked to its stage node. This is not a comprehensive linter.

| rule_id | Severity | Fires when |
|---|---|---|
| `DF_EXEC_FORM_NOT_JSON` | error | `CMD`/`ENTRYPOINT`/`RUN`/`SHELL`/`HEALTHCHECK CMD` written as `[...]` but not a valid JSON array of strings (e.g. single quotes); Docker runs it as a shell string, so the command fails. The fix previews the double-quoted form |
| `DF_APT_MISSING_YES` | error | `apt-get`/`apt` install, upgrade or remove without `-y` (also accepts `--yes`, `--assume-yes`, `-qq`, combined flags like `-qy`); the build cannot answer the prompt and aborts |
| `DF_UNPINNED_BASE_IMAGE` | warning | `FROM` an image with no tag or `:latest` and no `@sha256` digest (earlier stages, `scratch` and `$VAR` images are skipped) |
| `DF_RUNS_AS_ROOT` | warning | the final stage has no `USER`, or its last `USER` is `root`/`0` |
| `DF_APT_UPDATE_ALONE` | warning | a `RUN` with `apt-get update` but no install in the same `RUN` |
| `DF_APT_UPGRADE` | warning | `apt-get upgrade`, `dist-upgrade` or `full-upgrade` |
| `DF_ADD_LOCAL_FILE` | warning | `ADD` of a local file that is not a tar archive (URLs and git sources are skipped) |
| `DF_COPY_ALL_BEFORE_INSTALL` | info | `COPY . .` (or `ADD .`) before a dependency install (`npm install/ci`, `pip install -r`, `poetry install`, …) in the same stage |
| `DF_CONSECUTIVE_RUN` | info | two or more `RUN` in a row in one stage; reported once per group, at its first `RUN` |
| `DF_APT_UNPINNED_PACKAGES` | info | `apt-get install` packages without `=version` |

## 8b. GitHub Actions rules

`app/rules/github_actions_rules.py`, called by the YAML adapter. Workflows GitHub would reject are handled by the parser's schema checks (`YAML_SYNTAX_ERROR`). These rules flag workflows GitHub accepts but that likely do not do what was meant.

| rule_id | Severity | Fires when |
|---|---|---|
| `GHA_NUMBER_LOSES_ZERO` | warning | an unquoted number with a trailing zero in its fraction (`3.10`, `18.0`) anywhere in a job; YAML reads it as a number, so GitHub sees `3.1` / `18` |
| `GHA_SCRIPT_INJECTION` | warning | `${{ ... }}` with attacker-controlled event data (issue/PR/discussion title or body, comment and review bodies, `head_ref` and other branch names, commit messages and authors, page names) inside a `run` script or `actions/github-script`'s `script`. Values passed through `env` are not flagged. The recommendation previews the `env` rewrite |

Booleans and numbers in `env` (`DEBUG: true`, `PORT: 8080`) are *not* flagged: GitHub converts them to the strings `"true"` and `"8080"`.

## 9. Recommendations

The engine walks findings in final sorted order, so `diagnostic_index` is the index into `diagnostics`, and `id = "<rule_id>:<diagnostic_index>"`. In v1 every recommendation is `fix_kind: "judgment"`, because none can be proven safe. `preview` is set only when the exact edit is known. Nothing is ever applied to source.

| Diagnostic | rule_id | Proposed change |
|---|---|---|
| `DEPENDENCY_CYCLE` | `BREAK_DEPENDENCY_CYCLE` | Lists the cycle's edges, explicit `depends_on` first; description only |
| `UNRESOLVED_DEPENDENCY` | `RESOLVE_MISSING_DEPENDENCY` | "Did you mean X?" with a preview when `difflib` finds a close match |
| `DUPLICATE_NODE_ID` | `RENAME_DUPLICATE` | None |
| `DISCONNECTED_COMPONENT` | `REVIEW_DISCONNECTED` | None |
| `UNREACHABLE_NODE` | `REVIEW_UNUSED_NODE` | None |
| `UNSUPPORTED_CONSTRUCT` (warning only) | `UNSUPPORTED_LIMITATION` | None |
| `INVALID_GRAPH` | `REPORT_INTERNAL_INCONSISTENCY` | None |
| `SECURITY_RULE_VIOLATION` (Dockerfile) | the finding's `DF_*` rule id | Previews for `DF_APT_MISSING_YES` (adds `-y`), `DF_ADD_LOCAL_FILE` (ADD → COPY), `DF_RUNS_AS_ROOT`, `DF_APT_UPDATE_ALONE` and `DF_COPY_ALL_BEFORE_INSTALL` (example edits); description only for the others |
| `*_SYNTAX_ERROR` | `FIX_SYNTAX_ERROR` | None |
| `SECURITY_RULE_VIOLATION` | the rule's id | ACL → `private` and public DB → `false` have previews; CIDR and secret changes are description-only |

## 10. Integration guide

### For the YAML / Dockerfile parsers and the API (Saanvi)

```python
from app.compiler.adapters import ParseResult, register_adapter
from app.compiler.findings import make_finding
from app.compiler.ir import IRGraph, make_node_id, unique_id
from app.models import DiagnosticCode, Edge, EdgeType, Node, NodeType, Severity, SourceFormat, SourceLocation

class GithubActionsAdapter:
    format = SourceFormat.yaml
    def parse(self, source: str, filename: str | None) -> ParseResult: ...

ADAPTER = GithubActionsAdapter()   # add the module to BUILTIN_ADAPTER_MODULES, or call register_adapter(ADAPTER)
```

- Create `UNRESOLVED_DEPENDENCY` findings for unknown `needs` / `COPY --from` targets **instead of** dangling edges. A dangling edge becomes `INVALID_GRAPH`.
- Set `dependency_analysis_complete=False` if a construct you can't analyse may hide dependencies.
- Dockerfile stage nodes must set `metadata.stage_index` (int, 0-based) and `metadata.is_final_stage` (bool), per spec 4.2. Ordered instructions are in `metadata.instructions`, one object per instruction (comments excluded): `{"instruction": "RUN", "text": "RUN npm ci", "start_line": 4, "end_line": 4}`, with 1-based lines; `text` keeps line continuations. The frontend lists them in the node details panel, each clickable to its source line.
- Pass `details={"address": "...", "known_addresses": [...]}` on `UNRESOLVED_DEPENDENCY` findings to get "did you mean" recommendations.
- **API route:**

  ```python
  result = compile_source(req.source, req.format, req.filename)
  return result.model_dump(mode="json")
  ```

  It raises `AdapterNotAvailableError` when no adapter exists for a format. The API keeps ownership of `ValidationRequest`, the size limit (`SOURCE_TOO_LARGE`/413) and HTTP status codes.

### For the frontend (Pavithra)

- Render edges as `source → target`. Never reverse them.
- Edges have no `id`. Use `` `${source}->${target}:${type}` `` (Terraform merges repeated references, so it is unique there; other parsers should not emit duplicate edges).
- Diagnostics carry only `source_location`. Highlight nodes via `recommendations[i].related_node_ids` and link back via `recommendations[i].diagnostic_index`.
- `execution_order` may be `null`. When a warning-level `UNSUPPORTED_CONSTRUCT` is present, show the analysis as **partial**.
- Show `metadata.references` (Terraform edges) and `metadata` of nodes in the details panel.
