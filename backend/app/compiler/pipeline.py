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
   With ``format: "mixed"``, steps 1-5 run once per detected format and
   the results are merged before step 7.
7. **Sort** all findings deterministically, then derive recommendations
   (which refer to diagnostics by their index in the sorted list).

``execution_order`` is ``None`` unless *all* of these hold: the format's
policy says ordering is meaningful, the IR exists, there is no cycle,
dependency analysis is complete, and there are no error diagnostics. An
order computed from a graph known to be wrong or incomplete would be
misleading (spec 5.3).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.analysis.cycles import cycle_findings, detect_cycles
from app.analysis.multifile import analyze_multifile
from app.analysis.reachability import component_findings, reachability_findings
from app.analysis.topological_sort import topological_order
from app.analysis.validation import validate_graph
from app.compiler.adapters import ParseResult, SourceAdapter, get_adapter
from app.compiler.detect import detect_format
from app.compiler.findings import Finding, make_finding
from app.compiler.graph import DependencyGraph
from app.compiler.ir import IRGraph, sort_findings
from app.compiler.policy import policy_for
from app.models import (
    AnalysisResult,
    DiagnosticCode,
    GraphPayload,
    MultiFileSummary,
    Severity,
    SourceFormat,
    SourceLocation,
)
from app.recommendations.engine import generate_recommendations


@dataclass(frozen=True)
class _Analysis:
    """Every pass's findings for one parse, before the result is assembled."""

    findings: list[Finding]
    ir: IRGraph | None
    order: list[str] | None


def _analyze(parse: ParseResult, fmt: SourceFormat) -> _Analysis:
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
    return _Analysis(findings, clean_ir, order)


def _result(
    analysis: _Analysis,
    fmt: SourceFormat,
    file_list: list[str] | None,
    file_formats: dict[str, str] | None = None,
) -> AnalysisResult:
    ordered = sort_findings(analysis.findings)
    diagnostics = [f.diagnostic for f in ordered]

    multifile_summary: MultiFileSummary | None = None
    if file_list is not None:
        multifile_summary = analyze_multifile(analysis.ir, file_list, ordered)
        if file_formats:
            multifile_summary = multifile_summary.model_copy(
                update={"file_formats": file_formats}
            )

    return AnalysisResult(
        valid=not any(d.severity is Severity.error for d in diagnostics),
        format=fmt,
        diagnostics=diagnostics,
        graph=analysis.ir.to_payload() if analysis.ir is not None else GraphPayload(),
        execution_order=analysis.order,
        recommendations=generate_recommendations(ordered, analysis.ir),
        multifile=multifile_summary,
    )


def analyze_ir(
    parse: ParseResult,
    fmt: SourceFormat,
    file_list: list[str] | None = None,
) -> AnalysisResult:
    """Run every analysis pass over a parser's output."""
    return _result(_analyze(parse, fmt), fmt, file_list)


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


def _parse_files(adapter: SourceAdapter, files: list[tuple[str, str]]) -> ParseResult:
    if hasattr(adapter, "parse_files"):
        return adapter.parse_files(files)  # type: ignore[no-any-return]
    if len(files) == 1:
        return adapter.parse(files[0][1], files[0][0])
    combined_source = "\n".join(src for _, src in files)
    return adapter.parse(combined_source, files[0][0])


def compile_files(
    files: list[tuple[str, str]],
    fmt: SourceFormat,
    *,
    adapter: SourceAdapter | None = None,
) -> AnalysisResult:
    """Parse and analyse multiple source files together.

    Extracts cross-file references, detects duplicate variable declarations,
    and analyzes inter-file dependencies. ``fmt=mixed`` detects each file's
    format (see ``compile_mixed``).
    """
    if fmt is SourceFormat.mixed and adapter is None:
        return compile_mixed(files)
    chosen = adapter if adapter is not None else get_adapter(fmt)
    file_list = [filename for filename, _ in files]
    return analyze_ir(_parse_files(chosen, files), fmt, file_list=file_list)


# Analysis order of the groups (the graph output is sorted by node ID).
MIXED_GROUP_ORDER = (SourceFormat.yaml, SourceFormat.dockerfile, SourceFormat.terraform)


def compile_mixed(files: list[tuple[str, str]]) -> AnalysisResult:
    """Analyse files of different formats in one request.

    Each file's format is detected from its name (``detect_format``). Every
    format group goes through its own parser and the full analysis with that
    format's policy, exactly as if it had been sent alone; the results are then
    merged into one graph (node IDs never collide: they start with the format
    prefix) and one sorted diagnostic list. Files of no known format are build
    context for the Dockerfiles; with no Dockerfile, they are reported as not
    analysed.

    ``execution_order`` is ``None``: a workflow's job order, Terraform's apply
    order and Docker stages are different kinds of order, and one list mixing
    them would be misleading.
    """
    detected = {name: detect_format(name, source) for name, source in files}
    groups = {
        fmt: [(n, s) for n, s in files if detected[n] is fmt]
        for fmt in MIXED_GROUP_ORDER
    }
    context = [(n, s) for n, s in files if detected[n] is None]
    findings: list[Finding] = []
    if groups[SourceFormat.dockerfile]:
        groups[SourceFormat.dockerfile] += context
    else:
        findings.extend(
            make_finding(
                DiagnosticCode.UNSUPPORTED_CONSTRUCT,
                Severity.info,
                f"'{name}' was not analysed: it is not a workflow (.yml), "
                "Terraform (.tf) or Dockerfile, and there is no Dockerfile it "
                "could be build context for.",
                SourceLocation(file=name, start_line=1, start_column=1),
            )
            for name, _ in context
        )

    nodes, edges = [], []
    analysed = False
    for fmt in MIXED_GROUP_ORDER:
        if not groups[fmt]:
            continue
        analysis = _analyze(_parse_files(get_adapter(fmt), groups[fmt]), fmt)
        findings.extend(analysis.findings)
        if analysis.ir is not None:
            analysed = True
            nodes.extend(analysis.ir.nodes)
            edges.extend(analysis.ir.edges)

    ir = (
        IRGraph(format=SourceFormat.mixed, nodes=nodes, edges=edges)
        if analysed
        else None
    )
    file_formats = {
        name: (
            fmt.value
            if fmt
            else "build_context"
            if groups[SourceFormat.dockerfile]
            else "unknown"
        )
        for name, fmt in detected.items()
    }
    return _result(
        _Analysis(findings, ir, None),
        SourceFormat.mixed,
        [name for name, _ in files],
        file_formats,
    )
