"""Thin CLI adapter for the parent-owned submission workflow."""

from __future__ import annotations

import os
from pathlib import Path

from arw.cli_support import _load_request
from arw.kernel.core.canonical import strict_json_loads
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.state.models import (
    ArtifactAcceptanceRequest,
    LifecycleTransitionRequest,
)
from arw.kernel.state.submission import (
    SubmissionCheckReport,
    SubmissionResultObservation,
)


def configure(subparsers) -> None:
    parser = subparsers.add_parser(
        "submission",
        help="Prepare and qualify an auditable submission packet without external submission actions.",
    )
    actions = parser.add_subparsers(dest="submission_command", required=True)
    prepare = actions.add_parser("prepare")
    prepare.add_argument("--run-root", type=Path, required=True)
    prepare.add_argument("--kind", choices=(
        "journal-requirements",
        "submission-packet",
        "submission-review-round",
        "submission-response",
        "submission-check-report",
        "submission-verifier-observation",
        "submission-result-observation",
    ), required=True)
    prepare.add_argument("--input", type=Path, required=True)

    for name, kind in (
        ("record", None),
        ("review-import", "submission-review-round"),
        ("response-record", "submission-response"),
    ):
        command = actions.add_parser(name)
        command.add_argument("--run-root", type=Path, required=True)
        command.add_argument("--input", type=Path, required=True)
        command.add_argument("--request", type=Path, required=True)
        if kind is None:
            command.add_argument(
                "--kind",
                choices=(
                    "journal-requirements",
                    "submission-packet",
                    "submission-review-round",
                    "submission-response",
                    "submission-check-report",
                    "submission-verifier-observation",
                    "submission-result-observation",
                ),
                required=True,
            )

    qualify = actions.add_parser("qualify")
    qualify.add_argument("--run-root", type=Path, required=True)
    qualify.add_argument("--input", type=Path)
    qualify.add_argument("--request", type=Path, required=True)
    qualify.add_argument("--scope", choices=("readiness", "confirmation"), default="readiness")
    qualify.add_argument("--submission-id")
    qualify.add_argument("--subject-scope")
    qualify.add_argument("--subject-sha256")

    ready = actions.add_parser(
        "ready",
        help="Perform the registered parent lifecycle transition after fresh readiness and human approval.",
    )
    ready.add_argument("--run-root", type=Path, required=True)
    ready.add_argument("--submission-id", required=True)
    ready.add_argument("--request", type=Path, required=True)

    record_result = actions.add_parser("record-result")
    record_result.add_argument("--run-root", type=Path, required=True)
    record_result.add_argument("--input", type=Path, required=True)
    record_result.add_argument("--request", type=Path, required=True)

    for name in ("check", "status"):
        command = actions.add_parser(name)
        command.add_argument("--run-root", type=Path, required=True)
        command.add_argument("--submission-id", required=True)
        command.add_argument("--as-of", "--at", dest="as_of")
        command.add_argument("--cursor")
        command.add_argument("--limit", type=int, default=64)


def _input_bytes(run_root: Path, path: Path) -> bytes:
    try:
        relative = path.relative_to(run_root) if path.is_absolute() else path
    except ValueError as error:
        raise ValueError("submission input must be inside the run root") from error
    return read_retained_bytes(run_root, relative.as_posix(), max_bytes=256 * 1024)


def _model_input(raw: bytes, model):
    return model.model_validate_json(raw, strict=True)


def _plugin_manifest() -> Path | None:
    configured = os.environ.get("ARW_PLUGIN_MANIFEST")
    if configured:
        return Path(configured)
    if os.environ.get("ARW_PLUGIN_ROOT"):
        raise ValueError("plugin_manifest_missing")
    candidate = Path(__file__).resolve().parents[2] / ".codex-plugin" / "plugin.json"
    return candidate if candidate.is_file() else None


def _validate_with_optional_provider(kind: str, raw: bytes) -> None:
    """Use the installed plugin provider for preparation, never for admission."""

    from arw.composition import default_router

    payload = strict_json_loads(raw)
    if kind == "submission-packet":
        default_router(plugin_manifest=_plugin_manifest()).resolve(
            "submission.prepare"
        ).prepare(payload)
    elif kind == "submission-review-round":
        default_router(plugin_manifest=_plugin_manifest()).resolve(
            "submission.review_normalize"
        ).normalize_review(payload)
    elif kind == "submission-response":
        default_router(plugin_manifest=_plugin_manifest()).resolve(
            "submission.review_normalize"
        ).normalize_response(payload)


def handle(args):
    from arw.kernel.execution.submission import SubmissionWorkflowService

    service = SubmissionWorkflowService(args.run_root)
    command = args.submission_command
    if command == "prepare":
        raw = _input_bytes(args.run_root, args.input)
        _validate_with_optional_provider(args.kind, raw)
        return service.prepare(args.kind, raw)
    if command == "record":
        raw = _input_bytes(args.run_root, args.input)
        _validate_with_optional_provider(args.kind, raw)
        return service.record(
            args.kind,
            raw,
            _load_request(args.request, ArtifactAcceptanceRequest),
        )
    if command in {"review-import", "response-record"}:
        kind = "submission-review-round" if command == "review-import" else "submission-response"
        raw = _input_bytes(args.run_root, args.input)
        _validate_with_optional_provider(kind, raw)
        return service.record(
            kind,
            raw,
            _load_request(args.request, ArtifactAcceptanceRequest),
        )
    if command == "qualify":
        request = _load_request(args.request, ArtifactAcceptanceRequest)
        if args.scope == "confirmation":
            if not args.submission_id:
                raise ValueError("confirmation qualification requires --submission-id")
            if not args.subject_scope or not args.subject_sha256:
                raise ValueError(
                    "confirmation qualification requires --subject-scope and --subject-sha256"
                )
            return service.qualify_confirmation(
                args.submission_id,
                args.subject_scope,
                args.subject_sha256,
                request,
            )
        if args.input is None:
            raise ValueError("readiness qualification requires --input")
        report = _model_input(_input_bytes(args.run_root, args.input), SubmissionCheckReport)
        return service.qualify(
            report,
            request,
        )
    if command == "ready":
        return service.transition_ready(
            args.submission_id,
            _load_request(args.request, LifecycleTransitionRequest),
        ).model_dump(mode="json")
    if command == "record-result":
        observation = _model_input(
            _input_bytes(args.run_root, args.input), SubmissionResultObservation
        )
        return service.record_result(
            observation,
            _load_request(args.request, ArtifactAcceptanceRequest),
        )
    if command in {"check", "status"}:
        return service.check(
            args.submission_id,
            as_of=args.as_of,
            cursor=args.cursor,
            limit=args.limit,
        )
    raise ValueError(f"unsupported submission command: {command}")


__all__ = ["configure", "handle"]
