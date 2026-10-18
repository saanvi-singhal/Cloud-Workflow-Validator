"""Public node, edge and graph models (spec 3.1, 3.5, 3.7)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.models.common import EdgeType, NodeType, SourceLocation


class Node(BaseModel):
    """One normalized graph node. Format-specific detail goes in ``metadata``."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    label: str
    type: NodeType
    source_location: SourceLocation | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class Edge(BaseModel):
    """A directed dependency: ``source`` must precede ``target``."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    type: EdgeType
    label: str | None = None
    source_location: SourceLocation | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str, str]:
        """Sort/dedup key. The frontend can use the same triple as an edge id."""
        return (self.source, self.target, self.type.value)


class GraphPayload(BaseModel):
    """The ``graph`` object of the validation response."""

    model_config = ConfigDict(extra="forbid")

    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
