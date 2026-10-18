"""Diagnostic codes and the compact diagnostic model (spec 6.1).

Tests must assert on ``code`` (stable), not on ``message`` prose.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.models.common import Severity, SourceLocation


class DiagnosticCode(str, Enum):
    """Stable diagnostic codes. See docs/compiler-core.md for meanings."""

    YAML_SYNTAX_ERROR = "YAML_SYNTAX_ERROR"
    DOCKERFILE_SYNTAX_ERROR = "DOCKERFILE_SYNTAX_ERROR"
    TERRAFORM_SYNTAX_ERROR = "TERRAFORM_SYNTAX_ERROR"
    DUPLICATE_NODE_ID = "DUPLICATE_NODE_ID"
    UNRESOLVED_DEPENDENCY = "UNRESOLVED_DEPENDENCY"
    DEPENDENCY_CYCLE = "DEPENDENCY_CYCLE"
    DISCONNECTED_COMPONENT = "DISCONNECTED_COMPONENT"
    UNSUPPORTED_CONSTRUCT = "UNSUPPORTED_CONSTRUCT"
    SOURCE_TOO_LARGE = "SOURCE_TOO_LARGE"
    SECURITY_RULE_VIOLATION = "SECURITY_RULE_VIOLATION"
    # Added by approved decision D2:
    INVALID_GRAPH = "INVALID_GRAPH"  # internal IR inconsistency (a parser bug)
    UNREACHABLE_NODE = "UNREACHABLE_NODE"  # e.g. Docker stage unused by final stage


class Diagnostic(BaseModel):
    """A single analysis finding as exposed through the API."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: DiagnosticCode
    severity: Severity
    message: str = Field(min_length=1)
    source_location: SourceLocation | None = None
