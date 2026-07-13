"""Command-line entrypoint for the Academic Research Workbench control plane."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from arw.contracts import installed_route


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "route":
        if not args.json_output:
            parser.error("route requires --json")
        json.dump(
            installed_route().model_dump(mode="json"),
            fp=sys.stdout,
            sort_keys=True,
            separators=(",", ":"),
        )
        print()
        return 0

    parser.error(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
