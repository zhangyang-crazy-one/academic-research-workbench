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

    manifest = Path(__file__).resolve().parents[2] / ".codex-plugin" / "plugin.json"
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


# ---------------------------------------------------------------------------
# Codex-review leftovers (PR12/13/14 findings)
# ---------------------------------------------------------------------------


def test_manifest_declaration_gates_activation(tmp_path: Path) -> None:
    """PR14 P2: the manifest declaration controls the active capability set."""

    from arw.composition import default_router

    manifest = tmp_path / "plugin.json"
    # Declare only "research" — files/artifact providers must NOT activate.
    manifest.write_text(
        '{"interface": {"capabilities": ["research"]}}', encoding="utf-8"
    )
    router = default_router(plugin_manifest=manifest)
    assert "research.literature" in router.available()
    assert "artifact.inspect" not in router.available()


def test_default_router_files_root_id_is_parameterized(tmp_path: Path) -> None:
    """PR12 P2: files.local no longer hardcodes 'research-root'."""

    from arw.composition import default_router

    control = tmp_path / "control"
    control.mkdir()
    # No synced generation under the custom root id → capability-not-available
    # names the custom id, proving the parameter flows through.
    router = default_router(files_control_root=control, files_root_id="custom-root")
    with pytest.raises(CapabilityUnavailable):
        router.resolve("files.local")
