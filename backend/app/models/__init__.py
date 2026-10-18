"""Public, JSON-serializable contract models shared by all backend modules."""

from app.models.analysis import AnalysisResult
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
    "Node",
    "NodeType",
    "ProposedChange",
    "Recommendation",
    "Severity",
    "SourceFormat",
    "SourceLocation",
]
