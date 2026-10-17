# Vercel Monorepo Deployment Guide

This guide details how to deploy the **Compiler-Based Cloud Workflow Validator** on Vercel as two independently deployed projects (React/Vite Frontend and FastAPI Backend) from this single Git repository.

---

## 1. Monorepo Deployment Model

Rather than coupling the frontend build to the backend runtime, Vercel deploys each subproject independently by configuring the **Root Directory** setting for each project:

```
Git Repository (Cloud-Workflow-Validator)
 ├── frontend/  ──> Vercel Project 1: "cloud-workflow-validator-frontend" (Vite Static)
 └── backend/   ──> Vercel Project 2: "cloud-workflow-validator-backend"  (FastAPI Serverless)
```

Both projects connect to the same GitHub repository, automatically triggering preview deployments on pull requests and production deployments on merges to `main`.

---

## 2. Project 1: Frontend Deployment (React + Vite)

### A. Vercel Project Configuration
1. Go to the [Vercel Dashboard](https://vercel.com/dashboard) and click **Add New... -> Project**.
2. Import this Git repository (`Cloud-Workflow-Validator`).
3. Set the **Project Name**: e.g., `cloud-workflow-validator-frontend`.
4. In **Root Directory**, click *Edit* and select:
   ```
   frontend
   ```
5. **Framework Preset**: Vercel will detect **Vite** automatically.
6. Verify the Build & Output settings:
   - **Build Command**: `npm run build`
   - **Output Directory**: `dist`
   - **Install Command**: `npm install`

### B. Frontend Environment Variables
In **Project Settings -> Environment Variables**:
- **Key**: `VITE_API_BASE_URL`
- **Production Value**: `https://cloud-workflow-validator-backend.vercel.app` (URL of your deployed backend project)
- **Preview Value**: `https://cloud-workflow-validator-backend-preview.vercel.app` (or point to staging backend)
- **Development Value**: `http://localhost:8000`

> **Note**: Vite injects environment variables prefixed with `VITE_` into client code at build time. Never store private API keys or server secrets in `VITE_` variables.

---

## 3. Project 2: Backend Deployment (FastAPI Python Runtime)

### A. Vercel Project Configuration
1. Go to the Vercel Dashboard and click **Add New... -> Project**.
2. Import the same Git repository (`Cloud-Workflow-Validator`).
3. Set the **Project Name**: e.g., `cloud-workflow-validator-backend`.
4. In **Root Directory**, click *Edit* and select:
   ```
   backend
   ```
5. **Framework Preset**: Select **Other**.

### B. Dependency Discovery
Because the Root Directory is set to `backend`, Vercel discovers `requirements.txt` directly at the root of the project. Vercel installs dependencies listed in `backend/requirements.txt` into the serverless Python environment during build.

### C. FastAPI Entrypoint Discovery
Vercel's Python runtime routes requests to serverless functions using ASGI.
When the FastAPI application is implemented in `backend/app/main.py`:
1. Vercel requires an entrypoint adapter, typically located at `backend/api/index.py`:
   ```python
   # backend/api/index.py
   from app.main import app
   ```
2. Configure URL routing via `backend/vercel.json`:
   ```json
   {
     "rewrites": [
       {
         "source": "/(.*)",
         "destination": "/api/index.py"
       }
     ]
   }
   ```
This forwards all incoming requests (`/api/v1/health`, `/api/v1/validate`, etc.) to the FastAPI application instance.

### D. Backend Environment Variables
In **Project Settings -> Environment Variables**:
- `ENVIRONMENT`: `production` (or `preview`)
- `ALLOWED_ORIGINS`: Comma-separated list of allowed frontend origins for CORS:
  - Production: `https://cloud-workflow-validator-frontend.vercel.app`
  - Preview: `https://cloud-workflow-validator-frontend.vercel.app,https://*-your-team.vercel.app`
- `LOG_LEVEL`: `info`

---

## 4. CORS Configuration Strategy

FastAPI uses `CORSMiddleware` to authorize cross-origin browser requests from the frontend client.

- **Local Development**:
  `ALLOWED_ORIGINS="http://localhost:5173,http://localhost:3000"` allows Vite's default dev server port.
- **Production**:
  `ALLOWED_ORIGINS="https://cloud-workflow-validator-frontend.vercel.app"` allows the canonical frontend domain.
- **Vercel Preview Deployments**:
  Vercel creates dynamic URLs for pull requests (e.g. `https://cloud-workflow-validator-frontend-git-feat-*.vercel.app`).
  When configuring CORS in FastAPI:
  ```python
  from fastapi.middleware.cors import CORSMiddleware
  import os

  allowed_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]

  app.add_middleware(
      CORSMiddleware,
      allow_origins=allowed_origins,
      allow_origin_regex=r"^https:\/\/.*\.vercel\.app$",  # Allows all preview deployments
      allow_credentials=True,
      allow_methods=["*"],
      allow_headers=["*"],
  )
  ```

---

## 5. Vercel Platform Constraints & Limits

| Constraint | Limit | Consideration for Workflow Validator |
| :--- | :--- | :--- |
| **Python Runtime** | Python 3.9 / 3.12 | All dependencies in `backend/requirements.txt` are verified compatible across modern Python versions. |
| **Function Bundle Size** | 50 MB (compressed) / 250 MB (uncompressed) | Our chosen dependencies (`ruamel.yaml`, `dockerfile-parse`, `python-hcl2`, `fastapi`) bundle to under 10 MB. Avoid adding heavy numerical libraries (such as `numpy` or `pandas`) unless strictly necessary. |
| **Request Payload Size** | 4.5 MB | Input workflow configuration files must remain under 4.5 MB per validation request. |
| **Execution Timeout** | 10 seconds (Hobby) / 60 seconds (Pro) | Static analysis (cycle detection, AST parsing) executes in milliseconds for typical workflow and IaC files. |

---

## 6. Local Development Independence

Vercel configuration does **not** interfere with local development:
- **Run Backend locally**:
  ```bash
  cd backend
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
  ```
- **Run Frontend locally**:
  ```bash
  cd frontend
  npm run dev
  ```
Neither command requires the `vercel` CLI, mock cloud environments, or external cloud accounts.
