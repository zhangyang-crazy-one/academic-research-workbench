"""Strict observational hook and bounded-continuation contract tests."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from arw.kernel.policy.hook_contracts import (
    CONFIGURED_HOOK_NAMES,
    HOOK_STATUSES,
    MAX_HOOK_INPUT_BYTES,
    ContinuationBudget,
    ContinuationContractError,
    ContinuationRequest,
    HookContractError,
    HookInvocation,
    HookObservation,
    HookParityMatrix,
    load_codex_hook_receipt,
)


HOOK_DIGEST = "a" * 64
OBSERVATION_DIGEST = "b" * 64
AUTHORITY_DIGEST = "c" * 64
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
HOOK_SCRIPT = REPOSITORY_ROOT / "hooks" / "arw_hook.py"


def _observation(
    *,
    status: str = "trusted_enabled",
    continuation: ContinuationRequest | None = None,
    continuation_count: int = 0,
) -> HookObservation:
    return HookObservation(
        schema_version="arw.hook-observation-contract.v1",
        hook_name="SubagentStop",
        command_id="command.review-001",
        target_id="attempt.review-001",
        hook_definition_sha256=HOOK_DIGEST,
        status=status,
        observation_kind="proposal_incomplete",
        observation_sha256=OBSERVATION_DIGEST,
        redacted_error_code=None,
        failure_reason=("hook execution did not complete" if status in {"timeout", "failed"} else None),
        continuation_request=continuation,
        continuation_count=continuation_count,
        parity=HookParityMatrix.for_status(status, authority_digest=AUTHORITY_DIGEST),
    )


def test_p04_03_t03_hook_status_cannot_be_authority_input() -> None:
    observations = tuple(
        _observation(status=status)
        for status in HOOK_STATUSES
    )
    for observation in observations:
        assert all(control.parent_enforced for control in observation.parity.controls)
        assert observation.parity.authority_normalized_digest == AUTHORITY_DIGEST
        assert not hasattr(observation, "canonical_event")
        assert not hasattr(observation, "acceptance_decision")
        assert not hasattr(observation, "state_mutation_request")

    with pytest.raises(HookContractError, match="privilege|canonical_event"):
        HookObservation.from_wire(
            b'{"schema_version":"arw.hook-observation-contract.v1",'
            b'"canonical_event":{"event_type":"gate.evaluated"}}'
        )
    with pytest.raises(HookContractError, match="malformed|JSON"):
        HookObservation.from_wire(b"not-json")
    with pytest.raises(Exception):
        HookObservation.model_validate(
            {
                **_observation().model_dump(mode="json"),
                "observation_sha256": None,
            }
        )


def test_p04_03_t03_continuation_is_at_most_once_per_key() -> None:
    request = ContinuationRequest(
        schema_version="arw.hook-continuation.v1",
        owner="SubagentStop",
        target_id="attempt.review-001",
        idempotency_key="attempt.review-001.subagent-stop.repair",
        reason_code="proposal_incomplete",
    )
    observation = _observation(continuation=request, continuation_count=1)
    budget = ContinuationBudget.initial(
        owner="SubagentStop",
        target_id="attempt.review-001",
        idempotency_key=request.idempotency_key,
    )

    consumed = budget.admit(observation)
    assert consumed.used_count == 1
    with pytest.raises(ContinuationContractError, match="at most one|exhausted"):
        consumed.admit(observation)

    with pytest.raises(ContinuationContractError, match="owner|SubagentStop"):
        ContinuationBudget.initial(
            owner="Stop",
            target_id="deliverable.review-001",
            idempotency_key="deliverable.review-001.stop.parent",
        ).admit(observation)

    with pytest.raises(Exception):
        ContinuationRequest(
            schema_version="arw.hook-continuation.v1",
            owner="SubagentStop",
            target_id="attempt.review-001",
            idempotency_key="attempt.review-001.bad",
            reason_code="retry_assignment",
        )


def _invocation(**overrides: object) -> dict[str, object]:
    invocation: dict[str, object] = {
        "schema_version": "arw.hook-invocation.v1",
        "hook_name": "SessionStart",
        "command_id": "command.hook-001",
        "target_id": "session.hook-001",
        "hook_definition_sha256": HOOK_DIGEST,
        "input_sha256": OBSERVATION_DIGEST,
        "timeout_seconds": 10,
    }
    invocation.update(overrides)
    return invocation


def _official_invocation(hook_name: str, **overrides: object) -> dict[str, object]:
    invocation: dict[str, object] = {
        "session_id": "session-secret-001",
        "transcript_path": "/not/read/session-transcript.jsonl",
        "cwd": "/not/read/workspace",
        "hook_event_name": hook_name,
        "model": "gpt-test-secret",
        "permission_mode": "default",
    }
    if hook_name == "SessionStart":
        invocation["source"] = "startup"
    elif hook_name == "SubagentStop":
        invocation.update(
            {
                "turn_id": "turn-secret-001",
                "agent_id": "agent-secret-001",
                "agent_type": "reviewer",
                "agent_transcript_path": "/not/read/agent-transcript.jsonl",
                "last_assistant_message": "sensitive assistant message",
                "stop_hook_active": False,
            }
        )
    elif hook_name == "Stop":
        invocation.update(
            {
                "turn_id": "turn-secret-001",
                "last_assistant_message": "sensitive assistant message",
                "stop_hook_active": False,
            }
        )
    invocation.update(overrides)
    return invocation


def _run_hook(
    payload: bytes | dict[str, object],
    *,
    plugin_data: Path,
    plugin_root: Path = REPOSITORY_ROOT,
) -> subprocess.CompletedProcess[bytes]:
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    plugin_data.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["PLUGIN_ROOT"] = str(plugin_root)
    environment["PLUGIN_DATA"] = str(plugin_data)
    environment.pop("CODEX_PLUGIN_ROOT", None)
    environment.pop("CODEX_PLUGIN_DATA", None)
    return subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        cwd=plugin_data,
        input=raw,
        capture_output=True,
        check=False,
        env=environment,
        timeout=3,
    )


@pytest.mark.parametrize("hook_name", CONFIGURED_HOOK_NAMES)
def test_p04_06_t01_configured_events_accept_exact_codex_01443_wire_and_emit_official_output(
    tmp_path: Path, hook_name: str
) -> None:
    result = _run_hook(
        _official_invocation(hook_name),
        plugin_data=tmp_path / hook_name,
    )

    assert result.returncode == 0
    assert result.stdout.endswith(b"\n")
    assert result.stdout.count(b"\n") == 1
    output = json.loads(result.stdout)
    assert output["continue"] is True
    assert "decision" not in output
    assert "reason" not in output
    assert "schema_version" not in output
    if hook_name == "SessionStart":
        assert set(output) == {"continue", "hookSpecificOutput"}
        assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert "parent-owned" in output["hookSpecificOutput"]["additionalContext"]
    else:
        assert output == {"continue": True}
    assert result.stderr == b""


@pytest.mark.parametrize("hook_name", CONFIGURED_HOOK_NAMES)
def test_p04_06_t01_receipt_is_redacted_immutable_and_parent_controlled(
    tmp_path: Path, hook_name: str
) -> None:
    plugin_data = tmp_path / hook_name
    payload = _official_invocation(hook_name)
    first = _run_hook(payload, plugin_data=plugin_data)
    repeated = _run_hook(payload, plugin_data=plugin_data)
    assert first.returncode == repeated.returncode == 0

    receipt_files = tuple((plugin_data / "hook-observations" / "v1").glob("*.json"))
    assert len(receipt_files) == 1
    receipt_bytes = receipt_files[0].read_bytes()
    receipt = json.loads(receipt_bytes)
    assert receipt["schema_version"] == "arw.codex-hook-observation.v1"
    assert receipt["authority"] == "observational"
    assert receipt["hook_event_name"] == hook_name
    assert receipt["status"] == "observed"
    assert receipt["redacted_error_code"] is None
    assert [control["surface"] for control in receipt["parent_controls"]] == [
        "runtime",
        "mcp",
        "integrity",
        "gate",
        "provenance",
    ]
    assert all(
        control["parent_enforced"] and control["hook_bypass_safe"]
        for control in receipt["parent_controls"]
    )
    unsigned = dict(receipt)
    digest = unsigned.pop("receipt_sha256")
    canonical = (
        json.dumps(unsigned, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == digest
    assert receipt_files[0].name == f"{digest}.json"
    for secret in (
        "session-secret-001",
        "turn-secret-001",
        "agent-secret-001",
        "gpt-test-secret",
        "sensitive assistant message",
        "/not/read/",
    ):
        assert secret.encode("utf-8") not in receipt_bytes


def test_p04_06_t01_parent_consumer_revalidates_canonical_receipt_and_definition(
    tmp_path: Path,
) -> None:
    plugin_data = tmp_path / "consumer"
    result = _run_hook(_official_invocation("SubagentStop"), plugin_data=plugin_data)
    assert result.returncode == 0
    receipt_root = plugin_data / "hook-observations" / "v1"
    receipt_path = next(receipt_root.glob("*.json"))
    raw = json.loads(receipt_path.read_bytes())

    receipt = load_codex_hook_receipt(
        receipt_path,
        receipt_root=receipt_root,
        expected_hook_definition_sha256=raw["hook_definition_sha256"],
    )
    canonical = receipt.to_orchestration_observation()
    assert canonical.status == "trusted_enabled"
    assert canonical.observation_sha256 == receipt.receipt_sha256
    assert canonical.continuation_requested is False

    with pytest.raises(HookContractError, match="another hook definition"):
        load_codex_hook_receipt(
            receipt_path,
            receipt_root=receipt_root,
            expected_hook_definition_sha256="f" * 64,
        )

    tampered = dict(raw)
    tampered["authority"] = "canonical"
    receipt_path.write_text(json.dumps(tampered, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(HookContractError, match="invalid Codex hook receipt"):
        load_codex_hook_receipt(
            receipt_path,
            receipt_root=receipt_root,
            expected_hook_definition_sha256=raw["hook_definition_sha256"],
        )


def test_p04_06_t01_matching_hooks_can_persist_same_receipt_concurrently(tmp_path: Path) -> None:
    plugin_data = tmp_path / "concurrent"
    payload = _official_invocation("Stop")

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = tuple(
            pool.map(
                lambda _: _run_hook(payload, plugin_data=plugin_data),
                range(12),
            )
        )

    assert all(result.returncode == 0 for result in results)
    receipts = tuple((plugin_data / "hook-observations" / "v1").glob("*.json"))
    assert len(receipts) == 1
    assert json.loads(receipts[0].read_bytes())["authority"] == "observational"


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        b"{" + b"a" * (64 * 1024 + 1),
        {**_official_invocation("SessionStart"), "append_event": {"event_type": "hook.observed"}},
        {**_official_invocation("Stop"), "unexpected": True},
        {**_official_invocation("SubagentStop"), "permission_mode": "root"},
        {**_official_invocation("SessionStart"), "hook_event_name": ["SessionStart"]},
    ],
)
def test_p04_06_t01_nonofficial_or_privileged_input_fails_closed_with_official_output(
    tmp_path: Path, payload: bytes | dict[str, object]
) -> None:
    result = _run_hook(payload, plugin_data=tmp_path / "invalid")

    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert set(output) == {"continue", "systemMessage"}
    assert output["continue"] is True
    assert "parent-owned" in output["systemMessage"]
    assert not tuple((tmp_path / "invalid").glob("hook-observations/v1/*.json"))
    assert b"not-json" not in result.stdout


def test_p04_06_t01_internal_parent_invocation_contract_remains_bounded_and_strict() -> None:
    invocation = HookInvocation.model_validate(_invocation())
    assert HookInvocation.from_wire(invocation.to_wire()) == invocation
    with pytest.raises(HookContractError, match="bounded"):
        HookInvocation.from_wire(b"{" + b" " * MAX_HOOK_INPUT_BYTES)


def test_p04_06_t01_missing_plugin_data_is_a_non_authoritative_hook_failure(
    tmp_path: Path,
) -> None:
    environment = os.environ.copy()
    environment["PLUGIN_ROOT"] = str(REPOSITORY_ROOT)
    environment.pop("PLUGIN_DATA", None)
    result = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        cwd=tmp_path,
        input=json.dumps(_official_invocation("Stop")).encode("utf-8"),
        capture_output=True,
        check=False,
        env=environment,
        timeout=3,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["continue"] is True
    assert b"plugin-data-missing" in result.stderr


def test_p04_06_t01_host_plugin_data_path_may_be_created_on_first_observation(
    tmp_path: Path,
) -> None:
    plugin_data = tmp_path / "codex-home" / "plugins" / "data" / "arw-local"
    environment = os.environ.copy()
    environment["PLUGIN_ROOT"] = str(REPOSITORY_ROOT)
    environment["PLUGIN_DATA"] = str(plugin_data)

    result = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        cwd=tmp_path,
        input=json.dumps(_official_invocation("SessionStart")).encode("utf-8"),
        capture_output=True,
        check=False,
        env=environment,
        timeout=3,
    )

    assert result.returncode == 0
    assert plugin_data.is_dir()
    assert len(tuple(plugin_data.glob("hook-observations/v1/*.json"))) == 1


def test_p04_06_t01_plugin_data_symlink_escape_is_rejected(tmp_path: Path) -> None:
    plugin_data = tmp_path / "plugin-data"
    outside = tmp_path / "outside"
    plugin_data.mkdir()
    outside.mkdir()
    try:
        (plugin_data / "hook-observations").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlink creation is unavailable: {error}")

    result = _run_hook(_official_invocation("Stop"), plugin_data=plugin_data)

    assert result.returncode == 1
    assert json.loads(result.stdout)["continue"] is True
    assert b"plugin-data-boundary" in result.stderr
    assert tuple(outside.iterdir()) == ()


def test_p04_06_t01_hook_configuration_has_only_read_only_commands() -> None:
    config = json.loads((REPOSITORY_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    assert set(config["hooks"]) == set(CONFIGURED_HOOK_NAMES)
    assert config["hooks"]["SessionStart"][0]["matcher"] == "startup|resume|clear|compact"
    for hook_name in CONFIGURED_HOOK_NAMES:
        hook = config["hooks"][hook_name][0]["hooks"][0]
        assert hook["type"] == "command"
        assert hook["timeout"] == 10
        assert "arw_hook.py" in hook["command"]
        assert "${PLUGIN_ROOT}" in hook["command"]
        assert "CODEX_PLUGIN_ROOT" not in hook["command"]
        assert not any(
            token in hook["command"]
            for token in (">", "|", "tee", "events.jsonl", "state.json")
        )
        assert "async" not in hook
