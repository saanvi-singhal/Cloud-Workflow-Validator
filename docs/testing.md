# Testing Conventions & Quality Assurance

This document defines testing conventions, guidelines, and execution procedures for the **Compiler-Based Cloud Workflow Validator**.

---

## 1. Testing Philosophy

The validator's compiler architecture makes it exceptionally well-suited for automated testing:
- **Language Adapters** must be thoroughly tested against valid syntax, edge cases, and intentionally malformed configurations.
- **Graph Algorithms** (cycle detection, topological sort, reachability) must be tested against synthetic directed graphs with mathematically known structures (DAGs, self-loops, disjoint cycles, complex multi-edge cycles).
- **API Endpoints** must verify HTTP semantics, input schema validation, and expected response serialization.

---

## 2. Directory Layout & Test Categories

```
backend/tests/
├── unit/
│   ├── test_yaml_parser.py          # YAML syntax adapter tests
│   ├── test_dockerfile_parser.py    # Dockerfile multi-stage adapter tests
│   ├── test_terraform_parser.py     # Terraform HCL resource adapter tests
│   ├── test_ir_builder.py           # Intermediate Representation transformation tests
│   ├── test_graph_algorithms.py     # Tarjan's SCC, Kahn's topological sort, cycles
│   └── test_recommendations.py      # Lint rules and remediation generation
├── integration/
│   ├── test_api_validation.py       # FastAPI endpoints via httpx TestClient
│   └── test_compiler_pipeline.py    # Full pipeline passes on real workflow files
├── fixtures/
│   ├── valid_workflows/
│   ├── cyclic_workflows/
│   └── invalid_syntax/
└── test_scaffolding.py              # Environment sanity check
```

---

## 3. Test Markers

Standard pytest markers configured in `backend/pyproject.toml`:

| Marker | Description | Intended Usage |
| :--- | :--- | :--- |
| `@pytest.mark.unit` | Fast, isolated unit tests | Pure functions, graph algorithms, model validation |
| `@pytest.mark.parser` | Language adapter tests | YAML, Dockerfile, or HCL parser tests |
| `@pytest.mark.compiler` | Compiler core & graph passes | IR generation, cycle detection, topological sorting |
| `@pytest.mark.integration`| End-to-end API tests | FastAPI HTTP endpoints tested with `httpx` |

---

## 4. Running Tests Locally

### Running the Entire Backend Test Suite
From the repository root:
```bash
pytest backend/tests
```

Or from within `backend/`:
```bash
cd backend
pytest
```

### Running Specific Test Suites
```bash
# Run only unit tests
pytest -m unit backend/tests

# Run only compiler and graph algorithm tests
pytest -m compiler backend/tests

# Run with verbose output and print statements
pytest -v -s backend/tests
```

### Linting & Formatting Checks
Run before committing:
```bash
# Check for lint errors
ruff check backend

# Check formatting compliance
ruff format --check backend

# Automatically fix linting and formatting issues
ruff check --fix backend
ruff format backend
```

---

## 5. CI Integration & Pull Request Requirements

All pull requests targeting `dev` or `main` must:
1. Pass all lint and format checks via Ruff without warnings.
2. Pass 100% of automated tests executed via `.github/workflows/ci.yml`.
3. Include unit tests covering any newly added parser feature, graph algorithm, or recommendation rule.
