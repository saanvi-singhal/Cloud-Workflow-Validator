"""GitHub's own workflow schema, applied to a parsed workflow.

``workflow-schema.json`` is GitHub's ``workflow-v1.0.json`` from
github.com/actions/languageservices (MIT, see ``workflow-schema.LICENSE``,
commit 4043eda158e1): the schema GitHub's workflow parser and the VS Code
extension validate against. Using the file itself, rather than a hand-made copy
of its rules, means every structural rule it encodes is checked, and updating
the file updates the rules.

The file is a small template-schema language. Each definition is one of:

* ``mapping``: named ``properties`` (some ``required``), or ``loose`` keys and
  values of one type; any other key is rejected;
* ``sequence`` of ``item-type``;
* ``one-of`` several definitions;
* ``string`` (optionally a ``constant`` or ``require-non-empty``),
  ``allowed-values``, ``boolean``, ``number`` or ``null``;
* plus ``context``: the expression names (``github``, ``secrets``,
  ``matrix``, functions such as ``hashFiles(1,255)``) that may be used in
  ``${{ }}`` there. A value that is an expression is accepted for any type,
  and every name it uses must be in that list (that is how GitHub rejects,
  for example, ``secrets`` in a job's ``if``).

This module only reports problems; positions are 0-based (line, column) as
ruamel gives them. Rules GitHub enforces in code rather than in the schema
(filter conflicts, id formats, cron syntax, ``uses`` formats) are in
``workflow_rules.py``.
"""

from __future__ import annotations

import difflib
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

SCHEMA_FILE = Path(__file__).with_name("workflow-schema.json")
BUILTIN = frozenset(
    {"any", "string", "boolean", "number", "null", "sequence", "mapping"}
)
# Expression functions available everywhere; status functions and hashFiles
# are only allowed where a definition's context lists them.
BUILTIN_FUNCTIONS = frozenset(
    {
        "contains",
        "startswith",
        "endswith",
        "format",
        "join",
        "tojson",
        "fromjson",
        "case",
    }
)
_LITERALS = frozenset({"true", "false", "null", "nan", "infinity"})

Position = tuple[int, int] | None
_FILTER_PATH = re.compile(
    r"^on\.(?!schedule\b|workflow_dispatch\b|workflow_call\b)[a-z_]+"
    r"(\.(branches|branches-ignore|tags|tags-ignore|paths|paths-ignore|types))?$"
)


@dataclass(frozen=True)
class Problem:
    message: str
    position: Position
    path: str = ""

    @property
    def in_trigger_filter(self) -> bool:
        """An event's filters (``on.push``, ``on.push.tags``): GitHub is visibly
        more lenient there than its schema (popular repositories run with an
        empty ``tags:`` or a ``paths-ignore`` under ``merge_group``), so these
        are warnings. Schedules and input definitions are not filters."""
        return bool(_FILTER_PATH.match(self.path))


@cache
def definitions() -> dict[str, dict[str, Any]]:
    return json.loads(SCHEMA_FILE.read_text())["definitions"]


def mapping_keys(name: str) -> frozenset[str]:
    """The property names of a mapping definition (for the adapter's checks)."""
    return frozenset(definitions()[name]["mapping"].get("properties", {}))


def _type_name(prop: Any) -> str:
    return prop if isinstance(prop, str) else prop["type"]


def _is_bool(value: Any) -> bool:
    # ruamel's round-trip booleans are ScalarBoolean, an int subclass.
    return isinstance(value, bool) or type(value).__name__ == "ScalarBoolean"


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, Mapping):
        return "mapping"
    if isinstance(value, list):
        return "sequence"
    if _is_bool(value):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return "string"  # str, and scalars such as dates that YAML typed


def _scalar_text(value: Any) -> str:
    if _is_bool(value):
        return "true" if value else "false"
    return "" if value is None else str(value)


def _leaves(name: str) -> list[str]:
    """Flatten nested one-of definitions, keeping order."""
    if name in BUILTIN:
        return [name]
    d = definitions()[name]
    if "one-of" in d:
        return [leaf for option in d["one-of"] for leaf in _leaves(option)]
    return [name]


def _shape(name: str) -> str:
    """What kind of YAML value a (leaf) definition takes."""
    if name in BUILTIN:
        return "scalar" if name in ("string", "boolean", "number", "null") else name
    d = definitions()[name]
    for shape in ("mapping", "sequence"):
        if shape in d:
            return shape
    return "scalar"


def _expected(names: list[str]) -> str:
    """Plain words for what a set of definitions accepts."""
    constants, words = [], []
    for name in names:
        d = {} if name in BUILTIN else definitions()[name]
        if name in BUILTIN:
            word = {
                "string": "a string",
                "boolean": "true or false",
                "number": "a number",
                "null": "empty",
                "sequence": "a list",
                "mapping": "a mapping",
                "any": "any value",
            }[name]
        elif "string" in d and "constant" in d["string"]:
            constants.append(d["string"]["constant"])
            continue
        elif "allowed-values" in d:
            constants.extend(d["allowed-values"])
            continue
        elif "mapping" in d:
            word = "a mapping"
        elif "sequence" in d:
            word = "a list"
        elif "boolean" in d:
            word = "true or false"
        elif "number" in d:
            word = "a number"
        elif "null" in d:
            word = "empty"
        else:
            word = (
                "a non-empty string"
                if d.get("string", {}).get("require-non-empty")
                else "a string"
            )
        if word not in words:
            words.append(word)
    if constants:
        shown = ", ".join(dict.fromkeys(constants))
        words.insert(
            0, f"one of: {shown}" if len(constants) > 1 else f"'{constants[0]}'"
        )
    return " or ".join(words)


# --- expressions ------------------------------------------------------------------

_EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
_TOKEN = re.compile(
    r"'(?:[^']|'')*'"  # string literal ('' escapes a quote)
    r"|(?P<name>[A-Za-z_][A-Za-z0-9_-]*)"
    r"|(?P<dot>\.)"
    r"|\S"
)


def expression_names(expression: str) -> Iterator[tuple[str, bool]]:
    """(name, is_function) for every named value and function in an expression."""
    tokens = list(_TOKEN.finditer(expression))
    for i, token in enumerate(tokens):
        name = token.group("name")
        if name is None:
            continue
        if i > 0 and tokens[i - 1].group("dot"):
            continue  # a property: github.event, matrix.os
        following = expression[token.end() :].lstrip()
        is_function = following.startswith("(")
        if not is_function and name.lower() in _LITERALS:
            continue
        yield name, is_function


def _allowed_names(context: list[str]) -> tuple[set[str], set[str]]:
    values, functions = set(), set(BUILTIN_FUNCTIONS)
    for entry in context:
        if "(" in entry:
            functions.add(entry.split("(", 1)[0].lower())
        else:
            values.add(entry.lower())
    return values, functions


class SchemaValidator:
    """Walks a parsed workflow against the schema and collects problems."""

    def __init__(self) -> None:
        self.problems: list[Problem] = []
        self._path = ""
        self._anchors: dict[int, Position] = {}

    def validate(self, data: Any) -> list[Problem]:
        self._check(data, "workflow-root-strict", "workflow", (0, 0), None)
        return self.problems

    # -- helpers --
    def _report(self, message: str, position: Position) -> None:
        self.problems.append(Problem(message, position, self._path))

    @staticmethod
    def _key_pos(mapping: Any, key: Any) -> Position:
        try:
            return tuple(mapping.lc.key(key))  # type: ignore[return-value]
        except Exception:
            return None

    @staticmethod
    def _value_pos(mapping: Any, key: Any) -> Position:
        try:
            return tuple(mapping.lc.value(key))  # type: ignore[return-value]
        except Exception:
            return None

    @staticmethod
    def _item_pos(sequence: Any, index: int) -> Position:
        try:
            return tuple(sequence.lc.item(index))  # type: ignore[return-value]
        except Exception:
            return None

    # -- the walk --
    def _check(
        self, value: Any, name: str, path: str, pos: Position, context: list[str] | None
    ) -> None:
        self._path = path
        if name in BUILTIN:
            # cancel-in-progress: ${{ ... }}, matrix: ${{ fromJSON(...) }}
            if isinstance(value, str) and "${{" in value and context is not None:
                self._check_expression(value, context, path, pos, False)
            else:
                self._check_builtin(value, name, path, pos)
            return
        d = definitions()[name]
        context = d.get("context", context)
        if isinstance(value, str) and context is not None:
            whole = name.endswith("-if")  # conditions are expressions without ${{ }}
            if whole or "${{" in value:
                self._check_expression(value, context, path, pos, whole)
                return
        if "one-of" in d:
            self._check_one_of(value, _leaves(name), path, pos, context)
        elif "mapping" in d:
            self._check_mapping(value, d["mapping"], path, pos, context)
        elif "sequence" in d:
            if not isinstance(value, list):
                self._report(f"{path} must be a list, not {self._show(value)}.", pos)
                return
            item = d["sequence"]["item-type"]
            for i, entry in enumerate(value):
                self._check(
                    entry,
                    item,
                    f"{path}[{i}]",
                    self._item_pos(value, i) or pos,
                    context,
                )
        elif "allowed-values" in d:
            allowed = d["allowed-values"]
            if _scalar_text(value) not in allowed or _kind(value) in (
                "mapping",
                "sequence",
            ):
                self._report(self._not_allowed(value, allowed, path), pos)
        elif "string" in d:
            self._check_string(value, d["string"], path, pos)
        elif "boolean" in d:
            if not _is_bool(value):
                self._report(
                    f"{path} must be true or false, not {self._show(value)}.", pos
                )
        elif "number" in d:
            if _kind(value) != "number":
                self._report(f"{path} must be a number, not {self._show(value)}.", pos)
        elif "null" in d:
            if value is not None:
                self._report(
                    f"{path} takes no value, but has {self._show(value)}.", pos
                )

    def _check_builtin(self, value: Any, name: str, path: str, pos: Position) -> None:
        kind = _kind(value)
        ok = {
            "any": True,
            # GitHub turns numbers and booleans into strings (env: {DEBUG: true}).
            "string": kind in ("string", "number", "boolean", "null"),
            "boolean": kind == "boolean",
            "number": kind == "number",
            "null": kind == "null",
            "sequence": kind == "sequence",
            "mapping": kind == "mapping",
        }[name]
        if not ok:
            self._report(
                f"{path} must be {_expected([name])}, not {self._show(value)}.", pos
            )

    def _check_string(
        self, value: Any, spec: dict[str, Any], path: str, pos: Position
    ) -> None:
        if _kind(value) in ("mapping", "sequence"):
            self._report(f"{path} must be a string, not {self._show(value)}.", pos)
            return
        text = _scalar_text(value)
        if "constant" in spec and text != spec["constant"]:
            self._report(
                f"{path} must be '{spec['constant']}', not {self._show(value)}.", pos
            )
        elif spec.get("require-non-empty") and not text.strip():
            self._report(f"{path} must not be empty.", pos)

    def _matches(self, value: Any, leaf: str) -> bool:
        """Whether a scalar fits a scalar definition (used to pick a one-of)."""
        kind = _kind(value)
        if leaf in BUILTIN:
            if leaf == "string":
                return kind in ("string", "number", "boolean")
            return leaf == "any" or leaf == kind
        d = definitions()[leaf]
        if "allowed-values" in d:
            return kind == "string" and value in d["allowed-values"]
        if "string" in d:
            spec = d["string"]
            if kind not in ("string", "number", "boolean"):
                return False
            text = _scalar_text(value)
            if "constant" in spec:
                return text == spec["constant"]
            return not (spec.get("require-non-empty") and not text.strip())
        if "boolean" in d:
            return kind == "boolean"
        if "number" in d:
            return kind == "number"
        if "null" in d:
            return kind == "null"
        return False

    def _check_one_of(
        self,
        value: Any,
        leaves: list[str],
        path: str,
        pos: Position,
        context: list[str] | None,
    ) -> None:
        kind = _kind(value)
        if kind in ("mapping", "sequence"):
            fitting = [leaf for leaf in leaves if _shape(leaf) == kind]
            if not fitting:
                self._report(
                    f"{path} must be {_expected(leaves)}, not {self._show(value)}.", pos
                )
                return
            if kind == "mapping" and len(fitting) > 1:
                fitting = [self._narrow(value, fitting)]
            self._check(value, fitting[0], path, pos, context)
            return
        if not any(
            self._matches(value, leaf) for leaf in leaves if _shape(leaf) == "scalar"
        ):
            scalar_leaves = [leaf for leaf in leaves if _shape(leaf) == "scalar"]
            constants = self._constants(scalar_leaves)
            if constants and kind == "string":
                self._report(self._not_allowed(value, constants, path), pos)
            else:
                self._report(
                    f"{path} must be {_expected(leaves)}, not {self._show(value)}.", pos
                )

    def _constants(self, leaves: list[str]) -> list[str]:
        found: list[str] = []
        for leaf in leaves:
            if leaf in BUILTIN:
                continue
            d = definitions()[leaf]
            if "allowed-values" in d:
                found.extend(d["allowed-values"])
            elif "string" in d and "constant" in d["string"]:
                found.append(d["string"]["constant"])
        return found

    def _narrow(self, value: Mapping[Any, Any], leaves: list[str]) -> str:
        """Pick the mapping definition a mapping is meant to be.

        Like GitHub's reader: keep the definitions that have each key, in
        order; a key no remaining definition has is reported by the walk.
        For steps, the key that names the step kind (run, uses, wait, ...)
        decides.
        """
        remaining = leaves
        for key in value:
            keep = [
                leaf
                for leaf in remaining
                if str(key) in definitions()[leaf]["mapping"].get("properties", {})
                or "loose-key-type" in definitions()[leaf]["mapping"]
            ]
            if keep:
                remaining = keep
        # Prefer one whose required keys are all present.
        for leaf in remaining:
            props = definitions()[leaf]["mapping"].get("properties", {})
            required = [
                k for k, p in props.items() if isinstance(p, dict) and p.get("required")
            ]
            if all(k in value for k in required):
                return leaf
        return remaining[0]

    def _check_mapping(
        self,
        value: Any,
        spec: dict[str, Any],
        path: str,
        pos: Position,
        context: list[str] | None,
    ) -> None:
        if not isinstance(value, Mapping):
            self._report(f"{path} must be a mapping, not {self._show(value)}.", pos)
            return
        props: dict[str, Any] = spec.get("properties", {})
        loose_value = spec.get("loose-value-type")
        for key, item in value.items():
            key_text = _scalar_text(key)
            child = f"{path}.{key_text}" if path != "workflow" else key_text
            item_pos = self._value_pos(value, key) or self._key_pos(value, key) or pos
            # A missing required key is reported at the mapping's own key.
            if isinstance(item, Mapping):
                self._anchors[id(item)] = self._key_pos(value, key)
            if key_text in props:
                self._check(item, _type_name(props[key_text]), child, item_pos, context)
            elif loose_value:
                loose_key = spec.get("loose-key-type")
                if loose_key and loose_key not in BUILTIN:
                    key_spec = definitions()[loose_key].get("string", {})
                    if key_spec.get("require-non-empty") and not key_text.strip():
                        self._path = path
                        self._report(
                            f"{path} has an empty key.",
                            self._key_pos(value, key) or pos,
                        )
                self._check(item, loose_value, child, item_pos, context)
            else:
                self._path = path  # the walk below set it to a child's path
                close = difflib.get_close_matches(
                    key_text, list(props), n=1, cutoff=0.75
                )
                hint = f" Did you mean '{close[0]}'?" if close else ""
                allowed = ", ".join(props) if len(props) <= 12 else ""
                where = "the workflow" if path == "workflow" else path
                self._report(
                    f"'{key_text}' is not a valid key in {where}.{hint}"
                    + (f" Valid keys: {allowed}." if allowed and not close else ""),
                    self._key_pos(value, key) or pos,
                )
        self._path = path
        anchor = self._anchors.get(id(value)) or pos
        for key, prop in props.items():
            if isinstance(prop, dict) and prop.get("required") and key not in value:
                where = "The workflow" if path == "workflow" else path
                self._report(f"{where} is missing the required key '{key}'.", anchor)

    def _check_expression(
        self, text: str, context: list[str], path: str, pos: Position, whole: bool
    ) -> None:
        # An unclosed ${{ is a syntax error GitHub reports when loading.
        stripped = _EXPRESSION.sub("", text)
        if "${{" in stripped:
            self._report(f"{path} has a '${{{{' that is never closed with '}}}}'.", pos)
            return
        bodies = [m.group(1) for m in _EXPRESSION.finditer(text)]
        if whole and not bodies:
            bodies = [text]
        values, functions = _allowed_names(context)
        for body in bodies:
            for name, is_function in expression_names(body):
                low = name.lower()
                if is_function and low not in functions:
                    self._report(
                        f"{path} calls '{name}()', which is not available there.",
                        pos,
                    )
                elif not is_function and low not in values:
                    shown = ", ".join(sorted(values))
                    self._report(
                        f"{path} uses '{name}', which is not available there "
                        f"(available: {shown}).",
                        pos,
                    )

    @staticmethod
    def _show(value: Any) -> str:
        kind = _kind(value)
        if kind == "mapping":
            return "a mapping"
        if kind == "sequence":
            return "a list"
        if kind == "null":
            return "empty"
        return f"'{_scalar_text(value)}'"

    @staticmethod
    def _not_allowed(value: Any, allowed: Sequence[str], path: str) -> str:
        text = _scalar_text(value)
        close = difflib.get_close_matches(text, list(allowed), n=1, cutoff=0.6)
        hint = f" Did you mean '{close[0]}'?" if close else ""
        options = ", ".join(allowed) if len(allowed) <= 14 else ""
        tail = f" Valid values: {options}." if options and not close else ""
        return f"'{text}' is not valid for {path}.{hint}{tail}"


def validate(data: Any) -> list[Problem]:
    """All schema problems in a parsed workflow (``data`` from ruamel)."""
    return SchemaValidator().validate(data)
