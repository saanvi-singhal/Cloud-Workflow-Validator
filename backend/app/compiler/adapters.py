"""Parser adapter contract: the boundary between format parsers and the core.

Every format parser (GitHub Actions YAML, Dockerfile, Terraform) implements
``SourceAdapter``. It turns source text into a ``ParseResult``: shared IR plus
any format-specific findings (syntax errors, unresolved references,
unsupported constructs, security rules). The compiler core never imports a
parser library directly; it only sees this contract.

Example for a parser author::

    class GithubActionsAdapter:
        format = SourceFormat.yaml

        def parse(self, source: str, filename: str | None) -> ParseResult:
            ...
            return ParseResult(ir=IRGraph(format=SourceFormat.yaml, ...))

    ADAPTER = GithubActionsAdapter()   # picked up by get_adapter()
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.compiler.findings import Finding
from app.compiler.ir import IRGraph
from app.models import SourceFormat


@dataclass(frozen=True)
class ParseResult:
    """What a parser hands to the compiler core.

    ``ir`` is ``None`` only when nothing usable could be parsed (e.g. a syntax
    error). ``dependency_analysis_complete`` must be ``False`` when an
    unsupported construct may hide dependency edges. The pipeline then
    withholds ``execution_order`` instead of returning a misleading one.
    """

    ir: IRGraph | None
    findings: list[Finding] = field(default_factory=list)
    dependency_analysis_complete: bool = True


@runtime_checkable
class SourceAdapter(Protocol):
    """Interface every format parser implements."""

    format: SourceFormat

    def parse(self, source: str, filename: str | None) -> ParseResult: ...


class AdapterNotAvailableError(LookupError):
    """No parser adapter is registered for the requested format."""


_REGISTRY: dict[SourceFormat, SourceAdapter] = {}

# Modules that define a module-level ``ADAPTER``. They are imported lazily on
# first use, so the core has no import-time dependency on any parser library.
# Parser owners add their module here (or call register_adapter themselves).
BUILTIN_ADAPTER_MODULES: dict[SourceFormat, str] = {
    SourceFormat.terraform: "app.parsers.terraform",
}


def register_adapter(adapter: SourceAdapter, *, replace: bool = False) -> None:
    """Register ``adapter`` for its format (``replace=True`` to override)."""
    if not isinstance(adapter, SourceAdapter):
        raise TypeError(f"{adapter!r} does not implement SourceAdapter")
    if adapter.format in _REGISTRY and not replace:
        raise ValueError(f"an adapter for '{adapter.format.value}' is registered")
    _REGISTRY[adapter.format] = adapter


def unregister_adapter(fmt: SourceFormat) -> None:
    """Remove the adapter for ``fmt`` (mainly for tests)."""
    _REGISTRY.pop(fmt, None)


def get_adapter(fmt: SourceFormat) -> SourceAdapter:
    """Return the adapter for ``fmt``, importing a built-in one on first use."""
    if fmt not in _REGISTRY and fmt in BUILTIN_ADAPTER_MODULES:
        module = importlib.import_module(BUILTIN_ADAPTER_MODULES[fmt])
        register_adapter(module.ADAPTER)
    try:
        return _REGISTRY[fmt]
    except KeyError:
        raise AdapterNotAvailableError(
            f"no parser adapter registered for format '{fmt.value}'"
        ) from None
