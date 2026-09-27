#!/usr/bin/env python3
"""Install declared project dependencies and selected groups without uv project mode."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all-extras", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("groups", nargs="*")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    with (root / "pyproject.toml").open("rb") as source:
        groups = tomllib.load(source)["dependency-groups"]
    requirements: list[str] = []
    for name in args.groups:
        selected = groups.get(name)
        if not isinstance(selected, list) or not all(
            isinstance(item, str) and item.strip() and not item.lstrip().startswith("-")
            for item in selected
        ):
            parser.error(f"missing or unsupported dependency group: {name}")
        requirements.extend(selected)

    command = [
        "uv", "pip", "install", "--python", sys.executable,
        "--editable", ".", "-r", "pyproject.toml",
    ]
    if args.all_extras:
        command.append("--all-extras")
    if args.dry_run:
        command.append("--dry-run")
    command.extend(requirements)
    return subprocess.call(command, cwd=root)


if __name__ == "__main__":
    raise SystemExit(main())
