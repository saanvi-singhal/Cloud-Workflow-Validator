"""Format-aware analysis policy (spec 5.3-5.5, approved decision D10).

Generic graph algorithms shouldn't hide format-specific special cases. Every
format-dependent choice is therefore written down here as an explicit,
testable rule:

| format     | order | disconnected components           | reachability root |
|------------|-------|-----------------------------------|-------------------|
| yaml       | yes   | info, non-trivial components only | none              |
| terraform  | yes   | info, non-trivial components only | none              |
| dockerfile | no    | disabled (reachability covers it) | final stage       |

Independent GitHub Actions jobs run in parallel and independent Terraform
resources are normal, so isolated nodes are never reported, and separate
multi-node chains are only ``info``.

With several files, workflows and Dockerfiles are independent of each other
(``files_independent``): each file has its own main component and final
stage. Terraform files form one module, so they are judged as one graph.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.compiler.ir import IRGraph
from app.models import Severity, SourceFormat

RootSelector = Callable[[IRGraph], list[str]]


@dataclass(frozen=True)
class FormatPolicy:
    """What graph analysis means for one format."""

    execution_order_meaningful: bool
    disconnected_severity: Severity | None  # None: rule explicitly disabled
    report_isolated_nodes: bool
    roots: RootSelector | None = None  # None: format has no defined root
    root_description: str = ""
    unreachable_reason: str = ""
    # Multi-file: each file is a separate graph (workflows, Dockerfiles), so
    # connectivity and roots are judged per file. Terraform files form one
    # module and are judged together.
    files_independent: bool = False


def docker_final_stage(ir: IRGraph) -> list[str]:
    """Root for Dockerfiles: the final build stage.

    Contract with the Dockerfile parser: a stage node sets
    ``metadata["is_final_stage"] = True`` and/or ``metadata["stage_index"]``
    (0-based int). If neither is present we return no root, so the
    reachability check is skipped rather than guessed.
    """
    flagged = [n.id for n in ir.nodes if n.metadata.get("is_final_stage") is True]
    if flagged:
        return sorted(flagged)
    indexed = [
        (n.metadata["stage_index"], n.id)
        for n in ir.nodes
        if isinstance(n.metadata.get("stage_index"), int)
    ]
    return [max(indexed)[1]] if indexed else []


POLICIES: dict[SourceFormat, FormatPolicy] = {
    SourceFormat.yaml: FormatPolicy(
        execution_order_meaningful=True,
        disconnected_severity=Severity.info,
        report_isolated_nodes=False,
        files_independent=True,
    ),
    SourceFormat.terraform: FormatPolicy(
        execution_order_meaningful=True,
        disconnected_severity=Severity.info,
        report_isolated_nodes=False,
    ),
    SourceFormat.dockerfile: FormatPolicy(
        execution_order_meaningful=False,
        disconnected_severity=None,
        report_isolated_nodes=False,
        roots=docker_final_stage,
        root_description="the final build stage",
        unreachable_reason=(
            "A default build only builds the stages the target stage needs, "
            "so this stage is skipped unless it is selected with --target."
        ),
        files_independent=True,
    ),
}


def policy_for(fmt: SourceFormat) -> FormatPolicy:
    return POLICIES[fmt]
