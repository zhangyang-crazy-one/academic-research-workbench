"""Fresh-home host probes must use the project's native model policy."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_both_live_dispatches_explicitly_select_authenticated_project_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loader = importlib.machinery.SourceFileLoader(
        "qualify_codex_model", str(ROOT / "scripts/qualify-codex-host")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    (tmp_path / "codex-home").mkdir()
    commands: list[list[str]] = []

    def capture(_root: Path, argv: list[str]) -> subprocess.CompletedProcess:
        commands.append(argv)
        if len(commands) == 2:
            raise module.CanaryError("stop before any host execution")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(module, "_install_stage", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(module, "_copy_auth", lambda *_a: b"")
    monkeypatch.setattr(module, "_run_isolated", capture)
    monkeypatch.setattr(module, "_require_success", lambda *_a, **_k: None)
    monkeypatch.setattr(module, "_hook_receipts", lambda *_a: [])
    with pytest.raises(module.CanaryError, match="stop before any host execution"):
        module._run_one_home(
            ordinal=1, stage_root=tmp_path, fresh_root=tmp_path,
            evidence_root=tmp_path, auth_source=tmp_path / "unused-auth.json",
            tuple_sha256="a" * 64, arw_runtime_sha256="b" * 64,
            stage_sha256="c" * 64, hook_definition_sha256="d" * 64,
            codex_launcher=Path("/native/codex"),
        )
    assert len(commands) == 2
    for command in commands:
        assert command[:4] == ["/native/codex", "exec", "--model", "gpt-6.1-sol"]
        assert 'model_reasoning_effort="high"' in command
        assert command.count("--model") == 1
    assert not (tmp_path / "codex-home/auth.json").exists()
