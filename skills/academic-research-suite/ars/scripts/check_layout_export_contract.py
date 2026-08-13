#!/usr/bin/env python3
"""Verify that ARS keeps its LaTeX/PDF layout-export rules synchronized.

This is a source-contract check, not a substitute for compiling and visually
reviewing a manuscript. It prevents a future adapter refresh from retaining the
formatter heading while silently dropping the corresponding PDF, LaTeX, ACL,
or workflow instructions.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


DEFAULT_ARS_ROOT = Path(__file__).resolve().parents[1]


def required_markers(ars_root: Path) -> dict[Path, tuple[str, ...]]:
    """Return the synchronized contract surfaces rooted at *ars_root*."""

    return {
        ars_root / "academic-paper/agents/formatter_agent.md": (
            "## LaTeX Layout Export Gate",
            "full-page render contact sheet",
            "do not set global `\\parindent=0`",
            "never place `\\FloatBarrier` while an earlier double-column float is still",
        ),
        ars_root / "academic-paper/references/academic_pdf_format_reference.md": (
            "## Paragraph Indentation Rules",
            "Every page is rendered to PNG",
            "No barrier may strand a pending double-column float",
        ),
        ars_root / "academic-paper/references/latex_template_reference.md": (
            "## Paragraph And Two-Column Float Discipline",
            "preserve the original asset and fit it proportionally",
            "Do not issue a barrier while an earlier double-column float is",
        ),
        ars_root / "academic-paper/references/venue_family_hard_packs.md": (
            "| Float scheduling |",
            "| Render audit |",
            "compiler-only validation",
        ),
        ars_root / "academic-paper/WORKFLOW.md": (
            "LaTeX Layout\nExport Gate",
            "Compilation alone does not pass formatting",
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ars-root",
        type=Path,
        default=DEFAULT_ARS_ROOT,
        help="ARS root containing academic-paper/ (defaults to this script's parent)",
    )
    args = parser.parse_args()

    markers_by_path = required_markers(args.ars_root.resolve())
    failures: list[str] = []
    for path, markers in markers_by_path.items():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            failures.append(f"{path}: cannot read ({exc})")
            continue
        for marker in markers:
            if marker not in text:
                failures.append(f"{path}: missing marker {marker!r}")

    if failures:
        print("layout-export contract: FAIL", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print(
        "layout-export contract: PASS "
        f"({len(markers_by_path)} synchronized documents)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
