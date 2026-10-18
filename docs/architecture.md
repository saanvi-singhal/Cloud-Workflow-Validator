# Architecture

How Cloud-Workflow-Validator turns a configuration file into a dependency
graph, diagnostics and recommendations. The authoritative contract is
[PROJECT_SPEC.md sections 2-6](PROJECT_SPEC.md#2-architecture); the details of
the implemented compiler core are in [compiler-core.md](compiler-core.md).

## Static analysis only

The validator **never executes user configuration**. It does not run
workflows, build Docker images, run `terraform init/plan/apply`, contact cloud
providers, or evaluate variables. Source text is parsed and inspected; nothing
else (spec 1.2).

## Pipeline

```
 source text + format (+ optional filename)
          |
          v
 +---------------------------------------------+
 | Parser adapter (one per format)             |   app/compiler/adapters.py
 |   terraform       -> app/parsers/terraform  |   (SourceAdapter Protocol)
 |   yaml            -> app/parsers/github_actions  [not implemented yet]
 |   dockerfile      -> app/parsers/dockerfile      [not implemented yet]
 |   also runs the format's rules (app/rules/) |
 +---------------------------------------------+
          |
          v
 ParseResult = shared IR (IRGraph: nodes + edges)      app/compiler/ir.py
             + parser findings (syntax errors, unresolved references,
               unsupported constructs, security findings)
             + dependency_analysis_complete flag
          |
          v
 Integrity validation                                  app/analysis/validation.py
   unique node ids, edge endpoints exist, edge type allowed for format
          |
          v
 Graph analysis on a sorted adjacency index            app/compiler/graph.py
   - cycles: Tarjan SCC + DFS path reconstruction      app/analysis/cycles.py
   - execution order: Kahn topological sort            app/analysis/topological_sort.py
   - disconnected components / reachability            app/analysis/reachability.py
     (what is reported per format is decided in        app/compiler/policy.py)
          |
          v
 Deterministic sort of all diagnostics                 app/compiler/ir.py
          |
          v
 Recommendations (one rule per diagnostic code)        app/recommendations/
          |
          v
 AnalysisResult {valid, format, diagnostics, graph,    app/models/analysis.py
                 execution_order, recommendations}     (built by app/compiler/pipeline.py)
          |
          v
 FastAPI POST /api/v1/validate  [not implemented yet]  app/api/, app/main.py
          |
          v
 React + React Flow frontend    [not implemented yet]  frontend/
```

The single entry point is `app.compiler.pipeline.compile_source(source, format, filename)`.

## Key design rules

- **Parsers are separate from graph algorithms.** Parsers only produce IR and
  format-specific findings. The algorithms in `app/analysis/` only see the IR
  and never know which format it came from. Format differences (for example,
  "Dockerfiles have no execution order") are written as explicit rules in
  `app/compiler/policy.py`, not hidden special cases.
- **One shared IR.** Every format produces the same `Node`/`Edge` models
  (spec section 3). Format-specific detail lives in `metadata`.
- **Edge direction:** `A -> B` means A is a prerequisite of B (spec 3.6), everywhere.
- **Determinism:** IDs come from source identity (e.g. `tf:resource:aws_vpc.main`),
  never random. Nodes, edges and diagnostics are sorted, and topological ties
  are broken lexicographically.
- **No guessing.** A reference to something undeclared becomes an
  `UNRESOLVED_DEPENDENCY` diagnostic instead of an edge. An expression form the
  analyser can't interpret safely becomes an `UNSUPPORTED_CONSTRUCT` diagnostic
  and marks the analysis as partial.

## Algorithms

| Concern | Algorithm | Role |
|---|---|---|
| Integrity | Linear scans | Duplicate ids, dangling edges and wrong edge types are reported and removed before any algorithm runs. |
| Cyclic regions | **Tarjan's SCC** (iterative) | Finds *every* strongly connected component in one O(V+E) pass. A component with 2+ nodes, or one node with a self-loop, is a cyclic region. This yields exactly one `DEPENDENCY_CYCLE` per region, even when cycles overlap. |
| Readable cycle path | **DFS with WHITE/GRAY/BLACK colours** (iterative) | Run inside each cyclic region; an edge back to a GRAY node (one on the current path) closes a cycle, giving a path like `a -> b -> a` that users can follow in their source. Tarjan gives the set of nodes; DFS gives the path. |
| Execution order | **Kahn's algorithm**, min-heap tie-break | Lexicographically smallest ready node first. Returns nothing (`null`) when not all nodes can be ordered. It never returns a partial order. |
| Connectivity | BFS over weakly connected components | Reports extra multi-node components as `info` for YAML and Terraform. Never an error. |
| Reachability | BFS over predecessors (ancestors) | Only when the format defines a root. Today only Dockerfiles do (the final stage). No universal root is invented (spec 5.5). |

Both DFS and Tarjan use explicit stacks rather than recursion, so long
dependency chains do not hit Python's recursion limit.

## Module layout

Current tree under `backend/app/` (packages that do not exist yet are marked):

```
backend/app/
  main.py                  FastAPI entry point             [not created yet - Saanvi]
  api/                     routes, request models          [empty - Saanvi]
  models/                  shared wire contract (Pydantic): nodes, edges,
                           source locations, diagnostics, recommendations,
                           AnalysisResult
  compiler/                ir.py, graph.py, findings.py, policy.py,
                           adapters.py, pipeline.py
  analysis/                validation.py, cycles.py, topological_sort.py,
                           reachability.py
  parsers/
    github_actions/        GitHub Actions YAML adapter      [not created yet - Saanvi]
    dockerfile/            Dockerfile adapter               [not created yet - Saanvi]
    terraform/             hcl_loader.py, blocks.py, references.py, extractor.py
  rules/                   terraform_rules.py (selected security rules)
  recommendations/         engine.py, catalog.py
```

Dependencies point one way: `api -> compiler -> analysis / recommendations -> models`,
and `parsers -> compiler (adapter contract) -> models`. Only
`parsers/terraform/hcl_loader.py` imports the HCL parser library.

## Diagnostics and recommendations

Diagnostics use the compact schema of spec 6.1 (`code`, `severity`,
`message`, `source_location`). Recommendations are produced by deterministic
rules, link to one diagnostic by index, and only *describe* a change (with an
optional text preview). The tool never deletes edges, rewrites source or
modifies infrastructure (spec 6.2). See [api.md](api.md) for the schemas and
[compiler-core.md](compiler-core.md) for the code and rule catalogues.

## Ownership (spec section 12)

| Area | Owner |
|---|---|
| Shared IR and graph model, graph validation, DFS cycle paths and Tarjan SCC, Kahn ordering, reachability/disconnected components, **Terraform parsing, dependency extraction and semantic analysis**, recommendation engine and selected semantic/security checks, core algorithm and integration tests | Compiler core: project owner |
| GitHub Actions YAML parser, Dockerfile parser, FastAPI request/response models and endpoints, source-location diagnostic integration, parser/API tests, wiring parsers into the core, `/api/v1/health` and `/api/v1/validate` | Backend parsers/API: Saanvi |
| React/TypeScript/Vite/Tailwind UI, editor and upload, React Flow graph and layout, node and Dockerfile instruction details, diagnostics and source navigation, recommendation panel, API integration, frontend tests | Frontend: Pavithra |

The project owner has final authority over shared contracts (spec 12.4).
