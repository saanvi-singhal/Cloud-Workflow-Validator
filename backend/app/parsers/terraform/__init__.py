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
            findings=[*extraction.findings, *rule_findings],
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

        rule_findings = run_terraform_rules([*extraction.modelled, *all_provider_blocks])
        return ParseResult(
            ir=extraction.ir,
            findings=[*findings, *extraction.findings, *rule_findings],
            dependency_analysis_complete=extraction.complete,
        )


ADAPTER = TerraformAdapter()
