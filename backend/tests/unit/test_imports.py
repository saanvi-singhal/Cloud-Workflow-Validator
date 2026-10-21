"""Every backend module imports on its own (no circular imports)."""

import pkgutil
import subprocess
import sys
from pathlib import Path

import pytest

import app

MODULES = sorted(
    name for _, name, _ in pkgutil.walk_packages(app.__path__, prefix="app.")
)


def test_modules_were_found():
    assert "app.rules.terraform_rules" in MODULES
    assert "app.main" in MODULES


@pytest.mark.parametrize("module", MODULES)
def test_module_imports_in_a_fresh_interpreter(module):
    # A fresh interpreter, so modules other tests already imported cannot hide
    # an import cycle.
    backend = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=backend,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
