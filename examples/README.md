# Sample Workflow and Infrastructure Examples

This directory contains reference and test fixture files used for testing the Compiler-Based Cloud Workflow Validator.

## Subdirectories

- **`yaml/`**: Sample CI/CD workflow manifests (such as GitHub Actions workflow definitions) exhibiting valid patterns, dependency chains, missing inputs, and intentional cycle errors.
- **`dockerfile/`**: Sample container specifications demonstrating multi-stage builds, layer caching antipatterns, and missing dependencies.
- **`terraform/`**: Sample Terraform configurations (`.tf`) featuring resource dependency graphs, module references, cyclic references, and orphan resources.

These fixtures serve as test cases for the language adapters, intermediate representation (IR) constructors, and graph analysis algorithms.
