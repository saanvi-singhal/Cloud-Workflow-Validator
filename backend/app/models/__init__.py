"""Public, JSON-serializable contract models shared by all backend modules."""

from app.models.analysis import (
    AnalysisResult,
    InterFileDependency,
    MultiFileSummary,
    VariableOccurrence,
)
from app.models.common import EdgeType, NodeType, Severity, SourceFormat, SourceLocation
from app.models.diagnostics import Diagnostic, DiagnosticCode
from app.models.graph import Edge, GraphPayload, Node
from app.models.recommendations import FixKind, ProposedChange, Recommendation

__all__ = [
    "AnalysisResult",
    "Diagnostic",
    "DiagnosticCode",
    "Edge",
    "EdgeType",
    "FixKind",
    "GraphPayload",
    "InterFileDependency",
    "MultiFileSummary",
    "Node",
    "NodeType",
    "ProposedChange",
    "Recommendation",
    "Severity",
    "SourceFormat",
    "SourceLocation",
    "VariableOccurrence",
]
