"""CLI adapter for research artifact ports, independent of renderer implementation."""

import json
from pathlib import Path

from arw.cli_support import _load_request
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.state.models import RuntimeCommandRequest
from arw.kernel.state.research_artifact import ResearchArtifactIR


def configure(commands):
    for name in ("ir", "render", "qualify", "reproduce", "doctor", "purge"):
        parser = commands.add_parser(name)
        parser.add_argument("--run-root", type=Path, required=True)
        if name in {"ir", "render", "qualify"}:
            parser.add_argument(
                "--input",
                type=Path,
                required=True,
                help="IR/specification JSON inside the run root.",
            )
        if name in {"reproduce", "purge"}:
            parser.add_argument("artifact_id")
        if name == "qualify":
            parser.add_argument("--request", type=Path, required=True)
            parser.add_argument("--visual-review-id")
        if name == "purge":
            parser.add_argument("--authorization-artifact-id", required=True)
            parser.add_argument("--authorize-purge", action="store_true")


def handle(args, provider):
    action = args.artifact_command
    if action == "doctor":
        return provider.doctor(run_root=args.run_root)
    if action in {"inspect", "reproduce"}:
        if args.run_root is None:
            raise ValueError("run root is required for accepted artifact lookup")
        return getattr(provider, action)(args.artifact_id, run_root=args.run_root)
    if action == "purge":
        return provider.purge(
            args.artifact_id,
            run_root=args.run_root,
            authorization_artifact_id=args.authorization_artifact_id,
            authorized=args.authorize_purge,
        )
    relative = (
        args.input.relative_to(args.run_root)
        if args.input.is_absolute()
        else args.input
    )
    raw = read_retained_bytes(args.run_root, relative.as_posix(), max_bytes=1_048_576)
    from arw.kernel.core.privacy import reject_secret_shapes

    reject_secret_shapes(raw)
    if action == "ir":
        return provider.build(json.loads(raw), run_root=args.run_root).model_dump(
            mode="json"
        )
    ir = ResearchArtifactIR.model_validate_json(raw)
    if action == "render":
        return provider.render(ir, run_root=args.run_root)
    request = _load_request(args.request, RuntimeCommandRequest)
    return provider.qualify(
        ir,
        run_root=args.run_root,
        request=request,
        visual_review_id=args.visual_review_id,
    )
