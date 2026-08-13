"""Mutation tests for the LaTeX/PDF layout-export source contract."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPT = SCRIPT_DIR / "check_layout_export_contract.py"
ARS_ROOT = SCRIPT_DIR.parent


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--ars-root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def _copy_contract(tmp_path: Path) -> Path:
    root = tmp_path / "ars"
    paths = (
        "academic-paper/agents/formatter_agent.md",
        "academic-paper/references/academic_pdf_format_reference.md",
        "academic-paper/references/latex_template_reference.md",
        "academic-paper/references/venue_family_hard_packs.md",
        "academic-paper/WORKFLOW.md",
    )
    for relative in paths:
        source = ARS_ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return root


def test_repository_contract_passes() -> None:
    result = _run(ARS_ROOT)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "PASS (5 synchronized documents)" in result.stdout


def test_missing_formatter_rule_fails_closed(tmp_path: Path) -> None:
    root = _copy_contract(tmp_path)
    formatter = root / "academic-paper/agents/formatter_agent.md"
    text = formatter.read_text(encoding="utf-8")
    formatter.write_text(
        text.replace("full-page render contact sheet", "render preview", 1),
        encoding="utf-8",
    )

    result = _run(root)

    assert result.returncode == 1
    assert "layout-export contract: FAIL" in result.stderr
    assert "full-page render contact sheet" in result.stderr


def test_missing_reference_document_fails_closed(tmp_path: Path) -> None:
    root = _copy_contract(tmp_path)
    (root / "academic-paper/references/latex_template_reference.md").unlink()

    result = _run(root)

    assert result.returncode == 1
    assert "cannot read" in result.stderr
    assert "latex_template_reference.md" in result.stderr
