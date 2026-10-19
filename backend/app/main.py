"""FastAPI application entrypoint for Cloud-Workflow-Validator."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_v1_router

# Local Vite dev servers; deployments set ALLOWED_ORIGINS (spec 8.4, 11.4).
DEFAULT_ALLOWED_ORIGINS = "http://localhost:5173,http://localhost:3000"


def allowed_origins() -> list[str]:
    """Return the CORS origins from ALLOWED_ORIGINS (comma-separated)."""
    raw = os.getenv("ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def create_app() -> FastAPI:
    """Instantiate and configure the FastAPI application."""
    app = FastAPI(
        title="Cloud-Workflow-Validator Backend",
        description=(
            "Compiler-based static validator for cloud workflows, "
            "Dockerfiles, and Terraform configurations"
        ),
        version="0.1.0",
    )

    # Only explicitly listed origins; the API uses no cookies or auth headers.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    app.include_router(api_v1_router)

    # Optional root alias for health check
    @app.get("/health", tags=["health"])
    async def root_health():
        return {"status": "ok"}

    return app


app = create_app()
