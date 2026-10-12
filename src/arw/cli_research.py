"""Thin project/research administration; canonical services own every write."""

from pathlib import Path

from arw.kernel.ledger.projects import initialize_project, project_identity
from arw.research_startup import project_root, start, status


def configure(subparsers):
    parser = subparsers.add_parser(
        "research", help="Start and resume a project-bound research direction."
    )
    actions = parser.add_subparsers(dest="research_command", required=True)
    for name in ("project-init", "project-status", "start", "status", "resume"):
        action = actions.add_parser(name)
        action.add_argument("--project-root", type=Path, required=True)
        action.add_argument(
            "--project-id",
            help="Expected stable project identity; never inferred from the path.",
        )
        if name in {"start", "status", "resume"}:
            action.add_argument(
                "--run-id", help="Expected previously retained run identity."
            )
        if name == "start":
            action.add_argument("--direction", required=True)
            action.add_argument(
                "--phase",
                choices=("scoping", "literature", "experiment", "writing"),
                default="scoping",
            )
            action.add_argument(
                "--task-kind", choices=("other", "paper"), default="other"
            )
            action.add_argument(
                "--plan-only",
                action="store_true",
                help="Retain reviewable requests without initializing the run.",
            )


def handle(args):
    action = args.research_command
    if action in {"project-init", "project-status"}:
        root = project_root(args.project_root, create=action == "project-init")
        identity = (
            initialize_project(root, args.project_id)
            if action == "project-init"
            else project_identity(root)
        )
        if args.project_id is not None and identity.project_id != args.project_id:
            raise ValueError("project identity differs")
        return identity.model_dump(mode="json")
    keywords = {"expected_project_id": args.project_id, "expected_run_id": args.run_id}
    if action == "status":
        return status(args.project_root, **keywords)
    if action == "resume":
        return start(args.project_root, resume=True, **keywords)
    return start(
        args.project_root,
        direction=args.direction,
        phase=args.phase,
        task_kind=args.task_kind,
        plan_only=args.plan_only,
        **keywords,
    )
