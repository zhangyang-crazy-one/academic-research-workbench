"""Bounded, read-only evidence impact checklist CLI."""

from __future__ import annotations

from pathlib import Path

MAX_EVIDENCE_INPUT_BYTES = 65_536


def configure(subparsers) -> None:
    parser = subparsers.add_parser(
        "evidence",
        help="Produce read-only dependency impact checklists for declared source updates.",
    )
    actions = parser.add_subparsers(dest="evidence_command", required=True)
    impact = actions.add_parser(
        "impact",
        help="Trace active dependent claims, plans, experiments, and paragraphs without mutating runs.",
    )
    impact.add_argument("--control-root", required=True, type=Path)
    impact.add_argument("--root-id", required=True)
    impact.add_argument("--update", required=True, type=Path)
    impact.add_argument("--expected-watermark", required=True, type=int)
    impact.add_argument("--proposals", type=Path)
    impact.add_argument("--max-records", type=int, default=128)


def _read_json_object(path: Path, *, label: str) -> dict:
    from arw.kernel.core.canonical import strict_json_loads

    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be an existing regular file")
    with path.open("rb") as stream:
        raw = stream.read(MAX_EVIDENCE_INPUT_BYTES + 1)
    if len(raw) > MAX_EVIDENCE_INPUT_BYTES:
        raise ValueError(f"{label} byte budget exceeded")
    parsed = strict_json_loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must be a JSON object")
    return parsed


def handle(args) -> dict:
    from arw.composition import default_router, resolve_plugin_manifest
    from arw.graph_store import GraphStore
    from arw.kernel.core.canonical import canonical_json_bytes

    manifest = resolve_plugin_manifest()
    provider = default_router(plugin_manifest=manifest).resolve("evidence.impact")
    if args.control_root.is_symlink() or not args.control_root.is_dir():
        raise ValueError("control root must be an existing non-symlink directory")
    update_raw = _read_json_object(args.update, label="evidence update")
    update = provider.EvidenceUpdate.model_validate_json(
        canonical_json_bytes(update_raw)
    )
    proposals: dict[str, str] | None = None
    if args.proposals is not None:
        proposals_raw = _read_json_object(args.proposals, label="proposed revisions")
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in proposals_raw.items()
        ):
            raise ValueError("proposed revisions must map record IDs to strings")
        proposals = proposals_raw
    store = GraphStore(args.control_root, args.root_id)
    return provider.impact_checklist(
        store,
        update,
        expected_watermark=args.expected_watermark,
        proposed_text=proposals,
        max_records=args.max_records,
    )
