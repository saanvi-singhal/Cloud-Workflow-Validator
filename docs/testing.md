# Testing

Testing conventions for the backend. The required test layers and fixture
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
  parsers/
    test_terraform_references.py   structural reference extraction from HCL expressions
    test_terraform_extractor.py    Terraform blocks -> IR, syntax errors, literals
  integration/
    test_pipeline.py           parser output -> validation -> analysis -> AnalysisResult (fake adapters)
    test_terraform_pipeline.py Terraform fixtures through the full pipeline
    test_examples.py           every file in examples/terraform/ analyses as documented
  fixtures/
    terraform/                 valid, cyclic, unresolved, depends_on, unsupported, security, syntax_error (.tf)
```

Not present yet: YAML and Dockerfile parser tests and fixtures (Saanvi), and
the API tests under `tests/api/` that spec 2.1 and 9.1 call for (Saanvi; there
is no FastAPI app yet).

## Markers

Defined in `backend/pyproject.toml`. `--strict-markers` is on, so a typo in a
marker name fails the run.

| Marker | pyproject description | What it covers in practice |
|---|---|---|
| `unit` | "mark test as a fast unit test" | One module in isolation on hand-built inputs: models, IR helpers, each graph algorithm, recommendation rules, Terraform rules. |
| `compiler` | "mark test as a compiler core or graph test" | Anything exercising the compiler core: IR, validation, cycles, ordering, reachability, pipeline, recommendations. Combined with `unit` or `integration`. |
| `parser` | "mark test as a parser-specific test" | Format adapters on real source text (currently the Terraform adapter). |
| `integration` | "mark test as an integration test" | Multiple stages together, from **parser output or source text through IR, analysis and diagnostics to the `AnalysisResult` response payload**. It is not limited to HTTP API tests; there are no HTTP tests yet. |

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

`.github/workflows/ci.yml` defines a single job, `test` ("Backend Lint and
Tests"), on pushes and pull requests to `main` and `dev`. It:

1. sets up Python 3.11;
2. runs `pip install -r backend/requirements.txt`;
3. runs `ruff check backend` and `ruff format --check backend`;
4. runs `pytest backend/tests`.

**CI does not currently enforce the coverage target.** No coverage options are
passed to pytest in CI, and there are no frontend checks yet (spec 9.5 asks for
both backend and frontend checks once the frontend exists).
