"""The complete analysis result (spec 7.3 plus multi-file summary).

The FastAPI layer serializes this with ``model_dump(mode="json")``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.common import SourceFormat, SourceLocation
from app.models.diagnostics import Diagnostic
from app.models.graph import GraphPayload
from app.models.recommendations import Recommendation


class InterFileDependency(BaseModel):
    """A dependency from a node or file in one file to a node in another."""

    model_config = ConfigDict(extra="forbid")

    source_node: str
    target_node: str
    source_file: str
    target_file: str
    edge_type: str
    symbol: str | None = None


class VariableOccurrence(BaseModel):
    """Tracking of a variable declaration and its usage occurrences across files."""

    model_config = ConfigDict(extra="forbid")

    name: str
    declared_files: list[str] = Field(default_factory=list)
    referenced_files: list[str] = Field(default_factory=list)
    total_occurrences: int = 0
    is_duplicate: bool = False
    is_unused: bool = False
    locations: list[SourceLocation] = Field(default_factory=list)


class MultiFileSummary(BaseModel):
    """Aggregate summary of cross-file analysis and variable occurrences."""

    model_config = ConfigDict(extra="forbid")

    files: list[str] = Field(default_factory=list)
    # format: "mixed" only: what each file was analysed as ("yaml",
    # "dockerfile", "terraform", "build_context" or "unknown").
    file_formats: dict[str, str] = Field(default_factory=dict)
    interfile_dependencies: list[InterFileDependency] = Field(default_factory=list)
    variable_occurrences: list[VariableOccurrence] = Field(default_factory=list)
    duplicate_variables: list[str] = Field(default_factory=list)
    unused_variables: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    """Output of the compiler pipeline."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    format: SourceFormat
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    graph: GraphPayload = Field(default_factory=GraphPayload)
    execution_order: list[str] | None = None
    recommendations: list[Recommendation] = Field(default_factory=list)
    multifile: MultiFileSummary | None = None
