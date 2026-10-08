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
        if name in {"ir", "render", "qualify", "reproduce"}:
            parser.add_argument("--source-run-root", type=Path, action="append", default=[])
            parser.add_argument("--project-root", type=Path)
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
        options = {}
        if action == "reproduce" and args.source_run_root:
            from arw.kernel.ledger.accepted_refs import ResolutionContext

            inspected = provider.inspect(args.artifact_id, run_root=args.run_root)
            if inspected.get("receipt", {}).get("artifact_kind") != "result_plot":
                raise ValueError("plot_source_context_requires_result_plot")
            refs = inspected["receipt"]["inputs"]
            projects = {r["project_id"] for r in refs}
            if len(projects) != 1:
                raise ValueError("plot_project_scope_ambiguous")
            options["resolution_context"] = ResolutionContext(
                project_id=next(iter(projects)),
                run_roots=tuple(dict.fromkeys([args.run_root, *args.source_run_root])),
                project_root=args.project_root,
            )
        return getattr(provider, action)(args.artifact_id, run_root=args.run_root, **options)
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
    from arw.kernel.core.canonical import strict_json_loads

    payload = strict_json_loads(raw)
    if isinstance(payload, dict) and payload.get("artifact_kind") == "result_plot":
        from arw.kernel.state.result_plot import ResultPlotIR

        ir = ResultPlotIR.model_validate_json(raw)
        from arw.kernel.ledger.accepted_refs import ResolutionContext

        projects = {r.project_id for r in ir.source_refs}
        if len(projects) != 1:
            raise ValueError("plot_project_scope_ambiguous")
        options = {"resolution_context": ResolutionContext(
            project_id=next(iter(projects)),
            run_roots=tuple(dict.fromkeys([args.run_root, *args.source_run_root])),
            project_root=args.project_root,
        )}
    else:
        ir = ResearchArtifactIR.model_validate_json(raw)
        if args.source_run_root or args.project_root:
            raise ValueError("plot_source_context_requires_result_plot")
        options = {}
    if action == "render":
        return provider.render(ir, run_root=args.run_root, **options)
    request = _load_request(args.request, RuntimeCommandRequest)
    return provider.qualify(
        ir,
        run_root=args.run_root,
        request=request,
        visual_review_id=args.visual_review_id,
        **options,
    )
