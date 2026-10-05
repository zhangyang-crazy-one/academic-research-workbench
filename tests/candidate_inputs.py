"""Explicit gated candidate inputs for staged integration tests."""

from __future__ import annotations

import os

import pytest


def configured_package_environment() -> dict[str, str]:
    """Forward explicit index URLs without copying user configuration files."""
    return {
        name: os.environ[name]
        for name in ("PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL")
        if name in os.environ
    }


def candidate_stage_args() -> list[str]:
    names = (
        "ARW_CANDIDATE_WHEEL",
        "ARW_BUILD_EVIDENCE",
        "ARW_CANDIDATE_EVIDENCE_ROOT",
    )
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        pytest.skip(f"gated candidate test inputs are required: {', '.join(missing)}")
    return [
        "--candidate-wheel", os.environ[names[0]],
        "--build-evidence", os.environ[names[1]],
        "--candidate-evidence-root", os.environ[names[2]],
    ]
