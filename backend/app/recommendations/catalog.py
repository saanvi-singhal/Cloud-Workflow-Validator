"""The recommendation rules: one small function per diagnostic code.

Every rule is deterministic: the same finding always yields the same
recommendation. Each rule follows spec 6.2:

* it explains the problem and, where possible, proposes a change;
* ``fix_kind`` is ``judgment`` whenever the tool cannot prove the change is
  safe. In v1 that is every rule, because removing a dependency or changing
  an ACL alters behaviour, so none is labelled ``deterministic``;
* a ``preview`` is only given when the exact edit is known (e.g. a typo with
  a close match); otherwise only a description is given;
* nothing here modifies source. Recommendations are text.
"""

from __future__ import annotations

import difflib
import json
from collections.abc import Callable
from dataclasses import dataclass, field

from app.compiler.findings import EdgeKey, Finding
from app.models import (
    DiagnosticCode,
    Edge,
    EdgeType,
    FixKind,
    Node,
    ProposedChange,
    Recommendation,
    Severity,
)


@dataclass(frozen=True)
class RecommendationContext:
    """Read-only view of the analysed graph that rules may consult."""

    nodes: dict[str, Node] = field(default_factory=dict)
    edges: dict[EdgeKey, Edge] = field(default_factory=dict)

    def label(self, node_id: str) -> str:
        node = self.nodes.get(node_id)
        return node.label if node is not None else node_id


Rule = Callable[[Finding, int, RecommendationContext], Recommendation | None]


def _make(
    rule_id: str,
    finding: Finding,
    index: int,
    title: str,
    explanation: str,
    change: ProposedChange | None = None,
) -> Recommendation:
    return Recommendation(
        id=f"{rule_id}:{index}",
        rule_id=rule_id,
        title=title,
        explanation=explanation,
        diagnostic_code=finding.code,
        diagnostic_index=index,
        fix_kind=FixKind.judgment,
        proposed_change=change,
        source_location=finding.diagnostic.source_location,
        related_node_ids=list(finding.node_ids),
    )


# --- graph-level rules ---------------------------------------------------------


def break_dependency_cycle(
    finding: Finding, index: int, ctx: RecommendationContext
) -> Recommendation:
    path: list[str] = list(finding.details.get("path", []))
    if len(path) == 2:
        name = ctx.label(path[0])
        return _make(
            "BREAK_DEPENDENCY_CYCLE",
            finding,
            index,
            f"Remove the self-dependency of '{name}'",
            f"'{name}' depends on itself, so it can never be ready. Remove the "
            "reference to itself (in Terraform, use 'self' only inside "
            "provisioners/conditions where it is allowed).",
            ProposedChange(
                description=f"Remove the reference from '{name}' to itself.",
                source_location=finding.diagnostic.source_location,
            ),
        )

    steps: list[str] = []
    explicit: list[str] = []
    for key in finding.edge_keys:
        edge = ctx.edges.get(key)
        source, target = ctx.label(key[0]), ctx.label(key[1])
        via = f" (via '{edge.label}')" if edge is not None and edge.label else ""
        step = f"'{target}' depends on '{source}'{via}"
        if key[2] == EdgeType.terraform_explicit_dependency.value:
            explicit.append(step)
        else:
            steps.append(step)

    candidates = explicit + steps  # explicit depends_on entries are named first
    explanation = (
        "No valid execution order exists while this cycle remains. Break it by "
        "removing or inverting one of these dependencies: "
        + "; ".join(candidates)
        + "."
    )
    if explicit:
        explanation += (
            " Explicit depends_on entries are often the easiest to drop if "
            "they are not strictly required."
        )
    return _make(
        "BREAK_DEPENDENCY_CYCLE",
        finding,
        index,
        "Break the dependency cycle",
        explanation,
        ProposedChange(
            description="Remove one dependency on the cycle; which one depends "
            "on your intent, so this is not done automatically.",
            source_location=finding.diagnostic.source_location,
        ),
    )


def resolve_missing_dependency(
    finding: Finding, index: int, ctx: RecommendationContext
) -> Recommendation:
    address = finding.details.get("address")
    known = list(finding.details.get("known_addresses", []))
    if not isinstance(address, str):
        return _make(
            "RESOLVE_MISSING_DEPENDENCY",
            finding,
            index,
            "Declare the missing dependency",
            "The referenced item does not exist. Declare it, or correct the name.",
        )

    matches = difflib.get_close_matches(address, known, n=1, cutoff=0.6)
    if matches:
        suggestion = matches[0]
        return _make(
            "RESOLVE_MISSING_DEPENDENCY",
            finding,
            index,
            f"Did you mean '{suggestion}'?",
            f"'{address}' is not declared, but '{suggestion}' is and has a very "
            "similar name. If this is a typo, correct the reference.",
            ProposedChange(
                description=f"Replace '{address}' with '{suggestion}'.",
                preview=f"- {address}\n+ {suggestion}",
                source_location=finding.diagnostic.source_location,
            ),
        )
    if finding.details.get("context_file"):
        return _make(
            "RESOLVE_MISSING_DEPENDENCY",
            finding,
            index,
            f"Upload '{address}' to check it",
            f"'{address}' comes from the build context, which was only partly "
            "uploaded. Add it to the upload to have it checked; nothing else "
            "is needed if it exists in your build context.",
        )
    return _make(
        "RESOLVE_MISSING_DEPENDENCY",
        finding,
        index,
        f"Declare '{address}'",
        f"'{address}' is not declared in this file. Declare it here or correct "
        "the reference (multi-file projects are not analysed in v1).",
    )


def rename_duplicate(
    finding: Finding, index: int, ctx: RecommendationContext
) -> Recommendation:
    return _make(
        "RENAME_DUPLICATE",
        finding,
        index,
        "Rename or remove the duplicate declaration",
        "Two declarations share one identity, so references to it are "
        "ambiguous. Rename one of them, or delete it if it is an accidental copy.",
    )


def review_disconnected(
    finding: Finding, index: int, ctx: RecommendationContext
) -> Recommendation:
    return _make(
        "REVIEW_DISCONNECTED",
        finding,
        index,
        "Check whether a dependency is missing",
        "This part of the graph has no dependency relationship with the rest. "
        "That is often intentional (independent resources or jobs); if it "
        "should run before or after something else, add that dependency.",
    )


def review_unreachable(
    finding: Finding, index: int, ctx: RecommendationContext
) -> Recommendation:
    return _make(
        "REVIEW_UNUSED_NODE",
        finding,
        index,
        "Remove or use the unused stage",
        "Nothing the build target needs depends on this. Remove it, make a "
        "needed stage depend on it, or build it explicitly as a target.",
    )


def explain_unsupported(
    finding: Finding, index: int, ctx: RecommendationContext
) -> Recommendation | None:
    if finding.severity is Severity.info:
        return None  # informational only; it does not limit dependency analysis
    return _make(
        "UNSUPPORTED_LIMITATION",
        finding,
        index,
        "Analysis is partial here",
        "This construct is not analysed in v1, so dependencies inside it are "
        "missing from the graph and the execution order is withheld. The "
        "configuration may still be valid; review this part manually.",
    )


def report_invalid_graph(
    finding: Finding, index: int, ctx: RecommendationContext
) -> Recommendation:
    return _make(
        "REPORT_INTERNAL_INCONSISTENCY",
        finding,
        index,
        "Internal parser inconsistency",
        "The parser produced an inconsistent graph. This is a bug in the "
        "validator, not in your configuration; please report it.",
    )


def fix_syntax_error(
    finding: Finding, index: int, ctx: RecommendationContext
) -> Recommendation:
    return _make(
        "FIX_SYNTAX_ERROR",
        finding,
        index,
        "Fix the syntax or structure error",
        "The file is not valid for the selected format, so its dependencies "
        "may not have been analysed. Fix the problem at the reported position "
        "(or choose the right format) and validate again.",
    )


# --- security rules -------------------------------------------------------------


def _security_s3_public_acl(finding: Finding, index: int) -> Recommendation:
    value = finding.details.get("value", "public-read")
    return _make(
        "TF_S3_PUBLIC_ACL",
        finding,
        index,
        "Make the bucket ACL private",
        "A public ACL lets anyone on the internet read the bucket's objects. "
        "Unless the bucket intentionally hosts public content, use a private "
        "ACL and an aws_s3_bucket_public_access_block.",
        ProposedChange(
            description="Change the ACL to 'private' if public access is not needed.",
            preview=f'- acl = "{value}"\n+ acl = "private"',
            source_location=finding.diagnostic.source_location,
        ),
    )


def _security_open_ingress(finding: Finding, index: int) -> Recommendation:
    return _make(
        "TF_SG_OPEN_INGRESS",
        finding,
        index,
        "Restrict ingress to known address ranges",
        "Ingress from 0.0.0.0/0 or ::/0 accepts traffic from any address. "
        "Limit it to the CIDR ranges that actually need access (e.g. a VPN or "
        "office range), or put the service behind a load balancer.",
        ProposedChange(
            description="Replace the open CIDR with the specific ranges that "
            "need access (the right range cannot be inferred).",
            source_location=finding.diagnostic.source_location,
        ),
    )


def _security_hardcoded_secret(finding: Finding, index: int) -> Recommendation:
    attribute = finding.details.get("attribute", "the attribute")
    return _make(
        "TF_HARDCODED_SECRET",
        finding,
        index,
        "Move the secret out of source code",
        f"'{attribute}' holds a literal secret that anyone with repository "
        "access can read. Pass it through a variable marked sensitive = true "
        "or read it from a secrets manager, and rotate the exposed value.",
        ProposedChange(
            description="Replace the literal with a sensitive variable or a "
            "secrets-manager lookup.",
            source_location=finding.diagnostic.source_location,
        ),
    )


def _security_db_public(finding: Finding, index: int) -> Recommendation:
    return _make(
        "TF_DB_PUBLICLY_ACCESSIBLE",
        finding,
        index,
        "Disable public access to the database",
        "A publicly accessible database can be reached from the internet. "
        "Keep it in private subnets and connect through the application tier.",
        ProposedChange(
            description="Set publicly_accessible to false.",
            preview="- publicly_accessible = true\n+ publicly_accessible = false",
            source_location=finding.diagnostic.source_location,
        ),
    )


def _df_exec_form_not_json(finding: Finding, index: int) -> Recommendation:
    value = finding.details.get("value", "")
    fixed = value.replace("'", '"')
    preview = None
    try:
        if isinstance(json.loads(fixed), list):
            preview = f"- {value}\n+ {fixed}"
    except ValueError:
        pass
    return _make(
        "DF_EXEC_FORM_NOT_JSON",
        finding,
        index,
        "Write the exec form as a JSON array",
        "Docker only treats [...] as a list of arguments when it is valid JSON. "
        "Otherwise it hands the whole line to /bin/sh, brackets and quotes "
        "included, and the command fails.",
        ProposedChange(
            description="Use double quotes for every element.",
            preview=preview,
            source_location=finding.diagnostic.source_location,
        ),
    )


def _df_apt_missing_yes(finding: Finding, index: int) -> Recommendation:
    command = finding.details.get("command", "")
    sub = finding.details.get("subcommand", "install")
    words = command.split()
    change = ProposedChange(
        description=f"Add -y so apt does not wait for confirmation "
        f"(apt-get {sub} -y ...).",
        source_location=finding.diagnostic.source_location,
    )
    if sub in words:
        fixed = words[: words.index(sub) + 1] + ["-y"] + words[words.index(sub) + 1 :]
        change.preview = f"- {command}\n+ {' '.join(fixed)}"
    return _make(
        "DF_APT_MISSING_YES",
        finding,
        index,
        "Add -y to the apt command",
        "Docker builds have no terminal to answer apt's 'Do you want to "
        "continue?' prompt, so apt aborts and the build fails.",
        change,
    )


def _df_unpinned_base_image(finding: Finding, index: int) -> Recommendation:
    image = finding.details.get("image", "the image")
    return _make(
        "DF_UNPINNED_BASE_IMAGE",
        finding,
        index,
        "Pin the base image version",
        f"'{image}' is resolved again on every build, so a new upstream release "
        "can change or break the image without any change to this file.",
        ProposedChange(
            description="Use a specific version tag (for example name:22-slim), "
            "or a digest (name@sha256:...) for fully reproducible builds. The "
            "right version cannot be inferred from this file.",
            source_location=finding.diagnostic.source_location,
        ),
    )


def _df_runs_as_root(finding: Finding, index: int) -> Recommendation:
    return _make(
        "DF_RUNS_AS_ROOT",
        finding,
        index,
        "Run the container as a non-root user",
        "A process running as root inside the container has more power if it is "
        "compromised. Create or reuse an unprivileged user and switch to it after "
        "the steps that need root.",
        ProposedChange(
            description="Add a USER instruction before CMD/ENTRYPOINT (many base "
            "images already provide one, e.g. 'node' in node images).",
            preview="+ RUN useradd --create-home --uid 10001 app\n+ USER app",
            source_location=finding.diagnostic.source_location,
        ),
    )


def _df_apt_update_alone(finding: Finding, index: int) -> Recommendation:
    return _make(
        "DF_APT_UPDATE_ALONE",
        finding,
        index,
        "Run apt-get update and install in one RUN",
        "The layer with 'apt-get update' is cached, so later builds reuse an old "
        "package index and installs can fail or get outdated packages.",
        ProposedChange(
            description="Merge update, install and cleanup into one RUN.",
            preview="+ RUN apt-get update \\\n"
            "+  && apt-get install -y --no-install-recommends <packages> \\\n"
            "+  && rm -rf /var/lib/apt/lists/*",
            source_location=finding.diagnostic.source_location,
        ),
    )


def _df_apt_upgrade(finding: Finding, index: int) -> Recommendation:
    return _make(
        "DF_APT_UPGRADE",
        finding,
        index,
        "Avoid upgrading all packages in the build",
        "An upgrade installs whatever is newest at build time, so the same "
        "Dockerfile produces different images on different days.",
        ProposedChange(
            description="Remove the upgrade and use a newer pinned base image; "
            "install specific package versions if one needs a fix.",
            source_location=finding.diagnostic.source_location,
        ),
    )


def _df_add_local_file(finding: Finding, index: int) -> Recommendation:
    value = finding.details.get("value")
    return _make(
        "DF_ADD_LOCAL_FILE",
        finding,
        index,
        "Use COPY for local files",
        "ADD can also fetch URLs and unpack archives, which makes it easy to do "
        "more than intended. COPY only copies.",
        ProposedChange(
            description="Replace ADD with COPY.",
            preview=f"- ADD {value}\n+ COPY {value}" if value else None,
            source_location=finding.diagnostic.source_location,
        ),
    )


def _df_copy_all_before_install(finding: Finding, index: int) -> Recommendation:
    return _make(
        "DF_COPY_ALL_BEFORE_INSTALL",
        finding,
        index,
        "Install dependencies before copying the source",
        "Docker re-runs every step after the first changed layer. Copying only "
        "the dependency manifest first keeps the install cached until the "
        "dependencies themselves change.",
        ProposedChange(
            description="Copy the manifest, install, then copy everything else "
            "(example for npm).",
            preview="+ COPY package.json package-lock.json ./\n"
            "+ RUN npm ci\n"
            "  COPY . .",
            source_location=finding.diagnostic.source_location,
        ),
    )


def _df_consecutive_run(finding: Finding, index: int) -> Recommendation:
    return _make(
        "DF_CONSECUTIVE_RUN",
        finding,
        index,
        "Combine related RUN instructions",
        "Each RUN creates a layer. Deleting files in a later RUN hides them but "
        "does not remove them from the earlier layer, so the image stays large.",
        ProposedChange(
            description="Chain related commands with && in a single RUN, putting "
            "cleanup in the same RUN as the step that creates the files.",
            source_location=finding.diagnostic.source_location,
        ),
    )


def _df_apt_unpinned_packages(finding: Finding, index: int) -> Recommendation:
    packages = finding.details.get("packages", [])
    return _make(
        "DF_APT_UNPINNED_PACKAGES",
        finding,
        index,
        "Pin package versions if builds must be reproducible",
        "Without versions, apt installs whatever the package index offers at "
        "build time. This is a tradeoff: pinned versions must be updated by hand.",
        ProposedChange(
            description="Pin as name=version, e.g. "
            + ", ".join(f"{p}=<version>" for p in packages[:3]),
            source_location=finding.diagnostic.source_location,
        ),
    )


def _df_curl_pipe_shell(finding: Finding, index: int) -> Recommendation:
    return _make(
        "DF_CURL_PIPE_SHELL",
        finding,
        index,
        "Verify downloaded scripts before running them",
        "Piping a download into a shell runs whatever the server sends, and a "
        "URL on a branch (such as /main/) can change between builds. Pin the "
        "URL to a release and check a published checksum first.",
        ProposedChange(
            description="Download to a file, verify its SHA-256, then run it.",
            preview="- curl -sfL <url> | sh -s -- <args>\n"
            "+ curl -sfLo /tmp/install.sh <url-of-a-release>\n"
            '+ echo "<sha256>  /tmp/install.sh" | sha256sum -c -\n'
            "+ sh /tmp/install.sh <args>",
            source_location=finding.diagnostic.source_location,
        ),
    )


def _df_apk_no_cache(finding: Finding, index: int) -> Recommendation:
    command = finding.details.get("command", "apk add")
    fixed = command.replace("apk add", "apk add --no-cache", 1)
    return _make(
        "DF_APK_NO_CACHE",
        finding,
        index,
        "Use apk add --no-cache",
        "--no-cache fetches the package index for this command only, so it "
        "is not stored in the image layer.",
        ProposedChange(
            description="Add --no-cache to apk add.",
            preview=f"- {command}\n+ {fixed}",
            source_location=finding.diagnostic.source_location,
        ),
    )


def _df_apk_unpinned_packages(finding: Finding, index: int) -> Recommendation:
    packages = finding.details.get("packages", [])
    return _make(
        "DF_APK_UNPINNED_PACKAGES",
        finding,
        index,
        "Pin package versions if builds must be reproducible",
        "Without versions, apk installs whatever the repository offers at "
        "build time. This is a tradeoff: pinned versions must be updated by hand.",
        ProposedChange(
            description="Pin as name=version or name~major.minor, e.g. "
            + ", ".join(f"{p}~<version>" for p in packages[:3]),
            source_location=finding.diagnostic.source_location,
        ),
    )


def _gha_number_loses_zero(finding: Finding, index: int) -> Recommendation:
    text = finding.details.get("text", "")
    seen = finding.details.get("seen", "")
    return _make(
        "GHA_NUMBER_LOSES_ZERO",
        finding,
        index,
        "Quote the version number",
        f"Unquoted, {text} is a number, and GitHub turns it into the string "
        f"'{seen}'. For versions this silently selects the wrong one (3.10 "
        "becomes 3.1).",
        ProposedChange(
            description=f'Write the value as the string "{text}".',
            preview=f'- {text}\n+ "{text}"',
            source_location=finding.diagnostic.source_location,
        ),
    )


def _gha_script_injection(finding: Finding, index: int) -> Recommendation:
    expression = finding.details.get("expression", "${{ ... }}")
    field = finding.details.get("field", "")
    name = (field.rsplit(".", 1)[-1] or "VALUE").upper()
    return _make(
        "GHA_SCRIPT_INJECTION",
        finding,
        index,
        "Pass untrusted input through an environment variable",
        "An expression in a script is replaced by its text before the script "
        "runs, so a crafted issue title or branch name becomes shell code. An "
        "environment variable is passed as data and never parsed as code.",
        ProposedChange(
            description=f"Set {name} from the expression in the step's env and "
            f'use "${name}" (quoted) in the script.',
            preview=f"+ env:\n+   {name}: {expression}\n"
            f'- ... {expression} ...\n+ ... "${name}" ...',
            source_location=finding.diagnostic.source_location,
        ),
    )


def _gha_unpinned_action(finding: Finding, index: int) -> Recommendation:
    uses = finding.details.get("uses", "")
    action = finding.details.get("action", uses)
    return _make(
        "GHA_UNPINNED_ACTION",
        finding,
        index,
        "Pin the action to a release or commit",
        "A branch can be changed at any time, including by an attacker who "
        "takes over the action's repository (as happened to tj-actions/"
        "changed-files in 2025). A commit SHA cannot change; a release tag "
        "rarely does. Look up the release you want on the action's page.",
        ProposedChange(
            description="Replace the branch with a full commit SHA (keep the "
            "version in a comment), or at least a release tag.",
            preview=f"- uses: {uses}\n+ uses: {action}@<40-char commit SHA> # vX.Y.Z",
            source_location=finding.diagnostic.source_location,
        ),
    )


SECURITY_RECOMMENDATIONS: dict[str, Callable[[Finding, int], Recommendation]] = {
    "TF_S3_PUBLIC_ACL": _security_s3_public_acl,
    "TF_SG_OPEN_INGRESS": _security_open_ingress,
    "TF_HARDCODED_SECRET": _security_hardcoded_secret,
    "TF_DB_PUBLICLY_ACCESSIBLE": _security_db_public,
    "DF_EXEC_FORM_NOT_JSON": _df_exec_form_not_json,
    "DF_APT_MISSING_YES": _df_apt_missing_yes,
    "DF_UNPINNED_BASE_IMAGE": _df_unpinned_base_image,
    "DF_RUNS_AS_ROOT": _df_runs_as_root,
    "DF_APT_UPDATE_ALONE": _df_apt_update_alone,
    "DF_APT_UPGRADE": _df_apt_upgrade,
    "DF_ADD_LOCAL_FILE": _df_add_local_file,
    "DF_COPY_ALL_BEFORE_INSTALL": _df_copy_all_before_install,
    "DF_CONSECUTIVE_RUN": _df_consecutive_run,
    "DF_APT_UNPINNED_PACKAGES": _df_apt_unpinned_packages,
    "DF_CURL_PIPE_SHELL": _df_curl_pipe_shell,
    "DF_APK_NO_CACHE": _df_apk_no_cache,
    "DF_APK_UNPINNED_PACKAGES": _df_apk_unpinned_packages,
    "GHA_NUMBER_LOSES_ZERO": _gha_number_loses_zero,
    "GHA_SCRIPT_INJECTION": _gha_script_injection,
    "GHA_UNPINNED_ACTION": _gha_unpinned_action,
}


def security_recommendation(
    finding: Finding, index: int, ctx: RecommendationContext
) -> Recommendation:
    specific = SECURITY_RECOMMENDATIONS.get(finding.rule_id or "")
    if specific is not None:
        return specific(finding, index)
    return _make(
        finding.rule_id or "SECURITY_REVIEW",
        finding,
        index,
        "Review the security finding",
        "A security rule flagged this configuration; review it before deploying.",
    )


CATALOG: dict[DiagnosticCode, Rule] = {
    DiagnosticCode.DEPENDENCY_CYCLE: break_dependency_cycle,
    DiagnosticCode.UNRESOLVED_DEPENDENCY: resolve_missing_dependency,
    DiagnosticCode.DUPLICATE_NODE_ID: rename_duplicate,
    DiagnosticCode.DISCONNECTED_COMPONENT: review_disconnected,
    DiagnosticCode.UNREACHABLE_NODE: review_unreachable,
    DiagnosticCode.UNSUPPORTED_CONSTRUCT: explain_unsupported,
    DiagnosticCode.INVALID_GRAPH: report_invalid_graph,
    DiagnosticCode.YAML_SYNTAX_ERROR: fix_syntax_error,
    DiagnosticCode.DOCKERFILE_SYNTAX_ERROR: fix_syntax_error,
    DiagnosticCode.TERRAFORM_SYNTAX_ERROR: fix_syntax_error,
    DiagnosticCode.SECURITY_RULE_VIOLATION: security_recommendation,
    # SOURCE_TOO_LARGE is an API-level rejection; no analysis result exists.
}
