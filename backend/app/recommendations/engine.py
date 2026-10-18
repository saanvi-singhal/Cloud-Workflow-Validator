"""Recommendation engine: maps findings to deterministic recommendations."""

from __future__ import annotations

from collections.abc import Sequence

from app.compiler.findings import Finding
from app.compiler.ir import IRGraph
from app.models import Recommendation


def generate_recommendations(
    findings: Sequence[Finding], ir: IRGraph | None
) -> list[Recommendation]:
    """Return recommendations for ``findings`` (given in final sorted order)."""
    return []
