# Compiler-Based Cloud Workflow Validator

A static analysis tool that treats cloud infrastructure manifests, container definitions, and CI/CD pipelines as compiled software programs, constructing unified dependency graphs to detect defects, cycles, and optimization opportunities before execution.

---

## 1. Project Overview & Problem Statement

Modern cloud workflows comprise heterogeneous configurations—such as GitHub Actions YAML workflows, multi-stage Dockerfiles, and Terraform (HCL) infrastructure specifications. Subtle configuration errors (such as circular dependency deadlocks, missing prerequisite outputs, unreachable stages, and unoptimized execution ordering) typically remain undetected until runtime, causing failed CI runs, broken deployments, or dangling cloud resources.

The **Compiler-Based Cloud Workflow Validator** solves this by applying classical compiler techniques to static cloud configurations:
1. Parsing syntax into a **Common Intermediate Representation (IR)**.
2. Constructing an abstract **Dependency Graph**.
3. Executing generic **Static Analysis Passes** (cycle detection, topological sort, dead-path elimination).
4. Generating **Actionable Diagnostics and Recommendations** with remediation diffs.
5. Rendering the workflow graph and diagnostics in an interactive visual interface.

---

## 2. Planned Supported Formats

| Format | Target Specifications | Parser Library | Key Analysis Focus |
| :--- | :--- | :--- | :--- |
| **YAML** | CI/CD Pipelines (e.g., GitHub Actions) | `ruamel.yaml` | Job prerequisite cycles (`needs`), execution ordering, missing step inputs |
| **Dockerfile** | Container Build Specifications | `dockerfile-parse` | Multi-stage dependencies (`COPY --from`), layer caching ordering, unreachable stages |
| **Terraform (HCL)** | Cloud Infrastructure Manifests | `python-hcl2` | Inter-resource dependencies, circular references, orphan resource blocks |

---

## 3. High-Level Architecture & Compiler Pipeline

The core architectural tenet is the **strict separation of language-specific syntax parsers from generic graph algorithms**.

```
Input Configuration (YAML / Dockerfile / HCL)
                     │
                     ▼
             Language Adapter
                     │
                     ▼
       Intermediate Representation (IR)
                     │
                     ▼
             Dependency Graph
                     │
                     ▼
          Static Analysis Passes
     (Cycles, Topological Order, Orphans)
                     │
                     ▼
       Diagnostics & Recommendations
                     │
                     ▼
         Presentation Layer (API & UI)
```

For the complete architectural design and IR schema details, see [docs/architecture.md](docs/architecture.md).

---

## 4. Planned Features

> [!NOTE]
> All features listed below are **planned** and currently under active development. See [Current Implementation Status](#13-current-implementation-status--known-limitations) for details.

- **Multi-Format Ingestion**: Unified validation interface accepting YAML, Dockerfile, or Terraform configurations.
- **Cycle Detection**: Identification of circular dependencies using Tarjan's Strongly Connected Components and cycle chain reporting.
- **Topological Sorting**: Computation of valid execution orders and critical paths.
- **Orphan & Dead-Code Detection**: Identification of unreferenced build stages, unreachable steps, and dangling infrastructure resources.
- **Actionable Remediation Engine**: Pinpointed source code diagnostics with suggested fixes and diff previews.
- **Interactive Visual Canvas**: Visual graph rendering with pan/zoom, node status highlighting, and diagnostics inspection in React.
- **REST API**: Automated validation endpoints under `/api/v1` (`GET /api/v1/health`, `POST /api/v1/validate`) suitable for pre-commit hooks, CI/CD gates, and web client integration. See [docs/api.md](docs/api.md).

---

## 5. Technology Stack

- **Backend**:
  - Language: Python 3.10+
  - Web Framework: [FastAPI](https://fastapi.tiangolo.com/) & [Uvicorn](https://www.uvicorn.org/)
  - Data Validation & Schemas: [Pydantic v2](https://docs.pydantic.dev/)
  - Format Parsers: `ruamel.yaml`, `dockerfile-parse`, `python-hcl2`
  - Testing & Client: `pytest`, `httpx`
  - Code Quality: [Ruff](https://docs.astral.sh/ruff/) (linter & formatter)
- **Frontend**:
  - Framework: React with TypeScript
  - Build Tool: [Vite](https://vitejs.dev/)
  - Visualization: React Flow / Cytoscape
- **Infrastructure & CI**:
  - Continuous Integration: GitHub Actions (`.github/workflows/ci.yml`)
  - Cloud Deployment: [Vercel](https://vercel.com) (independent frontend and serverless backend projects)

---

## 6. Repository Directory Structure

```
Cloud-Workflow-Validator/
├── .github/
│   └── workflows/
│       └── ci.yml             # GitHub Actions CI workflow (linting & tests)
├── backend/
│   ├── app/
│   │   ├── api/               # FastAPI endpoints & routers
│   │   ├── compiler/          # Common IR and compiler pipeline core
│   │   ├── parsers/           # Language adapters (YAML, Dockerfile, HCL)
│   │   ├── analysis/          # Generic graph algorithms & cycle detection
│   │   ├── recommendations/   # Lint rules and remediation engine
│   │   └── models/            # Pydantic schemas (IR models, API contracts)
│   ├── tests/
│   │   └── test_scaffolding.py# Test discovery & environment tests
│   ├── pyproject.toml         # Pytest & Ruff configuration
│   ├── requirements.txt       # Python dependency manifest
│   └── .env.example           # Backend environment template
├── frontend/
│   ├── .env.example           # Frontend environment template
│   └── README.md              # Frontend setup & development guide
├── examples/
│   ├── yaml/                  # Sample CI/CD workflow fixtures
│   ├── dockerfile/            # Sample Dockerfile fixtures
│   ├── terraform/             # Sample Terraform HCL fixtures
│   └── README.md              # Examples overview
├── docs/
│   ├── architecture.md        # Compiler pipeline & IR architecture
│   ├── api.md                 # REST API specifications & contracts
│   ├── testing.md             # Testing conventions & commands
│   └── deployment.md          # Independent Vercel deployment guide
├── .editorconfig              # Multi-language formatting standards
├── .gitignore                 # Version control exclusions
├── .env.example               # Root environment reference template
├── LICENSE                    # GNU General Public License v3.0
└── README.md                  # Project overview and documentation
```

---

## 7. Prerequisites

- **Python**: Version 3.10 or higher
- **Node.js**: Version 18.0 or higher (with npm)
- **Git**: Version 2.30 or higher

---

## 8. Local Development Setup

### A. Clone Repository
```bash
git clone https://github.com/bibek/Cloud-Workflow-Validator.git
cd Cloud-Workflow-Validator
```

### B. Backend Setup
1. **Always** create the virtual environment *inside the repository root* as `.venv` (it is git-ignored) and activate it. Do not install project dependencies into the system Python:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```
2. Install Python dependencies into that venv (runtime + dev tools: pytest, pytest-cov, ruff, httpx), then the backend package itself in editable mode:
   ```bash
   pip install -r backend/requirements.txt
   pip install -e "backend[dev]"
   ```
   Re-run both commands whenever `backend/requirements.txt` or `backend/pyproject.toml` changes. Run every command below from the activated venv (or prefix it with `.venv/bin/`).
3. Initialize the backend environment file:
   ```bash
   cp backend/.env.example backend/.env
   ```
4. Run the backend development server:
   ```bash
   # [Placeholder: To be used once app/main.py is implemented by Saanvi]
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
   > *Note: `app.main:app` will be created during the backend feature development phase. Once started, the backend exposes canonical endpoints `GET /api/v1/health` and `POST /api/v1/validate`.*

### C. Frontend Setup
1. Navigate to the frontend directory:
   ```bash
   cd frontend
   ```
2. Initialize environment file:
   ```bash
   cp .env.example .env
   ```
3. Install dependencies and run development server:
   ```bash
   # [Placeholder: To be used once Vite project is initialized by Pavithra]
   npm install
   npm run dev
   ```
   Default development URL: `http://localhost:5173`

---

## 9. Testing & Code Quality

Run tests and quality checks from the repository root:

```bash
# Run pytest backend test suite
pytest backend/tests

# Run with coverage (target: at least 70% overall)
pytest backend/tests --cov=app --cov-report=term-missing

# Check for code linting errors
ruff check backend

# Check code formatting compliance
ruff format --check backend
```

For complete testing conventions, markers, and guidelines, see [docs/testing.md](docs/testing.md).

---

## 10. Environment Variables

| Variable | Scope | Default Value | Description |
| :--- | :--- | :--- | :--- |
| `ENVIRONMENT` | Backend | `development` | Runtime environment mode (`development`, `staging`, `production`) |
| `HOST` | Backend | `0.0.0.0` | Server binding host address |
| `PORT` | Backend | `8000` | Server binding network port |
| `ALLOWED_ORIGINS`| Backend | `http://localhost:5173,http://localhost:3000` | Comma-delimited origins permitted by CORS middleware |
| `LOG_LEVEL` | Backend | `info` | Application logging verbosity (`debug`, `info`, `warning`, `error`) |
| `VITE_API_BASE_URL` | Frontend | `http://localhost:8000` | Base endpoint URL for communicating with the backend API |

---

## 11. Git Branching & Collaboration Conventions

To facilitate parallel development across team members without conflicts, the team adheres to the following Git strategy:

### Branch Roles
- **`main`**: Production-ready, stable releases.
- **`dev`**: Active integration branch where all tested feature branches merge.
- **`feat/compiler-core`**: Feature branch for compiler core, Terraform parser, graph algorithms, and recommendations (**Me**).
- **`feat/backend-parsers`**: Feature branch for YAML & Dockerfile parsers and FastAPI backend routes (**Saanvi**).
- **`feat/frontend`**: Feature branch for React application, Vite setup, and graph visualization (**Pavithra**).

### Team Collaboration Workflow
1. Always base feature branches off the latest `dev`:
   ```bash
   git checkout dev
   git pull origin dev
   git checkout -b feat/<your-assigned-feature>
   ```
2. Make focused, well-documented commits.
3. Keep feature branches updated with `dev` regularly to avoid divergence:
   ```bash
   git fetch origin
   git merge origin/dev
   ```
4. Open a Pull Request targeting `dev` when a feature increment is ready.
5. Verify that GitHub Actions CI passes (all tests and lint checks green).
6. Request team review before merging.

---

## 12. Team Responsibilities

| Team Member | Branch | Assigned Components |
| :--- | :--- | :--- |
| **Lead Developer (Me)** | `feat/compiler-core` | Compiler core pipeline, Common IR design, Terraform (HCL) parser, graph analysis algorithms (cycle detection, topological sort), recommendations engine |
| **Saanvi** | `feat/backend-parsers` | YAML parser, Dockerfile parser, FastAPI endpoints, request schemas, error handling |
| **Pavithra** | `feat/frontend` | React + Vite application, graph visualization canvas (React Flow), diagnostics UI, API client integration |

---

## 13. Current Implementation Status & Known Limitations

### Current Status
- **Scaffolding Complete**: Repository directory structure, dependency manifests (`requirements.txt`), project configuration (`pyproject.toml`, `.editorconfig`), CI workflow (`.github/workflows/ci.yml`), environment templates, and comprehensive architectural documentation are established.
- **Verified Environment**: Dependency resolution and test execution runner verified.

### Known Limitations
- **Parsers Not Yet Implemented**: Language adapters for YAML, Dockerfiles, and Terraform are scaffolding placeholders; syntax parsing will be implemented on `feat/backend-parsers` and `feat/compiler-core`.
- **Compiler Passes Not Yet Implemented**: Cycle detection, topological sorting, and recommendation rules are pending feature implementation.
- **API Endpoints Not Yet Live**: FastAPI routing and HTTP endpoints are not yet registered.
- **Frontend Not Yet Initialized**: React components and Vite frontend are pending implementation on `feat/frontend`.

---

## 14. Deployment

The project is structured for independent deployment of the frontend static client and backend serverless function on **Vercel** from this single monorepo.

For comprehensive deployment instructions, project configuration, and platform constraints, see **[docs/deployment.md](docs/deployment.md)**.

---

## 15. Documentation Index

- [Architecture & Pipeline Specification](docs/architecture.md)
- [REST API Contracts](docs/api.md)
- [Testing Guidelines](docs/testing.md)
- [Vercel Deployment Guide](docs/deployment.md)
- [Frontend Documentation](frontend/README.md)
- [Sample Examples Overview](examples/README.md)
- [License (GPLv3)](LICENSE)