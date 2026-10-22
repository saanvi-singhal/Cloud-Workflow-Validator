"""Recommendation engine: maps findings to deterministic recommendations.

The engine walks the findings **in their final sorted order**, so position
``i`` is exactly ``diagnostics[i]`` in the response. Each recommendation
stores that index (``diagnostic_index``) plus the code, which links it to one
diagnostic instance. Rules live in ``catalog.py``; a code without a rule
simply gets no recommendation.

When the submitted source text is passed in, recommendations whose exact edit
is known also get a ``patch`` (``patches.py``): a unified diff the user can
apply themselves. Nothing is ever applied here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.compiler.findings import Finding
from app.compiler.ir import IRGraph
from app.models import NodeType, ProposedChange, Recommendation
from app.recommendations.catalog import CATALOG, RecommendationContext
from app.recommendations.patches import PatchContext, patch_for


def generate_recommendations(
    findings: Sequence[Finding],
    ir: IRGraph | None,
    sources: Mapping[str | None, str] | None = None,
    default_filename: str = "source",
) -> list[Recommendation]:
    """Return recommendations for ``findings`` (given in final sorted order).

    ``sources`` maps each file name (``None`` for an unnamed single file) to
    its text, for patches; ``default_filename`` names an unnamed file in them.
    """
    context = RecommendationContext(
        nodes=ir.node_map() if ir is not None else {},
        edges={e.key: e for e in ir.edges} if ir is not None else {},
    )
    patch_context = PatchContext(
        edges=context.edges,
        known_names={
            str(n.metadata.get("variable_name") or n.label.removeprefix("var."))
            for n in context.nodes.values()
            if n.type is NodeType.variable
        },
    )
    recommendations: list[Recommendation] = []
    for index, finding in enumerate(findings):
        rule = CATALOG.get(finding.code)
        if rule is None:
            continue
        recommendation = rule(finding, index, context)
        if recommendation is None:
            continue
        patch = (
            patch_for(finding, recommendation, sources, default_filename, patch_context)
            if sources
            else None
        )
        if patch is not None:
            change = recommendation.proposed_change or ProposedChange(
                description="Apply the patch.",
                source_location=finding.diagnostic.source_location,
            )
            recommendation = recommendation.model_copy(
                update={"proposed_change": change.model_copy(update={"patch": patch})}
            )
        recommendations.append(recommendation)
    return recommendations
