"""Dockerfile parser adapter.

Uses dockerfile-parse to inspect multi-stage Dockerfiles.
Constructs stage nodes and dependencies between stages:
- Base stage references (FROM <stage> AS ...)
- Multi-stage copy references (COPY --from=<stage> ...)
"""

from __future__ import annotations

import re
from typing import Any

from dockerfile_parse import DockerfileParser

from app.compiler.adapters import ParseResult, register_adapter
from app.compiler.findings import Finding, make_finding
from app.compiler.ir import FORMAT_ID_PREFIX, IRGraph, make_node_id, unique_id
from app.models import (
    DiagnosticCode,
    Edge,
    EdgeType,
    Node,
    NodeType,
    Severity,
    SourceFormat,
    SourceLocation,
)

ID_PREFIX = FORMAT_ID_PREFIX[SourceFormat.dockerfile]

# Regex to match: FROM <image> [AS <stage_name>]
_FROM_PATTERN = re.compile(
    r"^(?:--platform=\S+\s+)?(\S+)(?:\s+as\s+(\S+))?", re.IGNORECASE
)
# Regex to match: --from=<stage_name_or_index>
_COPY_FROM_PATTERN = re.compile(r"--from=(\S+)", re.IGNORECASE)


def _make_loc(
    start_line: int | None, end_line: int | None, filename: str | None
) -> SourceLocation | None:
    if start_line is None:
        return None
    # dockerfile-parse lines are 0-based
    return SourceLocation(
        file=filename,
        start_line=start_line + 1,
        start_column=1,
        end_line=(end_line + 1) if end_line is not None else None,
        end_column=None,
    )


class _StageInfo:
    def __init__(
        self,
        index: int,
        alias: str | None,
        base_image: str,
        node_id: str,
        start_line: int,
        end_line: int,
    ) -> None:
        self.index = index
        self.alias = alias
        self.base_image = base_image
        self.node_id = node_id
        self.start_line = start_line
        self.end_line = end_line


class _DockerfileExtractor:
    def __init__(self, filename: str | None) -> None:
        self.filename = filename
        self.findings: list[Finding] = []
        self.complete = True
        self.nodes: list[Node] = []
        self.edges: list[Edge] = []
        self.taken_ids: set[str] = set()

        # Maps stage alias (lowercased) -> _StageInfo
        self.alias_to_stage: dict[str, _StageInfo] = {}
        # Maps 0-based index -> _StageInfo
        self.index_to_stage: dict[int, _StageInfo] = {}
        self.stages: list[_StageInfo] = []

    def extract(self, structure: list[dict[str, Any]]) -> IRGraph:
        # Pass 1: Collect and declare all stages (FROM instructions)
        stage_idx = 0
        from_instructions: list[dict[str, Any]] = []

        for entry in structure:
            instruction = entry.get("instruction", "").upper()
            if instruction == "FROM":
                from_instructions.append(entry)

        total_stages = len(from_instructions)
        for entry in from_instructions:
            val = entry.get("value", "").strip()
            match = _FROM_PATTERN.match(val)
            start_line = entry.get("startline", 0)
            end_line = entry.get("endline", start_line)
            loc = _make_loc(start_line, end_line, self.filename)

            if not match:
                self.findings.append(
                    make_finding(
                        DiagnosticCode.DOCKERFILE_SYNTAX_ERROR,
                        Severity.error,
                        f"Malformed FROM instruction: 'FROM {val}'.",
                        loc,
                    )
                )
                continue

            base_image = match.group(1)
            raw_alias = match.group(2)
            is_final_stage = stage_idx == total_stages - 1

            # Determine stage label and base ID
            if raw_alias:
                label = raw_alias
                base_id = make_node_id(ID_PREFIX, "stage", raw_alias)
            else:
                label = f"stage-{stage_idx}"
                base_id = make_node_id(ID_PREFIX, "stage", f"stage_{stage_idx}")

            node_id = unique_id(base_id, self.taken_ids)

            if raw_alias:
                alias_lower = raw_alias.lower()
                if alias_lower in self.alias_to_stage:
                    self.findings.append(
                        make_finding(
                            DiagnosticCode.DUPLICATE_NODE_ID,
                            Severity.error,
                            f"Duplicate build stage alias '{raw_alias}'.",
                            loc,
                            node_ids=(self.alias_to_stage[alias_lower].node_id, node_id),
                            details={"alias": raw_alias},
                        )
                    )

            metadata: dict[str, Any] = {
                "stage_index": stage_idx,
                "base_image": base_image,
                "is_final_stage": is_final_stage,
            }
            if raw_alias:
                metadata["alias"] = raw_alias

            node = Node(
                id=node_id,
                label=label,
                type=NodeType.stage,
                source_location=loc,
                metadata=metadata,
            )
            self.nodes.append(node)

            stage_info = _StageInfo(
                index=stage_idx,
                alias=raw_alias,
                base_image=base_image,
                node_id=node_id,
                start_line=start_line,
                end_line=end_line,
            )
            self.stages.append(stage_info)
            self.index_to_stage[stage_idx] = stage_info
            if raw_alias and alias_lower not in self.alias_to_stage:
                self.alias_to_stage[alias_lower] = stage_info

            stage_idx += 1

        # Pass 2: Connect dependencies
        # 2a: FROM <stage_name> referencing previous stage
        for stage in self.stages:
            base_lower = stage.base_image.lower()
            if base_lower in self.alias_to_stage:
                dep_stage = self.alias_to_stage[base_lower]
                loc = _make_loc(stage.start_line, stage.end_line, self.filename)
                self.edges.append(
                    Edge(
                        source=dep_stage.node_id,
                        target=stage.node_id,
                        type=EdgeType.docker_stage_base,
                        label=f"FROM {dep_stage.alias or dep_stage.index}",
                        source_location=loc,
                    )
                )

        # 2b: COPY --from=<stage_or_index>
        curr_stage_idx = -1
        for entry in structure:
            instruction = entry.get("instruction", "").upper()
            if instruction == "FROM":
                curr_stage_idx += 1
                continue

            if curr_stage_idx < 0 or curr_stage_idx >= len(self.stages):
                continue

            current_stage = self.stages[curr_stage_idx]
            val = entry.get("value", "")
            start_line = entry.get("startline")
            end_line = entry.get("endline")
            loc = _make_loc(start_line, end_line, self.filename)

            if instruction == "COPY":
                from_matches = _COPY_FROM_PATTERN.findall(val)
                for from_target in from_matches:
                    from_clean = from_target.strip("\"'")
                    dep_stage: _StageInfo | None = None

                    # Check numeric index
                    if from_clean.isdigit():
                        idx = int(from_clean)
                        if idx in self.index_to_stage and idx < current_stage.index:
                            dep_stage = self.index_to_stage[idx]
                        else:
                            self.findings.append(
                                make_finding(
                                    DiagnosticCode.UNRESOLVED_DEPENDENCY,
                                    Severity.error,
                                    f"COPY --from references invalid stage index '{from_clean}'.",
                                    loc,
                                    node_ids=(current_stage.node_id,),
                                    details={"from": from_clean},
                                )
                            )
                            continue
                    else:
                        target_lower = from_clean.lower()
                        if target_lower in self.alias_to_stage:
                            dep_stage = self.alias_to_stage[target_lower]
                        else:
                            # If it looks like an external image (e.g. contains / or :), Docker allows --from=image:tag
                            if "/" in from_clean or ":" in from_clean:
                                # External image reference in COPY --from is valid in BuildKit
                                continue
                            else:
                                # Unresolved stage reference!
                                # CRUCIAL RULE: Do NOT create an edge to a non-existent node.
                                known = sorted(self.alias_to_stage.keys())
                                self.findings.append(
                                    make_finding(
                                        DiagnosticCode.UNRESOLVED_DEPENDENCY,
                                        Severity.error,
                                        f"COPY --from references unknown stage or image '{from_clean}'.",
                                        loc,
                                        node_ids=(current_stage.node_id,),
                                        details={
                                            "from": from_clean,
                                            "address": from_clean,
                                            "known_addresses": known,
                                        },
                                    )
                                )
                                continue

                    if dep_stage is not None:
                        self.edges.append(
                            Edge(
                                source=dep_stage.node_id,
                                target=current_stage.node_id,
                                type=EdgeType.docker_stage_base,
                                label=f"COPY --from={from_clean}",
                                source_location=loc,
                            )
                        )

        return IRGraph(
            format=SourceFormat.dockerfile,
            nodes=self.nodes,
            edges=self.edges,
        )


class DockerfileAdapter:
    """SourceAdapter implementation for Dockerfiles."""

    format = SourceFormat.dockerfile

    def parse(self, source: str, filename: str | None) -> ParseResult:
        dfp = DockerfileParser()
        dfp.content = source

        try:
            structure = dfp.structure
        except Exception as exc:
            finding = make_finding(
                DiagnosticCode.DOCKERFILE_SYNTAX_ERROR,
                Severity.error,
                f"Dockerfile syntax error: {exc}",
                SourceLocation(file=filename, start_line=1, start_column=1),
            )
            return ParseResult(ir=None, findings=[finding])

        extractor = _DockerfileExtractor(filename)
        ir = extractor.extract(structure)

        return ParseResult(
            ir=ir,
            findings=extractor.findings,
            dependency_analysis_complete=extractor.complete,
        )


ADAPTER = DockerfileAdapter()
