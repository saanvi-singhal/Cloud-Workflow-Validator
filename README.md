# Cloud Workflow Validator

A compiler-style static analyser for GitHub Actions workflows, Dockerfiles and Terraform. It parses a configuration into a shared intermediate representation (IR), builds a dependency graph, runs graph analyses and rule checks, and reports diagnostics, an execution order and suggested fixes, without running anything.

The authoritative contract is [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md).

---

## 1. What it does

1. **Parse** one source file into the shared IR: nodes (jobs, stages, Terraform blocks) and edges, where `A → B` means *A must come before B*.
2. **Validate** the graph, then find cycles (Tarjan SCC plus a DFS path for each cycle), compute a deterministic execution order (Kahn's algorithm), and check reachability and disconnected parts.
3. **Check rules**: schema errors the target tool would reject, plus a small, documented set of security and quality rules.
4. **Report** diagnostics with exact source locations and deterministic recommendations, some with a preview of the change. Nothing is ever applied to your files.
5. **Show** it all in a web UI: an interactive graph, clickable diagnostics and node details.

**Static analysis only.** User configurations are never executed, Terraform is never run and no provider or registry is contacted.

---

## 2. Supported formats and checks

| Format | Graph | Checks (summary) |
| :--- | :--- | :--- |
| **GitHub Actions YAML** | Jobs; `needs` edges | Unknown `needs` jobs; cycles; duplicate keys and job IDs; missing `on`/`jobs`; unknown trigger events; unknown workflow, job and step keys; missing `runs-on`; steps without exactly one of `uses`/`run`; `secrets` in `if`; reusable-workflow call rules. Rules: script injection from untrusted event data, numbers that lose a trailing zero (`3.10` → `3.1`), actions pinned to a branch (`@master`). |
| **Dockerfile** | Stages; `FROM <stage>` and `COPY --from` edges | No `FROM`; unknown instructions; instructions before `FROM`; malformed `HEALTHCHECK` and `ONBUILD`; unknown or later stage references; stages the final stage does not need. Rules: exec form that is not valid JSON, `apt-get` without `-y`, unpinned base images, running as root, `apt-get update` alone, `apt-get upgrade`, `ADD` for local files, copying the whole context before installing dependencies, consecutive `RUN`s, unpinned `apt`/`apk` packages, `apk add` without `--no-cache`, `curl … \| sh`. With several files, scripts and other build-context files are checked against `COPY` and `RUN`. |
| **Terraform (HCL)** | `resource`, `data`, `module`, `variable`, `output`; reference and `depends_on` edges | Undeclared references; cycles; duplicate blocks; `dynamic` blocks (iterator scoping, required `for_each`/`content`). Rules: public S3 ACLs, ingress open to the internet, hard-coded secrets, publicly accessible databases. |

The full lists, with rule IDs and severities, are in [docs/compiler-core.md](docs/compiler-core.md). Diagnostic codes are listed in spec section 6.1.

---

## 3. Architecture

```
source text ──► format adapter ──► IR (nodes, edges) ──► graph validation
   (YAML / Dockerfile / HCL)                                   │
                                                               ▼
       response ◄── recommendations ◄── diagnostics ◄── cycles · order · reachability · rules
```

- `backend/app/parsers/`: one adapter per format. Only the adapters know about ruamel.yaml, dockerfile-parse or python-hcl2.
- `backend/app/compiler/`, `backend/app/analysis/`: the format-independent IR, pipeline and graph algorithms.
- `backend/app/rules/`, `backend/app/recommendations/`: rule sets and the recommendation catalogue.
- `backend/app/api/`: FastAPI routes. `frontend/`: the React UI.

More detail: [docs/architecture.md](docs/architecture.md) and [docs/compiler-core.md](docs/compiler-core.md).

---

## 4. API

| Route | Purpose |
| :--- | :--- |
| `GET /api/v1/health` | Health check |
| `POST /api/v1/validate` | Body `{"source": "...", "format": "yaml" \| "dockerfile" \| "terraform", "filename": "optional"}`, or `{"files": [{"filename", "content"}, ...], "format": ...}` for several files; `"format": "mixed"` detects each file's format. Returns `valid`, `format`, `diagnostics`, `graph`, `execution_order`, `recommendations` and (multi-file) `multifile`. |

An invalid configuration is still HTTP 200, with diagnostics. A malformed request is 422, and a source larger than `MAX_SOURCE_BYTES` is 413. See [docs/api.md](docs/api.md).

---

## 5. Repository layout

```
Cloud-Workflow-Validator/
├── .github/workflows/ci.yml   # backend and frontend CI
├── backend/
│   ├── app/
│   │   ├── api/               # FastAPI routes (main.py is the app entry point)
│   │   ├── compiler/          # IR, pipeline, adapter registry, format policy
│   │   ├── analysis/          # validation, cycles, topological sort, reachability
│   │   ├── parsers/           # yaml/, dockerfile/, terraform/ adapters
│   │   ├── rules/             # Dockerfile, GitHub Actions and Terraform rules
│   │   ├── recommendations/   # recommendation engine and catalogue
│   │   └── models/            # Pydantic models: the shared contract
│   ├── tests/                 # unit/, parsers/, integration/, fixtures/
│   ├── pyproject.toml
│   └── requirements.txt
├── frontend/
│   ├── src/                   # App, components/, api.ts, analysis.ts, samples/, mocks/
│   └── scripts/generate_mocks.py
├── examples/                  # yaml/, dockerfile/, terraform/ (static fixtures)
└── docs/                      # spec, compiler core, API, architecture, testing, deployment
```

---

## 6. Local development

**Prerequisites:** Python 3.10+ (CI uses 3.11), Node.js 20.19+ or 22.12+ (required by Vite 8; CI uses 22), and Git.

### Backend

1. **Always** create the virtual environment *inside the repository root* as `.venv` (it is git-ignored). Do not install project dependencies into the system Python:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   ```
2. Install the dependencies into that venv, then the backend package itself in editable mode:
   ```bash
   pip install -r backend/requirements.txt
   pip install -e "backend[dev]"
   ```
   Re-run both whenever `backend/requirements.txt` or `backend/pyproject.toml` changes.
3. Start the API on `http://localhost:8000`:
   ```bash
   cd backend
   uvicorn app.main:app --reload --port 8000
   ```

### Frontend

```bash
cd frontend
npm ci
npm run dev        # http://localhost:5173
```

Open `http://localhost:5173` (not `127.0.0.1`: CORS allows the `localhost` origins by default). To work on the UI without the backend, start it with `VITE_USE_MOCK=true npm run dev`. The mocks are real backend output, regenerated with `.venv/bin/python frontend/scripts/generate_mocks.py`.

### Configuration

The backend reads environment variables from the process environment. It does not load a `.env` file, so export them or set them in your hosting platform.

| Variable | Used by | Default | Meaning |
| :--- | :--- | :--- | :--- |
| `ALLOWED_ORIGINS` | backend | `http://localhost:5173,http://localhost:3000` | Comma-separated CORS origins. Set it to the deployed frontend's origin. |
| `MAX_SOURCE_BYTES` | backend | `524288` (512 KB) | Largest accepted source; larger requests get HTTP 413. |
| `VITE_API_BASE_URL` | frontend (build time) | `http://localhost:8000` | Backend base URL; empty means same origin. |
| `VITE_USE_MOCK` | frontend (build time) | `false` | `true` serves the bundled mocks instead of calling the API. |

---

## 7. Tests and quality checks

```bash
# backend, from the repository root (inside the venv)
ruff check backend && ruff format --check backend
pytest backend/tests --cov=app --cov-fail-under=70

# frontend
cd frontend
npm run lint && npm test && npm run build   # build includes `tsc -b`
```

CI (`.github/workflows/ci.yml`) runs both sets on pushes and pull requests to `dev` and `main`. Backend coverage is about 96%, against the spec's 70% target. Every file in `examples/` is analysed in the test suite and must produce its documented result. See [docs/testing.md](docs/testing.md).

---

## 8. Current limitations

- **Only the files you upload.** Several files can be analysed together (Terraform modules, several workflows or Dockerfiles with their scripts, or a mix of formats), but reusable workflows, remote base images and modules from a registry are never fetched, so a reference to something not uploaded is reported as unresolved.
- **Terraform:** `local.*` references, `for` expressions, `%{}` template directives, heredocs with interpolation and `replace_triggered_by` are reported as unsupported constructs. The analysis is then marked partial and the execution order is withheld.
- **GitHub Actions:** expressions are not evaluated, so `if` conditions and matrix values do not change the graph. Only the structure GitHub validates when it loads a workflow is checked.
- **Dockerfile:** `ARG` and `ENV` values are not substituted into stage names or images. Stages have no execution order (spec 5.3).
- **Formats:** only GitHub Actions workflows are supported as YAML, not Docker Compose or other YAML files.
- **Rules:** the rule sets are small and deterministic. They are not a comprehensive security scanner or linter.
- **Deployment:** not yet configured or verified (see below).

---

## 9. Deployment

The goal is one Vercel project serving both the frontend and the API, with a documented fallback (spec section 11). Nothing has been deployed yet: there is no Vercel configuration, and the platform's request and bundle limits have not been measured, so the `MAX_SOURCE_BYTES` default is provisional. See [docs/deployment.md](docs/deployment.md).

---

## 10. Team workflow

| Member | Area | Branch |
| :--- | :--- | :--- |
| **Bibek** (project owner) | Compiler core: IR, graph algorithms, Terraform analysis, rules, recommendations | `feat/compiler-core` |
| **Saanvi** | YAML and Dockerfile parsers, FastAPI | `feat/backend-parsers` |
| **Pavithra** | React frontend and graph visualisation | `feat/frontend` |

`dev` is the integration branch and `main` holds releases. Branch from the latest `dev`, keep commits focused, open a pull request to `dev`, and merge only when CI passes. Changes to the shared contract (schemas, node and edge types, diagnostic fields, routes) need the project owner's approval first (spec section 12.4).

---

## 11. Documentation

- [Project specification (authoritative)](docs/PROJECT_SPEC.md)
- [Compiler core reference: IR, diagnostic codes, rules, format support](docs/compiler-core.md)
- [Compiler core plan (approved decisions D1–D17)](docs/claude-planning.md)
- [Architecture](docs/architecture.md)
- [API contract](docs/api.md)
- [Testing](docs/testing.md)
- [Deployment](docs/deployment.md)
- [Frontend](frontend/README.md)
- [Examples](examples/README.md)
- [License (GPLv3)](LICENSE)
