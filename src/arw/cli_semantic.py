"""Explicit optional semantic indexing and bounded advisory queries."""

import sqlite3
from pathlib import Path


def configure(subparsers):
    parser = subparsers.add_parser("semantic")
    actions = parser.add_subparsers(dest="semantic_command", required=True)
    for command in ("build", "rebuild", "search"):
        p = actions.add_parser(command)
        p.add_argument("--store", type=Path, required=True)
        p.add_argument("--run-root", type=Path, required=True)
        p.add_argument("--model", type=Path, required=True)
        p.add_argument("--model-sha256", required=True)
        if command == "search":
            p.add_argument("--query", required=True)
            p.add_argument("--limit", type=int, default=10)
            p.add_argument("--lexical-id", action="append", default=[])
            p.add_argument("--graph-id", action="append", default=[])
        else:
            p.add_argument("--artifact-id", action="append", required=True)


def _handle(args):
    from arw.composition import configured_semantic_provider

    provider = configured_semantic_provider(
        args.store, args.run_root, args.model, args.model_sha256
    )
    if args.semantic_command == "search":
        return provider.search(
            args.query,
            limit=args.limit,
            lexical_ids=args.lexical_id,
            graph_ids=args.graph_id,
        )
    return provider.build(args.artifact_id, rebuild=args.semantic_command == "rebuild")


def handle(args):
    try:
        return _handle(args)
    except sqlite3.Error as error:
        raise ValueError(
            "semantic projection database is invalid; rebuild explicitly"
        ) from error
