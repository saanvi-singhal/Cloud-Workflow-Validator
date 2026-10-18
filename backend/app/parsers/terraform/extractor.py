"""Build the shared IR from Terraform blocks (single ``.tf`` file, v1).

Two passes:

1. **Declare** a node for every ``resource``, ``data``, ``module``,
   ``variable`` and ``output`` block, in source order, with a stable id
   (``tf:resource:aws_vpc.main``). A repeated address is a
   ``DUPLICATE_NODE_ID`` error, and the repeat gets ``...#2``.
2. **Connect**: walk each block's expressions. For a block B that references
   A we add the edge ``A -> B`` (A is a prerequisite of B). ``depends_on``
   entries become ``terraform_explicit_dependency`` edges; all other
   references become ``terraform_reference`` edges.

Per-block rules (all documented in docs/compiler-core.md):

* ``variable`` blocks have no dependencies (Terraform requires literal defaults);
* ``provider = ...`` / module ``providers = {...}`` select provider
  configurations, which are not graph nodes, so they are skipped;
* ``lifecycle.ignore_changes`` lists attribute names, not references, so it is
  skipped; ``replace_triggered_by`` is unsupported;
* ``dynamic`` blocks are unsupported (iterator scoping);
* references to undeclared blocks become ``UNRESOLVED_DEPENDENCY`` errors and
  **no edge is created**.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import JsonValue

from app.compiler.findings import Finding, make_finding
from app.compiler.ir import IRGraph, make_node_id, unique_id
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
from app.parsers.terraform.blocks import (
    Attribute,
    Block,
    TerraformFile,
    literal_value,
)
from app.parsers.terraform.references import (
    ExpressionAnalysis,
    Reference,
    Unsupported,
    analyze_expression,
    explicit_dependencies,
)

ID_PREFIX = "tf"

# block type -> (number of labels, node type, id kind)
MODELLED_BLOCKS: dict[str, tuple[int, NodeType, str]] = {
    "resource": (2, NodeType.resource, "resource"),
    "data": (2, NodeType.data_source, "data"),
    "module": (1, NodeType.module, "module"),
    "variable": (1, NodeType.variable, "variable"),
    "output": (1, NodeType.output, "output"),
}
# Valid Terraform blocks that v1 does not put in the graph (reported as info).
UNMODELLED_BLOCKS = frozenset(
    {"provider", "terraform", "locals", "moved", "import", "check", "removed"}
)
_ADDRESS_KIND = {
    "resource": "resource",
    "data": "data",
    "module": "module",
    "variable": "variable",
}


def block_address(block: Block) -> str:
    """Terraform address of a modelled block, e.g. ``data.aws_ami.ubuntu``."""
    labels = ".".join(block.labels)
    if block.type == "resource":
        return labels
    if block.type == "variable":
        return f"var.{labels}"
    return f"{block.type}.{labels}"


@dataclass
class ExtractionResult:
    ir: IRGraph
    findings: list[Finding]
    complete: bool
    # (block, node id) for every modelled block, in source order; used by rules.
    modelled: list[tuple[Block, str]] = field(default_factory=list)


@dataclass
class _EdgeBuilder:
    """Merges repeated references between the same two nodes into one edge."""

    source: str
    target: str
    type: EdgeType
    label: str
    location: SourceLocation | None
    references: list[dict[str, JsonValue]] = field(default_factory=list)


class _Extractor:
    def __init__(self, filename: str | None) -> None:
        self.filename = filename
        self.findings: list[Finding] = []
        self.complete = True
        self.nodes: list[Node] = []
        self.taken_ids: set[str] = set()
        self.address_to_id: dict[str, str] = {}
        self.modelled: list[tuple[Block, str]] = []
        self.edges: dict[tuple[str, str, EdgeType], _EdgeBuilder] = {}

    # -- diagnostics helpers ------------------------------------------------

    def report_unsupported(
        self, item: Unsupported, severity: Severity = Severity.warning
    ) -> None:
        if severity is not Severity.info:
            self.complete = False
        self.findings.append(
            make_finding(
                DiagnosticCode.UNSUPPORTED_CONSTRUCT,
                severity,
                f"Unsupported construct '{item.construct}': {item.reason}. "
                "Dependencies inside it are not analysed.",
                item.location,
                details={"construct": item.construct},
            )
        )

    # -- pass 1: declare nodes ------------------------------------------------

    def declare(self, terraform_file: TerraformFile) -> None:
        for attribute in terraform_file.attributes:
            self.report_unsupported(
                Unsupported(
                    attribute.name,
                    "top-level attributes are not valid Terraform",
                    attribute.location,
                )
            )
        for block in terraform_file.blocks:
            if block.type in MODELLED_BLOCKS:
                self.declare_block(block)
            elif block.type in UNMODELLED_BLOCKS:
                self.report_unsupported(
                    Unsupported(
                        f"{block.type} block",
                        "not represented in the dependency graph in v1",
                        block.location,
                    ),
                    Severity.info,
                )
            else:
                self.report_unsupported(
                    Unsupported(
                        f"{block.type} block",
                        "unknown top-level block type",
                        block.location,
                    )
                )

    def declare_block(self, block: Block) -> None:
        label_count, node_type, id_kind = MODELLED_BLOCKS[block.type]
        if block.label_error or len(block.labels) != label_count:
            self.report_unsupported(
                Unsupported(
                    f"{block.type} block",
                    block.label_error or f"expected {label_count} label(s)",
                    block.location,
                )
            )
            return

        address = block_address(block)
        base_id = make_node_id(ID_PREFIX, id_kind, *block.labels)
        node_id = unique_id(base_id, self.taken_ids)
        if node_id != base_id:
            self.findings.append(
                make_finding(
                    DiagnosticCode.DUPLICATE_NODE_ID,
                    Severity.error,
                    f"'{address}' is declared more than once; references "
                    "resolve to the first declaration.",
                    block.location,
                    node_ids=(base_id, node_id),
                    details={"address": address},
                )
            )
        else:
            self.address_to_id[address] = node_id

        metadata: dict[str, JsonValue] = {
            "block_type": block.type,
            "address": address,
            "attributes": sorted({a.name for a in block.attributes}),
        }
        if block.type in ("resource", "data"):
            metadata["resource_type"] = block.labels[0]
            metadata["name"] = block.labels[1]
        else:
            metadata["name"] = block.labels[0]
        if block.type == "module":
            source = block.attribute("source")
            value = literal_value(source.expr) if source else None
            if isinstance(value, str):
                metadata["source"] = value

        self.nodes.append(
            Node(
                id=node_id,
                label=address,
                type=node_type,
                source_location=block.location,
                metadata=metadata,
            )
        )
        self.modelled.append((block, node_id))

    # -- pass 2: dependencies -------------------------------------------------

    def connect(self) -> None:
        for block, node_id in self.modelled:
            if block.type == "variable":
                continue
            self.connect_body(block, node_id, path=(), top_level=True)

    def connect_body(
        self, block: Block, node_id: str, path: tuple[str, ...], top_level: bool
    ) -> None:
        for attribute in block.attributes:
            self.connect_attribute(block, attribute, node_id, path, top_level)
        for nested in block.blocks:
            if nested.type == "dynamic":
                self.report_unsupported(
                    Unsupported("dynamic block", "iterator scoping", nested.location)
                )
                continue
            self.connect_body(nested, node_id, (*path, nested.type), top_level=False)

    def connect_attribute(
        self,
        block: Block,
        attribute: Attribute,
        node_id: str,
        path: tuple[str, ...],
        top_level: bool,
    ) -> None:
        name = attribute.name
        if top_level and name == "depends_on":
            analysis = explicit_dependencies(attribute.expr, self.filename)
            self.record(analysis, node_id, "depends_on", explicit=True)
            return
        if top_level and name in ("provider", "providers"):
            return  # provider configuration selection, not a graph dependency
        if path and path[-1] == "lifecycle":
            if name == "ignore_changes":
                return  # attribute names, not references
            if name == "replace_triggered_by":
                self.report_unsupported(
                    Unsupported(
                        "replace_triggered_by", "not analysed", attribute.location
                    )
                )
                return
        analysis = analyze_expression(attribute.expr, self.filename)
        self.record(analysis, node_id, ".".join((*path, name)), explicit=False)

    def record(
        self,
        analysis: ExpressionAnalysis,
        node_id: str,
        attribute_path: str,
        *,
        explicit: bool,
    ) -> None:
        for item in analysis.unsupported:
            self.report_unsupported(item)
        for reference in analysis.references:
            self.add_dependency(reference, node_id, attribute_path, explicit)

    def add_dependency(
        self, reference: Reference, node_id: str, attribute_path: str, explicit: bool
    ) -> None:
        target_id = self.address_to_id.get(reference.address)
        if target_id is None:
            kind = _ADDRESS_KIND[reference.kind]
            known = sorted(
                a for a in self.address_to_id if self._kind_of_address(a) == kind
            )
            self.findings.append(
                make_finding(
                    DiagnosticCode.UNRESOLVED_DEPENDENCY,
                    Severity.error,
                    f"Reference to undeclared {reference.kind.replace('_', ' ')} "
                    f"'{reference.address}' (in '{attribute_path}'). v1 analyses a "
                    "single .tf file, so it must be declared in this file.",
                    reference.location,
                    node_ids=(node_id,),
                    details={"address": reference.address, "known_addresses": known},
                )
            )
            return

        edge_type = (
            EdgeType.terraform_explicit_dependency
            if explicit
            else EdgeType.terraform_reference
        )
        key = (target_id, node_id, edge_type)
        location_json: JsonValue = (
            reference.location.model_dump(mode="json") if reference.location else None
        )
        entry: dict[str, JsonValue] = {
            "attribute": attribute_path,
            "expression": reference.text,
            "location": location_json,
        }
        if key not in self.edges:
            self.edges[key] = _EdgeBuilder(
                source=target_id,
                target=node_id,
                type=edge_type,
                label=attribute_path,
                location=reference.location,
            )
        self.edges[key].references.append(entry)

    @staticmethod
    def _kind_of_address(address: str) -> str:
        head = address.split(".", 1)[0]
        if head == "var":
            return "variable"
        if head in ("data", "module", "output"):
            return head
        return "resource"

    def build(self) -> IRGraph:
        edges = [
            Edge(
                source=b.source,
                target=b.target,
                type=b.type,
                label=b.label,
                source_location=b.location,
                metadata={"references": b.references},
            )
            for b in self.edges.values()
        ]
        return IRGraph(format=SourceFormat.terraform, nodes=self.nodes, edges=edges)


def extract(terraform_file: TerraformFile, filename: str | None) -> ExtractionResult:
    """Convert a parsed ``.tf`` file into IR plus parser findings."""
    extractor = _Extractor(filename)
    extractor.declare(terraform_file)
    extractor.connect()
    return ExtractionResult(
        ir=extractor.build(),
        findings=extractor.findings,
        complete=extractor.complete,
        modelled=extractor.modelled,
    )
