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

- Choose a format, then paste, upload or load a sample, and analyse it (`POST /api/v1/validate`).
- Status badge, partial-analysis banner, diagnostics and suggested fixes with previews.
- Dependency graph (React Flow, Dagre layout). Arrows point from a prerequisite to the item that depends on it. Boxes are coloured by their most severe issue, cycle edges are red and animated, and `depends_on` edges are dashed. The layout picks left-to-right or top-to-bottom, whichever fits. Full screen is available from the graph controls.
- Clicking a diagnostic selects its text in the editor and highlights its nodes. Clicking a node shows its details: metadata, linked issues and, for Dockerfile stages, the ordered instructions, each linked to its line.
- All graph meaning (cycles, validity, order) comes from the backend response; the UI does not re-analyse.

## Checks

```bash
npm run lint    # oxlint
npm test        # vitest: src/analysis.test.ts (helpers), src/App.test.tsx (UI, jsdom)
npm run build   # tsc -b (type check) + vite build
```

CI runs all three (`.github/workflows/ci.yml`).
