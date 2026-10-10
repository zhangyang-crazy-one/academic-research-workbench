"""Read-only adapters that preserve original proof contracts and scope."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from arw.kernel.core.canonical import (
    canonical_json_bytes,
    sha256_hex,
    strict_json_loads,
)
from arw.kernel.ledger.journal import (
    replay_run,
    replay_run_prefix,
    replay_run_under_held_lock,
)
from arw.kernel.ledger.manifests import load_artifact_manifest
from arw.kernel.ledger.source_locations import (
    located_bytes,
    read_retained_bytes,
    resolve_source_locator,
)
from arw.kernel.state.accepted_ref import (
    ACCEPTED_REF_ADAPTER,
    AcceptedRef,
    JournalEventRef,
    ParentArtifactRef,
)
from arw.kernel.state.models import ArtifactAcceptedPayload, RunManifest
from arw.kernel.state.provenance import SourceLocator
from arw.kernel.state.research_artifact import ResearchBinding
from arw.kernel.state.research_memory import MemoryLink
from arw.kernel.state.submission import SubmissionArtifactReference
from arw.kernel.state.venue_learning import VenueSourceCapsule


@dataclass(frozen=True)
class RunPrefix:
    run_id: str
    revision: int
    head_sha256: str
    run_manifest_sha256: str | None = None


@dataclass(frozen=True)
class ResolutionContext:
    project_id: str
    run_roots: tuple[Path, ...]
    project_root: Path | None = None
    run_prefixes: tuple[RunPrefix, ...] = ()
    journal_sequence: int | None = None
    journal_head_sha256: str | None = None
    # Internal service-only boundary, never a JSON/schema/CLI capability.
    # Each exact root is already held by the parent writer transaction.
    held_lock_roots: tuple[Path, ...] = ()


@dataclass(frozen=True)
class RefResolution:
    status: Literal["resolved", "unresolved", "unsupported"]
    original: object
    ref: AcceptedRef | None = None
    proven_scope: (
        Literal["bytes", "selected_bytes", "structural_capsule", "metadata_only"] | None
    ) = None
    reason: str | None = None
    raw_bytes: bytes | None = None
    selected_value: object = None


class ResolutionCache:
    """Single-operation memo for accepted-source resolution (#98).

    One cache is created per compile/capture operation and dropped when the
    operation ends; nothing is persisted or trusted across operations.  Keys
    bind the canonical ref bytes and the full resolution-context identity
    (roots, prefixes, journal pins, held locks), so a changed prefix, manifest
    or content digest can never be shadowed by an earlier hit.
    """

    def __init__(self) -> None:
        self._runs: dict[str, list] = {}
        self._refs: dict[tuple[str, str], RefResolution] = {}
        self._csv_rows: dict[tuple[str, str], tuple] = {}

    def csv_rows(self, ref: AcceptedRef, row_id_column: str, scan: Callable[[], tuple]) -> tuple:
        """Return the globally validated full-table row scan for one CSV source."""
        key = (
            sha256_hex(canonical_json_bytes(ref.model_dump(mode="json"))),
            row_id_column,
        )
        if key not in self._csv_rows:
            self._csv_rows[key] = scan()
        return self._csv_rows[key]


def _context_key(context: ResolutionContext) -> str:
    return sha256_hex(
        canonical_json_bytes(
            {
                "project_id": context.project_id,
                "run_roots": [str(Path(root).resolve()) for root in context.run_roots],
                "run_prefixes": [
                    {
                        "run_id": prefix.run_id,
                        "revision": prefix.revision,
                        "head_sha256": prefix.head_sha256,
                        "run_manifest_sha256": prefix.run_manifest_sha256,
                    }
                    for prefix in context.run_prefixes
                ],
                "journal_sequence": context.journal_sequence,
                "journal_head_sha256": context.journal_head_sha256,
                "held_lock_roots": sorted(
                    str(Path(root).resolve()) for root in context.held_lock_roots
                ),
            }
        )
    )


def _cached_runs(context: ResolutionContext, cache: ResolutionCache) -> list:
    key = _context_key(context)
    if key not in cache._runs:
        cache._runs[key] = _runs(context)
    return cache._runs[key]


def _resolve(
    ref: AcceptedRef, context: ResolutionContext, cache: ResolutionCache | None = None
) -> RefResolution:
    if isinstance(ref, JournalEventRef):
        return _resolve_journal(ref, context)
    return _resolve_parent(
        ref, context, _runs(context) if cache is None else _cached_runs(context, cache)
    )


def resolve_pointer(value: object, pointer: str) -> object:
    if pointer and not pointer.startswith("/") or re.search(r"~(?![01])", pointer):
        raise ValueError("invalid JSON Pointer")
    if not pointer:
        return value
    for component in pointer[1:].split("/"):
        key = component.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", key):
                raise ValueError("invalid array pointer")
            value = value[int(key)]
        elif isinstance(value, dict):
            value = value[key]
        else:
            raise TypeError("pointer traverses scalar")
    return value


def _runs(context: ResolutionContext):
    if len(context.run_roots) > 128:
        raise ValueError("run budget exceeded")
    prefixes = {p.run_id: p for p in context.run_prefixes}
    if len(prefixes) != len(context.run_prefixes):
        raise ValueError("duplicate run prefixes")
    result = []
    held_roots = {Path(root).absolute() for root in context.held_lock_roots}
    if held_roots - {Path(root).absolute() for root in context.run_roots}:
        raise ValueError("held lock root is outside resolution roots")
    for root in context.run_roots:
        raw = read_retained_bytes(root, "run-manifest.json")
        manifest = RunManifest.model_validate_json(raw)
        if (
            manifest.narrative_binding
            and manifest.narrative_binding.project_id != context.project_id
        ):
            raise ValueError("run belongs to another project")
        prefix = prefixes.get(manifest.run_id)
        if prefixes and prefix is None:
            raise ValueError("run missing fixed prefix")
        if Path(root).absolute() in held_roots:
            replay = replay_run_under_held_lock(
                root,
                revision=prefix.revision if prefix else None,
                expected_head_sha256=prefix.head_sha256 if prefix else None,
                expected_manifest_sha256=prefix.run_manifest_sha256 if prefix else None,
            )
        else:
            replay = (
                replay_run(root)
                if prefix is None
                else replay_run_prefix(
                    root,
                    revision=prefix.revision,
                    expected_head_sha256=prefix.head_sha256,
                    expected_manifest_sha256=prefix.run_manifest_sha256,
                )
            )
        if replay.recovery_health != "healthy":
            raise ValueError("current run does not have a healthy canonical journal")
        result.append((root, manifest, sha256_hex(raw), replay))
    if len({item[1].run_id for item in result}) != len(result):
        raise ValueError("duplicate run identity")
    if set(prefixes) - {item[1].run_id for item in result}:
        raise ValueError("prefix run root missing")
    return result


def _parent(root, manifest, manifest_sha, event, context, **selection):
    return ParentArtifactRef(
        project_id=context.project_id,
        run_id=manifest.run_id,
        run_manifest_sha256=manifest_sha,
        artifact_id=event.payload.artifact_id,
        accepting_event_id=event.event_id,
        accepting_event_sha256=event.event_sha256,
        content_sha256=event.payload.artifact_sha256,
        **selection,
    )


def _accepted_events(runs):
    for root, manifest, digest, replay in runs:
        for event in replay.events:
            if isinstance(event.payload, ArtifactAcceptedPayload):
                yield root, manifest, digest, replay, event


def _resolve_parent(
    ref: ParentArtifactRef, context: ResolutionContext, runs
) -> RefResolution:
    matches = [r for r in runs if r[1].run_id == ref.run_id]
    if len(matches) != 1:
        return RefResolution("unresolved", ref, reason="missing_run")
    root, _, manifest_sha, replay = matches[0]
    if manifest_sha != ref.run_manifest_sha256:
        return RefResolution("unresolved", ref, reason="digest_mismatch")
    event = next(
        (e for e in replay.events if e.event_id == ref.accepting_event_id), None
    )
    if event is None:
        return RefResolution("unresolved", ref, reason="no_accepting_event")
    if (
        not isinstance(event.payload, ArtifactAcceptedPayload)
        or event.event_sha256 != ref.accepting_event_sha256
        or event.payload.artifact_id != ref.artifact_id
        or event.payload.artifact_sha256 != ref.content_sha256
    ):
        return RefResolution("unresolved", ref, reason="digest_mismatch")
    artifact = load_artifact_manifest(root, event.payload.manifest_sha256)
    raw = read_retained_bytes(root, artifact.content_path)
    if artifact.artifact_id != ref.artifact_id or sha256_hex(raw) != ref.content_sha256:
        return RefResolution("unresolved", ref, reason="digest_mismatch")
    if ref.source_locator is not None:
        locator = ref.source_locator
        if (
            locator.source_artifact_id,
            locator.source_sha256,
            locator.source_event_id,
            locator.source_event_sha256,
            locator.quote_sha256,
            locator.producing_activity_id,
        ) != (
            ref.artifact_id,
            ref.content_sha256,
            ref.accepting_event_id,
            ref.accepting_event_sha256,
            ref.selected_sha256,
            ref.producing_activity_id,
        ) or ref.selector:
            return RefResolution("unresolved", ref, reason="digest_mismatch")
        resolve_source_locator(root, locator, replay.events)
        return RefResolution(
            "resolved",
            ref,
            ref,
            "selected_bytes",
            raw_bytes=raw,
            selected_value=located_bytes(raw, locator),
        )
    try:
        value = strict_json_loads(raw)
    except ValueError:
        if ref.selector or ref.selected_sha256:
            return RefResolution("unresolved", ref, reason="unsupported_selector")
        return RefResolution("resolved", ref, ref, "bytes", raw_bytes=raw)
    selected = resolve_pointer(value, ref.selector)
    if (
        ref.selected_sha256 is not None
        and sha256_hex(canonical_json_bytes(selected)) != ref.selected_sha256
    ):
        return RefResolution("unresolved", ref, reason="digest_mismatch")
    scope = "selected_bytes" if ref.selector or ref.selected_sha256 else "bytes"
    if (
        isinstance(value, dict)
        and value.get("schema_version") == "arw.venue-source-capsule.v2"
    ):
        VenueSourceCapsule.model_validate_json(raw)
        scope = "structural_capsule"
    elif (
        isinstance(value, dict)
        and value.get("schema_version") == "arw.research-source-manifest.v1"
    ):
        from arw.kernel.policy.research_integrity import ResearchSourceManifest

        ResearchSourceManifest.model_validate_json(raw)
        scope = "metadata_only"
    return RefResolution(
        "resolved", ref, ref, scope, raw_bytes=raw, selected_value=selected
    )


def _resolve_journal(ref: JournalEventRef, context: ResolutionContext) -> RefResolution:
    if context.project_root is None:
        return RefResolution("unresolved", ref, reason="missing_journal")
    from arw.kernel.ledger import narrative

    root = narrative._root(context.project_root)
    with narrative._locked(root, write=False, create_lock=False):
        if context.journal_sequence is None:
            events, _, _ = narrative._read(root)
        else:
            # The coordinated journal implementation owns prefix validation.
            events, _, _ = narrative._read(root, at_sequence=context.journal_sequence)
        if (
            context.journal_head_sha256 is not None
            and events[-1]["event_sha256"] != context.journal_head_sha256
        ):
            return RefResolution("unresolved", ref, reason="stale")
        if narrative._identity(root).project_id != context.project_id:
            return RefResolution("unresolved", ref, reason="project_mismatch")
        event = next((e for e in events if e["sequence"] == ref.sequence), None)
        if event is None:
            return RefResolution("unresolved", ref, reason="no_accepting_event")
        if event["event_sha256"] != ref.event_sha256:
            return RefResolution("unresolved", ref, reason="digest_mismatch")
        value = resolve_pointer(event["payload"], ref.payload_selector)
        return RefResolution(
            "resolved",
            ref,
            ref,
            "metadata_only",
            raw_bytes=canonical_json_bytes(event),
            selected_value=value,
        )


def resolve_ref(
    ref: AcceptedRef, context: ResolutionContext, cache: ResolutionCache | None = None
) -> RefResolution:
    try:
        # Frozen models may still be forged with model_construct/model_copy.
        ref = ACCEPTED_REF_ADAPTER.validate_json(
            canonical_json_bytes(ref.model_dump(mode="json"))
        )
        if ref.project_id != context.project_id:
            return RefResolution("unresolved", ref, reason="project_mismatch")
        if cache is None:
            return _resolve(ref, context)
        key = (
            _context_key(context),
            sha256_hex(canonical_json_bytes(ref.model_dump(mode="json"))),
        )
        if key not in cache._refs:
            cache._refs[key] = _resolve(ref, context, cache)
        return cache._refs[key]
    except (
        ValueError,
        RuntimeError,
        OSError,
        KeyError,
        IndexError,
        TypeError,
    ) as error:
        reason = (
            "digest_mismatch"
            if "digest" in str(error) or "hash" in str(error)
            else "validation_failed"
        )
        return RefResolution("unresolved", ref, reason=reason)


verify_ref = resolve_ref


def to_accepted_ref(
    value: object, context: ResolutionContext, *, adapter_kind: str | None = None
) -> RefResolution:
    # Original integrity contracts are imported lazily: this necessary
    # ledger -> policy dependency must not create an import-time cycle.
    from arw.kernel.policy.research_integrity import (
        ClaimEvidenceLink,
        EvidenceSpan,
        ResearchSourceManifest,
        validate_research_integrity_chain,
    )

    adapter_models = {
        "SourceLocator": SourceLocator,
        "EvidenceSpan": EvidenceSpan,
        "ClaimEvidenceLink": ClaimEvidenceLink,
        "ResearchBinding": ResearchBinding,
        "SubmissionArtifactReference": SubmissionArtifactReference,
        "MemoryLink": MemoryLink,
        "VenueSourceCapsule": VenueSourceCapsule,
    }
    original = value
    try:
        original_bytes = (
            canonical_json_bytes(value.model_dump(mode="json", exclude_unset=True))
            if isinstance(value, VenueSourceCapsule)
            else canonical_json_bytes(value)
            if isinstance(value, dict)
            else None
        )
        if isinstance(value, dict):
            if "scope" in value:
                value = ACCEPTED_REF_ADAPTER.validate_json(canonical_json_bytes(value))
            else:
                kind = adapter_kind or {
                    "arw.source-locator.v1": "SourceLocator",
                    "arw.source-locator.v2": "SourceLocator",
                    "arw.evidence-span.v1": "EvidenceSpan",
                    "arw.claim-evidence-link.v1": "ClaimEvidenceLink",
                    "arw.venue-source-capsule.v2": "VenueSourceCapsule",
                }.get(value.get("schema_version"))
                if kind not in adapter_models:
                    return RefResolution(
                        "unsupported", original, reason="unsupported_type"
                    )
                value = adapter_models[kind].model_validate_json(
                    canonical_json_bytes(value)
                )
        elif isinstance(value, BaseModel):
            value = type(value).model_validate_json(
                canonical_json_bytes(value.model_dump(mode="json"))
            )
        if isinstance(value, (ParentArtifactRef, JournalEventRef)):
            return replace(resolve_ref(value, context), original=original)
        if isinstance(value, ClaimEvidenceLink):
            return RefResolution("unsupported", original, reason="edge_not_ref")
        if isinstance(value, MemoryLink) and (
            value.kind != "artifact" or value.sha256 is None or value.event_id is None
        ):
            return RefResolution(
                "unsupported", original, reason="not_accepted_artifact"
            )
        if not isinstance(
            value,
            (
                SourceLocator,
                EvidenceSpan,
                ResearchBinding,
                SubmissionArtifactReference,
                MemoryLink,
                VenueSourceCapsule,
            ),
        ):
            return RefResolution("unsupported", original, reason="unsupported_type")
        runs = _runs(context)
        candidates = list(_accepted_events(runs))
        if isinstance(value, SourceLocator):
            candidates = [
                r
                for r in candidates
                if r[4].event_id == value.source_event_id
                and r[4].payload.artifact_id == value.source_artifact_id
            ]
        elif isinstance(
            value, (ResearchBinding, SubmissionArtifactReference, MemoryLink)
        ):
            artifact_id = (
                value.target_id if isinstance(value, MemoryLink) else value.artifact_id
            )
            candidates = [
                r for r in candidates if r[4].payload.artifact_id == artifact_id
            ]
        else:
            digest = (
                value.research_source_manifest_sha256
                if isinstance(value, EvidenceSpan)
                else sha256_hex(original_bytes)
            )
            candidates = [
                r for r in candidates if r[4].payload.artifact_sha256 == digest
            ]
        if len({r[1].run_id for r in candidates}) > 1:
            return RefResolution("unresolved", original, reason="ambiguous_run")
        if isinstance(
            value, (ResearchBinding, SubmissionArtifactReference, MemoryLink)
        ):
            event_id = (
                value.ledger_event_id
                if isinstance(value, ResearchBinding)
                else value.accepting_event_id
                if isinstance(value, SubmissionArtifactReference)
                else value.event_id
            )
            candidates = [r for r in candidates if r[4].event_id == event_id]
        if len(candidates) != 1:
            return RefResolution("unresolved", original, reason="no_accepting_event")
        root, manifest, digest, _replay, event = candidates[0]
        selection = {}
        if isinstance(value, SourceLocator):
            selection = {
                "selected_sha256": value.quote_sha256,
                "producing_activity_id": value.producing_activity_id,
                "source_locator": value,
            }
        if isinstance(value, ResearchBinding):
            if (
                event.event_sha256 != value.ledger_event_sha256
                or event.payload.artifact_sha256 != value.sha256
            ):
                return RefResolution("unresolved", original, reason="digest_mismatch")
            selection = {"selector": value.json_pointer}
        if isinstance(value, SubmissionArtifactReference) and (
            event.payload.manifest_sha256 != value.manifest_sha256
            or event.payload.artifact_sha256 != value.content_sha256
        ):
            return RefResolution("unresolved", original, reason="digest_mismatch")
        if (
            isinstance(value, MemoryLink)
            and event.payload.artifact_sha256 != value.sha256
        ):
            return RefResolution("unresolved", original, reason="digest_mismatch")
        ref = _parent(root, manifest, digest, event, context, **selection)
        result = _resolve_parent(ref, context, runs)
        if result.status == "resolved" and isinstance(value, ResearchBinding):
            # The original research-binding validator requires a JSON
            # document even for the empty pointer; binary/plain text must
            # not become valid through the generic accepted-bytes path.
            resolve_pointer(strict_json_loads(result.raw_bytes), value.json_pointer)
        if result.status == "resolved" and isinstance(value, EvidenceSpan):
            source = ResearchSourceManifest.model_validate_json(result.raw_bytes)
            validate_research_integrity_chain(
                sources=(source,), evidence_spans=(value,), claim_links=()
            )
            result = replace(result, proven_scope="metadata_only")
        return replace(result, original=original)
    except (
        ValueError,
        RuntimeError,
        OSError,
        TypeError,
        KeyError,
        IndexError,
    ) as error:
        reason = (
            "digest_mismatch"
            if "digest" in str(error) or "hash" in str(error)
            else "validation_failed"
        )
        return RefResolution("unresolved", original, reason=reason)
