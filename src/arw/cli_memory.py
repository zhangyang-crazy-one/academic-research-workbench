"""Bounded memory CLI: canonical parent writes and explicit recall scopes."""

import json
import os
from pathlib import Path

from arw.cli_support import _load_request
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.state.models import RuntimeCommandRequest
from arw.kernel.state.research_memory import MemoryInput, MemoryQuery


def configure(subparsers):
    parser = subparsers.add_parser("memory")
    actions = parser.add_subparsers(dest="memory_command", required=True)
    for name in (
        "init-project",
        "save",
        "handoff",
        "search",
        "read",
        "list",
        "doctor",
        "rebuild",
        "activate",
        "reject",
        "verify",
        "distill",
        "purge",
        "resume",
    ):
        p = actions.add_parser(name)
        p.add_argument("--project-root", type=Path, required=True)
        p.add_argument("--run-root", type=Path)
        p.add_argument(
            "--harness", choices=("codex", "claude", "cursor", "other"), default="codex"
        )
        if name == "init-project":
            p.add_argument("--project-id")
        if name in {"save", "handoff"}:
            p.add_argument("--input", type=Path, required=True)
        if name in {"save", "handoff", "activate", "reject", "verify", "distill"}:
            p.add_argument("--request", type=Path, required=True)
        if name in {
            "read",
            "activate",
            "reject",
            "verify",
            "distill",
            "purge",
            "resume",
        }:
            p.add_argument("memory_id")
        if name in {"verify", "distill", "purge"}:
            p.add_argument("--authorization-artifact-id", required=True)
        if name == "purge":
            p.add_argument("--authorize-purge", action="store_true")
        if name in {"search", "list", "read", "resume"}:
            p.add_argument(
                "--scope", choices=("run", "project", "team", "user"), default="project"
            )
            p.add_argument("--project-id")
            p.add_argument("--cross-project", action="store_true")
            p.add_argument("--run", dest="run_id")
            p.add_argument("--kind")
            p.add_argument("--since")
            p.add_argument("--max-items", type=int, default=10)
            p.add_argument("--max-tokens", type=int, default=4096)
            p.add_argument("--query", default="")


def handle(args):
    from arw.composition import default_router

    action = args.memory_command
    manifest = os.environ.get("ARW_PLUGIN_MANIFEST")
    if os.environ.get("ARW_PLUGIN_ROOT") and not manifest:
        raise ValueError("plugin_manifest_missing")
    if action == "init-project":
        # Project initialization is administrative, not part of MemoryProvider.
        from arw.composition import initialize_memory_project

        return initialize_memory_project(args.project_root, args.project_id).model_dump(
            mode="json"
        )
    operation = (
        action
        if action in {"save", "search", "read", "list", "doctor", "handoff"}
        else "handoff"
        if action == "resume"
        else "save"
    )
    provider = default_router(
        memory_project_root=args.project_root,
        memory_run_root=args.run_root,
        memory_harness=args.harness,
        plugin_manifest=Path(manifest) if manifest else None,
    ).resolve(f"research.memory.{operation}")
    if action in {"save", "handoff"}:
        relative = (
            args.input.relative_to(args.project_root)
            if args.input.is_absolute()
            else args.input
        )
        raw = read_retained_bytes(
            args.project_root, relative.as_posix(), max_bytes=65_536
        )
        value = MemoryInput.model_validate_json(raw)
        if action == "handoff" and value.kind != "handoff":
            raise ValueError("handoff command requires handoff kind")
        return provider.save(
            value, request=_load_request(args.request, RuntimeCommandRequest)
        )
    if action in {"search", "list", "read", "resume"}:
        query = MemoryQuery.model_validate_json(
            json.dumps({key: getattr(args, key) for key in MemoryQuery.model_fields})
        )
        if action in {"search", "list"}:
            return getattr(provider, action)(query)
        if action == "resume":
            return provider.resume_handoff(args.memory_id, query=query)
        return provider.read(args.memory_id, query=query)
    if action in {"doctor", "rebuild"}:
        return getattr(provider, action)()
    if action == "purge":
        return provider.purge(
            args.memory_id,
            authorization_artifact_id=args.authorization_artifact_id,
            authorized=args.authorize_purge,
        )
    return provider.govern(
        args.memory_id,
        action,
        request=_load_request(args.request, RuntimeCommandRequest),
        authorization_artifact_id=getattr(args, "authorization_artifact_id", None),
    )
