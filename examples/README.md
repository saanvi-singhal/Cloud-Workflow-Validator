# Examples

Static example files for each supported format. They are never executed. The
backend test `backend/tests/integration/test_examples.py` analyses every file
here and checks it produces the result described below, so the examples
cannot drift from what the tool actually does.

Each file's header comment says what it demonstrates and what to expect.

| File | Expected result |
| --- | --- |
| `yaml/valid_pipeline.yml` | Valid, with an execution order |
| `yaml/unresolved_needs.yml` | Invalid: `UNRESOLVED_DEPENDENCY` |
| `yaml/cyclic_needs.yml` | Invalid: `DEPENDENCY_CYCLE` |
| `yaml/schema_errors.yml` | Invalid: `YAML_SYNTAX_ERROR` (unknown event and key, missing `runs-on`, empty step, `secrets` in `if`) |
| `yaml/script_injection.yml` | Valid with a `GHA_SCRIPT_INJECTION` warning |
| `dockerfile/multi_stage.Dockerfile` | Valid, no findings |
| `dockerfile/unused_stage.Dockerfile` | Valid with an `UNREACHABLE_NODE` warning |
| `dockerfile/copy_from_typo.Dockerfile` | Valid with an `UNRESOLVED_DEPENDENCY` warning ("did you mean") |
| `dockerfile/best_practices.Dockerfile` | Invalid: `DF_*` rule findings, including `DF_APT_MISSING_YES` (error) |
| `dockerfile/syntax_errors.Dockerfile` | Invalid: `DOCKERFILE_SYNTAX_ERROR` |
| `terraform/valid_network.tf` | Valid, no findings |
| `terraform/depends_on.tf` | Valid, no findings |
| `terraform/dynamic_blocks.tf` | Valid, no findings |
| `terraform/cyclic.tf` | Invalid: `DEPENDENCY_CYCLE` |
| `terraform/unresolved_reference.tf` | Invalid: `UNRESOLVED_DEPENDENCY` |
| `terraform/unsupported_expression.tf` | Valid but partial: `UNSUPPORTED_CONSTRUCT` |
| `terraform/security_findings.tf` | Valid with `SECURITY_RULE_VIOLATION` warnings |
