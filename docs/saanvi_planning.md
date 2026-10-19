Plan Overview

You're on branch feat/yaml-dockerfile-parsers-api (off dev). The plan has 6 phases:

Phase 1 — YAML parser (app/parsers/yaml/)

Two-pass design using ruamel.yaml(typ="rt") for source locations:

Pass 1 declares a NodeType.task node per jobs.<id> entry, using make_node_id("gha", "job", id) + unique_id for collisions.
Pass 2 wires workflow_dependency edges from needs. Unknown needs targets → UNRESOLVED_DEPENDENCY finding, no edge.
Phase 2 — Dockerfile adapter (app/parsers/dockerfile/)

Two-pass design over dockerfile-parse instruction dicts:

Pass 1 declares NodeType.stage nodes from FROM instructions; marks the final stage is_final_stage=True.
Pass 2a wires docker_stage_base edges for FROM <base> when base is a known alias.
Pass 2b wires docker_stage_base edges for COPY --from=<alias> — external images (:, /, @) are silently skipped; undeclared aliases → UNRESOLVED_DEPENDENCY, no edge.
Phase 3 — Register adapters

One edit to adapters.py — add yaml and dockerfile to BUILTIN_ADAPTER_MODULES.

Phase 4 — FastAPI (app/main.py + app/api/routes.py)
GET /api/v1/health → {"status": "ok"}
POST /api/v1/validate → compile_source(source, fmt, filename).model_dump(mode="json"); size limit (configurable MAX_SOURCE_BYTES); 200 for analysed results, 422 for bad requests, 413 for oversized payloads.
Phase 5 — Tests

Fixture files + pytest coverage for all parsers and API endpoints (valid/invalid/edge-case scenarios).

Phase 6 — Risks

Key risks: .lc metadata wrapping, 0-based line offsets in dockerfile-parse, numeric --from indexes, adapter teardown in existing tests.