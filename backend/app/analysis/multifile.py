"""Multi-file cross-boundary analysis and variable occurrence tracking.

Analyzes dependencies crossing file boundaries and aggregates variable
occurrences across all files in a multi-file project.
"""

from __future__ import annotations

from app.compiler.findings import Finding
from app.compiler.ir import IRGraph
from app.models import (
    DiagnosticCode,
    InterFileDependency,
    MultiFileSummary,
    NodeType,
    SourceLocation,
    VariableOccurrence,
)


def analyze_multifile(
    ir: IRGraph | None,
    file_list: list[str],
    findings: list[Finding] | None = None,
) -> MultiFileSummary:
    """Derive cross-file dependencies and variable occurrence metrics."""
    findings = findings or []
    node_map = ir.node_map() if ir is not None else {}

    # 1. Inter-file dependencies
    interfile_deps: list[InterFileDependency] = []
    seen_dep_keys: set[tuple[str, str, str]] = set()

    if ir is not None:
        for edge in ir.edges:
            src_node = node_map.get(edge.source)
            tgt_node = node_map.get(edge.target)
            if not src_node or not tgt_node:
                continue

            src_file = (
                src_node.source_location.file
                if src_node.source_location
                else src_node.metadata.get("file")
            )
            tgt_file = (
                tgt_node.source_location.file
                if tgt_node.source_location
                else tgt_node.metadata.get("file")
            )

            if src_file and tgt_file and str(src_file) != str(tgt_file):
                key = (edge.source, edge.target, edge.type.value)
                if key not in seen_dep_keys:
                    seen_dep_keys.add(key)
                    interfile_deps.append(
                        InterFileDependency(
                            source_node=edge.source,
                            target_node=edge.target,
                            source_file=str(src_file),
                            target_file=str(tgt_file),
                            edge_type=edge.type.value,
                            symbol=src_node.label,
                        )
                    )

    # 2. Variable occurrences
    # Map variable_name -> dict of info
    var_dict: dict[str, dict] = {}

    # Check DUPLICATE_NODE_ID findings for duplicates across files
    duplicate_addresses: set[str] = set()
    for finding in findings:
        if finding.code == DiagnosticCode.DUPLICATE_NODE_ID:
            addr = str(finding.details.get("address", ""))
            if addr.startswith("var."):
                duplicate_addresses.add(addr.removeprefix("var."))

    if ir is not None:
        for node in ir.nodes:
            is_var = (
                node.type == NodeType.variable
                or node.metadata.get("block_type") == "variable"
                or node.id.startswith("tf:variable:")
            )
            if not is_var:
                continue

            raw_name = node.metadata.get("variable_name")
            name = str(raw_name) if raw_name else node.label.removeprefix("var.")
            file_name = (
                node.source_location.file
                if node.source_location
                else node.metadata.get("file")
            )

            if name not in var_dict:
                var_dict[name] = {
                    "declared_files": set(),
                    "referenced_files": set(),
                    "locations": [],
                    "declaration_count": 0,
                    "reference_count": 0,
                    "is_duplicate": name in duplicate_addresses,
                }

            if file_name:
                var_dict[name]["declared_files"].add(str(file_name))
            var_dict[name]["declaration_count"] += 1
            if node.source_location:
                var_dict[name]["locations"].append(node.source_location)

        # Track references to variables via edges
        for edge in ir.edges:
            src_node = node_map.get(edge.source)
            tgt_node = node_map.get(edge.target)
            if not src_node or not tgt_node:
                continue

            is_var = (
                src_node.type == NodeType.variable
                or src_node.metadata.get("block_type") == "variable"
                or src_node.id.startswith("tf:variable:")
            )
            if not is_var:
                continue

            raw_name = src_node.metadata.get("variable_name")
            name = str(raw_name) if raw_name else src_node.label.removeprefix("var.")
            if name not in var_dict:
                continue

            tgt_file = (
                tgt_node.source_location.file
                if tgt_node.source_location
                else tgt_node.metadata.get("file")
            )
            if tgt_file:
                var_dict[name]["referenced_files"].add(str(tgt_file))

            # Count reference occurrences
            ref_entries = edge.metadata.get("references")
            if isinstance(ref_entries, list) and ref_entries:
                var_dict[name]["reference_count"] += len(ref_entries)
                for entry in ref_entries:
                    if isinstance(entry, dict) and "location" in entry and entry["location"]:
                        loc_dict = entry["location"]
                        var_dict[name]["locations"].append(SourceLocation(**loc_dict))
            else:
                var_dict[name]["reference_count"] += 1
                if edge.source_location:
                    var_dict[name]["locations"].append(edge.source_location)

    # Check for unresolved variable references
    for finding in findings:
        if finding.code == DiagnosticCode.UNRESOLVED_DEPENDENCY:
            addr = str(finding.details.get("address", ""))
            if addr.startswith("var."):
                name = addr.removeprefix("var.")
                if name not in var_dict:
                    var_dict[name] = {
                        "declared_files": set(),
                        "referenced_files": set(),
                        "locations": [],
                        "declaration_count": 0,
                        "reference_count": 0,
                        "is_duplicate": False,
                    }
                file_name = (
                    finding.source_location.file
                    if finding.source_location
                    else None
                )
                if file_name:
                    var_dict[name]["referenced_files"].add(str(file_name))
                var_dict[name]["reference_count"] += 1
                if finding.source_location:
                    var_dict[name]["locations"].append(finding.source_location)

    # Assemble VariableOccurrence records
    variable_occurrences: list[VariableOccurrence] = []
    duplicate_variables: list[str] = []
    unused_variables: list[str] = []

    for name in sorted(var_dict.keys()):
        data = var_dict[name]
        declared = sorted(data["declared_files"])
        referenced = sorted(data["referenced_files"])
        is_dup = data["is_duplicate"] or len(declared) > 1 or data["declaration_count"] > 1
        is_unused = len(declared) > 0 and len(referenced) == 0

        if is_dup:
            duplicate_variables.append(name)
        if is_unused:
            unused_variables.append(name)

        variable_occurrences.append(
            VariableOccurrence(
                name=name,
                declared_files=declared,
                referenced_files=referenced,
                total_occurrences=data["declaration_count"] + data["reference_count"],
                is_duplicate=is_dup,
                is_unused=is_unused,
                locations=data["locations"],
            )
        )

    return MultiFileSummary(
        files=sorted(file_list),
        interfile_dependencies=interfile_deps,
        variable_occurrences=variable_occurrences,
        duplicate_variables=sorted(duplicate_variables),
        unused_variables=sorted(unused_variables),
    )
