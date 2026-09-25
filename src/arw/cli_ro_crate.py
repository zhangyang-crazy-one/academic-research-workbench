"""Thin command adapter for the read-only crate exporter and verifier."""

from __future__ import annotations

from pathlib import Path


def configure(commands) -> None:
    export = commands.add_parser(
        "ro-crate-export", help="Export a read-only run snapshot."
    )
    export.add_argument("--run-root", required=True, type=Path)
    export.add_argument("--output", required=True, type=Path)
    export.add_argument("--format", choices=("zip", "directory"), default="zip")
    export.add_argument("--include-artifact-id", action="append", default=[])
    export.add_argument("--max-events", type=int, default=4096)
    export.add_argument("--max-entries", type=int, default=512)
    export.add_argument("--max-bytes", type=int, default=64 * 1024 * 1024)
    verify = commands.add_parser(
        "ro-crate-verify", help="Check a local crate without extracting it."
    )
    verify.add_argument("--crate", required=True, type=Path)
    verify.add_argument("--run-root", type=Path)


def handle(args) -> dict:
    from arw.kernel.artifacts.ro_crate import export_ro_crate, verify_ro_crate

    if args.artifact_command == "ro-crate-export":
        return export_ro_crate(
            args.run_root,
            args.output,
            format=args.format,
            include_artifact_ids=tuple(args.include_artifact_id),
            max_events=args.max_events,
            max_entries=args.max_entries,
            max_bytes=args.max_bytes,
        )
    return verify_ro_crate(args.crate, run_root=args.run_root)
