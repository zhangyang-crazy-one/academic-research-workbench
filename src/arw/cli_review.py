"""Explicit advisory review commands; no scientific gate integration."""

from pathlib import Path


def configure(subparsers):
    parser = subparsers.add_parser(
        "review",
        help="Source-bound advisory concerns and PROV export, without scoring.",
    )
    commands = parser.add_subparsers(dest="review_command", required=True)
    for name in ("diagnose", "verify", "replay", "prov"):
        action = commands.add_parser(name)
        action.add_argument("--project-root", type=Path, required=True)
        action.add_argument("--run-root", type=Path, action="append", required=True)
        if name != "diagnose":
            action.add_argument("--input", type=Path, required=True)


def read(path):
    from arw.kernel.core.canonical import strict_json_loads

    if path.is_symlink():
        raise ValueError("review input must be a regular file")
    with path.open("rb") as handle:
        raw = handle.read(2_097_153)
    if len(raw) > 2_097_152:
        raise ValueError("review input budget exceeded")
    return strict_json_loads(raw)


def handle(args):
    from arw.kernel.core.canonical import canonical_json_bytes
    from arw.kernel.ledger.review_concerns import (
        diagnose,
        export_prov,
        replay_report,
        validate_concern,
    )
    from arw.kernel.state.review_concern import ReviewConcern, ReviewConcernReport

    roots = tuple(args.run_root)
    if args.review_command == "diagnose":
        report = diagnose(args.project_root, roots)
        return {**report.model_dump(mode="json"), "report_sha256": report.sha256}
    value = read(args.input)
    if args.review_command == "verify":
        concern = ReviewConcern.model_validate_json(canonical_json_bytes(value))
        validate_concern(concern, args.project_root, roots)
        return {
            "status": "advisory_target_verified",
            "concern": concern.model_dump(mode="json"),
        }
    digest = value.pop("report_sha256", None)
    report = ReviewConcernReport.model_validate_json(canonical_json_bytes(value))
    if digest != report.sha256:
        raise ValueError("review report digest differs")
    replay_report(report, args.project_root, roots)
    if args.review_command == "prov":
        return export_prov(report, args.project_root, roots)
    return {**report.model_dump(mode="json"), "report_sha256": report.sha256}
