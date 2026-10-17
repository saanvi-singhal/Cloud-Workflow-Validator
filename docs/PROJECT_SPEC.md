# Cloud-Workflow-Validator --- Project Specification

**Status:** Team implementation contract\
**Project name:** Cloud-Workflow-Validator\
**Primary file:** `docs/PROJECT_SPEC.md`\
**Version:** 1.0 draft for implementation\
**Audience:** All human contributors and coding agents

> **Authority rule:** This document is the shared source of truth for
> scope, schemas, edge semantics, API behavior, module boundaries,
> tests, and integration. Implementations must follow it. If a
> requirement is ambiguous or a change would affect a shared contract,
> scope, or consequential architecture, stop and ask the project owner
> before proceeding. Do not silently invent a competing contract.

------------------------------------------------------------------------

## 1. Purpose and product boundary

Cloud-Workflow-Validator is a static-analysis application that parses
supported configuration files, normalizes their meaningful structure
into a shared graph representation, analyzes dependencies and selected
configuration-quality/security rules, and displays the results with
source-linked diagnostics and recommendations.

### 1.1 Initial supported formats

The first release supports all three formats at a basic but real level:

1.  **GitHub Actions workflow YAML** --- recognize GitHub Actions
    workflow structure and workflow/job dependencies. Do not treat
    arbitrary YAML as a workflow.
2.  **Dockerfile** --- represent build stages and relationships as the
    primary graph. Show stage instructions and their ordering in node
    details rather than creating a graph node for every instruction by
    default.
3.  **Terraform/HCL** --- analyze resources, data sources, modules,
    references, and explicit `depends_on` dependencies. Use parsed HCL
    structure and expression/reference analysis, not regex-only
    scanning.

"Basic support for all three" means each format must have a working
parser/adapter, normalized graph output, useful diagnostics, tests, and
documented unsupported constructs. It does not mean complete
compatibility with every feature of each language.

### 1.2 Static analysis only

The application must **never execute user-supplied workflows, run Docker
builds, invoke Terraform plan/apply, deploy infrastructure, or execute
arbitrary configuration content**. Parsing and static inspection only.

Do not add execution features without explicit approval from the project
owner.

### 1.3 Product goals

-   Reliable parsing and graph normalization.
-   Correct dependency semantics and cycle analysis.
-   Deterministic diagnostics and output.
-   Useful graph visualization and source navigation.
-   Rule-based recommendations that explain issues and suggest safe
    changes.
-   Selected deterministic security/configuration checks.
-   A maintainable modular codebase that can be extended to additional
    constructs later.

------------------------------------------------------------------------

## 2. Architecture

Use the following high-level pipeline:

``` text
Source text + format
        |
        v
Format parser / adapter
  - GitHub Actions YAML
  - Dockerfile
  - Terraform / HCL
        |
        v
Format-specific parse result
        |
        v
Shared normalized IR / graph
        |
        v
Shared graph analysis
  - validation
  - cycle detection
  - topological ordering where meaningful
  - reachability / disconnected-component checks
        |
        v
Format-aware semantic and security rules
        |
        v
Diagnostics + recommendations
        |
        v
Versioned FastAPI response
        |
        v
React / TypeScript UI + React Flow
```

### 2.1 Module boundaries

Suggested backend layout (adjust only with approval if a material
architectural change is needed):

``` text
backend/
  app/
    main.py
    api/
    models/
    parsers/
      github_actions/
      dockerfile/
      terraform/
    compiler/
      ir.py
      graph.py
      pipeline.py
    analysis/
      validation.py
      cycles.py
      topological_sort.py
      reachability.py
    recommendations/
    rules/
    config.py
  tests/
    unit/
    parsers/
    api/
    integration/
    fixtures/
```

The frontend lives in `frontend/` and uses React, TypeScript, Vite,
Tailwind CSS, and `@xyflow/react`. Use Dagre or ELK (choose the simplest
suitable dependency after checking compatibility) for frontend graph
layout. Graph meaning and validation remain backend responsibilities;
layout coordinates are presentation concerns.

Existing repository scaffolding should be inspected and reused. Do not
replace or recreate existing files wholesale without checking their
contents first.

------------------------------------------------------------------------

## 3. Shared intermediate representation (IR)

The project owner owns the shared IR contract. Parsers may keep
format-specific parse structures internally, but must convert them to
the common IR before shared analysis.

### 3.1 Node schema

Every normalized node has the following common base fields:

  -----------------------------------------------------------------------------
  Field               Type                           Required Meaning
  ------------------- ----------------- --------------------- -----------------
  `id`                string                              yes Stable,
                                                              deterministic,
                                                              unique within one
                                                              analysis result

  `label`             string                              yes Human-readable
                                                              display label

  `type`              string enum or                      yes Shared semantic
                      documented                              node type
                      extensible string                       

  `source_location`   source-location                     yes Source span if
                      object or `null`                        available

  `metadata`          JSON-compatible                     yes Format-specific
                      object                                  properties; use
                                                              `{}` when none
  -----------------------------------------------------------------------------

The base schema is common to all formats. Format-specific details belong
in `metadata`; do not create incompatible top-level node schemas for
each parser.

### 3.2 Standard node types

Start with these types:

-   `task`
-   `stage`
-   `instruction`
-   `resource`
-   `data_source`
-   `module`
-   `variable`
-   `output`
-   `unknown`

Use the most accurate type for each construct. Do not force an object
into an inaccurate type just to fit the list. New shared types require
agreement and documentation. Format-specific detail may be represented
in `metadata`.

### 3.3 Source-location schema

Use a nullable source location with the following shape:

``` json
{
  "file": "main.tf",
  "start_line": 4,
  "start_column": 1,
  "end_line": 8,
  "end_column": 2
}
```

All numeric positions are one-based. If the parser cannot reliably
supply a position, use `null` for the location or the unavailable
fields; never invent line/column values. Preserve source locations
through parsing, IR conversion, analysis, diagnostics, and API
serialization wherever available.

### 3.4 Stable node IDs

Node IDs must be deterministic for identical source input and must not
collide when different constructs share a display name. Derive IDs from
format and source identity where appropriate, with deterministic
collision handling. Do not use random UUIDs. Original identifiers should
be retained in metadata when useful.

### 3.5 Edge schema

Each edge must contain:

  -----------------------------------------------------------------------------------
  Field               Type                           Required Meaning
  ------------------- ----------------- --------------------- -----------------------
  `source`            string                              yes Source node ID

  `target`            string                              yes Target node ID

  `type`              string                              yes Semantic relationship

  `label`             string or `null`                    yes Optional human-readable
                                                              explanation

  `source_location`   source-location                     yes Location of the
                      object or `null`                        dependency
                                                              declaration/reference
                                                              when available

  `metadata`          object                              yes Optional details; use
                                                              `{}` when empty
  -----------------------------------------------------------------------------------

Initial edge types should include `workflow_dependency`,
`terraform_reference`, `terraform_explicit_dependency`,
`docker_stage_base`, and `docker_instruction_order` where those
relationships are represented. The Dockerfile primary graph is
stage-oriented, so instruction ordering can be retained within stage
metadata unless a future approved graph mode explicitly represents
instructions as nodes.

### 3.6 Edge direction --- mandatory convention

**`A → B` means A must precede B / A is a prerequisite of B.**
Equivalently, B depends on A.

Every parser, graph algorithm, API response, test, diagram, and document
must use this direction. Do not reverse edges in the frontend.

### 3.7 Graph response shape

The public graph response uses:

``` json
{
  "nodes": [],
  "edges": []
}
```

Each node and edge follows the schemas above. Do not expose internal
Python objects or parser-specific objects directly through the API.
Serialize to JSON-compatible values.

------------------------------------------------------------------------

## 4. Format-specific requirements

### 4.1 GitHub Actions YAML

-   Support GitHub Actions workflow YAML, not arbitrary YAML inference.
-   Parse workflow-level fields and jobs using a YAML parser that
    preserves source locations where possible.
-   Treat each job as a graph node (`type: "task"` is acceptable).
-   Interpret `jobs.<job_id>.needs` as dependencies. If job A is listed
    in job B's `needs`, add edge `A → B` with a workflow dependency edge
    type.
-   Validate missing/unknown job IDs in `needs`, duplicate or otherwise
    invalid job identifiers where applicable, malformed YAML, and
    relevant schema violations.
-   Preserve useful workflow/job metadata in node metadata.
-   Do not execute expressions, actions, shell commands, or workflows.
-   Document which GitHub Actions features are supported and which are
    only preserved as metadata or reported as unsupported.
-   A workflow schema/version marker is not imposed on GitHub Actions
    YAML; its structure is determined by GitHub Actions conventions.

### 4.2 Dockerfile

-   Parse Dockerfile syntax with a suitable parser/library; do not rely
    on line-based regex as the sole parser.
-   The primary graph is stage-oriented. Represent build stages as nodes
    (`type: "stage"`), with relationships for base stages and
    `FROM ... AS ...` aliases where identifiable.
-   Keep ordered instructions and their source locations in each stage's
    metadata or a clearly documented equivalent structure.
-   Show instructions in node details in the UI. Do not require a
    separate graph node for every instruction in the first release.
-   Preserve the order of instructions in the source. Do not infer
    arbitrary dependencies or report a cycle merely because ordinary
    instructions are sequential.
-   Distinguish external base images from named stages. Do not invent
    graph nodes for external images unless the shared contract is
    updated to support them.
-   Provide diagnostics for syntax errors and supported deterministic
    configuration-quality/security rules.
-   Never build an image or execute Dockerfile commands.

### 4.3 Terraform/HCL

-   Use `python-hcl2` or another approved HCL parser. Do not parse
    Terraform references solely with regular expressions.
-   Support resources, data sources, modules, explicit `depends_on`, and
    references that can be reliably identified from parsed structures.
-   Create nodes for supported resource/data-source/module constructs.
    Other constructs such as variables, outputs, locals, and providers
    may be represented where they materially aid diagnostics/dependency
    analysis; do not claim complete Terraform semantic evaluation.
-   Infer a dependency edge `A → B` when B references A in a
    dependency-bearing expression, or when B explicitly declares A in
    `depends_on`.
-   Explicit `depends_on` dependencies should have a distinct edge type
    from inferred references.
-   Analyze HCL expressions structurally. If an expression form cannot
    be resolved safely, emit a structured unsupported/partial-analysis
    diagnostic rather than guessing.
-   The first release supports a single `.tf` source file. Design parser
    boundaries so multi-file projects and local modules can be added
    later, but do not claim multi-file/module resolution support in v1.
-   Do not evaluate variables, contact providers, run `terraform init`,
    or run Terraform plan/apply.
-   Include selected deterministic Terraform configuration/security
    rules, but do not present the product as a comprehensive Terraform
    security scanner.

------------------------------------------------------------------------

## 5. Graph analysis behavior

### 5.1 Validation before graph algorithms

Before analysis, validate node ID uniqueness, edge endpoint existence,
allowed edge fields/types, and internal consistency. Convert expected
user-input problems into diagnostics. Reserve unhandled exceptions for
unexpected failures.

### 5.2 Cycle detection

Use both: 1. **DFS with path/recursion-stack tracking** to reconstruct
and report a readable cycle path. 2. **Tarjan's strongly connected
components (SCC) algorithm** to identify cyclic components, including
multiple cyclic regions.

Tests must cover self-loops, a simple cycle, multiple cycles, acyclic
graphs, and disconnected components. Avoid duplicate diagnostics for the
same cycle/component where practical. A self-loop is a cycle.

### 5.3 Topological sort

Use Kahn's algorithm with deterministic tie-breaking (for example,
lexicographic node ID among currently available nodes). The result must
be stable for identical input.

-   If a dependency graph is acyclic and ordering is meaningful for the
    format, return an order.
-   If a cycle exists, set `execution_order` to `null` and return cycle
    diagnostics.
-   Do not return a misleading partial order as though it were complete.
-   For Dockerfiles, preserve stage/instruction semantics; do not treat
    the stage graph as a complete substitute for Docker's build
    semantics.
-   The public response may return `null` where an order is not
    meaningful or not supported.

### 5.4 Disconnected components

The chosen default is to **warn about disconnected components**. The
implementation must avoid calling every independent node an error or
declaring the graph invalid solely because it has more than one
component.

-   Use format-aware rules to avoid misleading warnings for
    intentionally independent jobs/stages/resources.
-   Where possible, distinguish isolated nodes from separate nontrivial
    components.
-   Diagnostics must explain why the component was considered
    noteworthy.
-   If a format's semantics make disconnected components normal,
    suppress or downgrade the warning through an explicit rule rather
    than a hidden special case.

### 5.5 Reachability

Only perform reachability checks when the format's semantics define a
meaningful expected relationship (for example, a configured entry point
or an explicitly defined root). Do not invent a universal root and mark
every node unreachable in its absence.

### 5.6 Determinism

For identical source and options, sort graph nodes, edges, diagnostics,
and otherwise-independent topological choices deterministically. Avoid
output depending on hash-map iteration order.

------------------------------------------------------------------------

## 6. Diagnostics and recommendations

### 6.1 Diagnostic schema

The selected diagnostic contract is intentionally compact:

``` json
{
  "code": "UNRESOLVED_DEPENDENCY",
  "severity": "error",
  "message": "Job 'build' depends on unknown job 'compile'.",
  "source_location": {
    "file": ".github/workflows/ci.yml",
    "start_line": 12,
    "start_column": 5,
    "end_line": 12,
    "end_column": 12
  }
}
```

Required fields: `code`, `severity`, and `message`. `source_location`
may be `null` or omitted if unavailable. Use severity values `error`,
`warning`, and `info`. Use stable, documented diagnostic codes. Do not
make tests depend on exact prose alone when a stable code is available.

The initial compact schema does not require a separate category,
related-location array, or documentation URL. Add such fields only after
the project owner approves the shared contract change.

Example diagnostic codes (final names must be consistent across code,
tests, and docs):

-   `YAML_SYNTAX_ERROR`
-   `DOCKERFILE_SYNTAX_ERROR`
-   `TERRAFORM_SYNTAX_ERROR`
-   `DUPLICATE_NODE_ID`
-   `UNRESOLVED_DEPENDENCY`
-   `DEPENDENCY_CYCLE`
-   `DISCONNECTED_COMPONENT`
-   `UNSUPPORTED_CONSTRUCT`
-   `SOURCE_TOO_LARGE`
-   `SECURITY_RULE_VIOLATION`

### 6.2 Recommendations

-   Recommendations are generated by deterministic rules, not by a
    required AI model.
-   Link each recommendation to a diagnostic code or a specific
    diagnostic instance.
-   Where possible, include an explanation, proposed change, and source
    location.
-   Do not promise a fix when the tool cannot establish that the fix is
    safe.
-   Separate deterministic fixes from judgment-dependent suggestions.
-   Do not automatically delete dependency edges, rewrite source, or
    modify infrastructure configuration.
-   The UI may show a suggested diff/preview, but the user must
    explicitly accept any future source modification feature.

### 6.3 Security and quality rules

Include a small, documented, deterministic first-release rule set for
selected Dockerfile and Terraform configuration risks, plus relevant
GitHub Actions workflow concerns where a clear rule is supported. Keep
rules testable and explain their scope. Avoid claiming comprehensive
security coverage.

### 6.4 Unsupported constructs and partial analysis

-   Report unsupported constructs explicitly.
-   Continue partial analysis only if doing so is safe and meaningful.
-   Mark analysis as incomplete when unsupported constructs materially
    limit correctness.
-   Never silently skip a construct and present the graph as complete.
-   Never fabricate a dependency to make a graph look connected.

------------------------------------------------------------------------

## 7. Public API contract

Base path: `/api/v1`.

### 7.1 Health endpoint

Canonical health route: **`GET /api/v1/health`**.

All source code, tests, README instructions, API docs, deployment docs,
and Vercel routing must use this canonical path. A root `/health` alias
is optional only if a hosting probe requires it; it must not replace the
canonical endpoint.

### 7.2 Validation endpoint

Canonical validation route: **`POST /api/v1/validate`**.

Request:

``` json
{
  "source": "name: CI\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-latest\n",
  "format": "yaml",
  "filename": ".github/workflows/ci.yml"
}
```

Required fields: - `source`: string containing the source text. -
`format`: one of `yaml`, `dockerfile`, `terraform`.

Optional fields: - `filename`: user-supplied file name/path for display
and diagnostics. It must not be treated as a filesystem path to open on
the server.

Use Pydantic request/response models. Reject unknown formats and
malformed request bodies with appropriate client errors.

### 7.3 Validation response

The public response shape:

``` json
{
  "valid": true,
  "format": "yaml",
  "diagnostics": [],
  "graph": {
    "nodes": [],
    "edges": []
  },
  "execution_order": [],
  "recommendations": []
}
```

Contract rules: - `valid` is false when analysis reports one or more
error-severity diagnostics; warnings alone do not make it false. -
`format` echoes the normalized supported format. - `diagnostics` is a
list of stable diagnostic objects. - `graph` contains the normalized
public nodes and edges. - `execution_order` is an ordered list of node
IDs when meaningful and available; otherwise `null`. - `recommendations`
is a list of structured, deterministic recommendations. The
recommendation schema must be defined in Pydantic and documented before
frontend integration; at minimum each item needs a stable
identifier/code, title/message, explanation, related diagnostic
reference, and optional proposed fix/preview. If a proposed change
cannot be expressed safely, omit it rather than inventing one. - Partial
analysis must be represented clearly in diagnostics. If an explicit
response completeness flag is later judged necessary, propose a contract
change rather than silently adding a new required field.

### 7.4 HTTP status semantics

-   Return **HTTP 200** when the request was processed and analysis
    completed, even if the source is invalid and the response contains
    diagnostics.
-   Use suitable `4xx` responses for malformed requests, unsupported
    format values, or source-size violations.
-   Use `5xx` only for unexpected server failures.
-   Do not convert every source syntax error into an HTTP error; syntax
    errors are expected analysis results.

### 7.5 Source-size limits

Implement a documented, configurable application-level source-size
limit. The exact default must be selected after checking the current
deployment platform's request limits and testing the actual deployment
bundle. Return a clear client error when the application limit is
exceeded. Do not assume a platform limit from an old document or an
unmeasured estimate.

### 7.6 API compatibility

The frontend and backend must share the exact request/response contract.
Do not rename fields or add incompatible requirements independently. If
the contract needs to change, the project owner approves the change and
all affected code/docs/tests are updated together.

------------------------------------------------------------------------

## 8. Frontend requirements

### 8.1 Stack

-   React
-   TypeScript
-   Vite
-   Tailwind CSS
-   `@xyflow/react`
-   Dagre or ELK for graph layout, after verifying compatibility and
    selecting one implementation

### 8.2 Initial user flow

1.  Choose `yaml`, `dockerfile`, or `terraform`.
2.  Paste source into the editor or upload a supported file.
3.  Submit the source to `POST /api/v1/validate`.
4.  Display validation status, diagnostics, graph, and recommendations.
5.  Allow graph pan/zoom, fit-to-view, node selection, and readable edge
    labels.
6.  Selecting a diagnostic highlights the associated node/edge when
    identifiable and navigates to the source line when location data is
    available.
7.  Selecting a node displays its metadata and, for Dockerfile stages,
    its ordered instructions.
8.  Show when results are partial or unsupported constructs limit the
    analysis.

### 8.3 Graph presentation

-   Use React Flow.
-   Use typed styling for node and edge types.
-   Keep source/target direction consistent with the mandatory `A → B`
    convention.
-   Layout is frontend presentation logic; do not make the backend
    depend on frontend coordinates.
-   Do not hide errors merely because a graph can be rendered.
-   Avoid implying that the graph is complete when the backend reports
    partial analysis.

### 8.4 API configuration

Use `VITE_API_BASE_URL` for the API base URL. Do not hardcode production
URLs. Configure CORS using deployment environment variables or explicit
environment-specific configuration. Do not commit secrets.

------------------------------------------------------------------------

## 9. Testing and quality gates

### 9.1 Test layers

Required: - Unit tests for IR validation, graph algorithms,
deterministic ordering, and recommendation rules. - Parser tests for
YAML, Dockerfile, and Terraform. - API tests for valid and invalid
requests and response schemas. - Integration tests across parser → IR →
analysis → diagnostics/recommendations → response. - Representative
end-to-end cases for all three formats. - Frontend tests for input
selection/submission, diagnostic display, graph integration, and API
error states where practical.

### 9.2 Fixture coverage

For every supported format, include valid and invalid fixtures. Cover at
least: - valid minimal input; - malformed syntax; - missing/unresolved
dependencies where relevant; - cycles where the format's graph semantics
allow them; - disconnected components; - source-location accuracy; -
unsupported constructs and partial-analysis behavior; - deterministic
output for repeated identical input; - selected security/quality
rules; - large-enough representative inputs to expose obvious
performance problems.

Do not write tests that assert cycles in ordinary sequential Dockerfile
instructions solely because they are ordered.

### 9.3 Coverage target

Target **at least 70% overall test coverage**. Also ensure critical
graph algorithms, parser behavior, and API contracts have meaningful
direct tests; an overall percentage must not be used to excuse untested
critical behavior.

### 9.4 Tooling

Backend: - pytest - Ruff linting and formatting checks - Python type
annotations and Pydantic models - `httpx` for API tests where needed

Frontend: - production build check - lint and test commands defined in
`frontend/package.json` - add type checking to CI if the frontend setup
supports it without disproportionate complexity

### 9.5 CI

GitHub Actions should run relevant backend and frontend checks on pushes
and pull requests to the integration branch. CI must fail on lint,
tests, formatting checks, or production build failures. Keep workflow
paths aligned with the real repository structure. Do not create CI steps
that refer to nonexistent scripts.

------------------------------------------------------------------------

## 10. Repository and local development

Use the existing repository layout where possible. Intended high-level
layout:

``` text
Cloud-Workflow-Validator/
  backend/
  frontend/
  examples/
    yaml/
    dockerfile/
    terraform/
  docs/
    PROJECT_SPEC.md
  .github/
    workflows/
      ci.yml
  .gitignore
  .editorconfig
  .env.example
  README.md
```

-   Keep `backend/requirements.txt` and `backend/pyproject.toml`
    aligned.
-   Use `.env.example` files for documented variable names only; never
    include real secrets.
-   Ignore Python virtual environments/caches, Node artifacts, local
    `.env` files, logs, IDE/OS artifacts, and `.vercel/`, while
    retaining example environment templates.
-   Local development should work with documented Python and Node
    environments.
-   Docker Compose is optional; do not require it unless it has a real,
    maintained use.
-   Examples must be safe static fixtures. They must not be executed by
    the application or CI.
-   The root README must explain purpose, supported formats, local
    setup, test commands, API routes, architecture, current limitations,
    deployment, and team workflow.

------------------------------------------------------------------------

## 11. Deployment

### 11.1 Goal

The goal is **one Vercel project** serving the frontend and FastAPI
backend. However, use a second Vercel project or separate backend host
if verified Vercel constraints make a single-project deployment
unreliable. Correct deployment takes priority over forcing one-project
architecture.

### 11.2 Verification requirements

Before committing to deployment configuration, verify with current
Vercel documentation and a real deployment or minimal deployment test:

-   how the chosen root directory affects file discovery;
-   Python function entry-point discovery and routing;
-   whether `backend/app/main.py` can be exposed directly or needs a
    small deployment adapter;
-   frontend build/output settings;
-   API path routing and rewrite behavior;
-   Python dependency bundling and actual bundle size;
-   request/body-size limits and function execution limits;
-   environment-variable configuration and CORS behavior.

Do not rely on guessed limits or outdated numbers. Do not claim
deployment is verified until it has been tested.

### 11.3 Application entry point

Keep `backend/app/main.py` as the canonical FastAPI application entry
point. Add a minimal deployment adapter only if required by the verified
Vercel configuration. Avoid duplicating route logic in the adapter.

### 11.4 Deployment configuration

-   Frontend base URL must come from `VITE_API_BASE_URL`.
-   Configure allowed CORS origins for the actual deployment.
-   Do not commit secrets.
-   Keep local development independent of Vercel.
-   Document the fallback architecture if one project cannot reliably
    host both pieces.
-   Keep the canonical health route `GET /api/v1/health` and validation
    route `POST /api/v1/validate` working after deployment.

------------------------------------------------------------------------

## 12. Team ownership and collaboration

### 12.1 Compiler core --- project owner

Responsible for: - shared IR and graph model; - graph validation; - DFS
cycle-path reconstruction and Tarjan SCC analysis; - deterministic Kahn
topological sorting; - reachability/disconnected-component analysis; -
Terraform dependency extraction and semantic analysis; - recommendation
engine and selected semantic checks; - core algorithm and integration
tests.

### 12.2 Backend parsers/API --- Saanvi

Responsible for: - GitHub Actions YAML parser and workflow validation; -
Dockerfile parser and stage/instruction extraction; - FastAPI
request/response models and endpoints; - source-location diagnostic
integration; - parser/API tests; - integrating parser output with the
approved shared core; - ensuring `/api/v1/health` and `/api/v1/validate`
match the contract.

Saanvi must not create a competing IR or alter API field names
independently.

### 12.3 Frontend --- Pavithra

Responsible for: - React/TypeScript/Vite/Tailwind UI; - format selector,
editor, and file upload; - React Flow graph and layout; - node/edge
details and Dockerfile instruction details; - diagnostic list, graph
highlighting, source navigation; - recommendation panel and fix
preview; - API integration and frontend tests.

Pavithra must consume the documented response contract and must not
invent frontend-only meanings for edge direction, diagnostic severity,
or execution order.

### 12.4 Shared contract authority

The project owner has final authority over the project specification and
shared contracts. Routine implementation within an assigned module may
proceed independently when it follows this document. Before changing
scope, shared IR, edge semantics, API schemas, diagnostic schema, module
boundaries, or consequential architecture, the contributor/agent must
ask the project owner and wait for approval.

Agents may identify and propose additional useful features, but must not
expand scope or introduce a breaking change silently.

------------------------------------------------------------------------

## 13. Branch and pull-request workflow

Use: - `dev` --- integration branch; - `feat/compiler-core` --- compiler
core; - `feat/backend-parsers` --- backend parsers/API; -
`feat/frontend` --- frontend.

Workflow: 1. Inspect `git status` and the current branch before making
changes. 2. Create or switch to the assigned feature branch only after
verifying the working tree and branch state. 3. Sync from `dev`
according to the team's agreed Git workflow. 4. Keep commits focused and
descriptive. 5. Open a pull request to `dev`. 6. Run relevant tests and
CI before merging. 7. Resolve contract changes with the project owner
before updating dependent modules. 8. Do not overwrite another
contributor's work or force-push shared branches without explicit
coordination.

Do not assume a branch exists or a working tree is clean; inspect first.

------------------------------------------------------------------------

## 14. Definition of done

A feature is complete only when: - it implements the approved behavior
and schema; - it has meaningful tests; - relevant lint, formatting,
test, and build checks pass; - documentation and examples are updated; -
diagnostics and output are deterministic where required; - it does not
execute user configuration; - it integrates with the agreed IR/API
contract; - unsupported behavior and limitations are disclosed; - the
pull request is reviewed and merged through the agreed workflow.

A feature is not complete merely because it runs on the author's machine
or looks convincing in a demo.

------------------------------------------------------------------------

## 15. Implementation sequence

All developers may begin work in their assigned areas, but shared
contracts must be treated as fixed.

1.  **Contract alignment:** read this document; agree on the
    Python/Pydantic representations for nodes, edges, diagnostics, and
    recommendations.
2.  **Core foundation:** implement IR validation, stable IDs, graph
    validation, cycle detection, deterministic topological sorting, and
    core tests.
3.  **Parser adapters:** implement GitHub Actions YAML, Dockerfile, and
    Terraform adapters against the same IR.
4.  **API integration:** wire parsers, analysis, recommendations, and
    Pydantic request/response models into FastAPI.
5.  **Frontend integration:** consume the exact API contract and
    implement graph, diagnostics, and recommendations.
6.  **Integration testing:** exercise each format through the full
    pipeline and verify consistent direction, IDs, source locations, and
    diagnostic codes.
7.  **Deployment verification:** test Vercel routing and constraints;
    use the documented fallback if necessary.
8.  **Release review:** update README and limitations, verify the 70%
    coverage target, and confirm no execution/deployment of user configs
    is possible.

### Required cross-team agreement before integration

The team must align on these exact contracts before merging dependent
code: - node and edge schemas; - standard node/edge types; - `A → B`
edge direction; - source-location indexing (one-based); - diagnostic
required fields and stable codes; - recommendation schema; - validation
request/response fields; - `execution_order` behavior; -
partial-analysis reporting; - health and validation route paths.

------------------------------------------------------------------------

## 16. Coding-agent instructions

Paste the relevant section below into each agent's task prompt and point
it to this file.

### Common instructions for every agent

1.  Read `docs/PROJECT_SPEC.md` and existing project files before
    editing.
2.  Follow the shared schemas and edge direction exactly.
3.  Do not independently redesign shared contracts.
4.  Do not execute user-provided configurations.
5.  Do not invent successful test results, API behavior, or deployment
    status.
6.  Add tests and update documentation for changes.
7.  Ask the project owner before changing scope, shared schemas,
    endpoint paths, graph semantics, or consequential architecture.
8.  At completion, report changed files, commands actually run, test
    results, unresolved issues, assumptions, and integration
    dependencies.
9.  Do not replace files wholesale without inspecting their current
    content.
10. Keep changes within the assigned ownership area unless coordinated.

### Agent A --- Compiler core

Implement the shared IR and graph model, graph integrity validation,
deterministic IDs, DFS cycle-path detection, Tarjan SCC analysis,
deterministic Kahn topological sorting, appropriate
reachability/disconnected-component checks, Terraform dependency
extraction from parsed HCL structures, deterministic recommendation
rules, selected semantic/security checks, and core tests. Keep Terraform
parser integration behind a clear adapter boundary. Do not implement the
frontend or duplicate the YAML/Dockerfile parser/API ownership.

### Agent B --- Backend parsers/API

Implement the GitHub Actions YAML parser, Dockerfile stage parser,
Terraform parser integration, FastAPI endpoints, Pydantic
request/response schemas, source-location diagnostics, API error
semantics, parser/API tests, and integration with the approved compiler
core. Use `POST /api/v1/validate` and `GET /api/v1/health`. Treat
invalid source as an analysis result (HTTP 200 if analysis completed),
not automatically as an HTTP failure. Do not create an incompatible IR.

### Agent C --- Frontend

Implement the React/TypeScript/Vite/Tailwind UI, format selector, editor
and file upload, React Flow visualization, frontend layout, stage
instruction details, diagnostics with source navigation/highlighting,
recommendation panel/fix preview, API integration through
`VITE_API_BASE_URL`, and tests. Consume the actual API schemas; do not
hardcode fake results as production behavior. Keep graph direction
consistent with `A → B` and show incomplete analysis clearly.

------------------------------------------------------------------------

## 17. Open implementation details to verify (not permission to change the contract)

The following are implementation checks, not invitations to silently
change the requirements:

-   Confirm exact installed dependency versions and compatibility before
    pinning them.
-   Choose the compatible YAML parsing approach that preserves useful
    source locations.
-   Verify the Dockerfile parser's stage and instruction metadata
    capabilities.
-   Verify the HCL parser's expression representation and implement
    conservative reference extraction.
-   Select Dagre or ELK based on compatibility and graph size needs.
-   Measure the actual deployment bundle and verify current Vercel
    limits.
-   Select a reasonable default source-size limit after deployment
    constraints are verified.
-   Define the recommendation object's exact fields in Pydantic and
    documentation before frontend integration, while preserving the
    minimum contract in Section 7.3.
-   Keep examples and tests aligned with actual supported constructs.

If any verification reveals that a requirement cannot be met as written,
document the evidence and propose an explicit decision to the project
owner. Do not quietly weaken the requirement.

------------------------------------------------------------------------

## 18. Release checklist

-   [ ] `GET /api/v1/health` works locally and in the chosen deployment.
-   [ ] `POST /api/v1/validate` accepts the agreed request schema.
-   [ ] GitHub Actions YAML produces a graph and useful diagnostics.
-   [ ] Dockerfile stages and their relationships are represented
    correctly.
-   [ ] Terraform resources, data sources, modules, references, and
    `depends_on` are analyzed to the documented level.
-   [ ] `A → B` semantics are consistent in all formats.
-   [ ] DFS cycle paths and Tarjan SCC analysis have tests.
-   [ ] Kahn ordering is deterministic and is `null` when cyclic or not
    meaningful.
-   [ ] Disconnected-component warnings are format-aware and not
    universally treated as errors.
-   [ ] Unsupported constructs and partial analysis are explicit.
-   [ ] Recommendations are deterministic and do not automatically
    modify source.
-   [ ] No user configuration is executed.
-   [ ] Diagnostics can navigate to source when locations are available.
-   [ ] Frontend and backend use the same response contract.
-   [ ] Unit, parser, API, integration, and frontend tests pass.
-   [ ] Overall test coverage is at least 70%.
-   [ ] CI passes.
-   [ ] Deployment routing, request-size limit, and actual function
    bundle have been verified.
-   [ ] README and examples describe the actual implementation and its
    limitations.
-   [ ] No secrets or local environment files are committed.

**End of specification.**
