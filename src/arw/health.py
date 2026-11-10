"""Shared observational diagnostics, not release or native qualification."""

from __future__ import annotations

import os

from arw.files_opt_in import health as file_base_health
from arw.platform_support import platform_support


def health_report() -> dict[str, object]:
    """Keep optional capability readiness separate from core runtime health.

    This lightweight collector performs no installation or activation and also
    serves source-checkout preflight without importing the full CLI.
    """
    return {
        "command": "health",
        "status": "ok",
        "runtime_mode": os.environ.get("ARW_RUNTIME_MODE", "direct"),
        "file_base": file_base_health(),
        "platform": platform_support(),
    }
