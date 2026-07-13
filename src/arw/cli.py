"""Command-line entrypoint for the Academic Research Workbench control plane."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from arw.build_identity import BuildIdentityError, load_packaged_build_identity
from arw.canonical import canonical_json_bytes, strict_json_loads
from arw.contracts import installed_route
from arw.journal import JournalError, append_probe, initialize_run, replay_run
from arw.models import AppendProbeRequest, InitRunRequest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arw",
        description="Academic Research Workbench control plane.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    route = subparsers.add_parser(
        "route",
        help="Emit the installed read-only ARS workflow route.",
    )
    route.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Write the strict route contract as JSON.",
    )
    version = subparsers.add_parser(
        "version",
        help="Report the installed packaged build identity.",
    )
    version.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Write the strict version-report contract as JSON.",
    )
    init = subparsers.add_parser(
        "init",
        help="Initialize an immutable run manifest and first canonical event.",
    )
    _add_run_request_arguments(init)
    append = subparsers.add_parser(
        "append",
        help="Append one Phase 1 baseline event through the sole writer.",
    )
    _add_run_request_arguments(append)
    replay = subparsers.add_parser(
        "replay",
        help="Replay and validate manifest plus canonical JSONL only.",
    )
    replay.add_argument("--run-root", required=True, type=Path)
    replay.add_argument("--lock-timeout", type=float, default=0.2)
    return parser


def _add_run_request_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--lock-timeout", type=float, default=0.2)


def _load_request(path: Path, model: type[InitRunRequest] | type[AppendProbeRequest]):
    try:
        raw = path.read_bytes()
        payload = strict_json_loads(raw)
        return model.model_validate(payload)
    except (OSError, UnicodeError, ValueError, ValidationError) as error:
        raise JournalError(f"request is missing or invalid: {error}") from error


def _write_json(payload: object) -> None:
    sys.stdout.buffer.write(canonical_json_bytes(payload))


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "route":
        if not args.json_output:
            parser.error("route requires --json")
        _write_json(installed_route().model_dump(mode="json"))
        return 0
    if args.command == "version":
        if not args.json_output:
            parser.error("version requires --json")
        try:
            identity, digest = load_packaged_build_identity()
        except BuildIdentityError as error:
            print(f"arw: build-identity-error: {error}", file=sys.stderr)
            return 65
        _write_json(
            {
                "schema_version": "1.0.0",
                "command": "version",
                "build_identity_sha256": digest,
                "identity": identity,
            }
        )
        return 0

    try:
        if args.command == "init":
            request = _load_request(args.request, InitRunRequest)
            state = initialize_run(
                args.run_root,
                request,
                lock_timeout=args.lock_timeout,
            )
            _write_json(
                {
                    "event_sha256": state.last_event_sha256,
                    "revision": state.revision,
                    "run_id": state.run_id,
                }
            )
            return 0
        if args.command == "append":
            request = _load_request(args.request, AppendProbeRequest)
            state = append_probe(
                args.run_root,
                request,
                lock_timeout=args.lock_timeout,
            )
            _write_json(
                {
                    "event_sha256": state.last_event_sha256,
                    "revision": state.revision,
                    "run_id": state.run_id,
                }
            )
            return 0
        if args.command == "replay":
            state = replay_run(args.run_root, lock_timeout=args.lock_timeout)
            _write_json(state.public_dict())
            return 0
    except JournalError as error:
        print(f"arw: canonical-error: {error}", file=sys.stderr)
        return 65

    parser.error(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
