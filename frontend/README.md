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
- **Blast radius** ("click a node, see what breaks"): a node's details list everything that depends on it, directly or through others, grouped by distance and with the edge each is reached through. "Show on graph" colours the selected node red, the affected nodes orange to yellow (nearest first), and fades the rest. `blastRadius.ts` walks the documented edge direction (`A → B`: B depends on A) breadth-first, like the backend's `descendants`. When the analysis is partial, the panel warns that dependents may be missing.
- **Compare versions** (graph diff): analyse an old and a new version and see both graphs, with added, removed and rewired items and any new cycle (`graphDiff.ts`).
- **Suggested fixes** show a ready-to-apply patch (Copy / Download .patch) when the backend provides one. The **layer & cache advisor** groups Dockerfile build-speed and image-size findings.
- Cycles, validity, order and diagnostics come from the backend response. The UI only follows edges in their documented direction (blast radius, diff); it does not re-analyse.

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
