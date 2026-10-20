"""FastAPI router implementation for validation endpoints.

Exposes:
- GET  /api/v1/health   -> Status check
- POST /api/v1/validate -> Source static analysis, returning AnalysisResult JSON
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.compiler.adapters import AdapterNotAvailableError
from app.compiler.pipeline import compile_source
from app.models import SourceFormat

router = APIRouter(prefix="/api/v1")

# Max payload source length in bytes (default: 512 KB, configurable via environment)
DEFAULT_MAX_SOURCE_BYTES = 512 * 1024
MAX_SOURCE_BYTES = int(os.getenv("MAX_SOURCE_BYTES", str(DEFAULT_MAX_SOURCE_BYTES)))


class ValidationRequest(BaseModel):
    """Payload for POST /api/v1/validate."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(description="Source text to statically analyse.")
    format: SourceFormat = Field(
        description="Source format: 'yaml', 'dockerfile', or 'terraform'."
    )
    filename: str | None = Field(
        default=None,
        description="Optional display name for diagnostics (e.g. 'main.tf', 'ci.yml').",
    )


class HealthResponse(BaseModel):
    """Response for GET /api/v1/health."""

    status: str = "ok"
    version: str = "0.1.0"


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Return application health status."""
    return HealthResponse(status="ok", version="0.1.0")


@router.post("/validate")
async def validate_endpoint(request: ValidationRequest) -> dict[str, Any]:
    """Parse and statically analyse one source configuration.

    Calls the compiler pipeline and returns the serialized AnalysisResult.
    Catches source size limit (413) and unknown format errors (422/400).
    """
    # Enforce application-level source size limit
    source_bytes = len(request.source.encode("utf-8"))
    if source_bytes > MAX_SOURCE_BYTES:
        raise HTTPException(
            # 413 Content Too Large; the constant's name differs across
            # Starlette versions, so use the number.
            status_code=413,
            detail={
                "code": "SOURCE_TOO_LARGE",
                "message": (
                    f"Source payload size ({source_bytes} bytes) exceeds "
                    f"the maximum allowed limit of {MAX_SOURCE_BYTES} bytes."
                ),
            },
        )

    try:
        result = compile_source(
            source=request.source,
            fmt=request.format,
            filename=request.filename,
        )
        return result.model_dump(mode="json")
    except AdapterNotAvailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "UNSUPPORTED_FORMAT", "message": str(exc)},
        ) from exc
