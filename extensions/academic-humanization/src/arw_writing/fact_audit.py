"""Reuse the bundled fact-locked checker, preserving its mechanical-only scope."""

import importlib.util
from pathlib import Path

CHECKER = (
    Path(__file__).resolve().parents[4]
    / "skills/academic-research-suite/codex/scripts/check_fact_locked_revision.py"
)


def audit(source, revision):
    if not CHECKER.is_file():
        return {
            "status": "unsupported",
            "reason": "bundled fact-locked checker unavailable",
            "mechanical_status": "not_run",
            "semantic_status": "human_review_required",
        }
    try:
        spec = importlib.util.spec_from_file_location(
            "arw_fact_locked_checker", CHECKER
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("checker loader unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        report = module.audit(source, revision)
    except (OSError, RuntimeError, ValueError, ImportError) as exc:
        return {
            "status": "error",
            "reason": type(exc).__name__,
            "mechanical_status": "not_run",
            "semantic_status": "human_review_required",
        }
    return {
        "status": "available",
        "mechanical_status": "passed" if report["passed"] else "failed",
        "semantic_status": "human_review_required",
        "report": report,
    }
