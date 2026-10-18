<!-- Approved by the project owner on 2026-10-18; all decisions D1–D17 accepted as proposed. -->

# Compiler core: Phase 1 plan (Cloud-Workflow-Validator)

## Context

The repository is scaffolding only: empty `backend/app/{analysis,api,compiler,models,parsers,recommendations}` (each holds just a `.gitkeep`), `pyproject.toml`, `requirements.txt`, one sanity test, and no `rules/` dir. I own the compiler core: the shared IR contract, graph validation and algorithms, the pipeline, Terraform extraction, rules and recommendations. Saanvi (YAML/Dockerfile parsers + FastAPI) and Pavithra (frontend) build against what I define, so the contract has to be settled before any code. `docs/PROJECT_SPEC.md` is authoritative. Branch `dev-bibek` has been created from a clean `dev`; no files have been changed yet.

### Facts verified so far (not assumed)
- Tooling: system Python is 3.14.8. There is no venv, `ruff` is not installed, and `pytest` exists only at system level. CI uses 3.11 and ruff targets py310, so I'll avoid `StrEnum`/3.11+ syntax.
- **python-hcl2 8.1.4** (the latest within the declared `>=7,<9` range; probed in a scratchpad venv):
  - `hcl2.load()` returns a dict where **expressions are opaque strings** (`"${aws_vpc.main.id}"`, `"${var.flag ? aws_vpc.main.id : null}"`) and labels keep their quotes (`"\"aws_vpc\""`). `with_meta=True` added no line info. Using the dict would force regex scanning of `${…}` strings, which the spec forbids, and it gives no source locations.
  - `hcl2.parses_to_tree(text)` returns a **Lark tree that is fully structural**: `block`, `attribute`, `expr_term`, `get_attr_expr_term`, `index_expr_term`, `conditional`, `tuple`, function calls. **Every subtree has 1-based `meta.line/column/end_line/end_column`, with end_column exclusive** (`aws_vpc.main.id` at col 7 → end_column 22).
  - Syntax errors raise `lark.exceptions.UnexpectedToken`/`UnexpectedInput`, which carry `.line`/`.column`.
  - **Decision:** the Terraform adapter walks the Lark tree, never the dict.

## 1. File layout (new files only; nothing of Saanvi's or Pavithra's is touched)

```
backend/app/
  models/                      # PUBLIC wire contract (JSON-serialised)
    __init__.py                # re-exports
    common.py                  # SourceFormat, Severity, NodeType, EdgeType, SourceLocation
    graph.py                   # Node, Edge, GraphPayload
    diagnostics.py             # DiagnosticCode, Diagnostic
    recommendations.py         # FixKind, ProposedChange, Recommendation
    analysis.py                # AnalysisResult (what the pipeline returns)
  compiler/
    ir.py                      # IRGraph container, make_node_id(), unique_id(), canonical sorting
    graph.py                   # DependencyGraph: sorted adjacency index used by algorithms
    findings.py                # internal Finding = Diagnostic + rule_id + node_ids (never serialised)
    policy.py                  # FormatPolicy per format (order meaningful? disconnected rule, roots)
    adapters.py                # SourceAdapter Protocol, ParseResult, adapter registry
    pipeline.py                # compile_source(), analyze_ir()
  analysis/
    validation.py              # graph integrity
    cycles.py                  # Tarjan SCC + DFS cycle-path reconstruction
    topological_sort.py        # Kahn with min-heap tie-break
    reachability.py            # weak components, ancestors/descendants, format-aware warnings
  parsers/terraform/           # my package (spec 2.1); only hcl_loader.py imports hcl2/lark
    __init__.py                # TerraformAdapter (implements SourceAdapter)
    hcl_loader.py              # parses_to_tree + syntax-error → TERRAFORM_SYNTAX_ERROR
    blocks.py                  # tree → TerraformBlock dataclasses (kind, labels, attrs, nested, location)
    references.py              # structural expression walker → Reference / Unsupported
    extractor.py               # blocks + references → IR nodes/edges + diagnostics
  rules/
    __init__.py
    terraform_rules.py         # small documented security/quality rule set
  recommendations/
    __init__.py
    engine.py                  # generate_recommendations(findings, ir)
    catalog.py                 # one rule function per diagnostic code / rule_id
backend/tests/
  conftest.py                  # graph-building helpers (hand-built IR fixtures)
  unit/      test_models.py test_ir.py test_validation.py test_cycles.py
             test_topological_sort.py test_reachability.py test_policy.py
             test_recommendations.py test_terraform_rules.py
  parsers/   test_terraform_loader.py test_terraform_references.py test_terraform_extractor.py
  integration/ test_pipeline.py test_terraform_pipeline.py test_examples.py
  fixtures/terraform/  valid.tf cyclic.tf unresolved.tf depends_on.tf unsupported.tf security.tf syntax_error.tf
examples/terraform/   valid_network.tf cyclic.tf unresolved_reference.tf depends_on.tf unsupported_expression.tf
docs/compiler-core.md          # contract reference: codes, ID scheme, rules, policy table
```
`test_examples.py` runs every file in `examples/terraform/` through the pipeline, so the examples can't drift from what is actually supported.

**Why models live in `app/models/` and not in the compiler package:** these models *are* the shared wire contract. Saanvi's FastAPI response model and Pavithra's TS types are derived from them, and `app/models` imports nothing from the compiler. That gives a one-way dependency: `api → compiler → models`, `parsers → models`. `compiler/ir.py` holds only the working container and the ID helpers.

## 2. Pydantic model definitions (Pydantic v2, `extra="forbid"`)

```python
class SourceFormat(str, Enum):  yaml="yaml"; dockerfile="dockerfile"; terraform="terraform"
class Severity(str, Enum):      error="error"; warning="warning"; info="info"
class NodeType(str, Enum):      task, stage, instruction, resource, data_source, module, variable, output, unknown
class EdgeType(str, Enum):      workflow_dependency, terraform_reference, terraform_explicit_dependency,
                                docker_stage_base, docker_instruction_order

class SourceLocation(BaseModel):            # all positions one-based; any field may be None
    file: str | None = None                 # None when the request has no filename
    start_line: int | None = Field(None, ge=1)
    start_column: int | None = Field(None, ge=1)
    end_line: int | None = Field(None, ge=1)
    end_column: int | None = Field(None, ge=1)   # EXCLUSIVE (see D4)

class Node(BaseModel):
    id: str; label: str; type: NodeType
    source_location: SourceLocation | None
    metadata: dict[str, JsonValue] = {}

class Edge(BaseModel):                      # source → target  ==  source is a prerequisite of target
    source: str; target: str; type: EdgeType
    label: str | None = None
    source_location: SourceLocation | None = None
    metadata: dict[str, JsonValue] = {}

class GraphPayload(BaseModel):  nodes: list[Node]; edges: list[Edge]

class DiagnosticCode(str, Enum):
    YAML_SYNTAX_ERROR, DOCKERFILE_SYNTAX_ERROR, TERRAFORM_SYNTAX_ERROR, DUPLICATE_NODE_ID,
    UNRESOLVED_DEPENDENCY, DEPENDENCY_CYCLE, DISCONNECTED_COMPONENT, UNSUPPORTED_CONSTRUCT,
    SOURCE_TOO_LARGE, SECURITY_RULE_VIOLATION
    # + proposed: INVALID_GRAPH, UNREACHABLE_NODE  (see D2, needs your approval)

class Diagnostic(BaseModel):
    code: DiagnosticCode; severity: Severity; message: str
    source_location: SourceLocation | None = None

class FixKind(str, Enum):  deterministic="deterministic"; judgment="judgment"

class ProposedChange(BaseModel):            # text preview only; nothing is ever applied
    description: str
    preview: str | None = None              # unified-diff-style snippet, omitted if not safe to express
    source_location: SourceLocation | None = None

class Recommendation(BaseModel):
    id: str                  # stable: f"{rule_id}:{diagnostic_index}"
    rule_id: str             # e.g. "BREAK_DEPENDENCY_CYCLE", "TF_S3_PUBLIC_ACL"
    title: str
    explanation: str
    diagnostic_code: DiagnosticCode
    diagnostic_index: int    # index into the final, sorted `diagnostics` list
    fix_kind: FixKind        # spec 6.2: deterministic vs judgment-dependent
    proposed_change: ProposedChange | None = None
    source_location: SourceLocation | None = None
    related_node_ids: list[str] = []         # lets the UI highlight nodes (see D3)

class AnalysisResult(BaseModel):            # exactly the spec 7.3 response fields
    valid: bool; format: SourceFormat; diagnostics: list[Diagnostic]
    graph: GraphPayload; execution_order: list[str] | None; recommendations: list[Recommendation]
```
Internal only (`compiler/findings.py`, a frozen dataclass): `Finding(diagnostic, rule_id: str | None, node_ids: tuple[str, ...], edge_keys: tuple[...])`. It keeps the public diagnostic compact while still letting recommendations know which rule and nodes are involved.

## 3. Stable node-ID scheme

`make_node_id(fmt_prefix, kind, *parts) -> "<prefix>:<kind>:<part.part>"`. No UUIDs or hashes, so IDs are readable in the viva and in the UI.

| Construct | ID | Owner |
|---|---|---|
| TF resource `aws_vpc.main` | `tf:resource:aws_vpc.main` | me |
| TF data `data.aws_ami.ubuntu` | `tf:data:aws_ami.ubuntu` | me |
| TF module `module.net` | `tf:module:net` | me |
| TF variable / output | `tf:variable:env`, `tf:output:vpc_id` | me |
| GHA job | `gha:job:<job_id>` | suggested to Saanvi |
| Docker stage | `docker:stage:<0-based index>` (alias in label/metadata, since stages can be unnamed and aliases can repeat) | suggested to Saanvi |

Collision handling is `unique_id(base, taken)`, which returns `base`, then `base#2`, `base#3` in source order. A parser that sees a duplicate declaration in the *source* (for example two `resource "aws_vpc" "main"`) emits `DUPLICATE_NODE_ID` at the second block's location. `validation.py` re-checks the final IR as a safety net. The original identifier is kept in `metadata` (`address`, `job_id`, `alias`).

## 4. Public function signatures

```python
# compiler/ir.py
class IRGraph(BaseModel):
    format: SourceFormat; nodes: list[Node]; edges: list[Edge]
    def canonical(self) -> "IRGraph"          # nodes by id; edges by (source, target, type)
def make_node_id(prefix: str, kind: str, *parts: str) -> str
def unique_id(base: str, taken: set[str]) -> str
def sort_diagnostics(ds: Iterable[Diagnostic]) -> list[Diagnostic]
    # key: (file or "", start_line or ∞, start_column or ∞, severity rank, code, message)

# compiler/graph.py
class DependencyGraph:                         # built only from VALID edges
    @classmethod
    def from_ir(cls, ir: IRGraph) -> "DependencyGraph"
    nodes: tuple[str, ...]                     # sorted
    def successors(self, n: str) -> tuple[str, ...]    # sorted, deduped
    def predecessors(self, n: str) -> tuple[str, ...]
    def has_self_loop(self, n: str) -> bool
    def edges_between(self, a: str, b: str) -> list[Edge]   # for cycle locations

# compiler/adapters.py  (Saanvi implements this for yaml/dockerfile)
@dataclass(frozen=True)
class ParseResult:
    ir: IRGraph | None                         # None only when nothing could be parsed (syntax error)
    findings: list[Finding]
    dependency_analysis_complete: bool = True  # False when unsupported constructs may hide edges
class SourceAdapter(Protocol):
    format: SourceFormat
    def parse(self, source: str, filename: str | None) -> ParseResult: ...
def register_adapter(adapter: SourceAdapter) -> None
def get_adapter(fmt: SourceFormat) -> SourceAdapter

# analysis/validation.py
def validate_graph(ir: IRGraph) -> tuple[IRGraph, list[Finding]]
    # duplicate ids (keep first), dangling endpoints, edge type allowed for the format → cleaned IR + findings

# analysis/cycles.py
@dataclass(frozen=True)
class CycleReport:
    components: list[list[str]]       # cyclic SCCs (size > 1, or size 1 with self-loop); sorted
    paths: list[list[str]]            # one readable closed path per component, e.g. [a, b, c, a]
def strongly_connected_components(g: DependencyGraph) -> list[list[str]]       # Tarjan
def find_cycle_path(g: DependencyGraph, component: Sequence[str]) -> list[str]  # DFS colours
def detect_cycles(g: DependencyGraph) -> CycleReport
def cycle_findings(report: CycleReport, ir: IRGraph) -> list[Finding]          # one per component

# analysis/topological_sort.py
def topological_order(g: DependencyGraph) -> list[str] | None   # None if not every node emitted

# analysis/reachability.py
def weakly_connected_components(g: DependencyGraph) -> list[list[str]]
def ancestors(g: DependencyGraph, targets: Iterable[str]) -> set[str]   # nodes with a path INTO targets
def descendants(g: DependencyGraph, sources: Iterable[str]) -> set[str]
def component_findings(g, ir, policy: FormatPolicy) -> list[Finding]
def reachability_findings(g, ir, policy: FormatPolicy) -> list[Finding] # [] when policy has no roots

# compiler/policy.py
@dataclass(frozen=True)
class FormatPolicy:
    execution_order_meaningful: bool
    disconnected_severity: Severity | None     # None = rule explicitly disabled
    report_isolated_nodes: bool
    roots: Callable[[IRGraph], list[str]] | None   # None = no defined root → no reachability
def policy_for(fmt: SourceFormat) -> FormatPolicy

# compiler/pipeline.py
def analyze_ir(parse: ParseResult, fmt: SourceFormat) -> AnalysisResult
def compile_source(source: str, fmt: SourceFormat, filename: str | None = None) -> AnalysisResult
# rules/terraform_rules.py
def run_terraform_rules(blocks: list[TerraformBlock], filename: str | None) -> list[Finding]
# recommendations/engine.py
def generate_recommendations(diagnostics: list[Diagnostic], findings: list[Finding],
                             ir: IRGraph | None) -> list[Recommendation]
```

### Algorithm design (what each docstring will explain)
- **Why Tarjan and DFS together:** Tarjan finds *every* cyclic region in one O(V+E) pass, but it only tells you which nodes form a strongly connected component, not an ordered path. For each cyclic SCC I then run a DFS **restricted to that SCC**, starting from its smallest ID, with WHITE (unvisited), GRAY (on the current recursion stack) and BLACK (finished) colours. The first edge to a GRAY node closes a cycle, and slicing the stack from that node gives a readable path like `a → b → c → a`. That produces **exactly one `DEPENDENCY_CYCLE` per SCC**, so overlapping cycles don't duplicate diagnostics. A self-loop is a size-1 SCC with a self-edge, giving the path `[a, a]`. The diagnostic's location is the location of the edge that closes the cycle, falling back to the node's location.
- **Kahn:** in-degree counts plus a `heapq` min-heap of ready node IDs, giving lexicographic tie-breaking. If fewer than V nodes come out, the function returns `None`. It never returns a partial order.
- **Determinism:** every adjacency list is sorted, iteration is always over sorted IDs, and the final output passes through `canonical()` and `sort_diagnostics()`. A test runs the pipeline repeatedly, plus on shuffled node and edge input order, and asserts byte-identical JSON.

### Pipeline order
parse → `validate_graph` → `DependencyGraph` → cycles → topo → components/reachability → (format rules from the adapter) → sort diagnostics → recommendations (which reference the sorted indices) → `valid = no error diagnostics`.
`execution_order` is `None` when any of these hold: policy says not meaningful, a cycle exists, integrity errors were found, the IR is `None`, or `dependency_analysis_complete` is False.

### Proposed format policy (D10)
| Format | order | disconnected | roots / reachability |
|---|---|---|---|
| yaml | yes | `info`, only for separate *non-trivial* components; isolated jobs not reported (parallel jobs are normal in GHA) | none |
| terraform | yes | `info` for non-trivial components; isolated resources not reported | none |
| dockerfile | **no** (spec 5.3) | disabled, because reachability covers it | final stage (node with `metadata.is_final_stage` true, otherwise the highest stage index) → stages not in `ancestors(final)` get a warning |

Each disconnected-component diagnostic is emitted once per extra component. The main component is the largest one, with ties broken by smallest ID. The message says why the component is reported ("2 nodes form a dependency chain unconnected to the rest of the graph").

## 5. Terraform extraction (conservative)
- **Nodes:** `resource`, `data`, `module`, `variable`, `output` blocks. `provider`, `terraform`, `locals`, `moved`, `import`, `check` are not modelled, and each produces one `info` `UNSUPPORTED_CONSTRUCT` ("not represented in the graph"), never a silent skip.
- **References** come from a structural walk of attribute expressions and nested blocks:
  - `TYPE.NAME…` → resource
  - `data.TYPE.NAME…` → data source
  - `module.NAME…` → module
  - `var.NAME` → variable
  - Indexes and splats (`aws_subnet.a[0].id`) resolve to the whole resource.
  - Function arguments, both conditional branches, tuples, objects and template interpolations are walked recursively.
- **Not dependencies (documented and skipped by name):** `count.*`, `each.*`, `self.*`, `path.*`, `terraform.*`, `provider = aws.west`, `lifecycle.ignore_changes`.
- **`UNSUPPORTED_CONSTRUCT` (warning) plus `dependency_analysis_complete=False`:** `for` expressions, `dynamic` blocks (iterator scoping), `%{}` template directives, `local.*` references (D6), `replace_triggered_by`, and any expression rule the walker doesn't recognise. The walker's default branch reports; it never ignores.
- **`depends_on`:** each item must be a bare resource/data/module traversal. That gives a `terraform_explicit_dependency` edge; anything else is reported as `UNSUPPORTED_CONSTRUCT`.
- **Edge dedup:** one edge per (source, target, type). `source_location` is the first reference, and `metadata.references = [{attribute, location}]` holds all of them.
- **Unknown target:** no edge is created, and an `UNRESOLVED_DEPENDENCY` error is reported at the reference span ("not declared in this file; v1 analyses a single .tf file").
- Lark exceptions become `TERRAFORM_SYNTAX_ERROR` with the parser's line/column. The end position is left `None` and is never invented.

## 6. Rules and recommendations
**Terraform rules.** Each emits `SECURITY_RULE_VIOLATION` at warning severity, with `rule_id` on the Finding. A rule fires only on *literal* values; a variable or reference is never guessed at.
- `TF_S3_PUBLIC_ACL`: `aws_s3_bucket`/`aws_s3_bucket_acl` with `acl` set to `public-read` or `public-read-write`
- `TF_SG_OPEN_INGRESS`: ingress `cidr_blocks`/`cidr_ipv4` contains `0.0.0.0/0` or `::/0` (`aws_security_group` ingress block, `aws_security_group_rule` with type ingress, `aws_vpc_security_group_ingress_rule`)
- `TF_HARDCODED_SECRET`: an attribute named `password`, `secret_key`, `access_key` or `token` with a non-empty string literal
- `TF_DB_PUBLICLY_ACCESSIBLE`: `aws_db_instance` with `publicly_accessible = true`

**Recommendation catalogue** (all `judgment` unless stated):
- `BREAK_DEPENDENCY_CYCLE`: lists the cycle's edges and suggests removing one. If an explicit `depends_on` edge is in the cycle, it is named first.
- `RESOLVE_MISSING_DEPENDENCY`: "did you mean X?" via `difflib.get_close_matches` over declared addresses (deterministic).
- `RENAME_DUPLICATE`
- `REVIEW_DISCONNECTED`: explanation only, no change
- `UNSUPPORTED_LIMITATION`: explanation only
- One recommendation per security rule, e.g. `acl = "private"` as a preview diff, marked `judgment` because it changes behaviour.

Nothing is ever applied; `preview` is text only. Each recommendation links via `diagnostic_code` + `diagnostic_index`.

## 7. Decisions (all approved by the project owner, 2026-10-18)
- **D1** Models in `app/models/` (§1 rationale).
- **D2** Two **new diagnostic codes**: `INVALID_GRAPH` (error; IR internal inconsistency such as a dangling edge endpoint or an edge type not allowed for the format, i.e. a parser bug, not user input) and `UNREACHABLE_NODE` (warning; Docker stage not needed by the final stage). The alternative is to squeeze these into `UNRESOLVED_DEPENDENCY` / `DISCONNECTED_COMPONENT`, which would misdescribe them.
- **D3** The diagnostic schema has **no node/edge reference**, so the frontend can only highlight by `source_location` (spec 8.2 wants highlighting). Proposal: keep the diagnostic compact for now, put `related_node_ids` on Recommendation, and treat an optional `Diagnostic.node_ids` as a separate contract change you decide on.
- **D4** **`end_column` is exclusive** (matches Lark and the spec's `main.tf` example where `}` at col 1 → `end_column: 2`). Saanvi's ruamel/dockerfile positions must follow the same rule.
- **D5** `SourceLocation.file` is nullable; it is `None` when the request has no `filename`.
- **D6** **Terraform `locals`:** there is no `local` node type in spec 3.2. Recommendation: v1 reports `local.*` references as `UNSUPPORTED_CONSTRUCT` (so execution_order becomes null for those files). The alternative is adding a `local` node type, which is a contract change.
- **D7** Model `variable` and `output` as nodes, since both are standard types in 3.2.
- **D8** An unresolved Terraform reference is an **error** (spec example severity). Because v1 is single-file, a multi-file module snippet will show `valid: false`.
- **D9** `execution_order = null` also when dependency analysis is incomplete (spec 5.3: no misleading order).
- **D10** The format policy table in §4.
- **D11** Security findings use `warning`; the rule ID lives on the recommendation (`rule_id`), not on the diagnostic.
- **D12** **Dependency changes:** pin `python-hcl2>=8.1,<9` (7.x has a different API and grammar; my walker depends on 8.x rule names), declare `lark` explicitly (needed for exception types), and add `pytest-cov` to dev deps and `requirements.txt`. These are shared files; I'd also fix pyproject's `readme = "README.md"`, which points at a nonexistent `backend/README.md`.
- **D13** I own `AnalysisResult` (identical to the spec 7.3 fields). Saanvi's `ValidationResponse` either *is* that model or a direct alias, which avoids a competing schema. She owns `ValidationRequest`, the size limit/`SOURCE_TOO_LARGE`, and HTTP codes.
- **D14** **Iterative** DFS and Tarjan with an explicit stack, documented step by step. Recursive versions are shorter but hit Python's ~1000-frame limit on long chains, which spec 9.2 "large inputs" would catch.
- **D15** The branch is `dev-bibek` per your instruction, while the spec and README say `feat/compiler-core`.
- **D16** Diagnostic sort key is location-first (§4).
- **D17** Ownership ambiguity: spec §16 Agent B lists "Terraform parser integration" for Saanvi, but §12.1 and your brief give Terraform extraction to me. I'll own all of `parsers/terraform/`.

## 8. Phases after approval (each ends with ruff + pytest, then a small commit)
**Owner feedback (approved):** all decisions D1–D17 accepted as proposed. Also: create a venv in the repo and install the deps; document that setup in the README; copy this plan to `docs/claude-planning.md`; report every file changed (README etc.) at the end.

2. venv at repo root `.venv` (check it's gitignored), `pip install -e "backend[dev]"`, README setup note, `docs/claude-planning.md` → models, ir.py, graph.py, findings.py, validation.py + unit tests
3. cycles, topological_sort, reachability, policy + tests (self-loop, simple, multiple, nested/overlapping, acyclic, disconnected, determinism with shuffled input, a 5000-node chain)
4. adapters.py, pipeline.py + integration tests using a hand-built fake adapter
5. Terraform package + fixtures/examples. Re-probe the tree shapes for templates, splats, `for`, heredoc and `dynamic` before writing the walker.
6. rules + recommendations + `docs/compiler-core.md`

## 9. Verification (per phase)
`backend/.venv/bin/ruff check backend`, `ruff format --check backend`, `pytest backend/tests --cov=app --cov-report=term-missing` (run from `backend/` per the pyproject `pythonpath`), with a ≥70% target and direct tests for each algorithm. A final integration test runs all `examples/terraform/*.tf` end to end and checks for identical JSON across repeated runs. Nothing is pushed and no PR is opened.

## 10. Doc conflicts found (reported only; docs NOT edited)
1. api.md request `content` vs spec `source`; api.md adds an `options` object that is not in the spec.
2. api.md `is_valid` + `summary` vs spec `valid`; api.md response has no `format` or `execution_order`.
3. Nodes: api.md `kind: "job"`, architecture.md `name/kind/attributes` vs spec `label/type/metadata` and `type: "task"`; architecture.md lists an "Artifact" node type that is not in the spec.
4. Edges: api.md edge `id` + `kind: explicit_needs`; architecture.md `source_id/target_id/dependency_kind` (EXPLICIT_NEEDS, DATA_REFERENCE, STAGE_INHERITANCE, ARTIFACT_CONSUMPTION; also "order, data, trigger") vs the spec's five edge types and `source/target/type`.
5. Diagnostics: `ERR_CYCLE_DETECTED`, `WARN_ORPHAN_RESOURCE`, uppercase `ERROR`, `location` instead of `source_location`, extra `element_ids`.
6. Recommendations: api.md `rule_id RULE-CYCLE-001`, `suggested_fix`, `diff`; architecture.md says "Auto-Fix Diffs", while spec 6.2 forbids auto-modification.
7. HTTP: api.md returns 422 for syntax errors (spec: 200 with diagnostics) and a fixed 4.5 MB 413 limit (spec: configurable and measured).
8. architecture.md has single files `parsers/hcl.py`, `yaml.py`, `docker.py` vs spec packages `parsers/{github_actions,dockerfile,terraform}/`.
9. architecture.md offers "Kahn or reverse post-order DFS" (spec: Kahn) and adds critical-path, bottleneck and resource-shadowing analysis that is not in scope, plus a generic "orphan detection" that conflicts with spec 5.5's no-invented-root rule.
10. deployment.md assumes two Vercel projects (spec goal: one, with a documented fallback), states unverified limits (4.5 MB, 10 s/60 s, Python 3.9/3.12, "<10 MB bundle"), and sets CORS `allow_origin_regex` for all `*.vercel.app` with credentials.
11. testing.md layout (`unit/test_yaml_parser.py`, …) vs spec `tests/{unit,parsers,api,integration}`; it describes the `integration` marker as "API tests"; it has no 70% coverage target.
12. README/spec branch names `feat/*` vs `dev-bibek`; README line 272 splits the Terraform parser across two branches.
13. Spec itself: `docker_instruction_order` is listed as an edge type, but instructions aren't nodes by default; end-column inclusivity is unspecified (D4).
14. Build config: pyproject `readme` points to a missing file; the python-hcl2 range spans two incompatible majors; CI uses 3.11, ruff targets py310, and the local machine runs 3.14.

## 11. What Saanvi and Pavithra get
- **Saanvi:** import `Node`, `Edge`, `SourceLocation`, `Diagnostic`, the enums and `make_node_id`/`unique_id` from `app.models` / `app.compiler.ir`. Implement `SourceAdapter.parse(source, filename) -> ParseResult` for yaml and dockerfile, and set `metadata.is_final_stage` on the last Docker stage. Register adapters via `register_adapter`. The route calls `compile_source(...)` and returns the `AnalysisResult` JSON (`model_dump(mode="json")`).
- **Pavithra:** the JSON shape is in §2, with `A → B` meaning A runs first. Edges have no `id`, so React Flow keys should be `${source}->${target}:${type}`. Diagnostics carry only `source_location`; node highlighting comes from `recommendations[].related_node_ids` (D3). `execution_order` may be `null`.
