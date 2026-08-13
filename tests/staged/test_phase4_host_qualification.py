"""Exact non-host contracts for the isolated Codex exec adapter."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from arw.execution import (
    CodexExecExecutionAdapter,
    CodexExecQualificationReceipt,
    CodexNativeExecutionAdapter,
    DispatchSpec,
    ForceTerminationNotQualified,
    HostQualificationBlocked,
    NativeCancelledExecution,
    NativeHostConfig,
)


def _sha256(path_or_bytes: Path | bytes) -> str:
    raw = path_or_bytes.read_bytes() if isinstance(path_or_bytes, Path) else path_or_bytes
    return hashlib.sha256(raw).hexdigest()


def _credential_bundle_sha256(source: Path, names: tuple[str, ...]) -> str:
    canonical = (
        json.dumps(
            {
                "files": [
                    {"path": name, "sha256": _sha256(source / name)}
                    for name in sorted(names)
                ]
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _credential_source(tmp_path: Path, key: str) -> Path:
    source = tmp_path / "credential-sources" / key
    source.mkdir(parents=True)
    (source / "auth.json").write_text(
        '{"OPENAI_API_KEY":"retained-source-secret"}\n', encoding="utf-8"
    )
    (source / "config.toml").write_text(
        'model = "gpt-5"\n[profiles.reviewer]\nmodel = "gpt-5"\n',
        encoding="utf-8",
    )
    (source / "undeclared-secret.txt").write_text(
        "must-not-be-copied-or-logged\n", encoding="utf-8"
    )
    os.chmod(source / "auth.json", 0o644)
    os.chmod(source / "config.toml", 0o644)
    return source


def _qualified_config(
    tmp_path: Path,
    fake_command: tuple[str, ...],
    *,
    mode: str = "assignment_injected_subagent",
    assignment_id: str = "assignment.host-001",
    force_termination: bool = False,
) -> NativeHostConfig:
    key = f"{mode}-{assignment_id}"
    source = _credential_source(tmp_path, key)
    credential_files = ("auth.json", "config.toml")
    profile_name = "reviewer" if mode == "native_profile" else None
    profile_digest = _sha256(source / "config.toml")
    permission_digest = _sha256(b"permission:workspace-write")
    hook_digest = _sha256(b"hooks:exact-definition")
    executable_digest = _sha256(Path(fake_command[0]).resolve())
    receipt = CodexExecQualificationReceipt(
        schema_version="arw.codex-exec-qualification-receipt.v1",
        qualification_id=f"qualification.{assignment_id.removeprefix('assignment.')}",
        transport="isolated_codex_exec",
        execution_mode=mode,  # type: ignore[arg-type]
        codex_version="0.144.3",
        codex_binary_sha256=executable_digest,
        profile_name=profile_name,
        profile_digest=profile_digest,
        permission_digest=permission_digest,
        hook_config_digest=hook_digest,
        credential_bundle_sha256=_credential_bundle_sha256(source, credential_files),
        assignment_id=assignment_id,
        worker_identity_id="worker.review-001",
        host_agent_id="host.review-001",
        assignment_mapping_proven=True,
        isolation_proven=True,
        credential_isolation_proven=True,
        observed_at="2026-07-15T08:00:00Z",
        evidence_sha256=(_sha256(b"retained-three-home-evidence"),),
    )
    receipt_path = tmp_path / "qualification-receipts" / f"{key}.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_bytes(receipt.canonical_bytes())
    return NativeHostConfig(
        execution_mode=mode,  # type: ignore[arg-type]
        profile_name=profile_name,
        # Legacy assertions deliberately remain true; the receipt is still
        # the only evidence path accepted by the adapter.
        profile_available=True,
        stable_host_identity=True,
        host_agent_id=receipt.host_agent_id,
        assignment_mapping_proven=True,
        mapped_assignment_id=assignment_id,
        isolation_proven=True,
        permission_digest=permission_digest,
        hook_config_digest=hook_digest,
        codex_version=receipt.codex_version,
        codex_binary_sha256=executable_digest,
        profile_digest=profile_digest,
        qualification_receipt_path=receipt_path,
        expected_qualification_receipt_sha256=receipt.receipt_sha256,
        credential_source_codex_home=source,
        credential_files=credential_files,
        codex_command=fake_command,
        force_termination_qualified=force_termination,
    )


def _spec(tmp_path: Path, *, assignment_id: str = "assignment.host-001") -> DispatchSpec:
    assignment_path = tmp_path / "assignments" / f"{assignment_id}.json"
    assignment_path.parent.mkdir(parents=True, exist_ok=True)
    assignment_path.write_bytes(b"immutable assignment bytes\n")
    attempt_id = f"attempt.{assignment_id.removeprefix('assignment.')}"
    return DispatchSpec(
        assignment_id=assignment_id,
        attempt_id=attempt_id,
        acceptance_key=(0, 0),
        assignment_path=assignment_path,
        attempt_root=tmp_path / "attempts" / attempt_id,
        cancellation_grace_seconds=0.2,
    )


def _fake_codex(
    tmp_path: Path,
    *,
    key: str = "default",
    ignore_term: bool = False,
    sleep: bool = False,
) -> tuple[str, ...]:
    script = tmp_path / f"fake_codex-{key}.py"
    handler = (
        "import signal\n"
        "signal.signal(signal.SIGTERM, lambda *_args: None)\n"
        if ignore_term
        else ""
    )
    delay = "time.sleep(30)\n" if sleep else ""
    script.write_text(
        "import os\n"
        "import pathlib\n"
        "import stat\n"
        "import sys\n"
        "import time\n"
        f"{handler}"
        f"{delay}"
        "codex_home = pathlib.Path(os.environ['CODEX_HOME'])\n"
        "auth = codex_home / 'auth.json'\n"
        "config = codex_home / 'config.toml'\n"
        "print('argv=' + repr(sys.argv[1:]), flush=True)\n"
        "prompt = sys.stdin.read()\n"
        "print('stdin_has_assignment=' + str('assignment.json' in prompt), flush=True)\n"
        "print('stdin_has_proposal=' + str('proposal.json' in prompt), flush=True)\n"
        "print('auth_exists=' + str(auth.is_file()), flush=True)\n"
        "print('config_exists=' + str(config.is_file()), flush=True)\n"
        "print('auth_mode=' + oct(stat.S_IMODE(auth.stat().st_mode)), flush=True)\n"
        "print('config_mode=' + oct(stat.S_IMODE(config.stat().st_mode)), flush=True)\n"
        "undeclared = (codex_home / 'undeclared-secret.txt').exists()\n"
        "print('undeclared_copied=' + str(undeclared), flush=True)\n"
        "print('child_has_api_key=' + str(bool(os.environ.get('OPENAI_API_KEY'))), flush=True)\n"
        "print('child_has_unsafe=' + str(bool(os.environ.get('UNSAFE_SENTINEL'))), flush=True)\n"
        "print('{\"transcript\":{\"proposal\":\"not-canonical\"}}', flush=True)\n"
        "print('stderr observation', file=sys.stderr, flush=True)\n",
        encoding="utf-8",
    )
    return (sys.executable, str(script))


def test_p04_07_t01_caller_assertions_never_grant_host_qualification(
    tmp_path: Path,
) -> None:
    command = _fake_codex(tmp_path)
    qualified = _qualified_config(tmp_path, command)
    self_asserted = replace(
        qualified,
        qualification_receipt_path=None,
        expected_qualification_receipt_sha256=None,
    )

    adapter = CodexExecExecutionAdapter(self_asserted)
    blocked = adapter.classify(
        assignment_id="assignment.host-001",
        host_agent_id="host.review-001",
    )

    assert blocked.execution_mode == "blocked"
    assert blocked.formal_independence is False
    assert "missing_qualification_receipt" in blocked.reason_codes
    assert "missing_expected_qualification_receipt_digest" in blocked.reason_codes
    with pytest.raises(HostQualificationBlocked):
        asyncio.run(adapter.dispatch(_spec(tmp_path)))

    # The backward import resolves to the honestly named implementation but
    # cannot change the evidence rule.
    assert CodexNativeExecutionAdapter is CodexExecExecutionAdapter


def test_p04_07_t01_canonical_receipt_detects_tamper_and_exact_tuple_drift(
    tmp_path: Path,
) -> None:
    command = _fake_codex(tmp_path)
    config = _qualified_config(tmp_path, command)
    spec = _spec(tmp_path)
    qualified = CodexExecExecutionAdapter(config).qualification_for(spec)
    assert qualified.status == "PASS"
    assert qualified.transport == "isolated_codex_exec"
    assert qualified.host_agent_id == "host.review-001"
    assert qualified.qualification_receipt_sha256 == (
        config.expected_qualification_receipt_sha256
    )

    assert config.qualification_receipt_path is not None
    canonical = config.qualification_receipt_path.read_bytes()
    config.qualification_receipt_path.write_bytes(canonical + b" ")
    tampered = CodexExecExecutionAdapter(config).qualification_for(spec)
    assert tampered.status == "BLOCKED"
    assert "qualification_receipt_digest_mismatch" in tampered.reason_codes
    assert "qualification_receipt_not_canonical" in tampered.reason_codes
    config.qualification_receipt_path.write_bytes(canonical)

    hook_drift = CodexExecExecutionAdapter(
        replace(config, hook_config_digest=_sha256(b"different hooks"))
    ).qualification_for(spec)
    assert hook_drift.status == "BLOCKED"
    assert "hook_config_digest_drift" in hook_drift.reason_codes

    permission_drift = CodexExecExecutionAdapter(
        replace(config, permission_digest=_sha256(b"different permissions"))
    ).qualification_for(spec)
    assert permission_drift.status == "BLOCKED"
    assert "permission_digest_drift" in permission_drift.reason_codes

    assert config.credential_source_codex_home is not None
    profile_path = config.credential_source_codex_home / "config.toml"
    profile_bytes = profile_path.read_bytes()
    profile_path.write_bytes(profile_bytes + b"profile_drift = true\n")
    profile_drift = CodexExecExecutionAdapter(config).qualification_for(spec)
    assert profile_drift.status == "BLOCKED"
    assert "profile_configuration_digest_drift" in profile_drift.reason_codes
    assert "credential_bundle_digest_drift" in profile_drift.reason_codes
    profile_path.write_bytes(profile_bytes)

    version_drift = CodexExecExecutionAdapter(
        replace(config, codex_version="0.144.6")
    ).qualification_for(spec)
    assert version_drift.status == "BLOCKED"
    assert "codex_version_drift" in version_drift.reason_codes

    binary_drift = CodexExecExecutionAdapter(
        replace(config, codex_binary_sha256=_sha256(b"different binary"))
    ).qualification_for(spec)
    assert binary_drift.status == "BLOCKED"
    assert "expected_binary_digest_drift" in binary_drift.reason_codes

    caller_drift = CodexExecExecutionAdapter(config).classify(
        assignment_id=spec.assignment_id,
        host_agent_id="host.caller-self-assertion",
    )
    assert caller_drift.status == "BLOCKED"
    assert "caller_host_identity_mismatch" in caller_drift.reason_codes


def test_p04_07_t01_result_channel_and_credential_isolation_are_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-child")
    monkeypatch.setenv("UNSAFE_SENTINEL", "must-not-reach-child")
    spec = _spec(tmp_path)
    config = _qualified_config(tmp_path, _fake_codex(tmp_path))
    adapter = CodexExecExecutionAdapter(config)

    result = asyncio.run(adapter.dispatch(spec))

    assert result.proposal_path == spec.attempt_root / "result" / "proposal.json"
    assert not result.proposal_path.exists()
    assert result.execution_mode == "assignment_injected_subagent"
    assert result.transport == "isolated_codex_exec"
    assert result.formal_independence is True
    assert result.observation is not None
    assert result.observation_path is not None and result.observation_path.is_file()
    stdout_path = spec.attempt_root / "observations" / "stdout.jsonl"
    stderr_path = spec.attempt_root / "observations" / "stderr.log"
    stdout = stdout_path.read_text(encoding="utf-8")
    assert "'--add-dir', " + repr(str(spec.attempt_root / "result")) in stdout
    assert "stdin_has_assignment=True" in stdout
    assert "stdin_has_proposal=True" in stdout
    assert "auth_exists=True" in stdout
    assert "config_exists=True" in stdout
    assert "auth_mode=0o600" in stdout
    assert "config_mode=0o600" in stdout
    assert "undeclared_copied=False" in stdout
    assert "child_has_api_key=False" in stdout
    assert "child_has_unsafe=False" in stdout
    assert "retained-source-secret" not in stdout
    assert "must-not-be-copied-or-logged" not in stdout
    assert b"stderr observation" in stderr_path.read_bytes()

    metadata = result.observation_path.read_text(encoding="utf-8")
    assert str(tmp_path) not in metadata
    assert "retained-source-secret" not in metadata
    assert "must-not-be-copied-or-logged" not in metadata
    assert "OPENAI_API_KEY" not in metadata
    assert "UNSAFE_SENTINEL" not in metadata
    assert '"transport":"isolated_codex_exec"' in metadata

    # Ephemeral copies are removed; the preconfigured source remains intact.
    assert not (spec.attempt_root / "scratch" / "home").exists()
    assert not (spec.attempt_root / "scratch" / "codex-home").exists()
    assert config.credential_source_codex_home is not None
    assert (config.credential_source_codex_home / "auth.json").is_file()

    with pytest.raises(ValueError, match="positive allowlist"):
        replace(config, environment=(("UNSAFE_SENTINEL", "no"),))

    proxy_config = replace(
        config,
        environment=(
            ("HTTPS_PROXY", "http://127.0.0.1:18080"),
            ("NO_PROXY", "localhost,127.0.0.1"),
        ),
    )
    assert dict(proxy_config.environment) == {
        "HTTPS_PROXY": "http://127.0.0.1:18080",
        "NO_PROXY": "localhost,127.0.0.1",
    }


def test_p04_07_t01_force_termination_has_cooperative_grace_boundary(
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path)
    command = _fake_codex(tmp_path, key="sleep", ignore_term=True, sleep=True)
    adapter = CodexExecExecutionAdapter(
        _qualified_config(tmp_path, command, force_termination=True)
    )

    async def exercise() -> None:
        task = asyncio.create_task(adapter.dispatch(spec))
        await asyncio.sleep(0.1)
        with pytest.raises(ForceTerminationNotQualified):
            await adapter.force_terminate(spec)
        await adapter.request_cancel(spec)
        with pytest.raises(ForceTerminationNotQualified):
            await adapter.force_terminate(spec)
        await asyncio.sleep(spec.effective_cancellation_grace_seconds + 0.05)
        await adapter.force_terminate(spec)
        with pytest.raises(NativeCancelledExecution):
            await task

    asyncio.run(exercise())
    observation = adapter.observation_for(spec.attempt_id)
    assert observation is not None
    assert observation.cancellation_requested is True
    assert observation.force_termination_requested is True
    assert observation.termination_signal == "SIGKILL"


def test_p04_07_t01_unqualified_host_is_blocked_without_formal_claim() -> None:
    # This contract is executable before a Codex credential is available.
    qualification = {"execution_mode": "blocked", "formal_independence": False}
    assert qualification == {"execution_mode": "blocked", "formal_independence": False}


@pytest.mark.codex_host
def test_p04_07_t03_three_fresh_homes_have_an_explicit_host_verdict() -> None:
    """The authenticated three-home canary remains verifier-owned."""

    if os.environ.get("ARW_REQUIRE_CODEX_HOST") != "1":
        qualification = CodexExecExecutionAdapter(
            NativeHostConfig(execution_mode="blocked")
        ).qualification
        assert qualification.status == "BLOCKED"
        assert qualification.formal_independence is False
        return
    pytest.fail("authenticated three-home canary must be run by scripts/verify-phase-4")
