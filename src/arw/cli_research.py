"""Thin project/research administration; canonical services own every write."""

from pathlib import Path

from arw.kernel.ledger.projects import initialize_project, project_identity
from arw.research_startup import project_root, start, status


def configure(subparsers):
    parser = subparsers.add_parser(
        "research", help="Start and resume a project-bound research direction."
    )
    actions = parser.add_subparsers(dest="research_command", required=True)
    direction = actions.add_parser(
        "direction",
        help="Inspect external data packages and prepare ordinary research artifacts.",
    )
    direction_actions = direction.add_subparsers(
        dest="direction_command", required=True
    )
    for name in ("inspect", "seal", "bind", "check", "intake", "definition"):
        action = direction_actions.add_parser(name)
        if name not in {"inspect", "seal"}:
            action.add_argument("--project-root", type=Path, required=True)
        if name in {"inspect", "bind", "intake"}:
            action.add_argument("--package", type=Path, required=True)
        elif name == "check":
            action.add_argument(
                "--package",
                type=Path,
                help="Explicit current package; differences mark downstream snapshots stale.",
            )
        if name in {"bind", "check"}:
            action.add_argument("--branch-ledger", type=Path)
        if name == "bind":
            action.add_argument("--ars-project-ref")
            action.add_argument(
                "--cases", type=Path, help="Bounded object with a cases array."
            )
        if name == "check":
            action.add_argument(
                "--binding-path",
                required=True,
                help="Project-relative retained direction binding.",
            )
        if name in {"intake", "definition"}:
            action.add_argument("--input", type=Path, required=True)
        if name == "seal":
            action.add_argument("--input", type=Path, required=True)
            action.add_argument("--output", type=Path, required=True)
        if name == "definition":
            action.add_argument("--package", type=Path)
            action.add_argument("--hypothesis-id")
        if name == "intake":
            action.add_argument("--citation-store", type=Path)
            action.add_argument("--previous-intake", type=Path)
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
            action.add_argument(
                "--ars-project-ref",
                help="Freeze an explicit ARS alias; default is the stable project ID.",
            )
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
    if action == "direction":
        from arw.research_directions import (
            bind,
            check,
            inspect_package,
            prepare_definition,
            prepare_intake,
            read_document,
        )

        if args.direction_command == "seal":
            from arw.kernel.core.canonical import canonical_json_bytes
            from arw.kernel.ledger.research_records import publish_once
            from arw.research_directions import ars_check, seal_package

            package = seal_package(read_document(args.input))
            ars_check(package.profile, profile_history=package.profile_history)
            output = args.output.absolute()
            project_root(output.parent)
            publish_once(
                output.parent,
                output.name,
                canonical_json_bytes(package.model_dump(mode="json")),
            )
            return {
                "status": "sealed_data",
                "package_sha256": package.package_sha256,
                "output": str(output),
                "scientific_status": "not_evaluated",
            }
        if args.direction_command == "inspect":
            return inspect_package(args.package)
        if args.direction_command == "bind":
            value = {"cases": []} if args.cases is None else read_document(args.cases)
            if set(value) != {"cases"} or not isinstance(value["cases"], list):
                raise ValueError("case input must contain only a cases array")
            return bind(
                args.project_root,
                args.package,
                ars_project_ref=args.ars_project_ref,
                branch_path=args.branch_ledger,
                cases=value["cases"],
            )
        if args.direction_command == "check":
            return check(
                args.project_root,
                args.binding_path,
                current_package=args.package,
                current_branch=args.branch_ledger,
            )
        if args.direction_command == "definition":
            if (args.package is None) != (args.hypothesis_id is None):
                raise ValueError(
                    "definition claim preparation requires both package and hypothesis ID"
                )
            return prepare_definition(
                args.project_root,
                args.input,
                package_path=args.package,
                hypothesis_id=args.hypothesis_id,
            )
        return prepare_intake(
            args.project_root,
            args.package,
            args.input,
            citation_store=args.citation_store,
            previous=args.previous_intake,
        )
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
        ars_project_ref=args.ars_project_ref,
        plan_only=args.plan_only,
        **keywords,
    )
