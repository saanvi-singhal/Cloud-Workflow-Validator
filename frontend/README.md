# Frontend: Cloud Workflow Validator

React + TypeScript + Vite + Tailwind UI for the validator. Owner: Pavithra (`feat/frontend`).

## Run

```bash
npm ci
npm run dev            # http://localhost:5173, talks to the API at VITE_API_BASE_URL
```

Use `http://localhost:5173`, not `127.0.0.1`: the backend's default CORS origins are the `localhost` ones. Without a backend, run `VITE_USE_MOCK=true npm run dev`. The mocks in `src/mocks/` are real backend output, regenerated from the repository root with `.venv/bin/python frontend/scripts/generate_mocks.py`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Backend base URL (empty = same origin) |
| `VITE_USE_MOCK` | `false` | `true` serves the bundled mocks instead of calling the API |

Both are read at build time (see `.env.example`).

## What the UI does

Three pages, linked from the top bar. They use hash URLs (`#/analyze`, `#/compare`, `#/how-it-works`), so links, reloads and the back button work. The Analyze page stays mounted, so switching pages keeps your input and results.

**Analyze** (`src/pages/AnalyzePage.tsx`)

- **Editor (left):** choose a format (Terraform, GitHub Actions, Dockerfile, or Mixed to detect each file's format), then paste, upload or load a sample.
  - Each file is a tab. "+ Add file" asks for a name straight away, and double-clicking a tab renames it.
  - Clicking an issue selects its text in the editor.
- **Results (right):** a deploy verdict ("Not ready to deploy", "Ready, with warnings to review", "Ready to deploy") with counts, then tabs:
  - **Issues:** every diagnostic, filterable by severity. Each issue has its fix underneath, with the ready-to-apply patch (Copy / Download .patch) or a preview. "Show in graph" switches to the graph with the issue's nodes highlighted.
  - **Graph:** the dependency graph (React Flow, Dagre layout).
    - Arrows point from a prerequisite to the item that depends on it.
    - Boxes are coloured by their most severe issue, and cycle edges are red and animated.
    - Clicking a box shows its details, including its **blast radius**: everything that depends on it, grouped by distance. "Show on graph" colours the affected items. `blastRadius.ts` walks the documented edge direction breadth-first, like the backend's `descendants`.
  - **Files** (several files only): each file and what it was analysed as, the dependencies between files, and the Terraform variables table.
  - **Build advisor** (Dockerfiles only): the layer and cache findings, grouped as cache order, image size and multi-stage builds.
- **Before analysing:** the results panel offers examples that load and analyse in one click.

**Compare versions** (`src/components/CompareView.tsx`): paste an old and a new version to see both graphs, with added, removed and rewired items and any new cycle (`graphDiff.ts`).

**How it works** (`src/pages/HowItWorksPage.tsx`): the pipeline, what each format is checked for, and what the tool never does.

Cycles, validity, order and diagnostics come from the backend response. The UI only follows edges in their documented direction (blast radius, diff); it does not re-analyse.

**Design tokens** live in `src/index.css` (`@theme`):

- **Colours:** steel-grey paper and white surfaces; ink text; one accent (teal) for actions and the current page; severity colours used only to carry meaning.
- **Type:** IBM Plex Sans for the interface, and IBM Plex Mono for code and identifiers.

## Checks

```bash
npm run lint    # oxlint
npm test        # vitest: src/analysis.test.ts (helpers), src/App.test.tsx (UI, jsdom)
npm run build   # tsc -b (type check) + vite build
```

CI runs all three (`.github/workflows/ci.yml`).

### End-to-end check against the real backend

`src/e2e.test.tsx` enters every file in `examples/` and every sample into the
real UI, submits it to a **running** backend, and checks the page shows exactly
what the API returned and what each example documents: the status, every
diagnostic and fix (with previews), the execution order or why it is missing,
the partial-analysis banner, and the empty-graph message. It is skipped unless
`E2E=1`:

```bash
(cd ../backend && ../.venv/bin/uvicorn app.main:app --port 8000) &
E2E=1 npm test -- e2e
```
