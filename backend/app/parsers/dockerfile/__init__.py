"""Dockerfile parser adapter.

Uses dockerfile-parse to inspect multi-stage Dockerfiles.
Constructs stage nodes and dependencies between stages:
- Base stage references (FROM <stage> AS ...)
- Multi-stage copy references (COPY --from=<stage> ...)
"""

from __future__ import annotations

import difflib
import io
import re
from typing import Any

from dockerfile_parse import DockerfileParser

from app.compiler.adapters import ParseResult
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
from app.rules.dockerfile_rules import DockerInstruction, run_dockerfile_rules

ID_PREFIX = FORMAT_ID_PREFIX[SourceFormat.dockerfile]

# Regex to match: FROM <image> [AS <stage_name>]
_FROM_PATTERN = re.compile(
    r"^(?:--platform=\S+\s+)?(\S+)(?:\s+as\s+(\S+))?", re.IGNORECASE
)
# Regex to match: --from=<stage_name_or_index>
_COPY_FROM_PATTERN = re.compile(r"--from=(\S+)", re.IGNORECASE)

# Instructions Docker accepts (https://docs.docker.com/reference/dockerfile/).
# dockerfile-parse accepts any word, so unknown ones are reported here.
KNOWN_INSTRUCTIONS = frozenset(
    {
        "ADD",
        "ARG",
        "CMD",
        "COPY",
        "ENTRYPOINT",
        "ENV",
        "EXPOSE",
        "FROM",
        "HEALTHCHECK",
        "LABEL",
        "MAINTAINER",
        "ONBUILD",
        "RUN",
        "SHELL",
        "STOPSIGNAL",
        "USER",
        "VOLUME",
        "WORKDIR",
    }
)


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


def _healthcheck_problem(value: str) -> str | None:
    """HEALTHCHECK [--options] CMD <command> | HEALTHCHECK NONE."""
    words = [w for w in value.split() if not w.startswith("--")]
    if not words:
        return "HEALTHCHECK needs CMD <command> or NONE."
    kind = words[0].upper()
    if kind == "NONE":
        return None if len(words) == 1 else "HEALTHCHECK NONE takes no command."
    if kind != "CMD":
        return (
            f"HEALTHCHECK needs the CMD keyword before the command "
            f"(found '{words[0]}'): HEALTHCHECK [options] CMD <command>."
        )
    if len(words) == 1:
        return "HEALTHCHECK CMD needs a command."
    return None


def _onbuild_problem(value: str) -> str | None:
    """ONBUILD <instruction>, where some instructions are not allowed."""
    words = value.split()
    if not words:
        return "ONBUILD needs an instruction to run later."
    trigger = words[0].upper()
    if trigger == "ONBUILD":
        return "ONBUILD ONBUILD is not allowed: ONBUILD triggers cannot be chained."
    if trigger in ("FROM", "MAINTAINER"):
        return f"ONBUILD {trigger} is not allowed."
    if trigger not in KNOWN_INSTRUCTIONS:
        return f"ONBUILD runs an unknown instruction '{words[0]}'."
    return None


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

    def _keyword_location(self, entry: dict[str, Any]) -> SourceLocation | None:
        """Locate the instruction keyword itself, e.g. `START` on its line."""
        start_line = entry.get("startline")
        if start_line is None:
            return None
        content = entry.get("content", "")
        stripped = content.lstrip()
        column = len(content) - len(stripped) + 1
        keyword = stripped.split(None, 1)[0] if stripped.strip() else ""
        return SourceLocation(
            file=self.filename,
            start_line=start_line + 1,
            start_column=column,
            end_line=start_line + 1,
            end_column=column + len(keyword),
        )

    def _check_instructions(self, structure: list[dict[str, Any]]) -> None:
        """Report what Docker itself rejects before building any stage.

        - an unknown instruction keyword;
        - an instruction other than ARG before the first FROM;
        - a file with no FROM at all (including an empty file). Then only that
          is reported, not every instruction as "before FROM";
        - a HEALTHCHECK without CMD or NONE, and ONBUILD with a trigger
          Docker forbids (ONBUILD, FROM, MAINTAINER) or does not know.
        """
        instructions = [e for e in structure if e.get("instruction") != "COMMENT"]
        seen_from = False
        before_from: list[Finding] = []
        for entry in instructions:
            keyword = entry.get("instruction", "").upper()
            if keyword not in KNOWN_INSTRUCTIONS:
                self.findings.append(
                    make_finding(
                        DiagnosticCode.DOCKERFILE_SYNTAX_ERROR,
                        Severity.error,
                        f"Unknown instruction '{entry.get('instruction', '')}'. "
                        "Docker will refuse to build this file.",
                        self._keyword_location(entry),
                    )
                )
            elif keyword == "FROM":
                seen_from = True
            elif not seen_from and keyword != "ARG":
                before_from.append(
                    make_finding(
                        DiagnosticCode.DOCKERFILE_SYNTAX_ERROR,
                        Severity.error,
                        f"'{keyword}' appears before the first FROM. Only ARG "
                        "may come before FROM.",
                        self._keyword_location(entry),
                    )
                )

        for entry in instructions:
            keyword = entry.get("instruction", "").upper()
            problem = None
            if keyword == "HEALTHCHECK":
                problem = _healthcheck_problem(entry.get("value", ""))
            elif keyword == "ONBUILD":
                problem = _onbuild_problem(entry.get("value", ""))
            if problem:
                self.findings.append(
                    make_finding(
                        DiagnosticCode.DOCKERFILE_SYNTAX_ERROR,
                        Severity.error,
                        f"{problem} Docker will refuse to build this file.",
                        self._keyword_location(entry),
                    )
                )

        if seen_from:
            self.findings.extend(before_from)
        else:
            self.findings.append(
                make_finding(
                    DiagnosticCode.DOCKERFILE_SYNTAX_ERROR,
                    Severity.error,
                    "No FROM instruction found. A Dockerfile must start a build "
                    "stage with FROM.",
                    SourceLocation(file=self.filename, start_line=1, start_column=1),
                )
            )

    def instructions(self, structure: list[dict[str, Any]]) -> list[DockerInstruction]:
        """Instructions in source order with their stage, for the rules."""
        result: list[DockerInstruction] = []
        stage = -1
        for entry in structure:
            keyword = entry.get("instruction", "").upper()
            if keyword == "COMMENT":
                continue
            if keyword == "FROM":
                stage += 1
            info = self.stages[stage] if 0 <= stage < len(self.stages) else None
            result.append(
                DockerInstruction(
                    keyword=keyword,
                    value=entry.get("value", ""),
                    location=_make_loc(
                        entry.get("startline"), entry.get("endline"), self.filename
                    ),
                    stage_index=info.index if info else None,
                    node_id=info.node_id if info else None,
                )
            )
        return result

    def _resolve_stage(
        self,
        name: str,
        stage: _StageInfo,
        loc: SourceLocation | None,
        where: str,
    ) -> _StageInfo | None:
        """The earlier stage ``name`` refers to, or None if it is an image.

        Warns when the name is probably a mistake: it matches a stage defined
        later (Docker then pulls an image of that name), or it is a near-miss
        of an earlier stage name.
        """
        wanted = name.lower()
        earlier = {
            s.alias.lower(): s for s in reversed(self.stages[: stage.index]) if s.alias
        }
        if wanted in earlier:
            return earlier[wanted]
        if "/" in name or ":" in name or "@" in name or "$" in name:
            return None  # clearly an image reference (or a build arg)

        later = [
            s
            for s in self.stages[stage.index :]
            if s.alias and s.alias.lower() == wanted
        ]
        close = difflib.get_close_matches(wanted, list(earlier), n=1, cutoff=0.8)
        if later:
            message = (
                f"{where} {name}: stage '{later[0].alias}' is defined later in the "
                "file, so Docker treats this as an image name, not that stage. "
                "Move the stage before this point."
            )
        elif close:
            message = (
                f"{where} {name}: there is no earlier stage '{name}', so Docker "
                f"will try to pull an image of that name. Did you mean '{close[0]}'?"
            )
        else:
            return None
        self.findings.append(
            make_finding(
                DiagnosticCode.UNRESOLVED_DEPENDENCY,
                Severity.warning,
                message,
                loc,
                node_ids=(stage.node_id,),
                details={"address": name, "known_addresses": sorted(earlier)},
            )
        )
        return None

    def extract(self, structure: list[dict[str, Any]]) -> IRGraph:
        self._check_instructions(structure)

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

            # IDs use the stage index (docs/compiler-core.md): stages may be
            # unnamed and aliases may repeat. The alias goes in label/metadata.
            label = raw_alias or f"stage-{stage_idx}"
            base_id = make_node_id(ID_PREFIX, "stage", str(stage_idx))
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
                            node_ids=(
                                self.alias_to_stage[alias_lower].node_id,
                                node_id,
                            ),
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

        # Collect instructions per stage for metadata
        stage_instructions: list[list[str]] = [[] for _ in range(len(self.stages))]
        curr_idx = -1
        for entry in structure:
            instruction = entry.get("instruction", "").upper()
            if instruction == "FROM":
                curr_idx += 1
            if 0 <= curr_idx < len(stage_instructions):
                content = entry.get("content", "").strip()
                if content:
                    stage_instructions[curr_idx].append(content)

        for i, node in enumerate(self.nodes):
            updated_meta = dict(node.metadata)
            updated_meta["instructions"] = stage_instructions[i]
            self.nodes[i] = node.model_copy(update={"metadata": updated_meta})

        # Pass 2: Connect dependencies. Docker resolves a name in FROM or
        # COPY --from to a stage only if that stage is defined *earlier*;
        # anything else is an image name.
        # 2a: FROM <earlier stage>
        for stage in self.stages:
            loc = _make_loc(stage.start_line, stage.end_line, self.filename)
            dep_stage = self._resolve_stage(stage.base_image, stage, loc, "FROM")
            if dep_stage is not None:
                self.edges.append(
                    Edge(
                        source=dep_stage.node_id,
                        target=stage.node_id,
                        type=EdgeType.docker_stage_base,
                        label=f"FROM {dep_stage.alias or dep_stage.index}",
                        source_location=loc,
                    )
                )

        # 2b: COPY --from=<earlier stage, index or image>
        curr_stage_idx = -1
        for entry in structure:
            instruction = entry.get("instruction", "").upper()
            if instruction == "FROM":
                curr_stage_idx += 1
                continue
            if instruction != "COPY":
                continue
            if curr_stage_idx < 0 or curr_stage_idx >= len(self.stages):
                continue

            current_stage = self.stages[curr_stage_idx]
            loc = _make_loc(entry.get("startline"), entry.get("endline"), self.filename)
            for from_target in _COPY_FROM_PATTERN.findall(entry.get("value", "")):
                from_clean = from_target.strip("\"'")
                dep_stage: _StageInfo | None = None
                if from_clean.isdigit():
                    idx = int(from_clean)
                    if idx < current_stage.index:
                        dep_stage = self.index_to_stage.get(idx)
                    if dep_stage is None:
                        self.findings.append(
                            make_finding(
                                DiagnosticCode.UNRESOLVED_DEPENDENCY,
                                Severity.error,
                                f"COPY --from={from_clean} does not name an earlier "
                                f"stage (this is stage {current_stage.index}; "
                                "stages are numbered from 0).",
                                loc,
                                node_ids=(current_stage.node_id,),
                                details={"from": from_clean},
                            )
                        )
                        continue
                else:
                    dep_stage = self._resolve_stage(
                        from_clean, current_stage, loc, "COPY --from"
                    )
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
        # Parse from memory. Without fileobj, dockerfile-parse reads and writes
        # ./Dockerfile in the working directory, which would overwrite a real
        # file and mix up concurrent requests.
        dfp = DockerfileParser(fileobj=io.BytesIO(source.encode("utf-8")))

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
        rule_findings = run_dockerfile_rules(extractor.instructions(structure))

        return ParseResult(
            ir=ir,
            findings=[*extractor.findings, *rule_findings],
            dependency_analysis_complete=extractor.complete,
        )


ADAPTER = DockerfileAdapter()
