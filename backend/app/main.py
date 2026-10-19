"""FastAPI application entrypoint for Cloud-Workflow-Validator."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_v1_router


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

    # Allow cross-origin requests from frontend (React/Vite)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_v1_router)

    # Optional root alias for health check
    @app.get("/health", tags=["health"])
    async def root_health():
        return {"status": "ok"}

    return app


app = create_app()
