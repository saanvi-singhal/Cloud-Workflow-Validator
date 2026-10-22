"""Shared enums and the source-location model.

These types are part of the public contract defined in docs/PROJECT_SPEC.md
(sections 3 and 6). Every parser, analysis pass and API response uses them,
so changing a value here is a contract change that needs owner approval.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class SourceFormat(str, Enum):
    """Input formats accepted by ``POST /api/v1/validate`` (spec 7.2).

    ``mixed`` is only valid with ``files``: each file's format is detected
    from its name (and content), every group is analysed by its own parser,
    and one combined result is returned.
    """

    yaml = "yaml"
    dockerfile = "dockerfile"
    terraform = "terraform"
    mixed = "mixed"


class Severity(str, Enum):
    """Diagnostic severities (spec 6.1). Only ``error`` makes ``valid`` false."""

    error = "error"
    warning = "warning"
    info = "info"


class NodeType(str, Enum):
    """Standard shared node types (spec 3.2)."""

    task = "task"
    stage = "stage"
    instruction = "instruction"
    resource = "resource"
    data_source = "data_source"
    module = "module"
    variable = "variable"
    output = "output"
    unknown = "unknown"


class EdgeType(str, Enum):
    """Semantic edge types (spec 3.5).

    Direction is always ``source -> target`` meaning *source is a prerequisite
    of target* (target depends on source), spec 3.6.
    """

    workflow_dependency = "workflow_dependency"
    terraform_reference = "terraform_reference"
    terraform_explicit_dependency = "terraform_explicit_dependency"
    docker_stage_base = "docker_stage_base"
    docker_instruction_order = "docker_instruction_order"


class SourceLocation(BaseModel):
    """A span in the user's source text.

    All positions are one-based. ``end_column`` is *exclusive*: it points one
    past the last character, which is the convention of the Lark parser used
    by python-hcl2 (approved decision D4). Any field may be ``None`` when the
    parser cannot supply it reliably; values are never invented.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    file: str | None = None
    start_line: int | None = Field(default=None, ge=1)
    start_column: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    end_column: int | None = Field(default=None, ge=1)
