"""Command-line entrypoint for the Academic Research Workbench control plane."""

from __future__ import annotations

import argparse
import asyncio
import os
import stat
import sys
from collections.abc import Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from arw.cli_support import (
    CLIInputError,
    _identity_receipt_reference,
    _is_sha256_text,
    _load_object,
    _load_request,
    _parse_utc,
    _write_json,
)
from arw.kernel.core.canonical import canonical_json_bytes, strict_json_loads
from arw.kernel.execution.host_dispatch import (
    _blocked_execution_adapter,
    _blocked_orchestration_result,
    _dispatch_report_json,
    _installed_route_diagnostics_from_environment,
    _installed_route_from_environment,
    _rehydrate_prepared_run,
    _verified_dispatch_adapter,
)

RequestModel = TypeVar("RequestModel", bound=BaseModel)
PROVENANCE_ARTIFACT_KIND = "provenance-record"


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
    route.add_argument(
        "--diagnostics",
        action="store_true",
        help="Explain the exact read-only integration layer that blocks routing.",
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
    storm.add_argument(
        "--api-key", default=None, help="Model API key (default: GEMINI_API_KEY)."
    )
    storm.add_argument(
        "--api-base",
        default=None,
        help="OpenAI-compatible API base (default: GOOGLE_GEMINI_BASE_URL).",
    )
    storm.add_argument(
        "--retriever",
        choices=["tavily", "duckduckgo"],
        default="tavily",
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
    status.add_argument(
        "--store",
        type=Path,
        default=None,
        help="Also report local-store projection health for this store file.",
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
    provenance = subparsers.add_parser(
        "provenance",
        help="Operate the opt-in Semantica-compatible Lite provenance sidecar.",
    )
    provenance_actions = provenance.add_subparsers(
        dest="provenance_action", required=True
    )
    for action in ("record", "lineage", "verify", "rebuild"):
        command = provenance_actions.add_parser(action)
        command.add_argument("--run-root", required=True, type=Path)
        command.add_argument("--store", required=True, type=Path)
        command.add_argument("--lock-timeout", type=float, default=0.2)
        if action == "record":
            command.add_argument("--record", required=True, type=Path)
        elif action == "lineage":
            command.add_argument("--entity-id", required=True)
            command.add_argument("--max-depth", type=int, default=8)
            command.add_argument("--max-rows", type=int, default=100)
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


def _write_rejection(error: Exception) -> None:
    from arw.kernel.state.models import Rejection

    rejection = Rejection(code="canonical-error", message=str(error))
    sys.stderr.buffer.write(canonical_json_bytes(rejection.model_dump(mode="json")))


def _is_status_json_request(args: argparse.Namespace) -> bool:
    return args.command == "status" and bool(args.json_output)


def _read_bounded_regular_file(
    root: Path, relative_path: str, *, max_bytes: int
) -> bytes | None:
    """Read one confined regular file through a stable run-root descriptor."""
    root = root if root.is_absolute() else Path.cwd() / root
    relative = Path(relative_path)
    if (
        not relative.parts
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise OSError("artifact path is not normalized and relative")
    close_descriptors: list[int] = []
    parent_descriptor: int | None = None
    leaf_name: str | None = None
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    descriptor_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | no_follow
    )
    supports_stable_walk = (
        no_follow != 0
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
    )
    if not supports_stable_walk:
        raise OSError("stable descriptor-relative artifact reads are unsupported")
    directory_flags = descriptor_flags | getattr(os, "O_DIRECTORY", 0)
    parent_descriptor = os.open(Path(root.anchor), directory_flags)
    close_descriptors.append(parent_descriptor)
    for component in root.parts[1:]:
        parent_descriptor = os.open(
            component, directory_flags, dir_fd=parent_descriptor
        )
        close_descriptors.append(parent_descriptor)
    for part in relative.parts[:-1]:
        parent_descriptor = os.open(part, directory_flags, dir_fd=parent_descriptor)
        close_descriptors.append(parent_descriptor)
    leaf_name = relative.parts[-1]
    descriptor = os.open(leaf_name, descriptor_flags, dir_fd=parent_descriptor)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise OSError("artifact is not a regular file")
        if before.st_size > max_bytes:
            return None
        chunks: list[bytes] = []
        total = 0
        while total <= max_bytes:
            chunk = os.read(descriptor, min(65_536, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        after = os.fstat(descriptor)
        if parent_descriptor is not None and leaf_name is not None:
            current = os.stat(
                leaf_name, dir_fd=parent_descriptor, follow_symlinks=False
            )
        else:
            current = os.stat(root / relative, follow_symlinks=False)

        def identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
            return (
                value.st_dev,
                value.st_ino,
                value.st_mode,
                value.st_size,
                value.st_mtime_ns,
            )

        if identity(before) != identity(after) or identity(after) != identity(current):
            raise OSError("artifact changed during bounded read")
        content = b"".join(chunks)
        return None if len(content) > max_bytes else content
    finally:
        os.close(descriptor)
        for directory_descriptor in reversed(close_descriptors):
            os.close(directory_descriptor)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "route":
        if not args.json_output:
            parser.error("route requires --json")
        if args.diagnostics:
            report = _installed_route_diagnostics_from_environment()
            _write_json(report.model_dump(mode="json"))
            return 0 if report.status == "PASS" else 65
        _write_json(_installed_route_from_environment().model_dump(mode="json"))
        return 0
    if args.command == "version":
        if not args.json_output:
            parser.error("version requires --json")
        from arw.kernel.policy.build_identity import (
            BuildIdentityError,
            load_packaged_build_identity,
        )

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

        config_kwargs: dict[str, Any] = {
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
        config = StormConfig(
            **config_kwargs,
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
        from arw.files import FilesAdminError

        try:
            builder_value = os.environ.get("ARW_FILES_NATIVE_BUILDER")
            from arw.composition import files_admin_service

            service = files_admin_service(args.control_root)
            if builder_value is not None:
                service.native_builder = Path(builder_value)
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
                # Feed the fresh generation into the local projection store so
                # the native files provider actually has data to serve (review
                # P1: previously nothing populated the store on this path).
                if receipt.selected_generation_id is not None:
                    from arw.composition import ingest_files_into_default_store

                    try:
                        ingest_files_into_default_store(
                            args.control_root,
                            args.root_id,
                            generation_id=receipt.selected_generation_id,
                        )
                    except Exception as error:
                        # Ingestion feeds the (disposable) projection; a
                        # failure here must not fail the completed sync.
                        print(
                            f"arw: local-store ingest warning: {error}",
                            file=sys.stderr,
                        )
                _write_json(receipt.model_dump(mode="json"))
            else:
                _write_json(service.status(args.root_id))
            return 0
        except (FilesAdminError, CLIInputError, ValidationError) as error:
            print(f"arw: files-admin-error: {error}", file=sys.stderr)
            return 65
    if args.command == "_graph-mcp":
        from arw.composition import default_router
        from arw.graph_mcp import GraphMcpServer, run_stdio

        # The manifest's declared capability set gates activation (PR5).
        # Resolution order: explicit env override (staged/installed plugin
        # sets it), then the source-tree layout.  Never guess from the
        # installed package location — that path differs per install.
        manifest_env = os.environ.get("ARW_PLUGIN_MANIFEST")
        manifest_path = (
            Path(manifest_env)
            if manifest_env
            else Path(__file__).resolve().parents[2] / ".codex-plugin" / "plugin.json"
        )
        router = default_router(
            graph_control_root=args.control_root,
            graph_root_id=args.root_id,
            plugin_manifest=manifest_path if manifest_path.is_file() else None,
        )
        provider = router.resolve("knowledge.graph")
        return run_stdio(GraphMcpServer(provider._store))
    if args.command == "provenance":
        from arw.composition import default_router
        from arw.kernel.capabilities import CapabilityUnavailable
        from arw.kernel.core.canonical import sha256_hex
        from arw.kernel.ledger.journal import locked_replay
        from arw.kernel.ledger.manifests import load_artifact_manifest
        from arw.kernel.state.models import ArtifactAcceptedPayload

        lock_stack = ExitStack()
        try:
            _, replayed = lock_stack.enter_context(
                locked_replay(args.run_root, lock_timeout=args.lock_timeout)
            )
            event_digests = {
                event.event_id: event.event_sha256 for event in replayed.events
            }
            accepted_artifacts: dict[str, tuple[str, ...]] = {}
            accepted_payloads: dict[str, ArtifactAcceptedPayload] = {}
            accepted_artifact_hashes: dict[str, str] = {}
            for event in replayed.events:
                if isinstance(event.payload, ArtifactAcceptedPayload):
                    accepted_artifacts[event.event_id] = (event.payload.artifact_id,)
                    accepted_payloads[event.event_id] = event.payload
                    accepted_artifact_hashes[event.event_id] = (
                        event.payload.artifact_sha256
                    )
            module = __import__("arw_semantica", fromlist=["ProvenanceRecord"])
            canonical_records: dict[str, Any] = {}
            for event_id, accepted in accepted_payloads.items():
                manifest = load_artifact_manifest(
                    args.run_root, accepted.manifest_sha256
                )
                if manifest.artifact_kind != PROVENANCE_ARTIFACT_KIND:
                    continue
                if manifest.media_type != "application/json":
                    raise ValueError(
                        "accepted provenance artifact must use application/json"
                    )
                content_bytes = _read_bounded_regular_file(
                    args.run_root, manifest.content_path, max_bytes=65_536
                )
                if content_bytes is None:
                    raise ValueError(
                        "accepted provenance artifact exceeds the Lite limit"
                    )
                if sha256_hex(content_bytes) != accepted.artifact_sha256:
                    raise ValueError("accepted provenance artifact content is unsafe")
                try:
                    record = module.ProvenanceRecord.model_validate_json(content_bytes)
                except ValidationError as error:
                    raise ValueError(
                        "accepted provenance artifact is malformed"
                    ) from error
                if (
                    record.ledger_event_id is not None
                    or record.ledger_event_digest is not None
                    or record.artifact_id != accepted.artifact_id
                    or record.checksum != accepted.artifact_sha256
                ):
                    raise ValueError(
                        "accepted artifact does not match its provenance assertion"
                    )
                bound_record = record.model_copy(
                    update={
                        "ledger_event_id": event_id,
                        "ledger_event_digest": event_digests[event_id],
                    }
                )
                if len(canonical_json_bytes(bound_record.canonical_payload())) > 65_536:
                    raise ValueError("bound provenance payload exceeds the Lite limit")
                existing = canonical_records.get(bound_record.record_id)
                if existing is not None and existing != bound_record:
                    raise ValueError("canonical provenance record ID collision")
                canonical_records[bound_record.record_id] = bound_record
                if len(canonical_records) > 500:
                    raise ValueError(
                        "canonical provenance inventory exceeds the Lite limit"
                    )
            sidecar_path = args.store.with_name(
                f"{args.store.name}.{replayed.run_id}.semantica.sqlite3"
            )
            if args.provenance_action == "rebuild":
                module.SemanticaSQLiteAdapter.prepare_rebuild(sidecar_path)
            router = default_router(
                store_path=args.store,
                semantica_store_path=sidecar_path,
                canonical_event_digests=event_digests,
                accepted_artifact_ids_by_event=accepted_artifacts,
                accepted_artifact_sha256_by_event=accepted_artifact_hashes,
                expected_provenance_record_sha256={
                    record_id: record.checksum
                    for record_id, record in canonical_records.items()
                },
            )
            provider = router.resolve("knowledge.provenance")
            if args.provenance_action == "record":
                try:
                    record_relative_path = (
                        args.record.resolve()
                        .relative_to(args.run_root.resolve())
                        .as_posix()
                    )
                except ValueError as error:
                    raise ValueError(
                        "provenance record must be inside the selected run root"
                    ) from error
                record_bytes = _read_bounded_regular_file(
                    args.run_root, record_relative_path, max_bytes=65_536
                )
                if record_bytes is None:
                    raise ValueError("provenance record exceeds the Lite byte limit")
                record = module.ProvenanceRecord.model_validate_json(record_bytes)
                if canonical_json_bytes(record.artifact_payload()) != record_bytes:
                    raise ValueError("provenance record bytes are not canonical JSON")
                if (
                    record.ledger_event_id is not None
                    or record.ledger_event_digest is not None
                ):
                    raise ValueError(
                        "provenance artifact input must not contain acceptance binding"
                    )
                matches = [
                    (event_id, accepted)
                    for event_id, accepted in accepted_payloads.items()
                    if accepted.artifact_id == record.artifact_id
                ]
                if (
                    len(matches) != 1
                    or record.checksum != matches[0][1].artifact_sha256
                ):
                    raise ValueError(
                        "provenance record bytes are not one accepted artifact content"
                    )
                event_id, accepted = matches[0]
                record = record.model_copy(
                    update={
                        "ledger_event_id": event_id,
                        "ledger_event_digest": event_digests[event_id],
                    }
                )
                checksum = provider.record(record)
                provider.verify()
                _write_json({"checksum": checksum})
            elif args.provenance_action == "rebuild":
                provider.rebuild(list(canonical_records.values()))
                if provider.verify():
                    raise RuntimeError(
                        "rebuilt Semantica sidecar failed canonical verification"
                    )
                _write_json({"rebuilt_records": len(canonical_records)})
            elif args.provenance_action == "lineage":
                _write_json(
                    {
                        "rows": provider.lineage(
                            args.entity_id,
                            max_depth=args.max_depth,
                            max_rows=args.max_rows,
                        )
                    }
                )
            else:
                _write_json(
                    {"audit_faults": [fault.__dict__ for fault in provider.verify()]}
                )
            return 0
        except (
            CapabilityUnavailable,
            CLIInputError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as error:
            print(f"arw: provenance-error: {error}", file=sys.stderr)
            return 65
        finally:
            lock_stack.close()

    # Writable/runtime services are intentionally imported only after the two
    # read-only installed commands above have returned.
    from arw.kernel.execution.orchestration import (
        AssignmentSpec,
        OrchestrationError,
        OrchestrationService,
    )
    from arw.kernel.execution.runtime import RuntimeCommandService
    from arw.kernel.ledger.journal import (
        JournalError,
        append_probe,
        initialize_run,
        locked_replay,
        replay_run,
    )
    from arw.kernel.ledger.manifests import ManifestError
    from arw.kernel.ledger.reducer import ReducerError, reduce_events
    from arw.kernel.state.models import (
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
    from arw.kernel.state.orchestration_models import GateDecision, HookObservation
    from arw.kernel.state.status import build_status_report, render_status_text

    handled_errors: tuple[type[Exception], ...] = (
        CLIInputError,
        JournalError,
        ManifestError,
        ReducerError,
        OrchestrationError,
        ValidationError,
        OSError,
    )

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
            with locked_replay(args.run_root, lock_timeout=args.lock_timeout) as (
                _,
                replayed,
            ):
                status_now = _parse_utc(args.at) or datetime.now(UTC)
                state = reduce_events(
                    replayed.workflow_definition_id,
                    replayed.events,
                    now=status_now,
                    recovery_health=replayed.recovery_health,
                )
                report = build_status_report(state)
                # Purely additive: projection health appears only when --store is
                # given, so the pinned v1 status envelope stays byte-identical
                # for every existing invocation.
                health = None
                if getattr(args, "store", None) is not None:
                    from arw.composition import local_store_health
                    from arw.kernel.ledger.manifests import load_artifact_manifest
                    from arw.kernel.state.models import ArtifactAcceptedPayload

                    provenance_sidecar = args.store.with_name(
                        f"{args.store.name}.{replayed.run_id}.semantica.sqlite3"
                    )
                    provenance_expected = False
                    for event in replayed.events:
                        if not isinstance(event.payload, ArtifactAcceptedPayload):
                            continue
                        manifest = load_artifact_manifest(
                            args.run_root, event.payload.manifest_sha256
                        )
                        if manifest.artifact_kind == PROVENANCE_ARTIFACT_KIND:
                            provenance_expected = True
                            break
                    provenance_active = (
                        provenance_expected
                        or os.path.lexists(provenance_sidecar)
                        or os.path.lexists(Path(f"{provenance_sidecar}.audit"))
                    )
                    health = local_store_health(
                        args.store,
                        provenance_audit_database_path=(
                            provenance_sidecar if provenance_active else None
                        ),
                    )
            if args.json_output:
                payload = report.model_dump(mode="json")
                if health is not None:
                    payload["projection_health"] = health
                _write_json(payload)
            else:
                text = render_status_text(report)
                if health is not None:
                    checkpoints = health.get("checkpoints", [])
                    watermark = (
                        str(checkpoints[0]["last_ledger_sequence"])
                        if checkpoints
                        else "none"
                    )
                    provenance_faults = health.get("provenance_faults", [])
                    text += (
                        f"\nprojection schema: {health['schema_version']}"
                        f"\nprojection checkpoint: {watermark}"
                        f"\nprojection checksums: {health['checksum_status']}"
                        f"\nprovenance faults: {len(provenance_faults)}"
                    )
                sys.stdout.write(text)
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
                raise JournalError(
                    f"assignments are missing or invalid: {error}"
                ) from error
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
                    "assignment_ids": [
                        item.assignment_id for item in prepared.assignments
                    ],
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
            from arw.kernel.execution.execution import DispatchSpec

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
                    reason for reason, proven in required_proofs.items() if not proven
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
            return (
                0 if all(item.status == "completed" for item in report.outcomes) else 65
            )
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
            raw_reviewer_identities = panel_request.get("reviewer_identities")
            if (
                set(panel_request) != expected_keys
                or panel_request.get("schema_version") != "arw.cli-panel-request.v1"
                or not isinstance(panel_request.get("panel_id"), str)
                or not panel_request["panel_id"]
                or not _is_sha256_text(panel_request.get("subject_sha256"))
                or not _is_sha256_text(panel_request.get("rubric_sha256"))
                or not isinstance(raw_reviewer_identities, dict)
                or panel_request.get("execution_mode")
                not in {"native_profile", "assignment_injected_subagent"}
            ):
                raise CLIInputError(
                    "panel request does not match the strict CLI contract"
                )
            reviewer_identities: dict[str, dict[str, str]] = {}
            for role_id, identity_reference in raw_reviewer_identities.items():
                if not isinstance(role_id, str) or not role_id:
                    raise CLIInputError(
                        "panel reviewer role IDs must be non-empty strings"
                    )
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
            service = RuntimeCommandService(
                args.run_root, lock_timeout=args.lock_timeout
            )
            outcome = getattr(service, method_name)(request)
            _write_json(outcome.model_dump(mode="json"))
            return 0 if outcome.accepted else 65
        if args.command == "passport-pointer-rebuild":
            pointer = RuntimeCommandService(
                args.run_root, lock_timeout=args.lock_timeout
            ).rebuild_passport_pointer()
            _write_json(pointer.model_dump(mode="json"))
            return 0
    except Exception as error:
        if not isinstance(error, handled_errors):
            raise
        if _is_status_json_request(args):
            _write_rejection(error)
            return 65
        if isinstance(error, OSError):
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
