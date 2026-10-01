"""Reuse the bundled fact-locked checker, preserving its mechanical-only scope."""

import importlib.util
import os
from pathlib import Path

CHECKER_RELATIVE = Path(
    "skills/academic-research-suite/codex/scripts/check_fact_locked_revision.py"
)
DEPENDENCY_RELATIVE = Path(
    "skills/academic-research-suite/ars/scripts/check_revision_token_conservation.py"
)
REPORT_SCHEMA = "arw.fact-locked-revision-report.v1"


def _valid_checker_report(report) -> bool:
    if (
        not isinstance(report, dict)
        or report.get("schema") != REPORT_SCHEMA
        or type(report.get("passed")) is not bool
        or not isinstance(report.get("findings"), list)
    ):
        return False
    for finding in report["findings"]:
        if (
            not isinstance(finding, dict)
            or not isinstance(finding.get("check"), str)
            or not finding["check"]
            or finding.get("severity") not in ("fail", "warn")
            or not isinstance(finding.get("detail"), str)
            or not finding["detail"]
            or not isinstance(finding.get("values"), list)
            or not all(isinstance(value, str) for value in finding["values"])
        ):
            return False
    return report["passed"] == (
        not any(finding["severity"] == "fail" for finding in report["findings"])
    )


def _checker_path() -> Path | None:
    plugin_root = os.environ.get("ARW_PLUGIN_ROOT")
    raw_root = (
        Path(plugin_root).absolute()
        if plugin_root
        else Path(__file__).resolve().parents[4]
    )
    if any(part.is_symlink() for part in (raw_root, *raw_root.parents)):
        raise ValueError("unsafe plugin root")
    try:
        resolved_root = raw_root.resolve(strict=True)
    except OSError:
        return None
    if not resolved_root.is_dir():
        raise ValueError("unsafe plugin root")
    checker = None
    for relative in (CHECKER_RELATIVE, DEPENDENCY_RELATIVE):
        candidate = raw_root
        for index, component in enumerate(relative.parts):
            candidate = candidate / component
            if candidate.is_symlink():
                raise ValueError("unsafe checker path")
            if not candidate.exists():
                return None
            if index < len(relative.parts) - 1 and not candidate.is_dir():
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
        if relative == CHECKER_RELATIVE:
            checker = resolved_candidate
    return checker


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
        checker_audit = getattr(module, "audit", None)
        if not callable(checker_audit):
            raise TypeError("checker audit unavailable")
        report = checker_audit(source, revision)
        if not _valid_checker_report(report):
            raise TypeError("invalid checker report")
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
