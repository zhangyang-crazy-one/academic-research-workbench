"""Capability discovery + graceful absence (PR5 tasks 2.1-2.3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arw.composition import declared_capabilities, default_router
from arw.kernel.capabilities import CapabilityRouter, CapabilityUnavailable


def test_declared_capabilities_reads_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "plugin.json"
    manifest.write_text(
        json.dumps({"interface": {"capabilities": ["research", "files", "audit"]}}),
        encoding="utf-8",
    )
    assert declared_capabilities(manifest) == ("research", "files", "audit")


def test_declared_capabilities_missing_manifest_is_typed_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unreadable plugin manifest"):
        declared_capabilities(tmp_path / "nope.json")


def test_declared_capabilities_matches_shipped_plugin() -> None:
    """The repository's plugin manifest declares the PR5 capability set."""

    manifest = (
        Path(__file__).resolve().parents[2] / ".codex-plugin" / "plugin.json"
    )
    declared = declared_capabilities(manifest)
    for capability in (
        "research",
        "literature",
        "experiment",
        "evidence",
        "files",
        "graph",
        "provenance",
        "artifact",
        "audit",
    ):
        assert capability in declared


def test_register_optional_degrades_import_error_to_capability_unavailable() -> None:
    router = CapabilityRouter()

    def _missing_engine():
        raise ModuleNotFoundError("no module named 'storm_backend'")

    router.register_optional("research.deep_survey", _missing_engine)
    assert "research.deep_survey" in router.available()
    with pytest.raises(CapabilityUnavailable) as exc_info:
        router.resolve("research.deep_survey")
    assert "optional engine not installed" in str(exc_info.value)


def test_register_optional_passes_through_when_present() -> None:
    router = CapabilityRouter()
    router.register_optional("research.deep_survey", lambda: object())
    assert router.resolve("research.deep_survey") is not None


def test_default_router_registers_optional_deep_survey() -> None:
    """The default routing table activates the optional STORM capability in
    guarded form; resolving it without the extra installed is a typed
    capability-not-available, not an ImportError."""

    router = default_router()
    assert "research.deep_survey" in router.available()
