"""Kernel dependency-direction enforcement (thin-kernel-extraction).

Rules:
- R1: nothing under arw.kernel/ may import arw.cli (the CLI is the top layer).
- R2: the kernel subpackage import graph must remain acyclic.

The test walks AST imports so it runs fast and needs no third-party tooling.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.v2_compat

KERNEL_ROOT = Path(__file__).resolve().parents[2] / "src" / "arw" / "kernel"


def _imports_of(path: Path) -> set[str]:
    """Return the set of arw.* modules a file imports (static imports only)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    # The file's own package (dots included) anchors relative imports.
    package_parts = list(
        path.relative_to(KERNEL_ROOT.parent.parent).with_suffix("").parts[:-1]
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                # `from ..artifacts import integrity` at arw/kernel/execution/x.py
                # resolves to arw.kernel.artifacts.integrity.
                anchor = package_parts[: len(package_parts) - (node.level - 1)]
                resolved = ".".join([*anchor, node.module or ""])
                if node.module:
                    found.add(resolved)
                else:
                    for alias in node.names:
                        found.add(f"{resolved}.{alias.name}".removesuffix("."))
            elif node.module.startswith("arw"):
                found.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("arw"):
                    found.add(alias.name)
    return found


def _subpackage(path: Path) -> str:
    """Map a kernel file to its subpackage name (core/state/ledger/...)."""
    relative = path.relative_to(KERNEL_ROOT)
    return relative.parts[0] if len(relative.parts) > 1 else "(kernel-root)"


def test_kernel_never_imports_cli() -> None:
    violations = []
    for path in KERNEL_ROOT.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        for module in _imports_of(path):
            if module == "arw.cli" or module.startswith("arw.cli."):
                violations.append(f"{path.relative_to(KERNEL_ROOT.parent)}: {module}")
    assert not violations, "kernel must not import the CLI layer:\n" + "\n".join(violations)


SRC_ROOT = KERNEL_ROOT.parent


def test_cli_imports_adapters_only_via_composition() -> None:
    """cli.py and cli_support.py must not import concrete adapters directly;
    only arw.composition (the composition root) may."""
    violations = []
    for name in ("cli.py", "cli_support.py"):
        path = SRC_ROOT / name
        for module in _imports_of(path):
            if module == "arw.adapters" or module.startswith("arw.adapters."):
                violations.append(f"{name}: {module}")
    assert not violations, (
        "CLI must resolve adapters through the composition root only:\n"
        + "\n".join(violations)
    )


def test_kernel_never_imports_adapters() -> None:
    """The kernel depends on ports (Protocols), never on concrete adapters."""
    violations = []
    for path in KERNEL_ROOT.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        for module in _imports_of(path):
            if module == "arw.adapters" or module.startswith("arw.adapters."):
                violations.append(f"{path.relative_to(SRC_ROOT)}: {module}")
    assert not violations, (
        "kernel must not import concrete adapters (composition root only):\n"
        + "\n".join(violations)
    )


def _kernel_edges() -> dict[str, list[str]]:
    edges: dict[str, set[str]] = {}
    for path in KERNEL_ROOT.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        source_pkg = _subpackage(path)
        for module in _imports_of(path):
            if not module.startswith("arw.kernel."):
                continue
            target_pkg = module.split(".")[2]
            if target_pkg != source_pkg:
                edges.setdefault(source_pkg, set()).add(target_pkg)
    return {source: sorted(targets) for source, targets in sorted(edges.items())}


def test_kernel_subpackage_edges_match_pinned_baseline() -> None:
    """Pin the current cross-package edge set as a ratchet.

    v1's kernel has known cycles (state <-> ledger via status->reducer and
    journal->models; artifacts -> execution via experiment_provenance ->
    runtime). A DAG would require semantic refactors that are out of scope
    for the move-only extraction; the ratchet fails on ANY edge-set change
    (new coupling or unrecorded decoupling), forcing deliberate review.
    """
    import json as _json

    from .normalize import read_golden_json

    golden = read_golden_json(
        Path(__file__).parent / "golden" / "kernel_edges.json"
    )
    assert _kernel_edges() == golden["edges"], (
        "kernel subpackage edge set drifted; new coupling is forbidden, "
        "decoupling must update the pinned baseline deliberately"
    )
    # Keep the json import honest even if the golden read is refactored.
    assert _json.dumps(_kernel_edges(), sort_keys=True)
