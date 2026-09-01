"""Extension ↔ kernel dependency-direction enforcement (PR4 Lane A).

Mirror of :mod:`tests.compat.test_kernel_dependency_direction` for the
``arw_ext.*`` extension packages that ship in the same wheel:

* The kernel MUST NOT import any ``arw_ext.*`` module — extensions register
  capabilities at the composition root only.
* The CLI / CLI-support layer MUST NOT import concrete adapters / extensions
  directly — only ``arw.composition`` may resolve them.

The test walks AST imports so it runs fast and needs no third-party tooling.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.v2_compat

KERNEL_ROOT = Path(__file__).resolve().parents[2] / "src" / "arw" / "kernel"
SRC_ROOT = KERNEL_ROOT.parent
EXTENSION_ROOT = (
    Path(__file__).resolve().parents[2] / "extensions" / "local-store" / "src"
)


def _imports_of(path: Path) -> set[str]:
    """Return the set of arw.* / arw_ext.* modules a file imports."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    package_parts = list(
        path.relative_to(EXTENSION_ROOT).with_suffix("").parts[:-1]
        if EXTENSION_ROOT in path.parents
        else path.relative_to(SRC_ROOT).with_suffix("").parts[:-1]
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                anchor = package_parts[: len(package_parts) - (node.level - 1)]
                resolved = ".".join([*anchor, node.module or ""])
                if node.module:
                    found.add(resolved)
                else:
                    for alias in node.names:
                        found.add(f"{resolved}.{alias.name}".removesuffix("."))
            else:
                if node.module and (
                    node.module.startswith("arw")
                    or node.module.startswith("arw_ext")
                ):
                    found.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("arw") or alias.name.startswith("arw_ext"):
                    found.add(alias.name)
    return found


def test_kernel_never_imports_arw_ext() -> None:
    """The kernel must depend only on ``arw.*`` and stdlib — never on extensions."""

    violations: list[str] = []
    for path in KERNEL_ROOT.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        for module in _imports_of(path):
            if module == "arw_ext" or module.startswith("arw_ext."):
                violations.append(
                    f"{path.relative_to(SRC_ROOT)}: {module}"
                )
    assert not violations, (
        "kernel must not import bundled extensions:\n"
        + "\n".join(violations)
    )


def test_cli_does_not_import_extensions_directly() -> None:
    """The CLI must resolve extensions through ``arw.composition`` only."""

    violations: list[str] = []
    for name in ("cli.py", "cli_support.py"):
        path = SRC_ROOT / name
        for module in _imports_of(path):
            if module == "arw_ext" or module.startswith("arw_ext."):
                violations.append(f"{name}: {module}")
    assert not violations, (
        "CLI must resolve extensions through the composition root only:\n"
        + "\n".join(violations)
    )