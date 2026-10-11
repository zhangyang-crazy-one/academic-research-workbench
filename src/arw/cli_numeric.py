"""Read-only exact derivation entry point, independent of claim graphs and plots."""

from pathlib import Path


def configure(subparsers):
    parser = subparsers.add_parser("numeric", help="Evaluate accepted-source rational expressions.")
    actions = parser.add_subparsers(dest="numeric_command", required=True)
    derive = actions.add_parser("derive")
    derive.add_argument("--request", required=True, type=Path)
    derive.add_argument("--project-id", required=True)
    derive.add_argument("--project-root", type=Path)
    derive.add_argument("--run-root", action="append", required=True, type=Path)


def handle(args):
    from arw.kernel.ledger.accepted_refs import ResolutionContext
    from arw.kernel.policy.numeric_core import evaluate_derivation
    from arw.kernel.state.numeric_core import DerivationRequest

    with args.request.open("rb") as stream:
        raw = stream.read(2_097_153)
    if len(raw) > 2_097_152:
        raise ValueError("numeric_request_budget_exceeded")
    request = DerivationRequest.model_validate_json(raw)
    context = ResolutionContext(
        project_id=args.project_id,
        run_roots=tuple(args.run_root),
        project_root=args.project_root,
    )
    return evaluate_derivation(request, context).model_dump(mode="json")
