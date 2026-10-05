"""Explicit source-bound writing proposals and parent receipt admission."""

import os
import stat
from pathlib import Path

from arw.kernel.core.canonical import strict_json_loads
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.state.models import RuntimeCommandRequest


def configure(subparsers):
    parser = subparsers.add_parser("writing")
    actions = parser.add_subparsers(dest="writing_command", required=True)
    for name in ("prepare", "record"):
        p = actions.add_parser(name)
        p.add_argument("--run-root", type=Path, required=True)
        p.add_argument("--source-id", required=True)
        p.add_argument("--proposal", type=Path, required=True)
        p.add_argument(
            "--detectors",
            type=Path,
            help="Local JSON detector configuration; no detector runs by default",
        )
        p.add_argument(
            "--allow-network",
            action="store_true",
            help="Explicitly send source and revision to configured HTTP endpoint",
        )
        if name == "record":
            p.add_argument("--request", type=Path, required=True)
            p.add_argument("--review-artifact-id")
    audit = actions.add_parser(
        "audit", help="Audit two local texts without modifying either"
    )
    audit.add_argument("--source", type=Path, required=True)
    audit.add_argument("--revision", type=Path, required=True)
    audit.add_argument("--detectors", type=Path, required=True)
    audit.add_argument("--allow-network", action="store_true")
    fit = actions.add_parser(
        "narrative-fit", help="Inspect a frozen, advisory venue fit"
    )
    fit.add_argument("--run-root", type=Path)
    fit.add_argument("--target", required=True)
    fit.add_argument("--manuscript-artifact-id")
    fit.add_argument(
        "--without-selected-narrative",
        action="store_true",
        help="Explicitly inspect accepted public evidence without an author narrative",
    )
    fit.add_argument(
        "--realization",
        type=Path,
        help="Proposed realization JSON relative to run root for an accepted manuscript source",
    )
    fit.add_argument("--profile", type=Path)
    fit.add_argument("--domain-id")
    fit.add_argument("--heuristic-id", action="append", default=[])
    fit.add_argument(
        "--heuristic-annotations",
        type=Path,
        help="Reviewed typed match predicates keyed by selected promoted heuristic ID",
    )
    fit.add_argument("--pdf-artifact-id")
    fit.add_argument("--judgment", type=Path)
    fit.add_argument(
        "--snapshot-out", type=Path, help="Create one immutable offline replay input"
    )
    fit.add_argument(
        "--snapshot", type=Path, help="Replay an existing frozen input offline"
    )
    fit.add_argument(
        "--freshness",
        action="store_true",
        help="Compare current narrative/profile separately",
    )
    fit.add_argument("--as-of", help="Explicit YYYY-MM-DD for profile review freshness")


def load(path):
    return strict_json_loads(
        read_retained_bytes(path.parent, path.name, max_bytes=262144)
    )


def _read_fit_snapshot(path: Path) -> bytes:
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("frozen snapshot path contains a symlink")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > 64 * 1024 * 1024:
            raise ValueError("frozen snapshot is not a bounded regular file")
        chunks = []
        total = 0
        while total <= 64 * 1024 * 1024:
            block = os.read(descriptor, min(65536, 64 * 1024 * 1024 + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
        after = os.fstat(descriptor)
        if (
            total > 64 * 1024 * 1024
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
        ):
            raise ValueError("frozen snapshot changed or exceeded its budget")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def handle(args):
    from arw.composition import default_router

    manifest_env = os.environ.get("ARW_PLUGIN_MANIFEST")
    if manifest_env:
        manifest_path = Path(manifest_env)
        if not manifest_path.is_file():
            raise ValueError("plugin_manifest_unreadable")
    elif os.environ.get("ARW_PLUGIN_ROOT"):
        raise ValueError("plugin_manifest_missing")
    else:
        candidate = (
            Path(__file__).resolve().parents[2] / ".codex-plugin" / "plugin.json"
        )
        manifest_path = candidate if candidate.is_file() else None

    if args.writing_command == "narrative-fit":
        from arw.kernel.core.canonical import canonical_json_bytes
        from arw.kernel.state.narrative_fit import FitSnapshot, PublicFitSnapshot

        snapshot: FitSnapshot | PublicFitSnapshot
        provider = default_router(
            writing_run_root=args.run_root or Path("."), plugin_manifest=manifest_path
        ).resolve("writing.narrative_fit")
        if args.snapshot:
            raw = _read_fit_snapshot(args.snapshot)
            model = (
                PublicFitSnapshot
                if strict_json_loads(raw).get("schema_version")
                == "arw.narrative-fit-public-snapshot.v1"
                else FitSnapshot
            )
            snapshot = model.model_validate_json(raw)
            if args.snapshot_out:
                raise ValueError("--snapshot-out is only for capture")
        else:
            if not args.run_root:
                raise ValueError("capture needs --run-root")
            snapshot = provider.freeze(
                args.target,
                args.manuscript_artifact_id,
                args.profile,
                heuristic_ids=args.heuristic_id,
                domain_id=args.domain_id,
                pdf_artifact_id=args.pdf_artifact_id,
                judgment_path=args.judgment,
                realization_path=args.realization,
                without_selected_narrative=args.without_selected_narrative,
                heuristic_annotations_path=args.heuristic_annotations,
            )
            if args.snapshot_out:
                encoded = canonical_json_bytes(snapshot.model_dump(mode="json"))
                if len(encoded) > 64 * 1024 * 1024:
                    raise ValueError("frozen snapshot exceeds its 64 MiB budget")
                if any(part.is_symlink() for part in args.snapshot_out.parents):
                    raise ValueError("frozen snapshot destination contains a symlink")
                with args.snapshot_out.open("xb") as output:
                    output.write(encoded)
        if snapshot.profile.venue_id != args.target:
            raise ValueError("frozen snapshot target differs from --target")
        result = provider.report(snapshot)
        if args.freshness:
            if not args.run_root:
                raise ValueError("--freshness needs --run-root")
            if not args.as_of:
                raise ValueError("--freshness needs an explicit --as-of date")
            from datetime import date

            as_of = date.fromisoformat(args.as_of)
            if as_of.isoformat() != args.as_of:
                raise ValueError("--as-of must be ISO YYYY-MM-DD")
            result = {
                "report": result,
                "freshness": provider.freshness(snapshot, args.profile, as_of=as_of),
            }
        return result
    detector_config = load(args.detectors) if args.detectors else None
    if args.writing_command == "audit":
        source = read_retained_bytes(
            args.source.parent, args.source.name, max_bytes=65536
        ).decode("utf-8")
        revision = read_retained_bytes(
            args.revision.parent, args.revision.name, max_bytes=65536
        ).decode("utf-8")
        return (
            default_router(plugin_manifest=manifest_path)
            .resolve("writing.audit")
            .audit_texts(
                source,
                revision,
                detector_config=detector_config,
                allow_network=args.allow_network,
            )
        )
    proposal = load(args.proposal)
    provider = default_router(
        writing_run_root=args.run_root, plugin_manifest=manifest_path
    ).resolve(proposal.get("capability", "writing.unavailable"))
    if args.writing_command == "prepare":
        return provider.prepare(
            args.source_id,
            proposal,
            detector_config=detector_config,
            allow_network=args.allow_network,
        )
    return provider.record(
        args.source_id,
        proposal,
        request=RuntimeCommandRequest.model_validate(load(args.request)),
        review_artifact_id=args.review_artifact_id,
        detector_config=detector_config,
        allow_network=args.allow_network,
    )
