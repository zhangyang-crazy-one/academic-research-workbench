"""Command-line entrypoint for the Academic Research Workbench control plane."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from arw.canonical import canonical_json_bytes, strict_json_loads


RequestModel = TypeVar("RequestModel", bound=BaseModel)


class CLIInputError(ValueError):
    """A CLI-only envelope or evidence input is invalid."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arw",
        description="Academic Research Workbench control plane.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    route = subparsers.add_parser(
        "route",
        help="Emit the installed read-only ARS workflow route.",
    )
    route.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Write the strict route contract as JSON.",
    )
    version = subparsers.add_parser(
        "version",
        help="Report the installed packaged build identity.",
    )
    version.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Write the strict version-report contract as JSON.",
    )
    storm = subparsers.add_parser(
        "storm",
        help="Run the opt-in STORM deep-research pipeline (experiments / deep thinking).",
    )
    storm.add_argument("--topic", required=True, help="Research topic for STORM.")
    storm.add_argument(
        "--output-dir",
        type=Path,
        default=Path("build/storm"),
        help="Directory for STORM artifacts (default: build/storm).",
    )
    storm.add_argument(
        "--backend",
        choices=["session", "litellm"],
        default="session",
        help="Model backend: session (current agent session model) or litellm "
        "(explicit OpenAI-compatible endpoint).",
    )
    storm.add_argument(
        "--model",
        default=None,
        help="LiteLLM model id, e.g. openai/gemini-2.5-flash.",
    )
    storm.add_argument("--api-key", default=None, help="Model API key (default: GEMINI_API_KEY).")
    storm.add_argument(
        "--api-base", default=None, help="OpenAI-compatible API base (default: GOOGLE_GEMINI_BASE_URL)."
    )
    storm.add_argument(
        "--retriever", choices=["tavily", "duckduckgo"], default="tavily",
        help="Search retriever (default: tavily; duckduckgo needs no key).",
    )
    storm.add_argument("--max-conv-turn", type=int, default=4)
    storm.add_argument("--max-perspective", type=int, default=5)
    storm.add_argument("--search-top-k", type=int, default=5)
    storm.add_argument("--retrieve-top-k", type=int, default=5)
    storm.add_argument("--max-thread-num", type=int, default=3)
    storm.add_argument(
        "--do-research", action=argparse.BooleanOptionalAction, default=True
    )
    storm.add_argument(
        "--do-generate-outline", action=argparse.BooleanOptionalAction, default=True
    )
    storm.add_argument(
        "--do-generate-article", action=argparse.BooleanOptionalAction, default=True
    )
    storm.add_argument("--do-polish-article", action="store_true")
    storm.add_argument("--remove-duplicate", action="store_true")
    init = subparsers.add_parser(
        "init",
        help="Initialize an immutable run manifest and first canonical event.",
    )
    _add_run_request_arguments(init)
    append = subparsers.add_parser(
        "append",
        help="Append one Phase 1 baseline event through the sole writer.",
    )
    _add_run_request_arguments(append)
    replay = subparsers.add_parser(
        "replay",
        help="Replay and validate manifest plus canonical JSONL only.",
    )
    replay.add_argument("--run-root", required=True, type=Path)
    replay.add_argument("--lock-timeout", type=float, default=0.2)
    status = subparsers.add_parser(
        "status",
        help="Render the canonical runtime state without modifying the run.",
    )
    status.add_argument("--run-root", required=True, type=Path)
    status.add_argument("--lock-timeout", type=float, default=0.2)
    status.add_argument("--json", action="store_true", dest="json_output")
    status.add_argument(
        "--at",
        metavar="UTC_TIMESTAMP",
        help="Evaluate dynamic freshness at an explicit YYYY-MM-DDTHH:MM:SSZ instant.",
    )
    for name, help_text in (
        ("transition", "Submit one registered lifecycle transition."),
        ("decision-request", "Record one pending human decision."),
        ("decision-resolve", "Resolve one pending human decision."),
        ("attempt-start", "Record one parent-controlled attempt start."),
        ("attempt-close", "Close one active parent-controlled attempt."),
        ("artifact-accept", "Accept one immutable content-addressed artifact."),
        ("checkpoint", "Create one coherent immutable Material Passport."),
        ("resume", "Resume once from the exact current Material Passport."),
        ("recover", "Quarantine one terminal tail and continue explicitly."),
    ):
        command = subparsers.add_parser(name, help=help_text)
        _add_run_request_arguments(command)
    orchestration_prepare = subparsers.add_parser(
        "orchestration-prepare",
        help="Freeze a Phase 4 parent run and materialize immutable assignments.",
    )
    _add_run_request_arguments(orchestration_prepare)
    orchestration_prepare.add_argument(
        "--assignments",
        required=True,
        type=Path,
        help="Canonical JSON array of parent-authored AssignmentSpec objects.",
    )
    orchestration_prepare.add_argument(
        "--execution-mode",
        choices=(
            "native_profile",
            "assignment_injected_subagent",
            "degraded_inline",
            "blocked",
        ),
        default="assignment_injected_subagent",
        help="Freeze execution intent; this does not itself qualify host dispatch.",
    )
    orchestration_dispatch = subparsers.add_parser(
        "orchestration-dispatch",
        help="Dispatch a frozen Phase 4 run only through exact Codex exec evidence.",
    )
    _add_run_request_arguments(orchestration_dispatch)
    _add_integration_arguments(orchestration_dispatch)
    orchestration_dispatch.add_argument(
        "--host-evidence",
        type=Path,
        help="Canonical assignment-to-Codex-exec qualification manifest.",
    )
    orchestration_dispatch.add_argument(
        "--host-evidence-sha256",
        help="Parent-expected SHA-256 of the exact host-evidence manifest bytes.",
    )
    orchestration_panel = subparsers.add_parser(
        "orchestration-panel",
        help="Freeze a canonical formal-panel manifest from retained host identities.",
    )
    _add_run_request_arguments(orchestration_panel)
    orchestration_panel.add_argument("--panel", required=True, type=Path)
    orchestration_gate = subparsers.add_parser(
        "orchestration-gate",
        help="Evaluate one canonical Phase 4 gate from parent-accepted evidence.",
    )
    _add_run_request_arguments(orchestration_gate)
    orchestration_gate.add_argument("--gate", required=True, type=Path)
    orchestration_hook = subparsers.add_parser(
        "orchestration-hook",
        help="Record one non-authoritative canonical hook observation.",
    )
    _add_run_request_arguments(orchestration_hook)
    orchestration_hook.add_argument("--observation", required=True, type=Path)
    orchestration_recover = subparsers.add_parser(
        "orchestration-recover",
        help="Reconcile replay-visible Phase 4 dispatch crash gaps idempotently.",
    )
    _add_run_request_arguments(orchestration_recover)
    rebuild_pointer = subparsers.add_parser(
        "passport-pointer-rebuild",
        help="Explicitly rebuild the derived Passport pointer from accepted events.",
    )
    rebuild_pointer.add_argument("--run-root", required=True, type=Path)
    rebuild_pointer.add_argument("--lock-timeout", type=float, default=0.2)
    files = subparsers.add_parser(
        "files",
        help="Parent-only file root, extraction, and generation administration.",
    )
    files_subcommands = files.add_subparsers(dest="files_command", required=True)
    for resource in ("root", "extraction"):
        command = files_subcommands.add_parser(resource)
        actions = command.add_subparsers(dest="files_action", required=True)
        register = actions.add_parser("register")
        register.add_argument("--control-root", required=True, type=Path)
        register.add_argument("--root-id", required=True)
        if resource == "root":
            register.add_argument("--root-path", required=True, type=Path)
            register.add_argument("--policy-id", required=True)
        else:
            register.add_argument("--request", required=True, type=Path)
            register.add_argument("--text", required=True, type=Path)
    for name in ("sync", "rebuild", "repair", "status"):
        command = files_subcommands.add_parser(name)
        command.add_argument("--control-root", required=True, type=Path)
        command.add_argument("--root-id", required=True)
        if name in {"sync", "rebuild", "repair"}:
            command.add_argument("--extractor-version", required=True)
    graph_mcp = subparsers.add_parser("_graph-mcp", help=argparse.SUPPRESS)
    graph_mcp.add_argument("--control-root", required=True, type=Path)
    graph_mcp.add_argument("--root-id", required=True)
    return parser


def _add_run_request_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--lock-timeout", type=float, default=0.2)


def _add_integration_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--integration-lock", type=Path)
    parser.add_argument("--stage-root", type=Path)
    parser.add_argument("--codex-launcher", type=Path)
    parser.add_argument("--codex-native-binary", type=Path)
    parser.add_argument("--host-canary-evidence", type=Path)


def _load_request(path: Path, model: type[RequestModel]) -> RequestModel:
    try:
        raw = path.read_bytes()
        payload = strict_json_loads(raw)
        return model.model_validate(payload)
    except (OSError, UnicodeError, ValueError, ValidationError) as error:
        raise CLIInputError(f"request is missing or invalid: {error}") from error


def _canonical_object_from_bytes(raw: bytes, *, label: str) -> dict[str, object]:
    try:
        value = strict_json_loads(raw)
    except (UnicodeError, ValueError) as error:
        raise CLIInputError(f"{label} is invalid: {error}") from error
    if not isinstance(value, dict):
        raise CLIInputError(f"{label} must be a JSON object")
    if canonical_json_bytes(value) != raw:
        raise CLIInputError(f"{label} bytes are not canonical")
    return value


def _load_object(path: Path, *, label: str) -> dict[str, object]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise CLIInputError(f"{label} is missing or invalid: {error}") from error
    return _canonical_object_from_bytes(raw, label=label)


def _is_sha256_text(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _identity_receipt_reference(value: object, *, label: str) -> dict[str, str]:
    digest = value.get("identity_receipt_sha256") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or set(value) != {"identity_receipt_sha256"}
        or not _is_sha256_text(digest)
    ):
        raise CLIInputError(f"{label} must contain one exact identity receipt digest")
    return {"identity_receipt_sha256": str(digest)}


def _write_json(payload: object) -> None:
    sys.stdout.buffer.write(canonical_json_bytes(payload))


def _parse_utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as error:
        raise CLIInputError(
            "--at must be an exact UTC YYYY-MM-DDTHH:MM:SSZ timestamp"
        ) from error


def _write_rejection(error: Exception) -> None:
    from arw.models import Rejection

    rejection = Rejection(code="canonical-error", message=str(error))
    sys.stderr.buffer.write(canonical_json_bytes(rejection.model_dump(mode="json")))


def _installed_route_from_environment():
    from arw.contracts import installed_route
    from arw.integration_lock import discover_codex_native_binary

    plugin_root = Path(
        os.environ.get("ARW_PLUGIN_ROOT", Path(__file__).resolve().parents[2])
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
    canary_default = next((path for path in canary_default_candidates if path.is_file()), None)
    launcher_default: str | None = None
    if lock_default.is_file():
        try:
            lock_payload = json.loads(lock_default.read_text(encoding="utf-8"))
            invoked = (
                lock_payload.get("codex_host", {})
                .get("launcher", {})
                .get("invoked_path")
            )
            if isinstance(invoked, str) and Path(invoked).is_file() and os.access(invoked, os.X_OK):
                launcher_default = invoked
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, AttributeError):
            launcher_default = None
        if launcher_default is None:
            launcher_default = shutil.which("codex")
    native_default: str | None = None
    if launcher_default:
        try:
            native_default = str(
                discover_codex_native_binary(Path(launcher_default))
            )
        except (OSError, ValueError):
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
    values = {
        key: os.environ.get(name) or defaults[key]
        for key, name in names.items()
    }
    # Installed qualification inputs travel with the plugin. Prefer them over
    # leftover ARW_* from a prior qualify session (foreign-runtime canaries /
    # bin-vs-sbin launcher drift), which would otherwise false-BLOCK route.
    for key in ("lock", "canary", "launcher", "native"):
        if defaults[key] is not None:
            values[key] = defaults[key]
    if not any(values.values()):
        return installed_route()
    if not all(values.values()):
        return installed_route(blocked_reason="integration_inputs_incomplete")
    from arw.integration_lock import IntegrationLockError, load_and_verify_integration_lock

    try:
        verification = load_and_verify_integration_lock(
            Path(values["lock"]),
            stage_root=plugin_root,
            codex_launcher=Path(values["launcher"]),
            codex_native_binary=Path(values["native"]),
            host_canary_evidence=Path(values["canary"]),
        )
    except (IntegrationLockError, OSError, ValueError):
        return installed_route(blocked_reason="integration_lock_invalid_or_drifted")
    return installed_route(verification)


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
    from arw.execution import CodexExecExecutionAdapter, NativeHostConfig

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
            from arw.execution import HostQualificationBlocked, NativeHostQualification

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

    from arw.execution import (
        CodexExecExecutionAdapter,
        CodexExecQualificationReceipt,
        NativeHostConfig,
    )
    from arw.integration_lock import (
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
    if (
        manifest.get("schema_version") != "arw.codex-exec-dispatch-evidence.v1"
        or manifest.get("integration_lock_sha256")
        != verification.integration_lock_sha256
        or not isinstance(manifest.get("assignments"), list)
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
        for raw_row in manifest["assignments"]:
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
    from arw.orchestration import OrchestrationError, PreparedRun

    state = service.runtime.read_state()
    if not all(
        (
            state.role_catalog_sha256,
            state.policy_sha256,
            state.dag_sha256,
            state.execution_mode,
        )
    ):
        raise OrchestrationError("canonical run has no complete prepared orchestration intent")
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


def _dispatch_report_json(report: Any, integration_lock_sha256: str) -> dict[str, object]:
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "route":
        if not args.json_output:
            parser.error("route requires --json")
        _write_json(_installed_route_from_environment().model_dump(mode="json"))
        return 0
    if args.command == "version":
        if not args.json_output:
            parser.error("version requires --json")
        from arw.build_identity import BuildIdentityError, load_packaged_build_identity

        try:
            identity, digest = load_packaged_build_identity()
        except BuildIdentityError as error:
            print(f"arw: build-identity-error: {error}", file=sys.stderr)
            return 65
        _write_json(
            {
                "schema_version": "1.0.0",
                "command": "version",
                "build_identity_sha256": digest,
                "identity": identity,
            }
        )
        return 0
    if args.command == "storm":
        from arw.storm import StormConfig, StormRunError, run_storm_research

        config_kwargs: dict[str, object] = {
            "topic": args.topic,
            "output_dir": Path(args.output_dir),
            "backend": args.backend,
            "retriever": args.retriever,
        }
        if args.model is not None:
            config_kwargs["model"] = args.model
        if args.api_key is not None:
            config_kwargs["api_key"] = args.api_key
        if args.api_base is not None:
            config_kwargs["api_base"] = args.api_base
        config = StormConfig(**config_kwargs,
            max_conv_turn=args.max_conv_turn,
            max_perspective=args.max_perspective,
            search_top_k=args.search_top_k,
            retrieve_top_k=args.retrieve_top_k,
            max_thread_num=args.max_thread_num,
            do_research=args.do_research,
            do_generate_outline=args.do_generate_outline,
            do_generate_article=args.do_generate_article,
            do_polish_article=args.do_polish_article,
            remove_duplicate=args.remove_duplicate,
        )
        try:
            receipt = run_storm_research(config)
        except StormRunError as error:
            print(f"arw: storm-error: {error}", file=sys.stderr)
            return 65
        _write_json(receipt.model_dump(mode="json"))
        return 0
    if args.command == "files":
        from arw.file_models import ExtractionRegistration
        from arw.files import FilesAdminError, FilesAdminService

        try:
            builder_value = os.environ.get("ARW_FILES_NATIVE_BUILDER")
            service = FilesAdminService(
                args.control_root,
                native_builder=None if builder_value is None else Path(builder_value),
            )
            if args.files_command == "root":
                result = service.register_root(
                    root_id=args.root_id,
                    root_path=args.root_path,
                    policy_id=args.policy_id,
                )
                _write_json(result.model_dump(mode="json"))
            elif args.files_command == "extraction":
                registration = _load_request(args.request, ExtractionRegistration)
                service.register_extraction(args.root_id, registration, args.text)
                _write_json(
                    registration.model_dump(mode="json", exclude_computed_fields=True)
                )
            elif args.files_command in {"sync", "rebuild", "repair"}:
                method = getattr(service, args.files_command)
                receipt = method(args.root_id, extractor_version=args.extractor_version)
                _write_json(receipt.model_dump(mode="json"))
            else:
                _write_json(service.status(args.root_id))
            return 0
        except (FilesAdminError, CLIInputError, ValidationError) as error:
            print(f"arw: files-admin-error: {error}", file=sys.stderr)
            return 65
    if args.command == "_graph-mcp":
        from arw.graph_mcp import GraphMcpServer, run_stdio
        from arw.graph_store import GraphStore

        return run_stdio(GraphMcpServer(GraphStore(args.control_root, args.root_id)))

    # Writable/runtime services are intentionally imported only after the two
    # read-only installed commands above have returned.
    from arw.journal import (
        JournalError,
        append_probe,
        initialize_run,
        replay_run,
    )
    from arw.manifests import ManifestError
    from arw.models import (
        AppendProbeRequest,
        ArtifactAcceptanceRequest,
        AttemptCloseRequest,
        AttemptStartRequest,
        CheckpointRequest,
        HumanDecisionRequest,
        HumanDecisionResolveRequest,
        InitRunRequest,
        LifecycleTransitionRequest,
        RecoveryRequest,
        ResumeRequest,
        RuntimeCommandRequest,
    )
    from arw.orchestration import (
        AssignmentSpec,
        OrchestrationError,
        OrchestrationService,
    )
    from arw.orchestration_models import GateDecision, HookObservation
    from arw.reducer import ReducerError, reduce_events
    from arw.runtime import RuntimeCommandService
    from arw.status import build_status_report, render_status_text

    try:
        if args.command == "init":
            request = _load_request(args.request, InitRunRequest)
            state = initialize_run(
                args.run_root,
                request,
                lock_timeout=args.lock_timeout,
            )
            _write_json(
                {
                    "event_sha256": state.last_event_sha256,
                    "revision": state.revision,
                    "run_id": state.run_id,
                }
            )
            return 0
        if args.command == "append":
            request = _load_request(args.request, AppendProbeRequest)
            state = append_probe(
                args.run_root,
                request,
                lock_timeout=args.lock_timeout,
            )
            _write_json(
                {
                    "event_sha256": state.last_event_sha256,
                    "revision": state.revision,
                    "run_id": state.run_id,
                }
            )
            return 0
        if args.command == "replay":
            state = replay_run(args.run_root, lock_timeout=args.lock_timeout)
            reduce_events(
                state.workflow_definition_id,
                state.events,
                recovery_health=state.recovery_health,
            )
            _write_json(state.public_dict())
            return 0
        if args.command == "status":
            replayed = replay_run(args.run_root, lock_timeout=args.lock_timeout)
            status_now = _parse_utc(args.at) or datetime.now(UTC)
            state = reduce_events(
                replayed.workflow_definition_id,
                replayed.events,
                now=status_now,
                recovery_health=replayed.recovery_health,
            )
            report = build_status_report(state)
            if args.json_output:
                _write_json(report.model_dump(mode="json"))
            else:
                sys.stdout.write(render_status_text(report))
            return 0
        if args.command == "orchestration-prepare":
            request = _load_request(args.request, LifecycleTransitionRequest)
            try:
                raw_assignments = strict_json_loads(args.assignments.read_bytes())
                if not isinstance(raw_assignments, list):
                    raise ValueError("--assignments must contain a JSON array")
                assignments = tuple(
                    AssignmentSpec(**item)
                    for item in raw_assignments
                    if isinstance(item, dict)
                )
                if len(assignments) != len(raw_assignments):
                    raise ValueError("every assignment entry must be a JSON object")
            except (OSError, UnicodeError, ValueError, TypeError) as error:
                raise JournalError(f"assignments are missing or invalid: {error}") from error
            prepared = OrchestrationService(
                args.run_root,
                adapter=_blocked_execution_adapter(),
                lock_timeout=args.lock_timeout,
            ).prepare(
                request,
                assignments=assignments,
                execution_mode=args.execution_mode,
            )
            _write_json(
                {
                    "accepted_revision": prepared.state.accepted_revision,
                    "assignment_ids": [item.assignment_id for item in prepared.assignments],
                    "dag_sha256": prepared.dag_sha256,
                    "execution_mode": prepared.execution_mode,
                    "ledger_head_sha256": prepared.state.ledger_head_sha256,
                    "policy_sha256": prepared.policy_sha256,
                    "role_catalog_sha256": prepared.role_catalog_sha256,
                    "run_id": prepared.state.run_id,
                    "stage": prepared.state.stage,
                }
            )
            return 0
        if args.command == "orchestration-dispatch":
            request = _load_request(args.request, RuntimeCommandRequest)
            adapter, verification, reasons = _verified_dispatch_adapter(args)
            if adapter is None or verification is None:
                _blocked_orchestration_result(args.command, *reasons)
                return 65
            service = OrchestrationService(
                args.run_root,
                adapter=adapter,
                lock_timeout=args.lock_timeout,
            )
            prepared = _rehydrate_prepared_run(service)
            assignment_ids = {item.assignment_id for item in prepared.assignments}
            if set(adapter.adapters) != assignment_ids:
                _blocked_orchestration_result(
                    args.command, "host_evidence_assignment_set_mismatch"
                )
                return 65
            from arw.execution import DispatchSpec

            qualification_reasons: list[str] = []
            for assignment in prepared.assignments:
                host_adapter = adapter.adapters[assignment.assignment_id]
                qualification = host_adapter.qualification_for(
                    DispatchSpec(
                        assignment_id=assignment.assignment_id,
                        attempt_id=f"attempt.{assignment.assignment_id}.qualification",
                        acceptance_key=assignment.acceptance_key.value,
                        assignment_path=(
                            args.run_root
                            / "assignments"
                            / f"{assignment.assignment_id}.json"
                        ),
                        attempt_root=(
                            args.run_root
                            / "attempts"
                            / f"attempt.{assignment.assignment_id}.qualification"
                        ),
                    )
                )
                required_proofs = {
                    "stable_host_identity_not_proven": qualification.stable_host_identity,
                    "assignment_mapping_not_proven": (
                        qualification.assignment_mapping_proven
                    ),
                    "isolation_not_proven": qualification.isolation_proven,
                    "profile_not_proven": qualification.profile_configured,
                    "permission_not_proven": qualification.permission_configured,
                    "hook_not_proven": qualification.hook_configured,
                }
                if not qualification.formal_independence:
                    qualification_reasons.extend(qualification.reason_codes)
                qualification_reasons.extend(
                    reason
                    for reason, proven in required_proofs.items()
                    if not proven
                )
                if qualification.execution_mode != prepared.execution_mode:
                    qualification_reasons.append("prepared_execution_mode_mismatch")
            if qualification_reasons:
                _blocked_orchestration_result(
                    args.command,
                    *(f"host_qualification:{item}" for item in qualification_reasons),
                )
                return 65
            # Library and app callers await OrchestrationService.dispatch;
            # asyncio.run is confined to this process-level CLI boundary.
            report = asyncio.run(service.dispatch(request, prepared))
            _write_json(
                _dispatch_report_json(
                    report,
                    verification.integration_lock_sha256,  # type: ignore[union-attr]
                )
            )
            return 0 if all(item.status == "completed" for item in report.outcomes) else 65
        if args.command == "orchestration-panel":
            request = _load_request(args.request, RuntimeCommandRequest)
            panel_request = _load_object(args.panel, label="panel request")
            expected_keys = {
                "schema_version",
                "panel_id",
                "subject_sha256",
                "rubric_sha256",
                "reviewer_identities",
                "synthesizer_identity",
                "execution_mode",
            }
            if (
                set(panel_request) != expected_keys
                or panel_request.get("schema_version") != "arw.cli-panel-request.v1"
                or not isinstance(panel_request.get("panel_id"), str)
                or not panel_request["panel_id"]
                or not _is_sha256_text(panel_request.get("subject_sha256"))
                or not _is_sha256_text(panel_request.get("rubric_sha256"))
                or not isinstance(panel_request.get("reviewer_identities"), dict)
                or panel_request.get("execution_mode")
                not in {"native_profile", "assignment_injected_subagent"}
            ):
                raise CLIInputError("panel request does not match the strict CLI contract")
            reviewer_identities: dict[str, dict[str, str]] = {}
            for role_id, identity_reference in panel_request[
                "reviewer_identities"
            ].items():
                if not isinstance(role_id, str) or not role_id:
                    raise CLIInputError("panel reviewer role IDs must be non-empty strings")
                reviewer_identities[role_id] = _identity_receipt_reference(
                    identity_reference,
                    label=f"panel reviewer {role_id}",
                )
            synthesizer_identity = panel_request["synthesizer_identity"]
            if synthesizer_identity is not None:
                synthesizer_identity = _identity_receipt_reference(
                    synthesizer_identity,
                    label="panel synthesizer",
                )
            service = OrchestrationService(
                args.run_root,
                adapter=_blocked_execution_adapter(),
                lock_timeout=args.lock_timeout,
            )
            panel = service.prepare_formal_panel(
                request,
                panel_id=panel_request["panel_id"],  # type: ignore[arg-type]
                subject_sha256=panel_request["subject_sha256"],  # type: ignore[arg-type]
                rubric_sha256=panel_request["rubric_sha256"],  # type: ignore[arg-type]
                reviewer_identities=reviewer_identities,
                synthesizer_identity=synthesizer_identity,
                execution_mode=panel_request["execution_mode"],  # type: ignore[arg-type]
            )
            _write_json(
                {
                    "schema_version": "arw.orchestration-command-result.v1",
                    "command": args.command,
                    "status": "PASS" if panel.status == "ready" else "BLOCKED",
                    "execution_mode": (
                        panel_request["execution_mode"]
                        if panel.status == "ready"
                        else "blocked"
                    ),
                    "panel_id": panel.panel_id,
                    "manifest_sha256": panel.manifest_sha256,
                    "reviewer_assignment_ids": [
                        item.assignment_id for item in panel.reviewer_assignments
                    ],
                    "synthesizer_assignment_id": (
                        panel.synthesizer_assignment.assignment_id
                        if panel.synthesizer_assignment is not None
                        else None
                    ),
                    "blockers": panel.blockers,
                    "limitations": panel.limitations,
                }
            )
            return 0 if panel.status == "ready" else 65
        if args.command == "orchestration-gate":
            request = _load_request(args.request, RuntimeCommandRequest)
            decision = GateDecision.model_validate(
                _load_object(args.gate, label="gate decision")
            )
            outcome = OrchestrationService(
                args.run_root,
                adapter=_blocked_execution_adapter(),
                lock_timeout=args.lock_timeout,
            ).evaluate_gate(request, decision)
            _write_json(outcome.model_dump(mode="json"))
            return 0 if outcome.accepted else 65
        if args.command == "orchestration-hook":
            request = _load_request(args.request, RuntimeCommandRequest)
            observation = HookObservation.model_validate(
                _load_object(args.observation, label="hook observation")
            )
            outcome = OrchestrationService(
                args.run_root,
                adapter=_blocked_execution_adapter(),
                lock_timeout=args.lock_timeout,
            ).record_hook_observation(request, observation)
            _write_json(outcome.model_dump(mode="json"))
            return 0 if outcome.accepted else 65
        if args.command == "orchestration-recover":
            request = _load_request(args.request, RuntimeCommandRequest)
            state = OrchestrationService(
                args.run_root,
                adapter=_blocked_execution_adapter(),
                lock_timeout=args.lock_timeout,
            ).recover_orphans(request)
            _write_json(
                {
                    "schema_version": "arw.orchestration-command-result.v1",
                    "command": args.command,
                    "status": state.status,
                    "execution_mode": state.execution_mode,
                    "accepted_revision": state.accepted_revision,
                    "ledger_head_sha256": state.ledger_head_sha256,
                    "attempt_count": len(state.attempts),
                }
            )
            return 0
        runtime_commands = {
            "transition": (LifecycleTransitionRequest, "execute_transition"),
            "decision-request": (HumanDecisionRequest, "request_decision"),
            "decision-resolve": (HumanDecisionResolveRequest, "resolve_decision"),
            "attempt-start": (AttemptStartRequest, "start_attempt"),
            "attempt-close": (AttemptCloseRequest, "close_attempt"),
            "artifact-accept": (ArtifactAcceptanceRequest, "accept_artifact"),
            "checkpoint": (CheckpointRequest, "create_checkpoint"),
            "resume": (ResumeRequest, "resume"),
            "recover": (RecoveryRequest, "recover"),
        }
        if args.command in runtime_commands:
            model, method_name = runtime_commands[args.command]
            request = _load_request(args.request, model)
            service = RuntimeCommandService(args.run_root, lock_timeout=args.lock_timeout)
            outcome = getattr(service, method_name)(request)
            _write_json(outcome.model_dump(mode="json"))
            return 0 if outcome.accepted else 65
        if args.command == "passport-pointer-rebuild":
            pointer = RuntimeCommandService(
                args.run_root, lock_timeout=args.lock_timeout
            ).rebuild_passport_pointer()
            _write_json(pointer.model_dump(mode="json"))
            return 0
    except (
        CLIInputError,
        JournalError,
        ManifestError,
        ReducerError,
        OrchestrationError,
        ValidationError,
        OSError,
    ) as error:
        if args.command == "status" and args.json_output:
            _write_rejection(error)
        elif isinstance(error, OSError):
            print(
                "arw: canonical-error: runtime event may already be committed to "
                f"the ledger; retry is safe: {error}",
                file=sys.stderr,
            )
        else:
            print(f"arw: canonical-error: {error}", file=sys.stderr)
        return 65

    parser.error(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
