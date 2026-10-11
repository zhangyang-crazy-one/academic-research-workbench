from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from arw.kernel.execution.harness_config import (
    HarnessConfigError,
    HarnessConfiguration,
    HarnessEntry,
    HarnessRegistry,
    load_harness_configuration,
    runtime_credentials,
)
from arw.kernel.state.models import HostIdentityAcceptedPayload
from arw.kernel.state.orchestration_models import (
    HostIdentityReceipt,
    HostIdentityReceiptV2,
)


def _configuration():
    return {
        "schema_version": "arw.harness-config.v1",
        "default": "native",
        "harnesses": {
            "native": {"kind": "codex"},
            "other-cli": {"kind": "command", "command": ["example-driver"]},
            "other-provider": {
                "kind": "api",
                "endpoint": "https://example.invalid/v1/responses",
                "model": "platform-selected-model",
            },
        },
        "roles": {"domain_reviewer": "other-cli"},
        "assignments": {"assignment.special": "other-provider"},
    }


def test_selection_precedence_and_byte_stable_round_trip(tmp_path):
    path = tmp_path / "harnesses.json"
    path.write_text(json.dumps(_configuration()))
    config = load_harness_configuration(path)
    assert config.select("assignment.special", "domain_reviewer")[0] == "other-provider"
    assert config.select("assignment.other", "domain_reviewer")[0] == "other-cli"
    assert config.select("assignment.other", "research_architect")[0] == "native"
    clone = HarnessConfiguration.model_validate_json(config.model_dump_json())
    assert clone.config_sha256 == config.config_sha256


@pytest.mark.parametrize(
    "entry",
    [
        {"kind": "command"},
        {
            "kind": "command",
            "command": ["driver"],
            "endpoint": "https://example.invalid",
        },
        {"kind": "api", "endpoint": "https://example.invalid"},
        {"kind": "api", "endpoint": "http://example.invalid", "model": "custom"},
        {"kind": "api", "endpoint": "https://key@example.invalid", "model": "custom"},
        {
            "kind": "api",
            "endpoint": "https://example.invalid?key=secret",
            "model": "custom",
        },
        {
            "kind": "api",
            "endpoint": "https://example.invalid",
            "model": "custom",
            "parameters": {"tools": []},
        },
        {
            "kind": "api",
            "endpoint": "https://example.invalid",
            "model": "custom",
            "parameters": {"api_key": "secret"},
        },
        {
            "kind": "api",
            "endpoint": "https://example.invalid",
            "model": "custom",
            "max_output_tokens": "100",
        },
        {"kind": "codex", "model": "override"},
    ],
)
def test_invalid_or_conflicting_config_rejected_without_echo(tmp_path, entry):
    path = tmp_path / "harnesses.json"
    config = _configuration()
    config["harnesses"]["other-provider"] = entry
    path.write_text(json.dumps(config))
    with pytest.raises(HarnessConfigError) as error:
        load_harness_configuration(path)
    assert "secret" not in str(error.value)


def test_explicit_env_selection_no_interpolation_and_environment_precedence(tmp_path):
    (tmp_path / ".env").write_text(
        'UNSELECTED=private\nTEST_KEY="$(never-execute)"\nOTHER=from-file\n'
    )
    entry = HarnessEntry(
        kind="command",
        command=("driver",),
        env_file=".env",
        credential_env=("TEST_KEY", "OTHER"),
    )
    assert runtime_credentials(
        entry, tmp_path, {"OTHER": "from-platform", "IGNORED": "private"}
    ) == {"TEST_KEY": "$(never-execute)", "OTHER": "from-platform"}
    with pytest.raises(HarnessConfigError, match="TEST_KEY"):
        runtime_credentials(
            entry.model_copy(update={"env_file": None}), tmp_path, {"OTHER": "present"}
        )


def test_unknown_selector_and_registry_kind_are_not_implicitly_substituted():
    config = _configuration()
    config["default"] = "unavailable"
    with pytest.raises(ValidationError):
        HarnessConfiguration.model_validate_json(json.dumps(config))
    registry = HarnessRegistry()
    entry = HarnessEntry(kind="my-harness")
    with pytest.raises(HarnessConfigError, match="unregistered"):
        registry.build(entry)
    registry.register("my-harness", lambda _entry, **context: context["token"])
    assert registry.build(entry, token=123) == 123


def test_v1_identity_decoder_keeps_original_bytes_and_v2_has_no_codex_field():
    legacy = HostIdentityReceipt(
        schema_version="arw.host-identity-receipt.v1",
        receipt_id="receipt.legacy",
        role_id="domain_reviewer",
        worker_identity_id="worker.legacy",
        host_agent_id="host.legacy",
        transport="isolated_codex_exec",
        codex_version="0.162.1",
        assignment_mapping_proven=True,
        isolation_proven=True,
        peer_isolation_proven=True,
        credential_isolation_proven=True,
        observed_at="2026-10-11T01:00:00Z",
        evidence_sha256=("a" * 64,),
    )
    accepted = HostIdentityAcceptedPayload(
        receipt=legacy, receipt_sha256=legacy.receipt_sha256
    )
    assert accepted.receipt.receipt_sha256 == legacy.receipt_sha256
    base = legacy.model_dump(mode="python")
    base.pop("codex_version")
    current = HostIdentityReceiptV2(
        **{
            **base,
            "schema_version": "arw.host-identity-receipt.v2",
            "assignment_id": "assignment.test",
            "attempt_id": "attempt.test",
            "transport": "isolated_api_worker",
            "harness_kind": "api",
            "harness_config_sha256": "b" * 64,
            "runtime_sha256": "c" * 64,
            "request_sha256": "d" * 64,
            "observation_sha256": "e" * 64,
        }
    )
    payload = HostIdentityAcceptedPayload.model_validate(
        {
            "receipt": current.model_dump(mode="python"),
            "receipt_sha256": current.receipt_sha256,
        }
    )
    assert isinstance(payload.receipt, HostIdentityReceiptV2)
    assert "codex_version" not in current.model_dump()
    with pytest.raises(ValidationError):
        HostIdentityAcceptedPayload(
            receipt=current.model_copy(update={"isolation_proven": False}),
            receipt_sha256=current.receipt_sha256,
        )


def test_configured_registry_cannot_downgrade_production_identity_guard(tmp_path):
    import asyncio

    from arw.kernel.execution.execution import DispatchSpec, HostResult, StaleAttempt
    from arw.kernel.execution.host_dispatch import _ConfiguredAssignmentAdapter

    class Unproven:
        async def dispatch(self, spec):
            return HostResult(
                spec.attempt_id, "host.unproven", tmp_path / "proposal.json"
            )

    adapter = _ConfiguredAssignmentAdapter({"assignment.test": Unproven()})
    with pytest.raises(StaleAttempt, match="proof"):
        asyncio.run(
            adapter.dispatch(
                DispatchSpec(
                    "assignment.test",
                    "attempt.test",
                    (0, 0),
                    tmp_path / "assignment.json",
                    tmp_path / "attempt",
                )
            )
        )


@pytest.mark.parametrize("invalid", ["role", "assignment", "digest"])
def test_routing_errors_fail_before_adapter_construction(tmp_path, invalid):
    from types import SimpleNamespace

    from arw.cli_support import CLIInputError
    from arw.kernel.execution.host_dispatch import build_configured_dispatch_adapter

    config = _configuration()
    if invalid == "role":
        config["roles"]["unknown_role"] = "other-provider"
    elif invalid == "assignment":
        config["assignments"]["assignment.missing"] = "other-provider"
    path = tmp_path / "harnesses.json"
    path.write_text(json.dumps(config))
    args = SimpleNamespace(
        harness_config=path,
        run_root=tmp_path / "run",
        harness_config_sha256="a" * 64 if invalid == "digest" else None,
    )
    assignment = SimpleNamespace(
        assignment_id="assignment.special", role_id="domain_reviewer"
    )
    constructed = []
    registry = HarnessRegistry()
    registry.register("api", lambda *args, **kwargs: constructed.append(args))
    with pytest.raises(CLIInputError):
        build_configured_dispatch_adapter(args, (assignment,), registry=registry)
    assert not constructed
