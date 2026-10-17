# System Architecture & Compiler Pipeline

This document defines the high-level architecture, intermediate representation design, and static analysis pipeline for the **Compiler-Based Cloud Workflow Validator**.

---

## 1. Pipeline Overview

The validator adopts a classic multi-stage compiler pipeline designed to ingest heterogeneous infrastructure and workflow configurations, transform them into a normalized graph model, and execute semantic analysis passes.

```
+-------------------------------------------------------------------------+
|                              Input Layer                                |
|   - CI/CD Workflows (.yaml/.yml)                                        |
|   - Container Specifications (Dockerfile)                              |
|   - Infrastructure-as-Code (.tf - Terraform HCL)                        |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                        Language Adapter Layer                           |
|   - YAML Parser (ruamel.yaml)                                           |
|   - Dockerfile Parser (dockerfile-parse)                                |
|   - Terraform Parser (python-hcl2)                                      |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                Common Intermediate Representation (IR)                  |
|   - Unified AST / Element Definitions                                   |
|   - Node typing (Task, Stage, Resource, Artifact)                       |
|   - Explicit dependency declarations & implicit data references          |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                     Dependency Graph Construction                       |
|   - Directed Graph / DAG model                                          |
|   - Generic Nodes (Identifiers, Metadata, Attributes)                   |
|   - Generic Directed Edges (DependencyType: order, data, trigger)       |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                         Static Analysis Passes                          |
|   - Cycle Detection (Tarjan's strongly connected components / DFS)      |
|   - Topological Ordering & Critical Path Analysis                       |
|   - Dead Path / Orphan Resource Detection                               |
|   - Resource Shadowing & Anti-pattern Linter                            |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                 Diagnostics & Recommendation Engine                     |
|   - Diagnostic Codes (ERR_CYCLE_DETECTED, WARN_ORPHAN_RESOURCE, etc.)  |
|   - Severity Levels (ERROR, WARNING, INFO)                              |
|   - Precise Source Mapping (file, line, column, element ID)             |
|   - Remediation Suggestions & Auto-Fix Diffs                            |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                           Presentation Layer                            |
|   - FastAPI REST API (backend/app/api)                                  |
|   - Interactive Dependency Graph Visualization (React Flow / Frontend)  |
|   - Diagnostics Console & Remediation Suggestions                       |
+-------------------------------------------------------------------------+
```

---

## 2. Decoupling Parsers from Generic Graph Algorithms

A core architectural principle of this validator is the **strict decoupling of language-specific parsers from generic graph analysis algorithms**.

### A. Language-Specific Parsers (`backend/app/parsers/`)
- Responsible strictly for reading raw configuration text and extracting syntax-level primitives:
  - **YAML Parser**: Reads job names, `needs` arrays, matrix configurations, step sequences, environment bindings.
  - **Dockerfile Parser**: Extracts build stages (`FROM ... AS stage`), base images, file copies (`COPY --from=...`), and command chains.
  - **Terraform Parser**: Parses HCL blocks, extracting resources, variables, providers, module calls, and inter-resource references (e.g. `aws_security_group.sg.id`).
- Parsers **do not** perform cycle detection, reachability queries, or cross-format validation. Their sole role is converting format-specific structures into the unified IR schema.

### B. Common Intermediate Representation (`backend/app/compiler/ir.py`)
- Defines standard Pydantic models representing:
  - `IRGraph`: Root container containing nodes and directed edges.
  - `IRNode`: Generic element representing a computation step, container layer, or infrastructure resource.
    - Attributes: `id`, `name`, `kind`, `source_location` (file, start_line, end_line), `attributes`.
  - `IREdge`: Directed dependency link.
    - Attributes: `source_id`, `target_id`, `dependency_kind` (`EXPLICIT_NEEDS`, `DATA_REFERENCE`, `STAGE_INHERITANCE`, `ARTIFACT_CONSUMPTION`).

### C. Generic Graph Engine (`backend/app/analysis/`)
- Operates strictly on `IRGraph` without awareness of whether the graph originated from YAML, Dockerfile, or HCL.
- Houses graph algorithms:
  - **Cycle Detection**: Identifies circular dependencies using Tarjan's Strongly Connected Components (SCC) or recursive DFS coloring.
  - **Topological Sorting**: Generates valid execution schedules using Kahn's algorithm or reverse post-order DFS.
  - **Reachability & Orphan Detection**: Identifies disconnected subgraphs, unreachable build stages, or unused cloud resources.
  - **Bottleneck Analysis**: Identifies critical execution paths and serial bottlenecks in parallel workflows.

---

## 3. Diagnostics & Recommendation Architecture (`backend/app/recommendations/`)

Once graph analysis passes complete:
1. Analysis passes produce raw diagnostics (`DiagnosticRecord`).
2. The **Recommendation Engine** maps diagnostics to actionable remediation rules:
   - For circular dependencies: Highlights the exact circular chain ($A \rightarrow B \rightarrow C \rightarrow A$) and suggests dependency inversion or decoupling.
   - For multi-stage Docker builds: Identifies missing layer caching opportunities or unnecessary intermediate dependencies.
   - For Terraform configurations: Flags dangling resource references or circular provider dependencies.
3. Every recommendation provides:
   - Unique diagnostic rule ID (e.g., `RULE-WF-001`, `RULE-DKR-004`, `RULE-TF-002`).
   - Human-readable title and technical rationale.
   - Suggested remediation strategy with optional code diff snippet.

---

## 4. Module Layout & Team Ownership Mapping

| Module Directory | Primary Responsibility | Team Member Ownership |
| :--- | :--- | :--- |
| `backend/app/compiler/` | IR schemas, graph builder, compiler core pipeline | **Lead** (Me) |
| `backend/app/parsers/hcl.py` | Terraform HCL parser & resource link extraction | **Lead** (Me) |
| `backend/app/analysis/` | Cycle detection, topological sort, orphan analysis | **Lead** (Me) |
| `backend/app/recommendations/`| Lint rules, remediation generator | **Lead** (Me) |
| `backend/app/parsers/yaml.py` | YAML workflow parser (GitHub Actions, etc.) | **Saanvi** |
| `backend/app/parsers/docker.py`| Dockerfile parser & multi-stage dependency extractor | **Saanvi** |
| `backend/app/api/` | FastAPI routes, request validation, CORS, error handling | **Saanvi** |
| `frontend/src/components/` | React UI, graph visualization canvas, diagnostics panel | **Pavithra** |
| `frontend/src/api/` | Frontend API client communicating with backend | **Pavithra** |
