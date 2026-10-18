"""The complete analysis result (exactly the fields of spec 7.3).

The FastAPI layer serializes this with ``model_dump(mode="json")``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.common import SourceFormat
from app.models.diagnostics import Diagnostic
from app.models.graph import GraphPayload
from app.models.recommendations import Recommendation


class AnalysisResult(BaseModel):
    """Output of the compiler pipeline for one source file."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    format: SourceFormat
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    graph: GraphPayload = Field(default_factory=GraphPayload)
    execution_order: list[str] | None = None
    recommendations: list[Recommendation] = Field(default_factory=list)
