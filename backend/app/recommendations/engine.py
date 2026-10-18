"""Recommendation engine: maps findings to deterministic recommendations.

The engine walks the findings **in their final sorted order**, so position
``i`` is exactly ``diagnostics[i]`` in the response. Each recommendation
stores that index (``diagnostic_index``) plus the code, which links it to one
diagnostic instance. Rules live in ``catalog.py``; a code without a rule
simply gets no recommendation.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.compiler.findings import Finding
from app.compiler.ir import IRGraph
from app.models import Recommendation
from app.recommendations.catalog import CATALOG, RecommendationContext


def generate_recommendations(
    findings: Sequence[Finding], ir: IRGraph | None
) -> list[Recommendation]:
    """Return recommendations for ``findings`` (given in final sorted order)."""
    context = RecommendationContext(
        nodes=ir.node_map() if ir is not None else {},
        edges={e.key: e for e in ir.edges} if ir is not None else {},
    )
    recommendations: list[Recommendation] = []
    for index, finding in enumerate(findings):
        rule = CATALOG.get(finding.code)
        if rule is None:
            continue
        recommendation = rule(finding, index, context)
        if recommendation is not None:
            recommendations.append(recommendation)
    return recommendations
