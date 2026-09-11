"""Meta-test: every third-party module actually imported somewhere in
backend/ must be importable in this environment.

This is the test that would have caught the real bug this file exists to
prevent: backend/parsers.py imported `docx`, `pdfplumber`, and `pyxlsb` (for
.docx/.pdf/.xlsb catalog parsing) but none of the three were ever listed in
requirements.txt or installed — a fresh CI-built venv (which installs only
from requirements.txt, unlike a long-lived local dev venv that accumulates
whatever's ever been pip-installed) would ship without them, silently
degrading .pdf/.docx uploads to zero rows and raising outright on .xlsb.

Walks every backend/*.py file's AST (no execution, so this can't be broken
by an unrelated runtime error), collects top-level third-party import
names, and asserts each one is importable. A new backend module that adds
an import without adding the matching requirements.txt entry now fails
this test instead of failing silently for whoever hits that code path.
"""
from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
BACKEND = APP_DIR / "backend"

# Import name -> the argument importlib.import_module() actually needs, for
# the handful of packages whose PyPI/import name diverge or whose import
# has real side effects/heavy deps we don't want a bare `import` test to run.
_IMPORT_NAME_OVERRIDES: dict[str, str] = {
    "docx": "docx",
}


def _collect_third_party_imports() -> dict[str, set[str]]:
    stdlib = set(sys.stdlib_module_names)
    local_modules = {p.stem for p in BACKEND.glob("*.py")}
    local_modules |= {p.name for p in BACKEND.iterdir() if p.is_dir() and (p / "__init__.py").exists()}

    found: dict[str, set[str]] = {}
    for py_file in BACKEND.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    found.setdefault(top, set()).add(str(py_file.relative_to(BACKEND)))
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    continue
                if node.module:
                    top = node.module.split(".")[0]
                    found.setdefault(top, set()).add(str(py_file.relative_to(BACKEND)))

    return {
        mod: files for mod, files in found.items()
        if mod not in stdlib and mod not in local_modules and mod != "__future__"
    }


def test_every_third_party_import_used_in_backend_is_installed():
    third_party = _collect_third_party_imports()
    assert third_party, "import scan found nothing — the scan itself is broken, not a real pass"

    missing: dict[str, set[str]] = {}
    for mod, files in third_party.items():
        try:
            importlib.import_module(_IMPORT_NAME_OVERRIDES.get(mod, mod))
        except ImportError:
            missing[mod] = files

    assert not missing, (
        "These modules are imported somewhere in backend/ but are not installed "
        f"(add them to requirements.txt): {missing}"
    )
