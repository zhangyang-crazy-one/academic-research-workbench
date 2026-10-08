"""Bounded JSON CLI for explicit, parent-owned learning operations."""

import json
import os
from pathlib import Path

from arw.cli_support import _load_request
from arw.kernel.capabilities import CapabilityUnavailable
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.state.models import RuntimeCommandRequest
from arw.kernel.state.research_learning import Applicability, HeuristicInput


def configure(subparsers):
    parser = subparsers.add_parser("learn")
    actions = parser.add_subparsers(dest="learning_command", required=True)
    for name in (
        "status",
        "observe",
        "observe-venue",
        "legacy-style-drafts",
        "migrate-style-candidate",
        "phase2-advisories",
        "extract",
        "import",
        "list",
        "inspect",
        "evaluate",
        "qualify",
        "promote",
        "reject",
        "rebuild",
        "purge",
        "applicable",
        "use",
        "evolve",
        "diagnose",
    ):
        p = actions.add_parser(name)
        p.add_argument("--project-root", type=Path, required=True)
        p.add_argument("--run-root", type=Path)
        if name in {
            "observe",
            "observe-venue",
            "migrate-style-candidate",
            "extract",
            "import",
            "evaluate",
            "qualify",
            "promote",
            "reject",
            "purge",
        }:
            p.add_argument("--request", type=Path, required=True)
        if name in {
            "inspect",
            "evaluate",
            "qualify",
            "promote",
            "reject",
            "use",
            "evolve",
        }:
            p.add_argument("heuristic_id")
        if name in {"extract", "import", "applicable", "legacy-style-drafts", "migrate-style-candidate", "phase2-advisories", "diagnose"}:
            p.add_argument("--input", type=Path, required=True)
        if name == "observe":
            p.add_argument("--event-id", required=True)
        if name == "observe-venue":
            p.add_argument("--artifact-id", required=True)
        if name == "evaluate":
            p.add_argument("--sample-artifact-id", action="append", required=True)
        if name == "promote":
            p.add_argument(
                "--to",
                choices=("run", "project", "domain", "global"),
                default="project",
            )
            p.add_argument("--approval-artifact-id", required=True)
            p.add_argument("--consent", action="store_true")
        if name == "reject":
            p.add_argument("--reason", required=True)
        if name == "purge":
            p.add_argument("--digest", required=True)
            p.add_argument("--authorization-artifact-id", required=True)
            p.add_argument("--consent", action="store_true")
        if name in {"list", "applicable", "phase2-advisories"}:
            p.add_argument("--max-items", type=int, default=10)
        if name in {"applicable", "phase2-advisories"}:
            p.add_argument("--venue-id", required=name == "phase2-advisories")
            p.add_argument("--domain-id", required=name == "phase2-advisories")
        if name == "use":
            p.add_argument("--decision-artifact-id", required=True)
        if name == "evolve":
            p.add_argument("--kind", default="workflow")


def handle(args):
    from arw.composition import default_router

    action = args.learning_command
    if action == "evolve":
        return {
            "status": "error",
            "code": "CapabilityUnavailable",
            "capability": "research.learning.evolve",
            "follow_up": "research-workflow-evolver",
        }
    if action == "legacy-style-drafts":
        from arw.kernel.state.venue_learning import legacy_style_drafts

        return legacy_style_drafts(
            read_retained_bytes(args.input.absolute().parent, args.input.name, max_bytes=65536)
        )
    if action == "diagnose":
        from arw.kernel.artifacts.failure_diagnosis import diagnose_failure
        from arw.kernel.state.failure_diagnosis import FailureDiagnosisRequest

        if args.run_root is None:
            raise ValueError("diagnose_requires_run_root")
        relative = args.input.absolute().relative_to(args.project_root.absolute())
        request = FailureDiagnosisRequest.model_validate_json(
            read_retained_bytes(args.project_root, relative.as_posix(), max_bytes=65_536)
        )
        memory_provider = None
        if request.handoff_memory_id is not None:
            manifest = os.environ.get("ARW_PLUGIN_MANIFEST")
            if os.environ.get("ARW_PLUGIN_ROOT") and not manifest:
                raise CapabilityUnavailable("research.memory.read")
            memory_provider = default_router(
                memory_project_root=args.project_root,
                memory_run_root=args.run_root,
                plugin_manifest=Path(manifest) if manifest else None,
            ).resolve("research.memory.read")
        diagnosis = diagnose_failure(args.run_root, request, memory_provider=memory_provider)
        return {
            "status": "diagnosed",
            "diagnosis": diagnosis.model_dump(mode="json", exclude_none=True),
            "diagnosis_sha256": diagnosis.diagnosis_sha256,
        }
    operation = (
        "research.learning.observe"
        if action in {"observe", "observe-venue"}
        else "research.learning.promote"
        if action == "promote"
        else "research.learning.heuristic."
        + (
            {
                "import": "extract",
                "migrate-style-candidate": "extract",
                "list": "inspect",
                "status": "inspect",
                "rebuild": "inspect",
                "applicable": "inspect",
                "phase2-advisories": "inspect",
                "purge": "reject",
                "use": "inspect",
            }.get(action, action)
        )
    )
    manifest = os.environ.get("ARW_PLUGIN_MANIFEST")
    if os.environ.get("ARW_PLUGIN_ROOT") and not manifest:
        raise CapabilityUnavailable(operation)
    service = default_router(
        learning_project_root=args.project_root,
        learning_run_root=args.run_root,
        plugin_manifest=Path(manifest) if manifest else None,
    ).resolve(operation)
    request = (
        _load_request(args.request, RuntimeCommandRequest)
        if hasattr(args, "request")
        else None
    )
    raw = (
        read_retained_bytes(
            args.input.absolute().parent, args.input.name, max_bytes=65536
        )
        if hasattr(args, "input")
        else None
    )
    if action in {"status", "rebuild"}:
        return getattr(service, action)()
    if action == "observe":
        return service.observe(args.event_id, request=request)
    if action == "observe-venue":
        return service.observe_venue(args.artifact_id, request=request)
    if action == "extract":
        return service.extract(HeuristicInput.model_validate_json(raw), request=request)
    if action == "migrate-style-candidate":
        return service.migrate_style_candidate(json.loads(raw), request=request)
    if action == "import":
        return service.import_heuristic(json.loads(raw), request=request)
    if action == "list":
        return service.list(max_items=args.max_items)
    if action == "inspect":
        return service.inspect(args.heuristic_id)
    if action == "evaluate":
        return service.evaluate(
            args.heuristic_id, args.sample_artifact_id, request=request
        )
    if action == "qualify":
        return service.qualify(args.heuristic_id, request=request)
    if action == "promote":
        return service.promote(
            args.heuristic_id,
            to_scope=args.to,
            consent=args.consent,
            approval_artifact_id=args.approval_artifact_id,
            request=request,
        )
    if action == "reject":
        return service.reject(args.heuristic_id, reason=args.reason, request=request)
    if action == "use":
        return service.decision_context(args.heuristic_id, args.decision_artifact_id)
    if action == "purge":
        return service.purge(
            args.digest,
            consent=args.consent,
            authorization_artifact_id=args.authorization_artifact_id,
            request=request,
        )
    if action == "phase2-advisories":
        return service.phase2_advisories(
            Applicability.model_validate_json(raw),
            venue_id=args.venue_id, domain_id=args.domain_id,
            max_items=args.max_items,
        )
    return service.applicable(
        Applicability.model_validate_json(raw), max_items=args.max_items,
        venue_id=args.venue_id, domain_id=args.domain_id,
    )
