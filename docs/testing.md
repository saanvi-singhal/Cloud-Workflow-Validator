# Testing
//testing deploy
Testing conventions for the backend and frontend. The required test layers and fixture
coverage are defined in [PROJECT_SPEC.md section 9](PROJECT_SPEC.md#9-testing-and-quality-gates).

## Environment

Always use a virtual environment named `.venv` in the **repository root**
(it is git-ignored), as described in the [README](../README.md):

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
pip install -e "backend[dev]"        # pytest, pytest-cov, httpx, ruff
```

## Layout

Current tree of `backend/tests/`:

```
backend/tests/
  graph_builders.py            helpers for hand-built IR fixtures (stand-ins for parser output)
  test_scaffolding.py          environment sanity check
  unit/
    test_models.py             public Pydantic contract (fields, validation)
    test_ir.py                 stable IDs, canonical sorting, adjacency index
    test_validation.py         graph integrity validation
    test_cycles.py             Tarjan SCC, DFS cycle paths, cycle diagnostics
    test_topological_sort.py   Kahn ordering and determinism
    test_reachability.py       components, ancestors/descendants, format policy
    test_recommendations.py    recommendation engine and catalogue
    test_terraform_rules.py    Terraform security rules
    test_dockerfile_rules.py   Dockerfile rules (DF_*)
  parsers/
    test_terraform_references.py   structural reference extraction from HCL expressions
    test_terraform_extractor.py    Terraform blocks -> IR, dynamic blocks, syntax errors
    test_yaml_parser.py            GitHub Actions adapter: needs, schema checks, GHA_* rules
    test_dockerfile_parser.py      Dockerfile adapter: stages, references, structure checks
  integration/
    test_pipeline.py           parser output -> validation -> analysis -> AnalysisResult (fake adapters)
    test_terraform_pipeline.py Terraform fixtures through the full pipeline
    test_api.py                HTTP routes: health, validate, 413, CORS
    test_examples.py           every file in examples/ analyses as documented, deterministically
  fixtures/
    terraform/ yaml/ dockerfile/
```

API tests live in `integration/test_api.py` rather than a separate
`tests/api/` folder.

### Frontend

`frontend/src/analysis.test.ts` tests the pure helpers that turn a response
into what the UI shows. `frontend/src/App.test.tsx` renders the real app with
React Testing Library and jsdom, with `fetch` stubbed by backend-generated
responses: format selection and request body, empty input, status, diagnostics
and fixes, API error states (unreachable, 413, 422, 500), diagnostic → node
details, and Dockerfile stage instructions. Run with `npm test` in `frontend/`.

`frontend/src/e2e.test.tsx` is an opt-in end-to-end check against a running
backend: every example and sample goes through the real UI and API, and the page
must show the backend's result and each example's documented outcome. Run it
with `E2E=1 npm test -- e2e` (see `frontend/README.md`); CI skips it.

`backend/tests/integration/test_invariants.py` runs every example, fixture and
sample, plus seeded random mutations of each, and checks invariants every
response must satisfy (no crash, `valid` iff no errors, in-range locations,
recommendations linked to real diagnostics and nodes, a consistent execution
order, deterministic output).

## Markers

Defined in `backend/pyproject.toml`. `--strict-markers` is on, so a typo in a
marker name fails the run.

| Marker | pyproject description | What it covers in practice |
|---|---|---|
| `unit` | "mark test as a fast unit test" | One module in isolation on hand-built inputs: models, IR helpers, each graph algorithm, recommendation rules, Terraform rules. |
| `compiler` | "mark test as a compiler core or graph test" | Anything exercising the compiler core: IR, validation, cycles, ordering, reachability, pipeline, recommendations. Combined with `unit` or `integration`. |
| `parser` | "mark test as a parser-specific test" | Format adapters on real source text. |
| `integration` | "mark test as an integration test" | Multiple stages together, from **parser output or source text through IR, analysis and diagnostics to the `AnalysisResult` response payload**. It is not limited to HTTP API tests; those are in `integration/test_api.py`. |

`test_scaffolding.py` carries no marker.

## Running tests

From the repository root, with the venv active:

```bash
pytest backend/tests                       # everything
pytest backend/tests -m unit               # one marker
pytest backend/tests -m "compiler and not integration"
pytest backend/tests --cov=app --cov-report=term-missing   # with coverage
```

`pytest` run from inside `backend/` works as well: pyproject sets
`testpaths = ["tests"]` and `pythonpath = ["."]`, so `app` is importable either
way.

Lint and formatting checks (must pass before committing):

```bash
ruff check backend
ruff format --check backend
```

## Coverage

- **Target: at least 70% overall coverage** (spec 9.3).
- The overall percentage never excuses untested critical behaviour. Every
  critical algorithm needs **direct tests**, whatever the total says:
  integrity validation, Tarjan SCC, DFS cycle-path reconstruction, Kahn
  ordering, connectivity/reachability, Terraform reference extraction, parser
  behaviour and the API contract.
- Graph-algorithm tests must include self-loops, a simple cycle, multiple
  cycles, acyclic graphs, disconnected components and repeated-run
  determinism (spec 5.2, 9.2). Do not assert cycles for ordinary sequential
  Dockerfile instructions.
- Assert on stable diagnostic **codes**, not on message prose (spec 6.1).

## CI

`.github/workflows/ci.yml` runs two jobs on pushes and pull requests to `main`
and `dev`:

- **Backend Lint and Tests**: Python 3.11, `pip install -r
  backend/requirements.txt`, `ruff check backend`, `ruff format --check
  backend`, then `pytest backend/tests --cov=app --cov-fail-under=70`, so CI
  fails below the 70% coverage target.
- **Frontend Lint, Tests and Build**: Node 22, `npm ci`, `npm run lint`
  (oxlint), `npm test` (vitest) and `npm run build`, which runs `tsc -b` first
  and so is also the type check.
