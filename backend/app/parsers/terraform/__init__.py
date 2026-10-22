"""Terraform/HCL adapter (single and multi-file).

Pipeline inside the adapter::

    source text --parse_hcl--> Lark tree --read_file--> blocks
        --extract--> IR + findings --run_terraform_rules--> security findings

Nothing is evaluated: no variables are resolved, no providers are contacted,
and terraform is never run.
"""

from __future__ import annotations

from app.compiler.adapters import ParseResult
from app.compiler.findings import Finding, make_finding
from app.models import DiagnosticCode, Severity, SourceFormat, SourceLocation
from app.parsers.terraform.blocks import TerraformFile, read_file
from app.parsers.terraform.extractor import extract, extract_files
from app.parsers.terraform.hcl_loader import HclSyntaxError, parse_hcl
from app.parsers.terraform.validate import validate_file


def _with_validation(
    findings: list[Finding], files: list[TerraformFile]
) -> list[Finding]:
    """Add Terraform's structural errors (validate.py).

    They replace the extractor's "unknown top-level block type" and "expected
    N label(s)" warnings, which describe the same problem less precisely.
    """
    errors = [f for tf in files for f in validate_file(tf)]
    kept = [
        f
        for f in findings
        if not (
            f.code == DiagnosticCode.UNSUPPORTED_CONSTRUCT
            and (
                "unknown top-level block type" in f.diagnostic.message
                or "label(s)" in f.diagnostic.message
                or "top-level attributes are not valid" in f.diagnostic.message
            )
        )
    ]
    return [*kept, *errors]


class TerraformAdapter:
    """``SourceAdapter`` implementation for Terraform."""

    format = SourceFormat.terraform

    def parse(self, source: str, filename: str | None) -> ParseResult:
        try:
            tree = parse_hcl(source)
        except HclSyntaxError as exc:
            location: SourceLocation | None = None
            if exc.line is not None or filename is not None:
                location = SourceLocation(
                    file=filename, start_line=exc.line, start_column=exc.column
                )
            finding = make_finding(
                DiagnosticCode.TERRAFORM_SYNTAX_ERROR,
                Severity.error,
                f"Terraform syntax error: {exc.message}",
                location,
            )
            return ParseResult(ir=None, findings=[finding])

        terraform_file = read_file(tree, filename)
        extraction = extract(terraform_file, filename)
        provider_blocks = [
            (block, None) for block in terraform_file.blocks if block.type == "provider"
        ]
        # Imported here: the rules import this package's `blocks` module, so a
        # module-level import would be circular when the rules load first.
        from app.rules.terraform_rules import run_terraform_rules

        rule_findings = run_terraform_rules([*extraction.modelled, *provider_blocks])
        return ParseResult(
            ir=extraction.ir,
            findings=_with_validation(extraction.findings, [terraform_file])
            + rule_findings,
            dependency_analysis_complete=extraction.complete,
        )

    def parse_files(self, files: list[tuple[str, str]]) -> ParseResult:
        """Parse multiple ``.tf`` files into a single unified module IR."""
        if len(files) == 1:
            filename, source = files[0]
            return self.parse(source, filename)

        findings: list[Finding] = []
        parsed_files: list[tuple[str, TerraformFile]] = []
        all_provider_blocks = []

        for filename, source in files:
            try:
                tree = parse_hcl(source)
            except HclSyntaxError as exc:
                loc = SourceLocation(
                    file=filename, start_line=exc.line, start_column=exc.column
                )
                findings.append(
                    make_finding(
                        DiagnosticCode.TERRAFORM_SYNTAX_ERROR,
                        Severity.error,
                        f"Terraform syntax error in '{filename}': {exc.message}",
                        loc,
                    )
                )
                continue

            tf_file = read_file(tree, filename)
            parsed_files.append((filename, tf_file))
            for block in tf_file.blocks:
                if block.type == "provider":
                    all_provider_blocks.append((block, None))

        if not parsed_files and findings:
            return ParseResult(ir=None, findings=findings)

        extraction = extract_files(parsed_files)
        from app.rules.terraform_rules import run_terraform_rules

        rule_findings = run_terraform_rules(
            [*extraction.modelled, *all_provider_blocks]
        )
        return ParseResult(
            ir=extraction.ir,
            findings=[
                *findings,
                *_with_validation(extraction.findings, [tf for _, tf in parsed_files]),
                *rule_findings,
            ],
            dependency_analysis_complete=extraction.complete,
        )


ADAPTER = TerraformAdapter()
