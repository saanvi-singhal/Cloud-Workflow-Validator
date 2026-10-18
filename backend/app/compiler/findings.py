"""Internal ``Finding``: a public diagnostic plus context for recommendations.

The public ``Diagnostic`` is deliberately compact (spec 6.1). Analysis passes
still know *which* nodes, edges or rule produced it, and the recommendation
engine needs that. A ``Finding`` carries both; only ``finding.diagnostic`` is
ever serialized.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.models import Diagnostic, DiagnosticCode, Severity, SourceLocation

EdgeKey = tuple[str, str, str]  # (source, target, edge type value)


@dataclass(frozen=True)
class Finding:
    """A diagnostic together with internal context that is never serialized."""

    diagnostic: Diagnostic
    rule_id: str | None = None
    node_ids: tuple[str, ...] = ()
    edge_keys: tuple[EdgeKey, ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict, hash=False)

    @property
    def code(self) -> DiagnosticCode:
        return self.diagnostic.code

    @property
    def severity(self) -> Severity:
        return self.diagnostic.severity


def make_finding(
    code: DiagnosticCode,
    severity: Severity,
    message: str,
    location: SourceLocation | None = None,
    *,
    rule_id: str | None = None,
    node_ids: tuple[str, ...] = (),
    edge_keys: tuple[EdgeKey, ...] = (),
    details: Mapping[str, Any] | None = None,
) -> Finding:
    """Convenience constructor so passes don't build two objects by hand."""
    return Finding(
        diagnostic=Diagnostic(
            code=code, severity=severity, message=message, source_location=location
        ),
        rule_id=rule_id,
        node_ids=node_ids,
        edge_keys=edge_keys,
        details=dict(details or {}),
    )
