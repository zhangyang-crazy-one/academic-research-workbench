"""Explicit source-bound writing proposals and parent receipt admission."""

from pathlib import Path

from arw.kernel.core.canonical import strict_json_loads
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.state.models import RuntimeCommandRequest


def configure(subparsers):
    parser = subparsers.add_parser("writing")
    actions = parser.add_subparsers(dest="writing_command", required=True)
    for name in ("prepare", "record"):
        p = actions.add_parser(name)
        p.add_argument("--run-root", type=Path, required=True)
        p.add_argument("--source-id", required=True)
        p.add_argument("--proposal", type=Path, required=True)
        p.add_argument(
            "--detectors",
            type=Path,
            help="Local JSON detector configuration; no detector runs by default",
        )
        p.add_argument(
            "--allow-network",
            action="store_true",
            help="Explicitly send source and revision to configured HTTP endpoint",
        )
        if name == "record":
            p.add_argument("--request", type=Path, required=True)
            p.add_argument("--review-artifact-id")
    audit = actions.add_parser(
        "audit", help="Audit two local texts without modifying either"
    )
    audit.add_argument("--source", type=Path, required=True)
    audit.add_argument("--revision", type=Path, required=True)
    audit.add_argument("--detectors", type=Path, required=True)
    audit.add_argument("--allow-network", action="store_true")


def load(path):
    return strict_json_loads(
        read_retained_bytes(path.parent, path.name, max_bytes=262144)
    )


def handle(args):
    detector_config = load(args.detectors) if args.detectors else None
    if args.writing_command == "audit":
        from arw_writing.detection import compare
        from arw_writing.fact_audit import audit

        source = read_retained_bytes(
            args.source.parent, args.source.name, max_bytes=65536
        ).decode("utf-8")
        revision = read_retained_bytes(
            args.revision.parent, args.revision.name, max_bytes=65536
        ).decode("utf-8")
        return {
            "detection": compare(
                source, revision, detector_config, allow_network=args.allow_network
            ),
            "fact_lock": audit(source, revision),
        }
    from arw.composition import default_router

    proposal = load(args.proposal)
    provider = default_router(writing_run_root=args.run_root).resolve(
        proposal.get("capability", "writing.unavailable")
    )
    if args.writing_command == "prepare":
        return provider.prepare(
            args.source_id,
            proposal,
            detector_config=detector_config,
            allow_network=args.allow_network,
        )
    return provider.record(
        args.source_id,
        proposal,
        request=RuntimeCommandRequest.model_validate(load(args.request)),
        review_artifact_id=args.review_artifact_id,
        detector_config=detector_config,
        allow_network=args.allow_network,
    )
