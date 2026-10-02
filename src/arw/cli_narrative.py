"""Paper narrative startup and deliberate author change commands."""

from pathlib import Path


def configure(subparsers):
    parser = subparsers.add_parser(
        "narrative",
        help="Select and inspect a project paper narrative before outlining.",
    )
    actions = parser.add_subparsers(dest="narrative_command", required=True)
    for name in ("register", "select", "status", "propose", "approve"):
        action = actions.add_parser(name)
        action.add_argument("--project-root", required=True, type=Path)
        if name in {"select", "propose"}:
            action.add_argument("--plan", required=True, type=Path)
        if name == "propose":
            action.add_argument("--expected-sha256", required=True)
            action.add_argument("--reason", required=True)
        if name == "approve":
            action.add_argument("--proposal-sha256", required=True)
            action.add_argument("--author-id", required=True)
            action.add_argument(
                "--author-confirmed",
                action="store_true",
                help="Assert the named author explicitly confirmed this exact proposal.",
            )


def handle(args):
    from arw.kernel.core.canonical import strict_json_loads
    from arw.kernel.ledger import narrative
    from arw.kernel.state.narrative import NarrativePlan

    command = args.narrative_command
    if command == "register":
        return narrative.register(args.project_root)
    if command == "status":
        return narrative.status(args.project_root)
    if command == "approve":
        if not args.author_confirmed:
            raise narrative.NarrativeError(
                "author_confirmation_missing",
                "approve requires an explicit author confirmation assertion",
            )
        return narrative.approve(
            args.project_root,
            proposal_sha256=args.proposal_sha256,
            author_id=args.author_id,
        ).model_dump(mode="json")
    raw = args.plan.read_bytes()
    if len(raw) > 65536:
        raise narrative.NarrativeError(
            "invalid_plan", "narrative plan exceeds byte budget"
        )
    plan = NarrativePlan.model_validate(strict_json_loads(raw))
    if command == "select":
        return narrative.select(args.project_root, plan).model_dump(mode="json")
    return narrative.propose(
        args.project_root,
        plan,
        expected_sha256=args.expected_sha256,
        reason=args.reason,
    )
