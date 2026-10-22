"""Unified-diff patches for recommendations whose exact edit is known.

A patch is text the user may apply themselves (``git apply fix.patch`` or
``patch -p1 < fix.patch``). The tool never applies it: nothing here writes a
file, and the source it reads is the text sent in the request.

A patch is only produced when the edit is certain: the text to change is
found exactly where the diagnostic points, and only once. Otherwise the
recommendation keeps its description and preview, without a patch.

==========================  ===================================================
rule_id                     edit
==========================  ===================================================
RESOLVE_MISSING_DEPENDENCY  replace a misspelled name with its close match
BREAK_DEPENDENCY_CYCLE      remove the minimum set of ``depends_on``/``needs``
                            entries that breaks the cycle (only when every
                            edge in that set is such an entry)
DF_APT_MISSING_YES          add ``-y`` to apt calls without it
DF_APK_NO_CACHE             add ``--no-cache`` to ``apk add``
DF_ADD_LOCAL_FILE           ``ADD`` -> ``COPY`` when every source is local
DF_EXEC_FORM_NOT_JSON       single quotes -> double quotes, when that makes
                            valid JSON
DF_APT_NO_RECOMMENDS        add ``--no-install-recommends``
DF_APT_LISTS_NOT_REMOVED    append ``&& rm -rf /var/lib/apt/lists/*``
DF_PIP_NO_CACHE_DIR         add ``--no-cache-dir``
GHA_NUMBER_LOSES_ZERO       quote the number
TF_S3_PUBLIC_ACL            ``acl = "private"``
TF_DB_PUBLICLY_ACCESSIBLE   ``publicly_accessible = false``
TF_HARDCODED_SECRET         reference a new sensitive variable instead
==========================  ===================================================
"""

from __future__ import annotations

import difflib
import json
import re
from collections.abc import Callable, Mapping

from app.analysis.feedback_arcs import minimum_feedback_arcs
from app.compiler.findings import EdgeKey, Finding
from app.models import EdgeType, Recommendation, SourceLocation

# Edges a patch can remove by deleting one list entry, and the relative cost
# of removing each kind of edge (see feedback_arcs.py).
REMOVABLE_EDGES = frozenset(
    {EdgeType.terraform_explicit_dependency.value, EdgeType.workflow_dependency.value}
)
REFERENCE_COST = 3


def edge_cost(key: EdgeKey) -> int:
    return 1 if key[2] in REMOVABLE_EDGES else REFERENCE_COST


def make_patch(filename: str, old: str, new: str) -> str | None:
    """A unified diff from ``old`` to ``new`` with git-style a/ b/ paths."""
    if old == new:
        return None
    lines = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    )
    # A last line without a newline needs git's marker, or the patch will
    # not apply.
    return "".join(
        line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
        for line in lines
    )


class _Source:
    """The lines of one file, edited in memory."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.lines = text.split("\n")

    def line(self, number: int) -> str:
        return self.lines[number - 1]

    def set(self, number: int, value: str | None) -> None:
        """Replace line ``number``; ``None`` deletes it (call bottom-up)."""
        if value is None:
            del self.lines[number - 1]
        else:
            self.lines[number - 1] = value

    def result(self) -> str:
        return "\n".join(self.lines)


def _token(name: str) -> re.Pattern[str]:
    # A name, not part of a longer one; `.attr` may follow a Terraform address.
    return re.compile(rf"(?<![\w.\-]){re.escape(name)}(?![\w\-])")


def _replace_once(text: str, old: re.Pattern[str], new: str) -> str | None:
    matches = list(old.finditer(text))
    if len(matches) != 1:
        return None
    m = matches[0]
    # `new` may refer to groups (\1); escape backslashes in plain names first.
    return text[: m.start()] + m.expand(new) + text[m.end() :]


def _span(location: SourceLocation) -> tuple[int, int] | None:
    """0-based [start, end) columns of a single-line location, if known."""
    if (
        location.start_line is None
        or location.start_column is None
        or location.end_column is None
        or location.end_line not in (None, location.start_line)
    ):
        return None
    return location.start_column - 1, location.end_column - 1


def _lines_of(location: SourceLocation) -> range:
    start = location.start_line or 1
    return range(start, (location.end_line or start) + 1)


# --- producers: (finding, recommendation, source, context) -> new text ------------


class PatchContext:
    def __init__(self, edges: Mapping[EdgeKey, object], known_names: set[str]) -> None:
        self.edges = edges
        self.known_names = known_names


Producer = Callable[[Finding, Recommendation, _Source, PatchContext], str | None]


def _did_you_mean(
    finding: Finding, rec: Recommendation, src: _Source, ctx: PatchContext
) -> str | None:
    address = finding.details.get("address")
    known = list(finding.details.get("known_addresses", []))
    location = finding.diagnostic.source_location
    if not isinstance(address, str) or location is None or location.start_line is None:
        return None
    matches = difflib.get_close_matches(address, known, n=1, cutoff=0.6)
    if not matches:
        return None
    suggestion = matches[0].replace("\\", "\\\\")
    line = src.line(location.start_line)
    span = _span(location)
    if span is not None and address in line[span[0] : span[1]]:
        inner = _replace_once(line[span[0] : span[1]], _token(address), suggestion)
        new = None if inner is None else line[: span[0]] + inner + line[span[1] :]
    else:
        new = _replace_once(line, _token(address), suggestion)
    if new is None:
        return None
    src.set(location.start_line, new)
    return src.result()


def _remove_list_entry(src: _Source, location: SourceLocation) -> bool:
    """Delete one ``depends_on``/``needs`` entry at ``location``."""
    span = _span(location)
    if span is None or location.start_line is None:
        return False
    number = location.start_line
    line = src.line(number)
    start, end = span
    item = line[start:end]
    before, after = line[:start], line[end:]
    stripped = line.strip()
    # A whole line: `- build` (YAML block list), `aws_a.x,` (HCL multi-line
    # list) or `needs: build` (a single YAML scalar).
    if stripped in (f"- {item}", item, f"{item},") or re.fullmatch(
        rf"needs:\s*{re.escape(item)}", stripped
    ):
        src.set(number, None)
        return True
    # Inside a flow list on one line: drop the entry and one comma.
    if re.match(r"\s*,", after):
        after = re.sub(r"^\s*,\s*", "", after)
    elif re.search(r",\s*$", before):
        before = re.sub(r",\s*$", "", before)
    elif not (re.search(r"\[\s*$", before) and re.match(r"\s*\]", after)):
        return False
    src.set(number, before + after)
    return True


def _break_cycle(
    finding: Finding, rec: Recommendation, src: _Source, ctx: PatchContext
) -> str | None:
    removal = cycle_removal(finding, ctx.edges)
    if not removal or any(key[2] not in REMOVABLE_EDGES for key in removal):
        return None
    locations = []
    for key in removal:
        edge = ctx.edges.get(key)
        location = getattr(edge, "source_location", None)
        if location is None:
            return None
        locations.append(location)
    # Bottom-up and right-to-left, so earlier positions stay valid.
    for location in sorted(
        locations, key=lambda loc: (loc.start_line, loc.start_column), reverse=True
    ):
        if not _remove_list_entry(src, location):
            return None
    return src.result()


def cycle_removal(
    finding: Finding, edges: Mapping[EdgeKey, object]
) -> tuple[EdgeKey, ...]:
    """The cheapest edges to remove to break the cycle of ``finding``."""
    component = set(finding.details.get("component", finding.node_ids))
    inside = [k for k in edges if k[0] in component and k[1] in component]
    if not inside:
        inside = list(finding.edge_keys)
    return minimum_feedback_arcs(inside, {k: edge_cost(k) for k in inside}).edges


def _each_line(
    finding: Finding, src: _Source, fix: Callable[[str], str | None]
) -> str | None:
    location = finding.diagnostic.source_location
    if location is None or location.start_line is None:
        return None
    changed = False
    for number in _lines_of(location):
        new = fix(src.line(number))
        if new is not None and new != src.line(number):
            src.set(number, new)
            changed = True
    return src.result() if changed else None


_APT_CALL = re.compile(
    r"\b(apt-get|apt)\b((?:\s+-\S+)*)\s+"
    r"(install|upgrade|dist-upgrade|full-upgrade|remove|purge|autoremove)\b"
)
_COMMAND_END = re.compile(r"&&|\|\||;|\||\\\s*$|$")


def _command_rest(line: str, start: int) -> str:
    """The rest of one shell command on this line, from ``start``."""
    m = _COMMAND_END.search(line, start)
    return line[start : m.start() if m else len(line)]


def _apt_yes(
    finding: Finding, rec: Recommendation, src: _Source, ctx: PatchContext
) -> str | None:
    def fix(line: str) -> str:
        for m in reversed(list(_APT_CALL.finditer(line))):
            command = m.group(0) + _command_rest(line, m.end())
            if re.search(r"(?<!\S)(-\w*y\w*|--yes|--assume-yes|-qq)(?!\S)", command):
                continue
            line = line[: m.end()] + " -y" + line[m.end() :]
        return line

    return _each_line(finding, src, fix)


def _apt_no_recommends(
    finding: Finding, rec: Recommendation, src: _Source, ctx: PatchContext
) -> str | None:
    def fix(line: str) -> str:
        for m in reversed(
            list(re.finditer(r"\b(apt-get|apt)\b(?:\s+-\S+)*\s+install\b", line))
        ):
            if "--no-install-recommends" in _command_rest(line, m.end()):
                continue
            line = line[: m.end()] + " --no-install-recommends" + line[m.end() :]
        return line

    return _each_line(finding, src, fix)


def _apt_remove_lists(
    finding: Finding, rec: Recommendation, src: _Source, ctx: PatchContext
) -> str | None:
    location = finding.diagnostic.source_location
    if location is None or location.start_line is None:
        return None
    last = location.end_line or location.start_line
    line = src.line(last)
    if "/var/lib/apt/lists" in line or line.rstrip().endswith("\\"):
        return None
    src.set(last, line.rstrip() + " \\\n    && rm -rf /var/lib/apt/lists/*")
    return src.result()


def _pip_no_cache(
    finding: Finding, rec: Recommendation, src: _Source, ctx: PatchContext
) -> str | None:
    def fix(line: str) -> str:
        for m in reversed(list(re.finditer(r"\bpip3?\s+install\b", line))):
            if "--no-cache-dir" in _command_rest(line, m.end()):
                continue
            line = line[: m.end()] + " --no-cache-dir" + line[m.end() :]
        return line

    return _each_line(finding, src, fix)


def _apk_no_cache(
    finding: Finding, rec: Recommendation, src: _Source, ctx: PatchContext
) -> str | None:
    def fix(line: str) -> str:
        for m in reversed(list(re.finditer(r"\bapk\b(?:\s+-\S+)*\s+add\b", line))):
            if "--no-cache" in _command_rest(line, m.end()):
                continue
            line = line[: m.end()] + " --no-cache" + line[m.end() :]
        return line

    return _each_line(finding, src, fix)


def _add_to_copy(
    finding: Finding, rec: Recommendation, src: _Source, ctx: PatchContext
) -> str | None:
    value = finding.details.get("value")
    sources = finding.details.get("sources", [])
    location = finding.diagnostic.source_location
    if not isinstance(value, str) or location is None or location.start_line is None:
        return None
    words = [w for w in value.split() if not w.startswith("--")]
    if len(words) - 1 != len(sources):  # an archive or URL would change meaning
        return None
    line = src.line(location.start_line)
    new = re.sub(r"^(\s*)ADD\b", r"\1COPY", line, count=1, flags=re.IGNORECASE)
    if new == line:
        return None
    src.set(location.start_line, new)
    return src.result()


def _exec_form_json(
    finding: Finding, rec: Recommendation, src: _Source, ctx: PatchContext
) -> str | None:
    value = finding.details.get("value")
    location = finding.diagnostic.source_location
    if not isinstance(value, str) or location is None or location.start_line is None:
        return None
    fixed = value.replace("'", '"')
    try:
        parsed = json.loads(fixed)
    except ValueError:
        return None
    if not (isinstance(parsed, list) and all(isinstance(p, str) for p in parsed)):
        return None
    line = src.line(location.start_line)
    if line.count(value) != 1:
        return None
    src.set(location.start_line, line.replace(value, fixed))
    return src.result()


def _quote_number(
    finding: Finding, rec: Recommendation, src: _Source, ctx: PatchContext
) -> str | None:
    text = finding.details.get("text")
    location = finding.diagnostic.source_location
    span = _span(location) if location else None
    if not isinstance(text, str) or span is None or location is None:
        return None
    line = src.line(location.start_line or 1)
    if line[span[0] : span[1]] != text:
        return None
    src.set(location.start_line or 1, f'{line[: span[0]]}"{text}"{line[span[1] :]}')
    return src.result()


def _in_attribute(pattern: str, replacement: str) -> Producer:
    def produce(
        finding: Finding, rec: Recommendation, src: _Source, ctx: PatchContext
    ) -> str | None:
        location = finding.diagnostic.source_location
        if location is None or location.start_line is None:
            return None
        line = src.line(location.start_line)
        new = _replace_once(line, re.compile(pattern), replacement)
        if new is None:
            return None
        src.set(location.start_line, new)
        return src.result()

    return produce


def _hardcoded_secret(
    finding: Finding, rec: Recommendation, src: _Source, ctx: PatchContext
) -> str | None:
    attribute = finding.details.get("attribute")
    location = finding.diagnostic.source_location
    # A variable's own default is fixed by removing it, not by another variable.
    if not isinstance(attribute, str) or attribute == "default" or location is None:
        return None
    if location.start_line is None or attribute in ctx.known_names:
        return None
    line = src.line(location.start_line)
    new = _replace_once(
        line,
        re.compile(rf'(\b{re.escape(attribute)}\s*=\s*)"[^"$]*"'),
        rf"\1var.{attribute}",
    )
    if new is None:
        return None
    src.set(location.start_line, new)
    block = f'\nvariable "{attribute}" {{\n  type      = string\n  sensitive = true\n}}'
    text = src.result()
    return text.rstrip("\n") + "\n" + block + ("\n" if text.endswith("\n") else "")


PRODUCERS: dict[str, Producer] = {
    "RESOLVE_MISSING_DEPENDENCY": _did_you_mean,
    "BREAK_DEPENDENCY_CYCLE": _break_cycle,
    "DF_APT_MISSING_YES": _apt_yes,
    "DF_APT_NO_RECOMMENDS": _apt_no_recommends,
    "DF_APT_LISTS_NOT_REMOVED": _apt_remove_lists,
    "DF_APK_NO_CACHE": _apk_no_cache,
    "DF_PIP_NO_CACHE_DIR": _pip_no_cache,
    "DF_ADD_LOCAL_FILE": _add_to_copy,
    "DF_EXEC_FORM_NOT_JSON": _exec_form_json,
    "GHA_NUMBER_LOSES_ZERO": _quote_number,
    "TF_S3_PUBLIC_ACL": _in_attribute(r'"public-read(?:-write)?"', '"private"'),
    "TF_DB_PUBLICLY_ACCESSIBLE": _in_attribute(
        r"(?<=publicly_accessible)(\s*=\s*)true\b", r"\1false"
    ),
    "TF_HARDCODED_SECRET": _hardcoded_secret,
}


def patch_for(
    finding: Finding,
    rec: Recommendation,
    sources: Mapping[str | None, str],
    default_filename: str,
    ctx: PatchContext,
) -> str | None:
    """The unified diff for ``rec``, or None when the edit is not certain."""
    producer = PRODUCERS.get(rec.rule_id)
    location = finding.diagnostic.source_location
    if producer is None or location is None:
        return None
    text = sources.get(location.file)
    if text is None:
        return None
    try:
        new = producer(finding, rec, _Source(text), ctx)
    except (IndexError, ValueError):  # a location outside the text: no patch
        return None
    if new is None:
        return None
    return make_patch(location.file or default_filename, text, new)
