"""Reuse the bundled fact-locked checker, preserving its mechanical-only scope."""

import importlib.util
import os
from pathlib import Path

CHECKER_RELATIVE = Path(
    "skills/academic-research-suite/codex/scripts/check_fact_locked_revision.py"
)


def _checker_path() -> Path | None:
    plugin_root = os.environ.get("ARW_PLUGIN_ROOT")
    raw_root = (
        Path(plugin_root).absolute()
        if plugin_root
        else Path(__file__).resolve().parents[4]
    )
    if raw_root.is_symlink():
        raise ValueError("unsafe plugin root")
    try:
        resolved_root = raw_root.resolve(strict=True)
    except OSError:
        return None
    if not resolved_root.is_dir():
        raise ValueError("unsafe plugin root")
    candidate = raw_root / CHECKER_RELATIVE
    for ancestor in (candidate, *candidate.parents):
        if ancestor == raw_root.parent:
            break
        if ancestor.is_symlink():
            raise ValueError("unsafe checker path")
    try:
        resolved_candidate = candidate.resolve(strict=True)
    except OSError:
        return None
    if (
        not resolved_candidate.is_relative_to(resolved_root)
        or not resolved_candidate.is_file()
    ):
        raise ValueError("unsafe checker path")
    return resolved_candidate


def audit(source, revision):
    try:
        checker = _checker_path()
    except (OSError, ValueError):
        return {
            "status": "error",
            "reason": "unsafe_checker_path",
            "mechanical_status": "not_run",
            "semantic_status": "human_review_required",
        }
    if checker is None:
        return {
            "status": "unsupported",
            "reason": "bundled fact-locked checker unavailable",
            "mechanical_status": "not_run",
            "semantic_status": "human_review_required",
        }
    try:
        spec = importlib.util.spec_from_file_location(
            "arw_fact_locked_checker", checker
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("checker loader unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        report = module.audit(source, revision)
    except (
        OSError,
        RuntimeError,
        ValueError,
        ImportError,
        SyntaxError,
        TypeError,
    ) as exc:
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
