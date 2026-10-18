# Deployment

> **Status: UNVERIFIED.** Nothing in this repository has been deployed yet.
> There is no `vercel.json`, no deployment adapter, and no FastAPI app
> (`backend/app/main.py` does not exist). Everything below is a plan to be
> confirmed by a real deployment test, as spec 11.2 requires. Do not treat any
> setting or limit here as verified.

Authoritative requirements: [PROJECT_SPEC.md section 11](PROJECT_SPEC.md#11-deployment).

## Goal and fallback

**Goal: one Vercel project** serving both the Vite frontend and the FastAPI
backend (spec 11.1). Frontend and API then share one origin, so the browser
calls `/api/v1/...` on the same host and production needs no CORS at all.

**Fallback: two deployments.** These can be two Vercel projects from the same
repository (root directories `frontend/` and `backend/`), or Vercel for the
frontend plus another host for the backend. Use this only if verified Vercel
constraints (Python entry-point discovery, routing, bundle size, request
limits) make the single project unreliable. If the fallback is chosen,
document the evidence and the final architecture here (spec 11.4).

Correct deployment takes priority over forcing the one-project layout.

## Fixed requirements (regardless of layout)

- Canonical routes: **`GET /api/v1/health`** and **`POST /api/v1/validate`**.
  An optional root `/health` alias may be added for a hosting probe, but it
  must not replace the canonical route.
- `backend/app/main.py` stays the canonical FastAPI entry point. A small
  deployment adapter (e.g. a file that only imports `app`) is added **only if**
  the verified Vercel configuration requires it, and it must not duplicate
  route logic (spec 11.3).
- The frontend reads the API base URL from **`VITE_API_BASE_URL`**. No
  production URL is hard-coded. In the one-project layout it can be empty or a
  relative path. `VITE_` variables are embedded in the client bundle, so never
  put secrets in them.
- No secrets are committed; only `.env.example` templates (they exist at the
  repo root, `backend/` and `frontend/`).
- Local development stays independent of Vercel:
  `uvicorn app.main:app --reload` (once `main.py` exists) and `npm run dev`.

## CORS

Configure allowed origins **explicitly** from the `ALLOWED_ORIGINS`
environment variable (comma-separated; already listed in
`backend/.env.example`). Do not use a wildcard regex such as
`^https://.*\.vercel\.app$`: that admits every project on `vercel.app`,
including other people's.

- **One-project layout:** production needs no cross-origin access. Keep
  `ALLOWED_ORIGINS` to local development origins
  (`http://localhost:5173`, ...).
- **Two-deployment layout:** list the production frontend origin explicitly.
- **Preview deployments (the tradeoff):** each Vercel preview gets a new URL,
  so a fixed list will not cover them. The options are:
  1. use the one-project layout, where previews are same-origin;
  2. point previews at a stable per-branch preview alias and list those origins;
  3. accept a regex **narrowly scoped to this project's own preview URL
     pattern**, after verifying exactly what that pattern is.

  Options 1 and 2 are safer than option 3. Credentials are not needed: the API
  has no authentication, so `allow_credentials` can stay off.

## Platform limits: claimed, not verified

The previous version of this page stated the following numbers. They are
**claims that must be checked against current Vercel documentation** and a
real deployment before anyone relies on them:

| Item | Previously claimed | Status |
|---|---|---|
| Python function bundle size | 50 MB compressed / 250 MB uncompressed | must be verified |
| Request body size | 4.5 MB | must be verified |
| Function timeout | 10 s (Hobby) / 60 s (Pro) | must be verified |
| Python runtime versions | 3.9 / 3.12 | must be verified (CI uses 3.11; pyproject requires >= 3.10) |
| Backend bundle size | "under 10 MB" | never measured |

The application's own source-size limit (spec 7.5) is configurable, and its
default has **not been chosen yet**. Pick it only after measuring the real
request limit.

## Verification checklist (from spec 11.2)

Before committing to a deployment configuration, verify with current Vercel
documentation **and** a real (or minimal) deployment test:

- [ ] how the chosen root directory affects file discovery;
- [ ] Python function entry-point discovery and routing;
- [ ] whether `backend/app/main.py` can be exposed directly or needs a small deployment adapter;
- [ ] frontend build/output settings;
- [ ] API path routing and rewrite behaviour;
- [ ] Python dependency bundling and the actual bundle size;
- [ ] request/body-size limits and function execution limits;
- [ ] environment-variable configuration and CORS behaviour.

After deploying, confirm that `GET /api/v1/health` and `POST /api/v1/validate`
work on the deployed URL (spec 11.4). Do not mark deployment as verified until
all of the above has actually been tested.
