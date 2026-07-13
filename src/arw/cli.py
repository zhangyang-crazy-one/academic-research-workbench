"""Command-line entrypoint for the Academic Research Workbench control plane."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from arw.build_identity import BuildIdentityError, load_packaged_build_identity
from arw.canonical import canonical_json_bytes, strict_json_loads
from arw.contracts import installed_route
from arw.files import FilesAdminError, FilesAdminService
from arw.file_models import ExtractionRegistration
from arw.journal import JournalError, append_probe, initialize_run, replay_run
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
    Rejection,
    RecoveryRequest,
    ResumeRequest,
    StrictModel,
)
from arw.reducer import ReducerError, reduce_events
from arw.runtime import RuntimeCommandService
from arw.status import build_status_report, render_status_text


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
    return parser


def _add_run_request_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--lock-timeout", type=float, default=0.2)


def _load_request(path: Path, model: type[StrictModel]) -> StrictModel:
    try:
        raw = path.read_bytes()
        payload = strict_json_loads(raw)
        return model.model_validate(payload)
    except (OSError, UnicodeError, ValueError, ValidationError) as error:
        raise JournalError(f"request is missing or invalid: {error}") from error


def _write_json(payload: object) -> None:
    sys.stdout.buffer.write(canonical_json_bytes(payload))


def _parse_utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as error:
        raise JournalError("--at must be an exact UTC YYYY-MM-DDTHH:MM:SSZ timestamp") from error


def _write_rejection(error: Exception) -> None:
    rejection = Rejection(code="canonical-error", message=str(error))
    sys.stderr.buffer.write(canonical_json_bytes(rejection.model_dump(mode="json")))


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "route":
        if not args.json_output:
            parser.error("route requires --json")
        _write_json(installed_route().model_dump(mode="json"))
        return 0
    if args.command == "version":
        if not args.json_output:
            parser.error("version requires --json")
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
    if args.command == "files":
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
        except (FilesAdminError, JournalError, ValidationError) as error:
            print(f"arw: files-admin-error: {error}", file=sys.stderr)
            return 65

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
    except (JournalError, ManifestError, ReducerError) as error:
        if args.command == "status" and args.json_output:
            _write_rejection(error)
        else:
            print(f"arw: canonical-error: {error}", file=sys.stderr)
        return 65

    parser.error(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
