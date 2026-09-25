"""Strict observational hook and bounded-continuation contract tests."""

from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError

from arw.kernel.policy.hook_contracts import (
    CONFIGURED_HOOK_NAMES,
    HOOK_STATUSES,
    MAX_HOOK_INPUT_BYTES,
    CodexHookReceipt,
    ContinuationBudget,
    ContinuationContractError,
    ContinuationRequest,
    HookContractError,
    HookInvocation,
    HookObservation,
    HookParityMatrix,
    LegacyCodexHookReceipt,
    load_codex_hook_receipt,
)

HOOK_DIGEST = "a" * 64
OBSERVATION_DIGEST = "b" * 64
AUTHORITY_DIGEST = "c" * 64
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
HOOK_SCRIPT = REPOSITORY_ROOT / "hooks" / "arw_hook.py"
HOST_FIXTURES = REPOSITORY_ROOT / "tests" / "fixtures" / "hooks"
LEGACY_RECEIPT = (
    HOST_FIXTURES / "legacy-v1"
    / "cb42a36430800257e5dbb337ac92713d2ab74882882f65d63d21b81473046bed.json"
)
LEGACY_FILE_SHA256 = "d42ae38c1b766f4d0bd45220ff187ebedfd8cb55630bb1d8e39b31e8b62c45e2"

# Authentic captured stdin hashes, recorded in each version's fixture README.
HOST_EVENT_CASES = (
    (
        "0.144.4", "SessionStart",
        "6d5fda9fb7529c65bfc6a796d348227aeb647e0968db3221a47ab7ecd82e9ae7",
    ),
    (
        "0.144.4", "SubagentStop",
        "6682c52c92a29bfe9c8805bcf52e15c4a8354e116f2b8892a309d1cb61ac9acb",
    ),
    (
        "0.144.4", "Stop",
        "ddf1de5d1d4df0369007997fe3be52a27a31a0f29d1352acb171cdba7fe41dfd",
    ),
    (
        "0.147.0", "SessionStart",
        "3903ef4e4b5456a890404c9c80781bb440a8b3c9b5e0ce34ee1a78f88721db1b",
    ),
    (
        "0.147.0", "SubagentStop",
        "022341b991664b4b452d0cd54a170c941bd814a4deba6375bf67e44b230b5c04",
    ),
    (
        "0.147.0", "Stop",
        "38c399b2afbaf7972545da4d2614582c7fd8f2c56ab5a4bf9c59061b1e84dfe8",
    ),
    (
        "0.156.1", "SessionStart",
        "f48e58d15ed987bc6c955c035e568135ddb384209e419c900ff5fde1232c33ec",
    ),
    (
        "0.156.1", "SubagentStop",
        "96067957c847979f2b4d8f715cef764e7b793863060fa47953d634244295c066",
    ),
    (
        "0.156.1", "Stop",
        "a414e152ead24ce09b65d3485b0a47b782fdee89341371abd9eea72b83bd4653",
    ),
)


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
    """Construct synthetic host-like input for boundary and property tests."""
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


@pytest.mark.parametrize(
    "version,hook_name,original_sha256",
    HOST_EVENT_CASES,
    ids=[f"codex-{version}-{event}" for version, event, _ in HOST_EVENT_CASES],
)
def test_p04_06_t01_real_host_stdin_golden_output_and_parent_receipt(
    tmp_path: Path, version: str, hook_name: str, original_sha256: str
) -> None:
    fixture = (HOST_FIXTURES / f"codex-{version}" / f"{hook_name}.json").read_bytes()
    assert fixture.endswith(b"\n")
    assert not fixture.endswith(b"\n\n")
    raw_stdin = fixture[:-1]  # Fixture storage adds one newline; captured stdin had none.
    assert hashlib.sha256(raw_stdin).hexdigest() == original_sha256
    assert json.loads(raw_stdin)["hook_event_name"] == hook_name

    plugin_data = tmp_path / f"codex-{version}-{hook_name}"
    result = _run_hook(raw_stdin, plugin_data=plugin_data)

    assert result.returncode == 0, result.stderr
    assert result.stderr == b""
    assert result.stdout.endswith(b"\n")
    assert result.stdout.count(b"\n") == 1
    output = json.loads(result.stdout)
    assert "systemMessage" not in output
    if hook_name == "SessionStart":
        assert output == {
            "continue": True,
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": (
                    "ARW hook context is observational only. Canonical state, evidence "
                    "admission, retries, provenance, and gates remain parent-owned."
                ),
            },
        }
    else:
        assert output == {"continue": True}

    receipt_root = plugin_data / "hook-observations" / "v1"
    (receipt_path,) = receipt_root.glob("*.json")
    receipt_wire = json.loads(receipt_path.read_bytes())
    receipt = load_codex_hook_receipt(
        receipt_path,
        receipt_root=receipt_root,
        expected_hook_definition_sha256=receipt_wire["hook_definition_sha256"],
    )
    assert receipt.input_sha256 == original_sha256
    assert receipt.hook_event_name == hook_name
    assert receipt.permission_mode == "bypassPermissions"
    assert receipt.status == "observed"
    assert receipt.redacted_error_code is None
    assert receipt.to_orchestration_observation().continuation_requested is False


# Constructed host-like inputs below are synthetic boundary and property cases.
@pytest.mark.parametrize("hook_name", CONFIGURED_HOOK_NAMES)
def test_p04_06_t01_configured_events_accept_synthetic_wire_and_emit_official_output(
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
    assert receipt["unrecognized_fields"] == []
    assert receipt["permission_mode_unrecognized"] is False
    assert receipt["permission_mode"] == "default"
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


def test_prechange_v1_receipt_loads_without_changing_captured_bytes(tmp_path: Path) -> None:
    captured = LEGACY_RECEIPT.read_bytes()
    assert hashlib.sha256(captured).hexdigest() == LEGACY_FILE_SHA256
    path = tmp_path / LEGACY_RECEIPT.name
    path.write_bytes(captured)
    definition = json.loads(captured)["hook_definition_sha256"]

    receipt = load_codex_hook_receipt(
        path, receipt_root=tmp_path, expected_hook_definition_sha256=definition
    )
    assert isinstance(receipt, LegacyCodexHookReceipt)
    assert not isinstance(receipt, CodexHookReceipt)
    assert path.read_bytes() == captured
    assert receipt.receipt_sha256 == LEGACY_RECEIPT.stem
    assert receipt.permission_mode == "bypassPermissions"
    assert "unrecognized_fields" not in receipt.model_dump()
    assert "permission_mode_unrecognized" not in receipt.model_dump()
    observation = receipt.to_orchestration_observation()
    assert observation.hook_name == "SessionStart"
    assert observation.observation_sha256 == receipt.receipt_sha256
    assert observation.continuation_requested is False
    with pytest.raises(ValidationError):
        CodexHookReceipt.model_validate_json(captured, strict=True)


@pytest.mark.parametrize("change", ["stale_hash", "extra_field", "noncanonical"])
def test_prechange_v1_receipt_rejects_changed_bytes(tmp_path: Path, change: str) -> None:
    payload = json.loads(LEGACY_RECEIPT.read_bytes())
    if change == "stale_hash":
        payload["input_sha256"] = "0" * 64
    elif change == "extra_field":
        payload["unrecognized_fields"] = []
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
    if change == "noncanonical":
        raw = raw[:-1] + b"  \n"
    path = tmp_path / LEGACY_RECEIPT.name
    path.write_bytes(raw)
    with pytest.raises(HookContractError):
        load_codex_hook_receipt(
            path,
            receipt_root=tmp_path,
            expected_hook_definition_sha256=payload["hook_definition_sha256"],
        )


def test_prechange_v1_receipt_requires_filename_and_definition_binding(tmp_path: Path) -> None:
    raw = LEGACY_RECEIPT.read_bytes()
    definition = json.loads(raw)["hook_definition_sha256"]
    wrong_name = tmp_path / ("0" * 64 + ".json")
    wrong_name.write_bytes(raw)
    with pytest.raises(HookContractError, match="filename"):
        load_codex_hook_receipt(
            wrong_name, receipt_root=tmp_path, expected_hook_definition_sha256=definition
        )
    path = tmp_path / LEGACY_RECEIPT.name
    path.write_bytes(raw)
    with pytest.raises(HookContractError, match="another hook definition"):
        load_codex_hook_receipt(
            path, receipt_root=tmp_path, expected_hook_definition_sha256="f" * 64
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


def _receipt_path(plugin_data: Path) -> Path:
    (path,) = (plugin_data / "hook-observations" / "v1").glob("*.json")
    return path


@pytest.mark.parametrize("hook_name", CONFIGURED_HOOK_NAMES)
def test_additive_fields_are_bounded_redacted_and_parent_loadable(
    tmp_path: Path, hook_name: str
) -> None:
    rng = random.Random(28)
    extras = {f"added_{index:02d}_{rng.randrange(10000):04d}": {"secret": "NEVER_RETAIN_ME"}
              for index in range(40)}
    extras.update({
        "": "BAD_NAME_VALUE",
        "bad\x00name": "BAD_NAME_VALUE",
        "\ud800": "BAD_NAME_VALUE",
        "x" * 129: "BAD_NAME_VALUE",
        "界" * 42: "NEVER_RETAIN_ME",
        "append_event": {"event_type": "forged", "secret": "NEVER_RETAIN_ME"},
    })
    payload = _official_invocation(hook_name, **extras, permission_mode="new-private-mode")
    plugin_data = tmp_path / hook_name
    result = _run_hook(payload, plugin_data=plugin_data)
    assert result.returncode == 0, result.stderr
    assert "systemMessage" not in json.loads(result.stdout)
    path = _receipt_path(plugin_data)
    raw = path.read_bytes()
    receipt = json.loads(raw)
    expected = sorted(
        name for name in extras
        if name and name != "\ud800" and "\x00" not in name and len(name.encode("utf-8")) <= 128
    )[:32]
    assert receipt["unrecognized_fields"] == expected
    assert receipt["permission_mode"] is None
    assert receipt["permission_mode_unrecognized"] is True
    assert b"NEVER_RETAIN_ME" not in raw
    assert b"BAD_NAME_VALUE" not in raw
    assert b"new-private-mode" not in raw
    assert load_codex_hook_receipt(
        path, receipt_root=path.parent,
        expected_hook_definition_sha256=receipt["hook_definition_sha256"],
    ).unrecognized_fields == tuple(expected)


@pytest.mark.parametrize("hook_name", CONFIGURED_HOOK_NAMES)
@pytest.mark.parametrize("case", [
    "missing", "wrong_type", "nul", "too_long", "bad_permission_type", "empty_permission",
    "long_permission", "nul_permission", "surrogate_permission", "unsupported_event",
    "duplicate_key", "oversized",
])
def test_required_fields_and_wire_boundaries_still_fail_closed(
    tmp_path: Path, hook_name: str, case: str
) -> None:
    payload = _official_invocation(hook_name)
    if case == "missing":
        del payload["session_id"]
    elif case == "wrong_type":
        payload["session_id"] = 1
    elif case == "nul":
        payload["session_id"] = "x\x00y"
    elif case == "too_long":
        payload["session_id"] = "x" * 513
    elif case == "bad_permission_type":
        payload["permission_mode"] = ["default"]
    elif case == "empty_permission":
        payload["permission_mode"] = ""
    elif case == "long_permission":
        payload["permission_mode"] = "界" * 43
    elif case == "nul_permission":
        payload["permission_mode"] = "new\x00mode"
    elif case == "surrogate_permission":
        payload["permission_mode"] = "\ud800"
    elif case == "unsupported_event":
        payload["hook_event_name"] = "PreToolUse"
    raw = json.dumps(payload).encode("utf-8")
    if case == "duplicate_key":
        raw = raw[:-1] + b',"session_id":"duplicate"}'
    elif case == "oversized":
        raw = raw[:-1] + b',"extra":"' + b"x" * (64 * 1024) + b'"}'
    result = _run_hook(raw, plugin_data=tmp_path / f"{hook_name}-{case}")
    assert result.returncode == 1
    assert "systemMessage" in json.loads(result.stdout)
    assert not tuple((tmp_path / f"{hook_name}-{case}").glob("hook-observations/v1/*.json"))


@pytest.mark.parametrize("metadata", [
    {"unrecognized_fields": ["b", "a"]},
    {"unrecognized_fields": ["a", "a"]},
    {"unrecognized_fields": [""]},
    {"unrecognized_fields": ["bad\x00name"]},
    {"unrecognized_fields": ["界" * 43]},
    {"unrecognized_fields": [f"x{i:02d}" for i in range(33)]},
    {"permission_mode": "default", "permission_mode_unrecognized": True},
    {"permission_mode": None, "permission_mode_unrecognized": False},
])
def test_parent_rejects_resigned_invalid_receipt_metadata(
    tmp_path: Path, metadata: dict[str, object]
) -> None:
    plugin_data = tmp_path / "parent"
    assert _run_hook(_official_invocation("Stop"), plugin_data=plugin_data).returncode == 0
    original = _receipt_path(plugin_data)
    receipt = json.loads(original.read_bytes())
    receipt.update(metadata)
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    receipt["receipt_sha256"] = hashlib.sha256(
        (json.dumps(unsigned, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    ).hexdigest()
    path = original.parent / f'{receipt["receipt_sha256"]}.json'
    path.write_bytes((json.dumps(receipt, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8"))
    with pytest.raises(HookContractError, match="invalid Codex hook receipt"):
        load_codex_hook_receipt(
            path, receipt_root=path.parent,
            expected_hook_definition_sha256=receipt["hook_definition_sha256"],
        )


@pytest.mark.parametrize("hook_name,field,bad_value", [
    ("SessionStart", "source", "unexpected"),
    ("SubagentStop", "agent_id", ""),
    ("SubagentStop", "agent_transcript_path", 4),
    ("Stop", "turn_id", "x" * 513),
    ("Stop", "stop_hook_active", 1),
])
def test_event_specific_required_fields_remain_strict(
    tmp_path: Path, hook_name: str, field: str, bad_value: object
) -> None:
    plugin_data = tmp_path / hook_name
    result = _run_hook(
        _official_invocation(hook_name, **{field: bad_value}), plugin_data=plugin_data
    )
    assert result.returncode == 1
    assert not tuple(plugin_data.glob("hook-observations/v1/*.json"))


def test_additive_hook_during_research_run_does_not_change_canonical_state(
    tmp_path: Path,
) -> None:
    from arw.kernel.ledger.journal import initialize_run, replay_run
    from arw.kernel.ledger.workflows import CORE_WORKFLOW
    from arw.kernel.state.models import InitRunRequest

    run_root = tmp_path / "research-run"
    source = run_root / "input" / "source.txt"
    source.parent.mkdir(parents=True)
    source.write_text("Research question: how does retrieval affect citation accuracy?\n", encoding="utf-8")
    initialize_run(run_root, InitRunRequest.model_validate({
        "schema_version": "1.0.0",
        "run_id": "run-00000000-0000-4000-8000-000000000028",
        "occurred_at": "2026-09-25T00:00:00Z",
        "immutable_input": {
            "path": "input/source.txt",
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        },
        "workflow_family": "academic-pipeline",
        "workflow_mode": "inline-role-prompts",
        "workflow_definition_id": CORE_WORKFLOW.definition_id,
        "workflow_definition_sha256": CORE_WORKFLOW.sha256,
        "journal_layout": "segmented-v1",
        "capabilities": ["canonical-journal"],
        "event_id": "evt-00000000-0000-4000-8000-000000000028",
        "command_id": "cmd-00000000-0000-4000-8000-000000000028",
        "actor_id": "parent.runtime",
    }))
    before = {path.relative_to(run_root): path.read_bytes()
              for path in run_root.rglob("*") if path.is_file()}
    revision_before = replay_run(run_root).revision
    plugin_data = tmp_path / "plugin-data"
    result = _run_hook(
        _official_invocation(
            "SessionStart", cwd=str(run_root), research_host_extension={"private": "DO_NOT_STORE"}
        ),
        plugin_data=plugin_data,
    )
    assert result.returncode == 0, result.stderr
    path = _receipt_path(plugin_data)
    receipt = json.loads(path.read_bytes())
    loaded = load_codex_hook_receipt(
        path, receipt_root=path.parent,
        expected_hook_definition_sha256=receipt["hook_definition_sha256"],
    )
    assert loaded.unrecognized_fields == ("research_host_extension",)
    assert loaded.to_orchestration_observation().continuation_requested is False
    assert b"DO_NOT_STORE" not in path.read_bytes()
    assert replay_run(run_root).revision == revision_before
    assert {path.relative_to(run_root): path.read_bytes()
            for path in run_root.rglob("*") if path.is_file()} == before


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
