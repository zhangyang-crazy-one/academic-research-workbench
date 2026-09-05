"""Installed-mode graph MCP manifest gating (PR15 follow-up).

Background
----------
``bin/arw _graph-mcp`` runs the graph MCP server from an installed wheel.
The CLI composition site gates provider activation on the plugin manifest's
declared capability set; without an installed manifest binding the gate is
skipped and every registered provider stays available regardless of the
manifest's declaration (PRRC_kwDOTWKrXs7pXTQG historical finding).

The minimal fix binds ``ARW_PLUGIN_ROOT`` and ``ARW_PLUGIN_MANIFEST`` from
the launcher and makes ``cli.py`` fail closed when the installed mode lacks
a readable manifest while preserving the source-development fallback. These
tests pin the contract:

* default_router rejects an undeclared capability (gating works).
* default_router admits a declared capability (gating does not over-block).
* cli.py fails closed when ``ARW_PLUGIN_ROOT`` is set but no manifest is bound.
* cli.py fails closed when ``ARW_PLUGIN_MANIFEST`` points at an unreadable file.
* cli.py preserves the source-tree fallback when no installed root is in scope.
* ``bin/arw`` binds ``ARW_PLUGIN_ROOT`` and ``ARW_PLUGIN_MANIFEST`` for the
  ``_graph-mcp`` case (the launcher half of the fix).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arw.composition import default_router
from arw.kernel.capabilities import CapabilityUnavailable

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_PATH = REPOSITORY_ROOT / "bin" / "arw"


def _write_manifest(path: Path, capabilities: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "name": "academic-research-workbench",
                "version": "0.1.0",
                "interface": {"capabilities": capabilities},
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def stub_run_stdio(monkeypatch: pytest.MonkeyPatch):
    """Bypass ``run_stdio`` so the success-path tests do not need real stdin.

    The installed-mode failure tests assert exit code 65 BEFORE ``run_stdio``
    is reached, so they do not need this fixture.  We expose the captured
    server so the success-path tests can prove the manifest gate admitted
    ``knowledge.graph`` end-to-end.
    """

    captured: dict[str, object] = {}

    def _fake(server):
        captured["server"] = server
        return 0

    monkeypatch.setattr("arw.graph_mcp.run_stdio", _fake)
    return captured


# ---------------------------------------------------------------------------
# default_router: capability gating semantics
# ---------------------------------------------------------------------------


def test_default_router_admits_graph_when_manifest_declares_capability(
    tmp_path: Path,
) -> None:
    """A manifest that declares ``graph`` keeps ``knowledge.graph`` registered."""

    manifest = _write_manifest(tmp_path / "plugin.json", ["graph"])
    router = default_router(
        graph_control_root=tmp_path / "control",
        graph_root_id="research-root",
        plugin_manifest=manifest,
    )
    assert "knowledge.graph" in router.available()
    provider = router.resolve("knowledge.graph")
    # GraphProjectionAdapter wraps GraphStore; the gate only checks that the
    # capability is reachable, not that a generation has been projected yet.
    assert provider is not None


def test_default_router_drops_graph_when_manifest_omits_capability(
    tmp_path: Path,
) -> None:
    """A manifest that omits ``graph`` deregisters ``knowledge.graph`` (PR15 gate)."""

    manifest = _write_manifest(tmp_path / "plugin.json", ["research"])
    router = default_router(
        graph_control_root=tmp_path / "control",
        graph_root_id="research-root",
        plugin_manifest=manifest,
    )
    assert "knowledge.graph" not in router.available()
    with pytest.raises(CapabilityUnavailable):
        router.resolve("knowledge.graph")


# ---------------------------------------------------------------------------
# cli.py _graph-mcp: installed-mode fail-closed branches
# ---------------------------------------------------------------------------


def _build_graph_control_root(tmp_path: Path) -> Path:
    control_root = tmp_path / "control"
    (control_root / "roots/research-root").mkdir(parents=True)
    return control_root


def test_cli_graph_mcp_fails_closed_when_installed_root_lacks_manifest_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Installed mode (``ARW_PLUGIN_ROOT`` set) without ``ARW_PLUGIN_MANIFEST``
    must fail closed rather than silently bypass capability gating."""

    from arw.cli import main

    monkeypatch.delenv("ARW_PLUGIN_MANIFEST", raising=False)
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(tmp_path / "installed"))
    control_root = _build_graph_control_root(tmp_path)

    exit_code = main(
        [
            "_graph-mcp",
            "--control-root",
            str(control_root),
            "--root-id",
            "research-root",
        ]
    )

    assert exit_code == 65
    captured = capsys.readouterr()
    assert "plugin-manifest-missing" in captured.err
    # The error must surface before run_stdio consumes stdin; an empty
    # stdin buffer is the harness default.
    assert "ARW_PLUGIN_MANIFEST" in captured.err


def test_cli_graph_mcp_fails_closed_when_manifest_env_points_at_missing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An explicit ``ARW_PLUGIN_MANIFEST`` that resolves to a missing file
    must fail closed (the launcher would otherwise advertise a manifest
    that nobody can read)."""

    from arw.cli import main

    missing = tmp_path / "no-such-plugin.json"
    monkeypatch.setenv("ARW_PLUGIN_MANIFEST", str(missing))
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(tmp_path / "installed"))
    control_root = _build_graph_control_root(tmp_path)

    exit_code = main(
        [
            "_graph-mcp",
            "--control-root",
            str(control_root),
            "--root-id",
            "research-root",
        ]
    )

    assert exit_code == 65
    captured = capsys.readouterr()
    assert "plugin-manifest-unreadable" in captured.err
    assert str(missing) in captured.err


def test_cli_graph_mcp_fails_closed_when_manifest_env_points_at_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A directory path masquerading as the manifest must fail closed."""

    from arw.cli import main

    manifest_dir = tmp_path / "plugin-dir"
    manifest_dir.mkdir()
    monkeypatch.setenv("ARW_PLUGIN_MANIFEST", str(manifest_dir))
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(tmp_path / "installed"))
    control_root = _build_graph_control_root(tmp_path)

    exit_code = main(
        [
            "_graph-mcp",
            "--control-root",
            str(control_root),
            "--root-id",
            "research-root",
        ]
    )

    assert exit_code == 65
    captured = capsys.readouterr()
    assert "plugin-manifest-unreadable" in captured.err


def test_cli_graph_mcp_succeeds_with_explicit_installed_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_run_stdio: dict,
) -> None:
    """The happy installed-mode path: an explicit manifest declaring ``graph``
    plus a stubbed ``run_stdio`` yields exit 0 and reaches the server."""

    from arw.cli import main

    manifest = _write_manifest(tmp_path / "plugin.json", ["graph"])
    monkeypatch.setenv("ARW_PLUGIN_MANIFEST", str(manifest))
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(tmp_path / "installed"))
    control_root = _build_graph_control_root(tmp_path)

    exit_code = main(
        [
            "_graph-mcp",
            "--control-root",
            str(control_root),
            "--root-id",
            "research-root",
        ]
    )

    assert exit_code == 0
    assert "server" in stub_run_stdio, "main must reach run_stdio on the success path"


def test_cli_graph_mcp_preserves_source_development_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_run_stdio: dict,
) -> None:
    """Source-development behavior: with neither env var set the cli.py
    fallback to ``<repo>/.codex-plugin/plugin.json`` (which the repo ships)
    keeps the gate functional. ``run_stdio`` is stubbed."""

    from arw.cli import main

    monkeypatch.delenv("ARW_PLUGIN_MANIFEST", raising=False)
    monkeypatch.delenv("ARW_PLUGIN_ROOT", raising=False)
    control_root = _build_graph_control_root(tmp_path)

    exit_code = main(
        [
            "_graph-mcp",
            "--control-root",
            str(control_root),
            "--root-id",
            "research-root",
        ]
    )

    assert exit_code == 0
    assert "server" in stub_run_stdio


def test_cli_graph_mcp_source_development_allows_missing_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_run_stdio: dict,
) -> None:
    """When no installed root is in scope AND the source-tree fallback is
    absent (e.g. an out-of-tree source build), the historical contract of
    ``plugin_manifest=None`` (no gating, no failure) is preserved. The
    installed-mode fail-closed branch above covers the security-sensitive
    case; source dev keeps the old permissive behavior so partial checkouts
    do not break."""

    # Reload cli.py under a fake __file__ whose parents[2] resolves to a
    # directory with no .codex-plugin/plugin.json.  We swap the module
    # entry so ``main`` (and the manifest-resolution block we just changed)
    # picks up the relocated module instead of the in-repo one.
    import importlib
    import importlib.util
    import sys

    src_cli_path = REPOSITORY_ROOT / "src" / "arw" / "cli.py"
    fake_root = tmp_path / "fake-package"
    fake_package = fake_root / "arw"
    fake_package.mkdir(parents=True)
    fake_cli_path = fake_package / "cli.py"
    fake_cli_path.write_text(src_cli_path.read_text(encoding="utf-8"))

    monkeypatch.delenv("ARW_PLUGIN_MANIFEST", raising=False)
    monkeypatch.delenv("ARW_PLUGIN_ROOT", raising=False)

    spec = importlib.util.spec_from_file_location("arw._cli_relocated", fake_cli_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    # Sanity: under this relocated __file__, the source-tree fallback path
    # resolves to <tmp>/fake-package/.codex-plugin/plugin.json, which does
    # not exist — so manifest_path must become None and gating is skipped.
    fallback = fake_cli_path.resolve().parents[2] / ".codex-plugin" / "plugin.json"
    assert not fallback.is_file()

    control_root = _build_graph_control_root(tmp_path)
    exit_code = module.main(
        [
            "_graph-mcp",
            "--control-root",
            str(control_root),
            "--root-id",
            "research-root",
        ]
    )
    # The historical contract: no installed root + no source manifest ⇒
    # plugin_manifest=None ⇒ default_router skips gating ⇒ run_stdio
    # is reached.  This is the source-dev escape hatch we intentionally
    # preserve.
    assert exit_code == 0
    assert "server" in stub_run_stdio


# ---------------------------------------------------------------------------
# bin/arw launcher: env-binding contract for the _graph-mcp case
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case_label", ["_graph-mcp", "_files-store-mcp"])
def test_launcher_binds_plugin_manifest_env(case_label: str) -> None:
    """The installed launcher must export ``ARW_PLUGIN_ROOT`` and
    ``ARW_PLUGIN_MANIFEST`` before exec'ing any installed-mode MCP server
    (graph + store-backed files); otherwise the wheel-mode discovery in
    cli.py / files_store_mcp.py misses and the capability gate is silently
    bypassed (PR15 follow-up + store-MCP symmetry P1)."""

    script = LAUNCHER_PATH.read_text(encoding="utf-8")

    # Locate the case block. The case line is followed by the
    # env-binding and exec lines; we anchor on the case label and check the
    # lines that follow until the next `;;`.
    needle = f"{case_label})\n"
    case_start = script.index(needle) + len(needle)
    case_end = script.index("\n    ;;\n", case_start)
    case_body = script[case_start:case_end]

    assert "export ARW_PLUGIN_ROOT=" in case_body, (
        f"bin/arw {case_label} case must export ARW_PLUGIN_ROOT for "
        "downstream code to detect installed mode and refuse a missing "
        "manifest binding"
    )
    assert "export ARW_PLUGIN_MANIFEST=" in case_body, (
        f"bin/arw {case_label} case must export ARW_PLUGIN_MANIFEST "
        "pointing at .codex-plugin/plugin.json so the wheel-mode discovery "
        "path stops relying on the source-tree fallback"
    )
    assert "$PLUGIN_ROOT/.codex-plugin/plugin.json" in case_body
    # The launcher must also refuse to start the server if the bundled
    # manifest is missing — the same fail-closed posture as the cli.py side.
    assert 'fail "plugin-manifest-missing"' in case_body
