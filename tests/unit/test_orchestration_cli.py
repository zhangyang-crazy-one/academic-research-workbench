"""Installed CLI surface and fail-closed orchestration routing tests."""

from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from arw.canonical import canonical_json_bytes


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATION_COMMANDS = {
    "orchestration-prepare",
    "orchestration-dispatch",
    "orchestration-panel",
    "orchestration-gate",
    "orchestration-hook",
    "orchestration-recover",
}


def _runtime_request(path: Path) -> Path:
    path.write_bytes(
        canonical_json_bytes(
            {
                "schema_version": "1.0.0",
                "run_id": "run-00000000-0000-4000-8000-000000000401",
                "event_id": "evt-00000000-0000-4000-8000-000000000451",
                "command_id": "cmd-00000000-0000-4000-8000-000000000451",
                "expected_revision": 1,
                "occurred_at": "2026-07-15T08:00:00Z",
                "actor_id": "parent.runtime",
                "actor_role": "parent_control_plane",
            }
        )
    )
    return path


def test_orchestration_surface_and_public_bin_allowlist_are_exact() -> None:
    from arw.cli import build_parser

    parser = build_parser()
    action = next(
        item for item in parser._actions if item.dest == "command"  # noqa: SLF001
    )
    assert ORCHESTRATION_COMMANDS <= set(action.choices)

    launcher = (REPOSITORY_ROOT / "bin/arw").read_text(encoding="utf-8")
    for command in action.choices:
        assert command in launcher
    for command in ORCHESTRATION_COMMANDS:
        assert command in launcher
    assert "DeterministicFakeAdapter" not in (
        REPOSITORY_ROOT / "src/arw/cli.py"
    ).read_text(encoding="utf-8")


def test_dispatch_without_exact_integration_evidence_is_blocked_before_asyncio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    import arw.cli as cli

    request = _runtime_request(tmp_path / "request.json")
    for name in (
        "ARW_INTEGRATION_LOCK",
        "ARW_PLUGIN_ROOT",
        "ARW_ARS_ROOT",
        "ARW_CODEX_LAUNCHER",
        "ARW_CODEX_NATIVE_BINARY",
        "ARW_HOST_CANARY_EVIDENCE",
    ):
        monkeypatch.delenv(name, raising=False)

    def forbidden_asyncio_run(_coroutine: object) -> None:
        raise AssertionError("blocked dispatch must not enter the event loop")

    monkeypatch.setattr(cli.asyncio, "run", forbidden_asyncio_run)
    status = cli.main(
        [
            "orchestration-dispatch",
            "--run-root",
            str(tmp_path / "absent-run"),
            "--request",
            str(request),
        ]
    )

    assert status == 65
    output = json.loads(capfd.readouterr().out)
    assert output == {
        "schema_version": "arw.orchestration-command-result.v1",
        "command": "orchestration-dispatch",
        "status": "BLOCKED",
        "execution_mode": "blocked",
        "reason_codes": ["integration_inputs_incomplete"],
    }


def test_dispatch_rejects_receipt_without_assignment_mapping_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    import arw.cli as cli
    import arw.orchestration as orchestration

    assignment = SimpleNamespace(
        assignment_id="assignment.alpha",
        acceptance_key=SimpleNamespace(value=(0, 0, "assignment.alpha")),
    )
    prepared = SimpleNamespace(
        assignments=(assignment,),
        execution_mode="assignment_injected_subagent",
    )
    qualification = SimpleNamespace(
        formal_independence=True,
        stable_host_identity=True,
        assignment_mapping_proven=False,
        isolation_proven=True,
        profile_configured=True,
        permission_configured=True,
        hook_configured=True,
        execution_mode="assignment_injected_subagent",
        reason_codes=(),
    )
    host_adapter = SimpleNamespace(
        qualification_for=lambda _spec: qualification,
    )
    adapter = SimpleNamespace(adapters={"assignment.alpha": host_adapter})
    verification = SimpleNamespace(integration_lock_sha256="a" * 64)
    monkeypatch.setattr(
        cli,
        "_verified_dispatch_adapter",
        lambda _args: (adapter, verification, ()),
    )
    monkeypatch.setattr(cli, "_rehydrate_prepared_run", lambda _service: prepared)
    monkeypatch.setattr(
        orchestration,
        "OrchestrationService",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )

    def forbidden_asyncio_run(_coroutine: object) -> None:
        raise AssertionError("unqualified dispatch must not enter the event loop")

    monkeypatch.setattr(cli.asyncio, "run", forbidden_asyncio_run)
    status = cli.main(
        [
            "orchestration-dispatch",
            "--run-root",
            str(tmp_path / "run"),
            "--request",
            str(_runtime_request(tmp_path / "request.json")),
        ]
    )

    assert status == 65
    assert json.loads(capfd.readouterr().out) == {
        "schema_version": "arw.orchestration-command-result.v1",
        "command": "orchestration-dispatch",
        "status": "BLOCKED",
        "execution_mode": "blocked",
        "reason_codes": ["host_qualification:assignment_mapping_not_proven"],
    }


def test_panel_rejects_unstructured_identity_claim_before_service_construction(
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    import arw.cli as cli

    panel = tmp_path / "panel.json"
    panel.write_bytes(
        canonical_json_bytes(
            {
                "schema_version": "arw.cli-panel-request.v1",
                "panel_id": "panel.alpha",
                "subject_sha256": "a" * 64,
                "rubric_sha256": "b" * 64,
                "reviewer_identities": {
                    "methodology_reviewer": "caller-asserted-identity"
                },
                "synthesizer_identity": None,
                "execution_mode": "assignment_injected_subagent",
            }
        )
    )
    status = cli.main(
        [
            "orchestration-panel",
            "--run-root",
            str(tmp_path / "absent-run"),
            "--request",
            str(_runtime_request(tmp_path / "request.json")),
            "--panel",
            str(panel),
        ]
    )

    assert status == 65
    captured = capfd.readouterr()
    assert captured.out == ""
    assert "must contain one exact identity receipt digest" in captured.err


def test_only_cli_process_boundary_drives_async_dispatch() -> None:
    import arw.cli as cli
    from arw.orchestration import OrchestrationService

    source = inspect.getsource(cli)
    assert source.count("asyncio.run(") == 1
    assert inspect.iscoroutinefunction(OrchestrationService.dispatch)


def test_read_only_route_import_never_probes_a_writable_temp_directory(
    tmp_path: Path,
) -> None:
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        "import tempfile\n"
        "def unavailable_tempdir(*_args, **_kwargs):\n"
        "    raise RuntimeError('temporary directory probing is forbidden')\n"
        "tempfile.gettempdir = unavailable_tempdir\n",
        encoding="utf-8",
    )
    environment = dict(os.environ)
    for name in (
        "TMPDIR",
        "TMP",
        "TEMP",
        "ARW_INTEGRATION_LOCK",
        "ARW_PLUGIN_ROOT",
        "ARW_ARS_ROOT",
        "ARW_CODEX_LAUNCHER",
        "ARW_CODEX_NATIVE_BINARY",
        "ARW_HOST_CANARY_EVIDENCE",
    ):
        environment.pop(name, None)
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(tmp_path), str(REPOSITORY_ROOT / "src"))
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import arw.cli as cli; "
                "status = cli.main(['route', '--json']); "
                "assert 'arw.files' not in sys.modules; "
                "assert 'arw.journal' not in sys.modules; "
                "assert 'portalocker' not in sys.modules; "
                "raise SystemExit(status)"
            ),
        ],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    route = json.loads(result.stdout)
    assert route["integration_status"] == "BLOCKED"
    assert route["reason_codes"] == ["integration_lock_not_verified"]
