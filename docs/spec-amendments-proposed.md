# Proposed amendments to PROJECT_SPEC.md

**Status: awaiting project-owner approval. `docs/PROJECT_SPEC.md` has NOT been edited.**

Each amendment gives the exact current text ("Before") and the proposed
replacement ("After"), followed by how it relates to the code on branch
`dev-bibek`. Quoted "Before" text is copied verbatim, line wrapping included,
so it can be found with a plain search.

---

## A1. `end_column` is exclusive (decision D4)

**Section:** 3.3 Source-location schema

**Before:**

```text
All numeric positions are one-based. If the parser cannot reliably
supply a position, use `null` for the location or the unavailable
fields; never invent line/column values. Preserve source locations
through parsing, IR conversion, analysis, diagnostics, and API
serialization wherever available.
```

**After:**

```text
All numeric positions are one-based. `end_line` is inclusive (the line
holding the last character of the span). `end_column` is exclusive: it
is the column one past the last character, so a span ending with `}` in
column 1 has `end_column: 2` (as in the example above). Frontend editor
highlighting must treat `end_column` as exclusive. If the parser cannot
reliably supply a position, use `null` for the location or the
unavailable fields; never invent line/column values. Preserve source
locations through parsing, IR conversion, analysis, diagnostics, and API
serialization wherever available.
```

**Code check:** consistent. The `SourceLocation` docstring in
`backend/app/models/common.py` documents an exclusive `end_column`. The
Terraform adapter copies Lark's `meta.end_column`, which is exclusive (verified:
`aws_vpc.main.id` starting at column 7 ends at `end_column` 22). The YAML and
Dockerfile parsers don't exist yet and must follow this rule.

---

## A2. When `execution_order` is `null`

**Section:** 5.3 Topological sort

**Before:**

```text
-   If a dependency graph is acyclic and ordering is meaningful for the
    format, return an order.
-   If a cycle exists, set `execution_order` to `null` and return cycle
    diagnostics.
```

**After:**

```text
-   If a dependency graph is acyclic, ordering is meaningful for the
    format, dependency analysis is complete, and there are no
    error-severity diagnostics, return an order.
-   Otherwise set `execution_order` to `null`. In particular it is
    `null` when:
    -   any error-severity diagnostic exists (including cycles,
        unresolved dependencies and syntax errors);
    -   a cycle exists (cycle diagnostics are still returned);
    -   ordering is not meaningful for the format (Dockerfiles in v1);
    -   dependency analysis is incomplete because an unsupported
        construct may hide dependencies (a warning-level
        `UNSUPPORTED_CONSTRUCT`).
```

**Code check:** consistent, with one addition to flag. The instruction listed
three conditions (any error, a cycle, not meaningful). The code in
`backend/app/compiler/pipeline.py` also returns `null` when
`ParseResult.dependency_analysis_complete` is `False`. That is approved
decision D9, so it is included above rather than left out. If you don't want
D9 in the spec, drop the last sub-bullet, but the code would then disagree
with the spec.

---

## A3. Unknown references are error-severity `UNRESOLVED_DEPENDENCY` (decision D8)

**Section:** 4.1 GitHub Actions YAML

**Before:**

```text
-   Validate missing/unknown job IDs in `needs`, duplicate or otherwise
    invalid job identifiers where applicable, malformed YAML, and
    relevant schema violations.
```

**After:**

```text
-   Validate missing/unknown job IDs in `needs`, duplicate or otherwise
    invalid job identifiers where applicable, malformed YAML, and
    relevant schema violations. Each unknown job ID in `needs` is an
    error-severity `UNRESOLVED_DEPENDENCY` diagnostic located at the
    reference, and no edge is created for it.
```

**Section:** 4.3 Terraform/HCL

**Before:**

```text
-   Explicit `depends_on` dependencies should have a distinct edge type
    from inferred references.
```

**After:**

```text
-   Explicit `depends_on` dependencies should have a distinct edge type
    from inferred references.
-   A reference (inferred or in `depends_on`) to a resource, data
    source, module or variable that is not declared in the analysed
    file is an error-severity `UNRESOLVED_DEPENDENCY` diagnostic located
    at the reference. No edge is created for it.
```

**Code check:** consistent for Terraform. `backend/app/parsers/terraform/extractor.py`
emits `UNRESOLVED_DEPENDENCY` at `Severity.error` and creates no edge (tested in
`tests/parsers/test_terraform_extractor.py::test_unresolved_reference_creates_no_edge`).
The GitHub Actions part is a requirement on a parser that doesn't exist yet;
no code contradicts it.

---

## A4. Dockerfile stage metadata required for reachability

**Section:** 4.2 Dockerfile

**Before:**

```text
-   The primary graph is stage-oriented. Represent build stages as nodes
    (`type: "stage"`), with relationships for base stages and
    `FROM ... AS ...` aliases where identifiable.
```

**After:**

```text
-   The primary graph is stage-oriented. Represent build stages as nodes
    (`type: "stage"`), with relationships for base stages and
    `FROM ... AS ...` aliases where identifiable.
-   Every stage node must carry `metadata.stage_index` (integer,
    0-based position of the stage in the file) and
    `metadata.is_final_stage` (boolean, `true` only for the last
    stage). Reachability analysis uses these to identify the final
    stage; stages the final stage does not need are reported as
    `UNREACHABLE_NODE` warnings.
```

**Code check:** consistent. `docker_final_stage()` in `backend/app/compiler/policy.py`
uses nodes whose `is_final_stage` is exactly `True`, otherwise the highest
integer `stage_index`. If neither is present, it returns no root and the
reachability check is skipped (no root is invented), so the code tolerates the
fields being missing while the spec would make them mandatory. The Dockerfile
parser doesn't exist yet. Note that `UNREACHABLE_NODE` is itself one of the
codes added by D2 that are not yet in the spec's 6.1 code list (see
"Not proposed here" below).

---

## A5. `docker_instruction_order` is reserved, not emitted in v1

**Section:** 3.5 Edge schema

**Before:**

```text
Initial edge types should include `workflow_dependency`,
`terraform_reference`, `terraform_explicit_dependency`,
`docker_stage_base`, and `docker_instruction_order` where those
relationships are represented. The Dockerfile primary graph is
stage-oriented, so instruction ordering can be retained within stage
metadata unless a future approved graph mode explicitly represents
instructions as nodes.
```

**After:**

```text
Initial edge types should include `workflow_dependency`,
`terraform_reference`, `terraform_explicit_dependency`,
`docker_stage_base`, and `docker_instruction_order` where those
relationships are represented. `docker_instruction_order` is reserved
and is not emitted in v1: instructions are not graph nodes in v1, so
instruction ordering is retained within stage metadata. The type stays
in the contract so that a future approved graph mode that represents
instructions as nodes can use it without a schema change.
```

**Code check:** consistent. `EdgeType.docker_instruction_order` exists in
`backend/app/models/common.py` and is accepted for Dockerfile graphs by
`backend/app/analysis/validation.py`. No implemented code emits it.

---

## A6. Remove "Terraform parser integration" from Agent B

**Section:** 16, "Agent B --- Backend parsers/API"

Section 12.2 (Saanvi's responsibilities) doesn't mention Terraform; only the
Agent B paragraph does. Sections 4.3, 12.1 and "Agent A" assign Terraform to the
compiler core.

**Before:**

```text
Implement the GitHub Actions YAML parser, Dockerfile stage parser,
Terraform parser integration, FastAPI endpoints, Pydantic
request/response schemas, source-location diagnostics, API error
semantics, parser/API tests, and integration with the approved compiler
core.
```

**After:**

```text
Implement the GitHub Actions YAML parser, Dockerfile stage parser,
FastAPI endpoints, Pydantic request/response schemas, source-location
diagnostics, API error semantics, parser/API tests, and integration
with the approved compiler core. Terraform parsing and analysis belong
to the compiler core (Agent A).
```

**Code check:** consistent. The Terraform adapter lives in
`backend/app/parsers/terraform/` and is registered by the compiler core
(`BUILTIN_ADAPTER_MODULES` in `backend/app/compiler/adapters.py`).

---

## A7. Branch naming: decision needed (no recommendation made)

The spec (section 13) and the README name the compiler-core branch
`feat/compiler-core`. The compiler core was actually developed on `dev-bibek`.
Two options:

### Option 1: keep `feat/compiler-core` (spec unchanged)

- Rename the local branch: `git branch -m dev-bibek feat/compiler-core`.
  It hasn't been pushed, so no remote cleanup is needed.
- **Files to change:** none in the spec or README. Optionally update the
  historical mention in `docs/claude-planning.md` (decision D15 and conflict
  item 12) to record the rename.

### Option 2: adopt `dev-<name>` branches

You must also decide whether this applies to all three contributors
(`dev-bibek`, `dev-saanvi`, `dev-pavithra`) or only to the compiler core. A
mixed scheme would leave the spec inconsistent.

**Spec, section 13. Before:**

```text
Use: - `dev` --- integration branch; - `feat/compiler-core` --- compiler
core; - `feat/backend-parsers` --- backend parsers/API; -
`feat/frontend` --- frontend.
```

**After (if the scheme applies to everyone):**

```text
Use: - `dev` --- integration branch; - `dev-bibek` --- compiler core; -
`dev-saanvi` --- backend parsers/API; - `dev-pavithra` --- frontend.
```

**Files to change for Option 2:**

| File | Lines (current) | What |
|---|---|---|
| `docs/PROJECT_SPEC.md` | 859-861 | branch list above |
| `README.md` | 237-239 | branch role list |
| `README.md` | 246 | `git checkout -b feat/<your-assigned-feature>` |
| `README.md` | 264-266 | ownership table "Branch" column |
| `README.md` | 277, 280 | "Current limitations" mentions of `feat/*` branches |
| `frontend/README.md` | 7 | `**Branch**: feat/frontend`. **Pavithra's file; coordinate before editing.** |
| `docs/claude-planning.md` | D15, conflict item 12 | historical note (optional) |

CI (`.github/workflows/ci.yml`) triggers only on `main` and `dev`, so neither
option requires a CI change.

---

## Not proposed here

These are other differences between the code and the spec. They were not on
the list of decisions, so no amendment text is proposed for them:

- **Spec 5.4** says "The chosen default is to **warn** about disconnected
  components". The code (approved D10) reports them as `info` for YAML and
  Terraform, and disables the rule for Dockerfiles.
- **Spec 6.1** example code list doesn't include `INVALID_GRAPH` or
  `UNREACHABLE_NODE` (approved D2), although the spec requires final names to
  be consistent across code, tests and docs.
