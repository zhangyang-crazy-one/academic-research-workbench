"""Explicit offline AI disclosure drafts with human final review pending."""

from pathlib import Path


def configure(subparsers):
    parser = subparsers.add_parser(
        "disclosure",
        help="Summarize canonical AI participation and prepare a human-review draft.",
    )
    actions = parser.add_subparsers(dest="disclosure_command", required=True)
    for name in ("summary", "draft", "replay"):
        action = actions.add_parser(name)
        action.add_argument("--project-root", type=Path, required=True)
        action.add_argument("--run-root", type=Path, action="append", required=True)
        if name == "draft":
            action.add_argument("--policy", type=Path, required=True)
        if name == "replay":
            action.add_argument("--draft", type=Path, required=True)


def read(path):
    from arw.kernel.core.canonical import strict_json_loads
    from arw.kernel.ledger.ai_disclosure import MAX_BYTES

    if path.is_symlink():
        raise ValueError("disclosure input must be a regular file")
    with path.open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("disclosure input budget exceeded")
    return strict_json_loads(raw)


def handle(args):
    from arw.kernel.core.canonical import canonical_json_bytes
    from arw.kernel.ledger.accepted_refs import ResolutionContext
    from arw.kernel.ledger.ai_disclosure import capture, make_draft, replay_draft
    from arw.kernel.ledger.narrative import _identity
    from arw.kernel.state.ai_disclosure import AIDisclosurePolicy

    context = ResolutionContext(
        _identity(args.project_root).project_id, tuple(args.run_root), args.project_root
    )
    if args.disclosure_command == "summary":
        return capture(context)
    if args.disclosure_command == "draft":
        policy = AIDisclosurePolicy.model_validate_json(
            canonical_json_bytes(read(args.policy))
        )
        return make_draft(context, policy)
    return replay_draft(read(args.draft), context)
