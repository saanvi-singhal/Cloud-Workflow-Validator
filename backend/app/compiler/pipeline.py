"""The compiler pipeline: source -> IR -> validation -> analysis -> result.

This is the single entry point the API layer calls::

    result = compile_source(request.source, request.format, request.filename)
    return result.model_dump(mode="json")

Or for multi-file analysis::

    files = [(f.filename, f.content) for f in request.files]
    result = compile_files(files, request.format)
    return result.model_dump(mode="json")

Stages, in order:

1. **Parse** (format adapter): IR plus parser findings.
2. **Validate** the IR (unique ids, edge endpoints, edge types).
3. **Cycles**: Tarjan SCC + DFS path reconstruction.
4. **Order**: Kahn's topological sort, only when meaningful (see below).
5. **Connectivity**: components and reachability, as the format policy says.
6. **Cross-file & Variables**: inter-file dependency & variable occurrence tracking.
7. **Sort** all findings deterministically, then derive recommendations
   (which refer to diagnostics by their index in the sorted list).

``execution_order`` is ``None`` unless *all* of these hold: the format's
policy says ordering is meaningful, the IR exists, there is no cycle,
dependency analysis is complete, and there are no error diagnostics. An
order computed from a graph known to be wrong or incomplete would be
misleading (spec 5.3).
"""

from __future__ import annotations

from app.analysis.cycles import cycle_findings, detect_cycles
from app.analysis.multifile import analyze_multifile
from app.analysis.reachability import component_findings, reachability_findings
from app.analysis.topological_sort import topological_order
from app.analysis.validation import validate_graph
from app.compiler.adapters import ParseResult, SourceAdapter, get_adapter
from app.compiler.findings import Finding
from app.compiler.graph import DependencyGraph
from app.compiler.ir import IRGraph, sort_findings
from app.compiler.policy import policy_for
from app.models import (
    AnalysisResult,
    GraphPayload,
    MultiFileSummary,
    Severity,
    SourceFormat,
)
from app.recommendations.engine import generate_recommendations


def analyze_ir(
    parse: ParseResult,
    fmt: SourceFormat,
    file_list: list[str] | None = None,
) -> AnalysisResult:
    """Run every analysis pass over a parser's output."""
    findings: list[Finding] = list(parse.findings)
    clean_ir: IRGraph | None = None
    order: list[str] | None = None

    if parse.ir is not None:
        if parse.ir.format != fmt:
            raise ValueError(
                f"adapter returned '{parse.ir.format.value}' IR for '{fmt.value}'"
            )
        policy = policy_for(fmt)
        clean_ir, integrity = validate_graph(parse.ir)
        findings.extend(integrity)

        graph = DependencyGraph.from_ir(clean_ir)
        cycles = detect_cycles(graph)
        findings.extend(cycle_findings(cycles, clean_ir, graph))
        findings.extend(component_findings(graph, clean_ir, policy))
        findings.extend(reachability_findings(graph, clean_ir, policy))

        has_errors = any(f.severity is Severity.error for f in findings)
        if (
            policy.execution_order_meaningful
            and not cycles.has_cycles
            and parse.dependency_analysis_complete
            and not has_errors
        ):
            order = topological_order(graph)

    ordered = sort_findings(findings)
    diagnostics = [f.diagnostic for f in ordered]

    multifile_summary: MultiFileSummary | None = None
    if file_list is not None:
        multifile_summary = analyze_multifile(clean_ir, file_list, ordered)

    return AnalysisResult(
        valid=not any(d.severity is Severity.error for d in diagnostics),
        format=fmt,
        diagnostics=diagnostics,
        graph=clean_ir.to_payload() if clean_ir is not None else GraphPayload(),
        execution_order=order,
        recommendations=generate_recommendations(ordered, clean_ir),
        multifile=multifile_summary,
    )


def compile_source(
    source: str,
    fmt: SourceFormat,
    filename: str | None = None,
    *,
    adapter: SourceAdapter | None = None,
) -> AnalysisResult:
    """Parse and analyse one source file. Static analysis only; nothing is run.

    ``filename`` is only a display name for diagnostics; it is never opened.
    Raises ``AdapterNotAvailableError`` if no parser exists for ``fmt``.
    """
    chosen = adapter if adapter is not None else get_adapter(fmt)
    return analyze_ir(chosen.parse(source, filename), fmt)


def compile_files(
    files: list[tuple[str, str]],
    fmt: SourceFormat,
    *,
    adapter: SourceAdapter | None = None,
) -> AnalysisResult:
    """Parse and analyse multiple source files together.

    Extracts cross-file references, detects duplicate variable declarations,
    and analyzes inter-file dependencies.
    """
    chosen = adapter if adapter is not None else get_adapter(fmt)
    file_list = [filename for filename, _ in files]
    if hasattr(chosen, "parse_files"):
        parse_result = chosen.parse_files(files)  # type: ignore[no-any-return]
    elif len(files) == 1:
        parse_result = chosen.parse(files[0][1], files[0][0])
    else:
        combined_source = "\n".join(src for _, src in files)
        parse_result = chosen.parse(combined_source, files[0][0])
    return analyze_ir(parse_result, fmt, file_list=file_list)
