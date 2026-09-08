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
        if name == "record":
            p.add_argument("--request", type=Path, required=True)
            p.add_argument("--review-artifact-id")


def load(path):
    return strict_json_loads(
        read_retained_bytes(path.parent, path.name, max_bytes=262144)
    )


def handle(args):
    from arw.composition import default_router

    proposal = load(args.proposal)
    provider = default_router(writing_run_root=args.run_root).resolve(
        proposal.get("capability", "writing.unavailable")
    )
    if args.writing_command == "prepare":
        return provider.prepare(args.source_id, proposal)
    return provider.record(
        args.source_id,
        proposal,
        request=RuntimeCommandRequest.model_validate(load(args.request)),
        review_artifact_id=args.review_artifact_id,
    )
