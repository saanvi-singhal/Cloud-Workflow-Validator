"""Recommendation model (spec 6.2, 7.3, 17).

Recommendations are produced by deterministic rules. They only *describe* a
change; nothing in this project applies a change to user source.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.models.common import SourceLocation
from app.models.diagnostics import DiagnosticCode


class FixKind(str, Enum):
    """Whether the suggested change is mechanically safe or needs human judgment."""

    deterministic = "deterministic"
    judgment = "judgment"


class ProposedChange(BaseModel):
    """A textual preview of a suggested change. Never applied automatically."""

    model_config = ConfigDict(extra="forbid")

    description: str
    preview: str | None = None  # unified-diff-style snippet; omitted if unsafe
    source_location: SourceLocation | None = None
    # A complete unified diff against the submitted file (git apply / patch
    # -p1), only when the exact edit is certain. The user applies it; this
    # project never does.
    patch: str | None = None


class Recommendation(BaseModel):
    """A structured, deterministic recommendation linked to one diagnostic."""

    model_config = ConfigDict(extra="forbid")

    id: str  # stable: "<rule_id>:<diagnostic_index>"
    rule_id: str
    title: str
    explanation: str
    diagnostic_code: DiagnosticCode
    diagnostic_index: int = Field(ge=0)  # index into the sorted diagnostics list
    fix_kind: FixKind
    proposed_change: ProposedChange | None = None
    source_location: SourceLocation | None = None
    related_node_ids: list[str] = Field(default_factory=list)
