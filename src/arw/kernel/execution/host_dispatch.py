"""Installed-host route discovery and Phase 4 dispatch glue.

Moved verbatim from cli.py during the v2 thin-kernel extraction: this is
domain logic (integration-lock discovery, host evidence verification,
dispatch reporting), not CLI parsing/formatting.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Sequence

from arw.kernel.core.canonical import canonical_json_bytes

from arw.cli_support import (
    CLIInputError,
    _canonical_object_from_bytes,
    _is_sha256_text,
    _load_object,
    _write_json,
)

def _discover_installed_route_inputs() -> tuple[Path, dict[str, Path | None]]:
    from arw.kernel.policy.integration_lock import (
        IntegrationLockError,
        discover_codex_native_binary,
    )

    plugin_root = Path(
        os.environ.get("ARW_PLUGIN_ROOT", Path(__file__).resolve().parents[4])
    ).resolve()
    # A staged plugin carries the lock as a runtime input. Discovering that
    # path is safe, but it never constitutes qualification: the exact host
    # tuple and retained canary below remain mandatory and are verified from
    # bytes on every route request.
    lock_default = plugin_root / "supply-chain/integration-lock.json"
    canary_default_candidates = (
        plugin_root / "supply-chain/host-canary/canary.json",
        plugin_root / "supply-chain/host-canary.json",
    )
    canary_default = next(
        (path for path in canary_default_candidates if path.is_file()), None
    )
    launcher_default: str | None = None
    if lock_default.is_file():
        try:
            lock_payload = json.loads(lock_default.read_text(encoding="utf-8"))
            invoked = (
                lock_payload.get("codex_host", {})
                .get("launcher", {})
                .get("invoked_path")
            )
            if (
                isinstance(invoked, str)
                and Path(invoked).is_file()
                and os.access(invoked, os.X_OK)
            ):
                launcher_default = invoked
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, AttributeError):
            launcher_default = None
        if launcher_default is None:
            launcher_default = shutil.which("codex")
    native_default: str | None = None
    if launcher_default:
        try:
            native_default = str(discover_codex_native_binary(Path(launcher_default)))
        except (IntegrationLockError, OSError, ValueError):
            native_default = None
    names = {
        "lock": "ARW_INTEGRATION_LOCK",
        "launcher": "ARW_CODEX_LAUNCHER",
        "native": "ARW_CODEX_NATIVE_BINARY",
        "canary": "ARW_HOST_CANARY_EVIDENCE",
    }
    defaults = {
        "lock": str(lock_default) if lock_default.is_file() else None,
        "launcher": launcher_default,
        "native": native_default,
        "canary": str(canary_default) if canary_default is not None else None,
    }
    values = {key: os.environ.get(name) or defaults[key] for key, name in names.items()}
    # Installed qualification inputs travel with the plugin. Prefer them over
    # leftover ARW_* from a prior qualify session (foreign-runtime canaries /
    # bin-vs-sbin launcher drift), which would otherwise false-BLOCK route.
    for key in ("lock", "canary", "launcher", "native"):
        if defaults[key] is not None:
            values[key] = defaults[key]
    return plugin_root, {
        key: Path(value) if value is not None else None for key, value in values.items()
    }

def _installed_route_from_environment():
    from arw.kernel.policy.contracts import installed_route

    plugin_root, values = _discover_installed_route_inputs()
    lock_path = values["lock"]
    launcher_path = values["launcher"]
    native_path = values["native"]
    canary_path = values["canary"]
    if not any((lock_path, launcher_path, native_path, canary_path)):
        return installed_route()
    if (
        lock_path is None
        or launcher_path is None
        or native_path is None
        or canary_path is None
    ):
        return installed_route(blocked_reason="integration_inputs_incomplete")
    from arw.kernel.policy.integration_lock import (
        IntegrationLockError,
        load_and_verify_integration_lock,
    )

    try:
        verification = load_and_verify_integration_lock(
            lock_path,
            stage_root=plugin_root,
            codex_launcher=launcher_path,
            codex_native_binary=native_path,
            host_canary_evidence=canary_path,
        )
    except (IntegrationLockError, OSError, ValueError):
        return installed_route(blocked_reason="integration_lock_invalid_or_drifted")
    return installed_route(verification)

def _installed_route_diagnostics_from_environment():
    from arw.kernel.policy.integration_lock import diagnose_integration_lock

    plugin_root, values = _discover_installed_route_inputs()
    return diagnose_integration_lock(
        values["lock"],
        stage_root=plugin_root,
        codex_launcher=values["launcher"],
        codex_native_binary=values["native"],
        host_canary_evidence=values["canary"],
    )

def _blocked_orchestration_result(command: str, *reason_codes: str) -> None:
    _write_json(
        {
            "schema_version": "arw.orchestration-command-result.v1",
            "command": command,
            "status": "BLOCKED",
            "execution_mode": "blocked",
            "reason_codes": list(dict.fromkeys(reason_codes)),
        }
    )

def _blocked_execution_adapter():
    from arw.kernel.execution.execution import CodexExecExecutionAdapter, NativeHostConfig

    return CodexExecExecutionAdapter(NativeHostConfig(execution_mode="blocked"))

def _path_argument_or_environment(
    args: argparse.Namespace,
    attribute: str,
    environment_name: str,
) -> Path | None:
    value = getattr(args, attribute, None)
    if value is not None:
        return Path(value)
    environment_value = os.environ.get(environment_name)
    return Path(environment_value) if environment_value else None

class _AssignmentCodexExecAdapter:
    """Route each frozen assignment to its independently qualified adapter."""

    def __init__(self, adapters: Mapping[str, Any]) -> None:
        self.adapters = dict(adapters)

    def _adapter(self, spec: Any) -> Any:
        adapter = self.adapters.get(spec.assignment_id)
        if adapter is None:
            from arw.kernel.execution.execution import HostQualificationBlocked, NativeHostQualification

            raise HostQualificationBlocked(
                NativeHostQualification(
                    requested_mode="blocked",
                    execution_mode="blocked",
                    formal_independence=False,
                    stable_host_identity=False,
                    assignment_mapping_proven=False,
                    isolation_proven=False,
                    profile_configured=False,
                    permission_configured=False,
                    hook_configured=False,
                    reason_codes=("assignment_host_evidence_missing",),
                )
            )
        return adapter

    async def dispatch(self, spec: Any) -> Any:
        return await self._adapter(spec).dispatch(spec)

    async def request_cancel(self, spec: Any) -> None:
        await self._adapter(spec).request_cancel(spec)

    async def force_terminate(self, spec: Any) -> None:
        await self._adapter(spec).force_terminate(spec)

def _verified_dispatch_adapter(
    args: argparse.Namespace,
) -> tuple[_AssignmentCodexExecAdapter | None, object | None, tuple[str, ...]]:
    """Build no executable route until integration and host evidence both pass."""

    from arw.kernel.execution.execution import (
        CodexExecExecutionAdapter,
        CodexExecQualificationReceipt,
        NativeHostConfig,
    )
    from arw.kernel.policy.integration_lock import (
        IntegrationLockError,
        load_and_verify_integration_lock,
        load_integration_lock,
    )

    integration_paths = {
        "lock": _path_argument_or_environment(
            args, "integration_lock", "ARW_INTEGRATION_LOCK"
        ),
        "stage": _path_argument_or_environment(args, "stage_root", "ARW_PLUGIN_ROOT"),
        "launcher": _path_argument_or_environment(
            args, "codex_launcher", "ARW_CODEX_LAUNCHER"
        ),
        "native": _path_argument_or_environment(
            args, "codex_native_binary", "ARW_CODEX_NATIVE_BINARY"
        ),
        "canary": _path_argument_or_environment(
            args, "host_canary_evidence", "ARW_HOST_CANARY_EVIDENCE"
        ),
    }
    if any(value is None for value in integration_paths.values()):
        return None, None, ("integration_inputs_incomplete",)
    try:
        verification = load_and_verify_integration_lock(
            integration_paths["lock"],  # type: ignore[arg-type]
            stage_root=integration_paths["stage"],  # type: ignore[arg-type]
            codex_launcher=integration_paths["launcher"],  # type: ignore[arg-type]
            codex_native_binary=integration_paths["native"],  # type: ignore[arg-type]
            host_canary_evidence=integration_paths["canary"],  # type: ignore[arg-type]
        )
        lock = load_integration_lock(integration_paths["lock"])  # type: ignore[arg-type]
        loaded_lock_sha256 = hashlib.sha256(
            canonical_json_bytes(lock.model_dump(mode="json"))
        ).hexdigest()
        if loaded_lock_sha256 != verification.integration_lock_sha256:
            raise CLIInputError("integration lock changed during verification")
    except (IntegrationLockError, OSError, ValueError):
        return None, None, ("integration_lock_invalid_or_drifted",)

    evidence_path = args.host_evidence
    expected_evidence_digest = args.host_evidence_sha256
    if evidence_path is None or expected_evidence_digest is None:
        return None, verification, ("host_evidence_missing_or_incomplete",)
    if (
        not _is_sha256_text(expected_evidence_digest)
        or evidence_path.is_symlink()
        or not evidence_path.is_file()
    ):
        return None, verification, ("host_evidence_invalid_or_drifted",)
    try:
        raw = evidence_path.read_bytes()
    except OSError:
        return None, verification, ("host_evidence_invalid_or_drifted",)
    if hashlib.sha256(raw).hexdigest() != expected_evidence_digest:
        return None, verification, ("host_evidence_invalid_or_drifted",)
    try:
        manifest = _canonical_object_from_bytes(raw, label="host evidence")
    except CLIInputError:
        return None, verification, ("host_evidence_invalid_or_drifted",)
    if set(manifest) != {"schema_version", "integration_lock_sha256", "assignments"}:
        return None, verification, ("host_evidence_invalid_or_drifted",)
    assignment_rows = manifest.get("assignments")
    if (
        manifest.get("schema_version") != "arw.codex-exec-dispatch-evidence.v1"
        or manifest.get("integration_lock_sha256")
        != verification.integration_lock_sha256
        or not isinstance(assignment_rows, list)
    ):
        return None, verification, ("host_evidence_invalid_or_drifted",)

    codex_version = lock.codex_host.cli_version.removeprefix("codex-cli ")
    adapters: dict[str, CodexExecExecutionAdapter] = {}
    expected_row_keys = {
        "assignment_id",
        "qualification_receipt_path",
        "qualification_receipt_sha256",
        "credential_source_codex_home",
        "permission_digest",
    }
    try:
        for raw_row in assignment_rows:
            if not isinstance(raw_row, dict) or set(raw_row) != expected_row_keys:
                raise CLIInputError("host evidence assignment row is invalid")
            if any(not isinstance(raw_row[key], str) for key in expected_row_keys):
                raise CLIInputError("host evidence assignment values must be strings")
            assignment_id = raw_row["assignment_id"]
            if assignment_id in adapters:
                raise CLIInputError("host evidence assignment IDs must be unique")
            receipt_path = Path(raw_row["qualification_receipt_path"])
            credential_home = Path(raw_row["credential_source_codex_home"])
            if not receipt_path.is_absolute() or not credential_home.is_absolute():
                raise CLIInputError("host evidence paths must be absolute")
            receipt = CodexExecQualificationReceipt.from_canonical_bytes(
                receipt_path.read_bytes()
            )
            if receipt.assignment_id != assignment_id:
                raise CLIInputError("host receipt assignment mapping drifted")
            adapters[assignment_id] = CodexExecExecutionAdapter(
                NativeHostConfig(
                    execution_mode=receipt.execution_mode,
                    profile_name=receipt.profile_name,
                    permission_digest=raw_row["permission_digest"],
                    hook_config_digest=verification.hook_definition_sha256,
                    codex_version=codex_version,
                    codex_binary_sha256=lock.codex_host.native_binary.sha256,
                    profile_digest=receipt.profile_digest,
                    qualification_receipt_path=receipt_path,
                    expected_qualification_receipt_sha256=raw_row[
                        "qualification_receipt_sha256"
                    ],
                    credential_source_codex_home=credential_home,
                    credential_files=("auth.json", "config.toml"),
                    codex_command=(str(integration_paths["native"]),),
                )
            )
    except (CLIInputError, OSError, ValueError):
        return None, verification, ("host_evidence_invalid_or_drifted",)
    if not adapters:
        return None, verification, ("host_evidence_missing_or_incomplete",)
    return _AssignmentCodexExecAdapter(adapters), verification, ()

def _rehydrate_prepared_run(service: Any) -> Any:
    from arw.kernel.execution.orchestration import OrchestrationError, PreparedRun

    state = service.runtime.read_state()
    if not all(
        (
            state.role_catalog_sha256,
            state.policy_sha256,
            state.dag_sha256,
            state.execution_mode,
        )
    ):
        raise OrchestrationError(
            "canonical run has no complete prepared orchestration intent"
        )
    assignments = tuple(item.assignment for item in state.assignments)
    if not assignments:
        raise OrchestrationError("canonical run has no prepared assignments")
    return PreparedRun(
        state=state,
        assignments=assignments,
        role_catalog_sha256=state.role_catalog_sha256,
        policy_sha256=state.policy_sha256,
        dag_sha256=state.dag_sha256,
        execution_mode=state.execution_mode,
    )

def _dispatch_report_json(
    report: Any, integration_lock_sha256: str
) -> dict[str, object]:
    return {
        "schema_version": "arw.orchestration-command-result.v1",
        "command": "orchestration-dispatch",
        "status": report.state.status,
        "execution_mode": report.state.execution_mode,
        "accepted_revision": report.state.accepted_revision,
        "ledger_head_sha256": report.state.ledger_head_sha256,
        "integration_lock_sha256": integration_lock_sha256,
        "outcomes": [
            {
                "assignment_id": outcome.assignment_id,
                "status": outcome.status,
                "classification": outcome.classification,
                "retry_reason": outcome.retry_reason,
                "attempts": [
                    {
                        "attempt_id": attempt.attempt_id,
                        "attempt_number": attempt.attempt_number,
                        "status": attempt.status,
                        "failure_reason": attempt.failure_reason,
                    }
                    for attempt in outcome.attempts
                ],
            }
            for outcome in report.outcomes
        ],
    }

