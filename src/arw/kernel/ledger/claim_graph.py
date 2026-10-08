"""Read-only claims projection over fixed, validated parent/journal prefixes."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from arw.kernel.core.canonical import (
    canonical_json_bytes,
    sha256_hex,
    strict_json_loads,
)
from arw.kernel.ledger import narrative
from arw.kernel.ledger.journal import (
    _read_manifest,
    _replay_unlocked,
    replay_run_prefix,
)
from arw.kernel.ledger.manifests import load_artifact_manifest
from arw.kernel.ledger.source_locations import MAX_SOURCE_BYTES, read_retained_bytes
from arw.kernel.state.claim_graph import (
    ClaimRegistration,
    DeclaredAttestation,
    DeclaredAuthority,
    JournalPrefix,
    Occurrence,
    RunPrefix,
    SnapshotManifest,
)

MAX_NODES = 4096
MAX_BYTES = 2_097_152
MAX_CLAIMS = 256
MVP_SCOPE = "numeric_tokens_figure_captions_cited_sentences"
EXTRACTION_VERSION = "arw.claim-occurrences.en-zh.v1"
ADAPTER_KINDS = {
    "source_locator": "SourceLocator",
    "evidence_span": "EvidenceSpan",
    "research_binding": "ResearchBinding",
    "submission_reference": "SubmissionArtifactReference",
    "memory_link": "MemoryLink",
    "venue_capsule": "VenueSourceCapsule",
}
MANUSCRIPT_KINDS = {
    "narrative-draft",
    "paper-draft",
    "draft",
    "manuscript",
    "paper-manuscript",
    "writing-derived",
}


class ClaimGraphError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _registrations(events: list[dict]) -> dict[str, ClaimRegistration]:
    current = {}
    for event in events:
        if event["kind"] in {"claim.registered", "claim.evidence.updated"}:
            record = ClaimRegistration.model_validate(event["payload"])
            current[record.claim.claim_id] = record
    return current


def validate_claim_journal_event(event: dict, prior: list[dict]) -> None:
    """Validate new kinds without re-encoding or migrating historical events."""
    kind = event["kind"]
    latest = _registrations(prior)
    if kind in {"claim.registered", "claim.evidence.updated"}:
        record = ClaimRegistration.model_validate(event["payload"])
        old = latest.get(record.claim.claim_id)
        if kind == "claim.evidence.updated":
            if (
                old is None
                or old.claim != record.claim
                or old.occurrences != record.occurrences
            ):
                raise ValueError(
                    "evidence update cannot change claim revision or occurrences"
                )
            if old == record:
                raise ValueError("evidence update has no change")
        elif old is None:
            if len(latest) >= MAX_CLAIMS:
                raise ValueError("claim registration count exceeds budget")
            if record.claim.revision != 1:
                raise ValueError("first semantic revision must be one")
        elif (
            record.claim.revision != old.claim.revision + 1
            or record.claim.supersedes != old.claim.sha256
        ):
            raise ValueError("semantic claim predecessor or revision mismatch")
        return
    from arw.kernel.state.claim_authentication import parse_attestation

    attestation = parse_attestation(event["payload"])
    snapshot = attestation.snapshot_manifest
    claim = latest.get(attestation.claim_id)
    if (
        claim is None
        or claim.claim.revision != attestation.claim_revision
        or claim.claim.sha256 != attestation.claim_sha256
    ):
        raise ValueError("attestation targets a stale or unknown semantic claim")
    if (
        snapshot.project_id != event["project_id"]
        or snapshot.journal.sequence != event["sequence"] - 1
        or snapshot.journal.head_sha256 != event["previous_sha256"]
    ):
        raise ValueError("attestation must bind the exact N-1 journal prefix")


@dataclass(frozen=True)
class Inputs:
    root: Path
    manifest: SnapshotManifest
    journal: list[dict]
    runs: dict  # run_id -> (root, manifest, validated replay)
    cache: dict = field(default_factory=dict, compare=False)
    held_lock_roots: tuple[Path, ...] = ()
    figure_verifier: object = None


def _roots(root: Path, run_roots) -> tuple[Path, ...]:
    roots = []
    if len(run_roots) > 32:
        raise ClaimGraphError("limit_exceeded", "snapshot contains too many runs")
    for value in run_roots:
        run = Path(value).absolute()
        if not run.is_relative_to(root) or run.resolve() != run or not run.is_dir():
            raise ClaimGraphError(
                "project_run_mismatch",
                "run must be a real directory inside the project",
            )
        roots.append(run)
    if len(set(roots)) != len(roots):
        raise ClaimGraphError("duplicate_run", "run roots must be unique")
    return tuple(roots)


def _read_inputs(
    root: Path,
    run_roots,
    fixed: SnapshotManifest | None = None,
    *,
    held_lock_roots: tuple[Path, ...] = (),
    figure_verifier=None,
) -> Inputs:
    root = narrative._root(root)
    identity = narrative._identity(root)
    roots = _roots(root, run_roots)
    try:
        events, _, _ = narrative._read(
            root, at_sequence=fixed.journal.sequence if fixed else None
        )
        runs = {}
        prefixes = []
        cuts = {r.run_id: r for r in fixed.runs} if fixed else {}
        for run in roots:
            manifest, raw = _read_manifest(run)
            digest = sha256_hex(raw)
            if manifest.run_id in runs:
                raise ClaimGraphError(
                    "duplicate_run", "distinct run roots repeat a run ID"
                )
            if fixed:
                cut = cuts.get(manifest.run_id)
                if cut is None:
                    raise ClaimGraphError(
                        "mixed_snapshot", "run set differs from historical snapshot"
                    )
                from arw.kernel.ledger.journal import replay_run_under_held_lock

                prefix_reader = (
                    replay_run_under_held_lock
                    if run in held_lock_roots
                    else replay_run_prefix
                )
                replay = prefix_reader(
                    run,
                    revision=cut.revision,
                    expected_head_sha256=cut.head_sha256,
                    expected_manifest_sha256=cut.run_manifest_sha256,
                )
            else:
                replay = _replay_unlocked(run)
                if replay.recovery_health != "healthy":
                    raise ClaimGraphError(
                        "corrupt_run_history", "included run requires recovery"
                    )
            binding = manifest.narrative_binding
            if binding is not None and (
                binding.project_id != identity.project_id
                or narrative._binding_root(run, binding) != root
                or not any(
                    e["event_sha256"] == binding.initial_sha256
                    and e["version"] == binding.initial_version
                    for e in events
                )
            ):
                raise ClaimGraphError(
                    "dependency_outside_prefix",
                    "run narrative binding is outside the journal prefix",
                )
            runs[manifest.run_id] = (run, manifest, replay)
            prefixes.append(
                RunPrefix(
                    run_id=manifest.run_id,
                    run_manifest_sha256=digest,
                    revision=replay.revision,
                    head_sha256=replay.last_event_sha256,
                )
            )
        vector = SnapshotManifest(
            project_id=identity.project_id,
            journal=JournalPrefix(
                sequence=len(events), head_sha256=events[-1]["event_sha256"]
            ),
            runs=tuple(sorted(prefixes, key=lambda r: r.run_id)),
        )
        if fixed is not None and vector != fixed:
            raise ClaimGraphError(
                "mixed_snapshot", "fixed vector does not match validated log prefixes"
            )
        return Inputs(
            root,
            vector,
            events,
            runs,
            held_lock_roots=held_lock_roots,
            figure_verifier=figure_verifier,
        )
    except ClaimGraphError:
        raise
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        raise ClaimGraphError(
            "corrupt_log", "snapshot prefix cannot be validated"
        ) from error


def _context(inputs: Inputs):
    from arw.kernel.ledger.accepted_refs import (
        ResolutionContext,
    )
    from arw.kernel.ledger.accepted_refs import (
        RunPrefix as AcceptedRunPrefix,
    )

    return ResolutionContext(
        project_id=inputs.manifest.project_id,
        run_roots=tuple(inputs.runs[r.run_id][0] for r in inputs.manifest.runs),
        project_root=inputs.root,
        run_prefixes=tuple(
            AcceptedRunPrefix(
                run_id=r.run_id,
                revision=r.revision,
                head_sha256=r.head_sha256,
                run_manifest_sha256=r.run_manifest_sha256,
            )
            for r in inputs.manifest.runs
        ),
        journal_sequence=inputs.manifest.journal.sequence,
        journal_head_sha256=inputs.manifest.journal.head_sha256,
        held_lock_roots=inputs.held_lock_roots,
    )


def _closure(inputs: Inputs) -> None:
    """Every explicitly recorded cross-log reference belongs to this vector."""
    parent_events = {
        run_id: {e.event_id: e for e in item[2].events}
        for run_id, item in inputs.runs.items()
    }
    all_events = [e for item in inputs.runs.values() for e in item[2].events]
    journal_events = {e["sequence"]: e for e in inputs.journal}

    visited = [0]

    def walk(value, referring_sequence, depth=0):
        visited[0] += 1
        if depth > 32 or visited[0] > 262144:
            raise ClaimGraphError(
                "limit_exceeded", "cross-log dependency traversal exceeds budget"
            )
        if isinstance(value, dict):
            scope = value.get("scope")
            if scope == "parent-artifact":
                prefix = next(
                    (
                        r
                        for r in inputs.manifest.runs
                        if r.run_id == value.get("run_id")
                    ),
                    None,
                )
                event = parent_events.get(value.get("run_id"), {}).get(
                    value.get("accepting_event_id")
                )
                if prefix is None or event is None:
                    raise ClaimGraphError(
                        "dependency_outside_prefix",
                        "journal parent reference is outside included prefixes",
                    )
                if (
                    value.get("project_id") != inputs.manifest.project_id
                    or value.get("run_manifest_sha256") != prefix.run_manifest_sha256
                    or value.get("accepting_event_sha256") != event.event_sha256
                ):
                    raise ClaimGraphError(
                        "digest_mismatch", "cross-log parent identity or digest differs"
                    )
            elif scope == "project-journal":
                seq = value.get("sequence")
                event = journal_events.get(seq) if type(seq) is int else None
                if event is None or seq >= referring_sequence:
                    raise ClaimGraphError(
                        "dependency_outside_prefix",
                        "journal reference is not a preceding included event",
                    )
                if (
                    value.get("project_id") != inputs.manifest.project_id
                    or value.get("event_sha256") != event["event_sha256"]
                ):
                    raise ClaimGraphError(
                        "digest_mismatch", "cross-log journal reference differs"
                    )
            # Legacy accepted reference contracts have unscoped event identities.
            for id_key, hash_key in (
                ("source_event_id", "source_event_sha256"),
                ("ledger_event_id", "ledger_event_sha256"),
                ("accepting_event_id", "accepting_event_sha256"),
            ):
                if id_key in value and scope != "parent-artifact":
                    matches = [
                        e
                        for e in all_events
                        if e.event_id == value[id_key]
                        and e.event_sha256 == value.get(hash_key)
                    ]
                    if not matches:
                        raise ClaimGraphError(
                            "dependency_outside_prefix",
                            "legacy parent reference is outside included prefixes",
                        )
            if value.get("schema_version") == "arw.claim-graph-snapshot.v1":
                vector = SnapshotManifest.model_validate(value)
                if vector.project_id != inputs.manifest.project_id:
                    raise ClaimGraphError(
                        "project_mismatch",
                        "confirmation references a different project",
                    )
                for old in vector.runs:
                    item = inputs.runs.get(old.run_id)
                    if item is None or not any(
                        e.resulting_revision == old.revision
                        and e.event_sha256 == old.head_sha256
                        for e in item[2].events
                    ):
                        raise ClaimGraphError(
                            "dependency_outside_prefix",
                            "confirmation run snapshot is outside included prefixes",
                        )
            for child in value.values():
                walk(child, referring_sequence, depth + 1)
        elif isinstance(value, (list, tuple)):
            for child in value:
                walk(child, referring_sequence, depth + 1)

    for event in inputs.journal:
        walk(event["payload"], event["sequence"])
    for item in inputs.runs.values():
        for event in item[2].events:
            if event.event_type in {"artifact.accepted", "research_artifact_accepted"}:
                manifest = load_artifact_manifest(
                    item[0], event.payload.manifest_sha256
                )
                if manifest.media_type == "application/json":
                    raw = read_retained_bytes(
                        item[0], manifest.content_path, max_bytes=MAX_SOURCE_BYTES
                    )
                    if sha256_hex(raw) != event.payload.artifact_sha256:
                        raise ClaimGraphError(
                            "digest_mismatch",
                            "accepted dependency container bytes differ",
                        )
                    try:
                        value = strict_json_loads(raw)
                    except ValueError:
                        value = None
                    walk(value, inputs.manifest.journal.sequence + 1)
            if event.event_type == "claim.attestation_anchored":
                source = journal_events.get(event.payload.journal_sequence)
                if source is None:
                    raise ClaimGraphError(
                        "dependency_outside_prefix",
                        "parent anchor journal confirmation is outside snapshot",
                    )
                if source["event_sha256"] != event.payload.journal_event_sha256:
                    raise ClaimGraphError(
                        "digest_mismatch",
                        "parent anchor journal confirmation hash differs",
                    )


def _resolve(original: dict, inputs: Inputs, adapter: str = "accepted_ref"):
    from arw.kernel.ledger.accepted_refs import to_accepted_ref

    key = (adapter, sha256_hex(canonical_json_bytes(original)))
    if key not in inputs.cache:
        inputs.cache[key] = to_accepted_ref(
            original, _context(inputs), adapter_kind=ADAPTER_KINDS.get(adapter)
        )
    return inputs.cache[key]


def _resolution(value) -> dict:
    reason = value.reason
    integrity = (
        "resolved"
        if value.status == "resolved"
        else "digest_mismatch"
        if reason == "digest_mismatch"
        else "stale"
        if reason == "stale"
        else "missing"
    )
    return {
        "integrity": integrity,
        "adapter_status": value.status,
        "proven_scope": value.proven_scope,
        "reason": reason,
        "accepted_ref": value.ref.model_dump(mode="json") if value.ref else None,
    }


def _parent_ref(inputs: Inputs, run_id: str, event) -> dict:
    from arw.kernel.state.accepted_ref import ParentArtifactRef

    prefix = next(r for r in inputs.manifest.runs if r.run_id == run_id)
    return ParentArtifactRef(
        project_id=inputs.manifest.project_id,
        run_id=run_id,
        run_manifest_sha256=prefix.run_manifest_sha256,
        artifact_id=event.payload.artifact_id,
        accepting_event_id=event.event_id,
        accepting_event_sha256=event.event_sha256,
        content_sha256=event.payload.artifact_sha256,
    ).model_dump(mode="json")


def _manuscript(ref: dict, inputs: Inputs) -> tuple[bytes, dict | None, str]:
    """AcceptedRef verifies the container; original narrative validator binds body."""
    resolved = _resolve(ref, inputs)
    if resolved.status != "resolved" or resolved.raw_bytes is None:
        raise ClaimGraphError(
            resolved.reason or "missing", "manuscript accepted reference is unresolved"
        )
    raw = resolved.raw_bytes
    try:
        value = strict_json_loads(raw)
    except ValueError:
        return raw, None, "unknown"
    if (
        isinstance(value, dict)
        and isinstance(value.get("candidate"), str)
        and ref.get("selector", "") in {"", "/candidate"}
    ):
        from arw.kernel.state.text_spans import validate_citation_bindings

        validate_citation_bindings(
            value["verification"], value["source"], value["candidate"]
        )
        body = value["candidate"].encode("utf-8")
        if sha256_hex(body) != value.get("candidate_sha256"):
            raise ClaimGraphError("digest_mismatch", "writing candidate digest differs")
        return (
            body,
            value["verification"].get("citation_bindings"),
            "recorded_writing_activity",
        )
    if (
        isinstance(value, dict)
        and value.get("schema_version") == "arw.narrative-realization.v1"
    ):
        from arw.kernel.ledger.narrative_content import verify_realization_source
        from arw.kernel.state.narrative_realization import NarrativeRealization

        realization = NarrativeRealization.model_validate(value)
        root = inputs.runs[ref["run_id"]][0]
        verify_realization_source(root, realization)
        body = read_retained_bytes(
            root, realization.source_path, max_bytes=MAX_SOURCE_BYTES
        )
        return body, None, "unknown"
    if isinstance(resolved.selected_value, str) and ref.get("selector"):
        return resolved.selected_value.encode("utf-8"), None, "unknown"
    raise ClaimGraphError(
        "unsupported_manuscript", "accepted artifact has no supported manuscript body"
    )


def _extract(ref: dict, inputs: Inputs) -> tuple[list[Occurrence], dict]:
    from arw.kernel.state.text_spans import (
        CITATION_BINDINGS_VERSION,
        PATTERNS,
        sentence_spans,
    )

    raw, citation_table, provenance = _manuscript(ref, inputs)
    if len(raw) > 1_048_576:
        raise ClaimGraphError("limit_exceeded", "manuscript exceeds extraction budget")
    text = raw.decode("utf-8")
    body_sha = sha256_hex(raw)
    offsets = [0]
    for char in text:
        offsets.append(offsets[-1] + len(char.encode("utf-8")))
    sentence_ranges = list(sentence_spans(text))
    occurrences = []

    def add(kind, offset, length, version="arw.utf8-byte-span.v1"):
        if len(occurrences) >= MAX_NODES:
            raise ClaimGraphError(
                "limit_exceeded", "manuscript occurrence count exceeds budget"
            )
        occurrences.append(
            Occurrence(
                kind=kind,
                manuscript_ref=ref,
                manuscript_sha256=body_sha,
                offset=offset,
                length=length,
                selected_sha256=sha256_hex(raw[offset : offset + length]),
                locator_version=version,
            )
        )

    for match in re.finditer(PATTERNS["numbers_units"], text):
        add(
            "numeric_token",
            offsets[match.start()],
            offsets[match.end()] - offsets[match.start()],
        )
    citation_scope = "fresh_surface_segmentation"
    if (
        citation_table is not None
        and citation_table.get("version") == CITATION_BINDINGS_VERSION
    ):
        citation_scope = "retained_v2_byte_spans"
        for span in citation_table["candidate"]["assertions"]:
            add(
                "citation_sentence",
                span["offset"],
                span["length"],
                CITATION_BINDINGS_VERSION,
            )
    elif citation_table is not None:
        # Old sentence-only receipts cannot distinguish repeated assertions.
        # Retain their original shape and mark location unknown; never recut.
        citation_scope = "legacy_sentence_scopes_location_unknown"
    else:
        for start, end in sentence_ranges:
            if re.search(PATTERNS["citations"], text[start:end]):
                add("citation_sentence", offsets[start], offsets[end] - offsets[start])
    for match in re.finditer(
        r"(?m)^\s*(?:Figure|Fig\.|图)\s*\d+[^\n]*", text, flags=re.IGNORECASE
    ):
        start, end = match.span()
        while start < end and text[start].isspace():
            start += 1
        add("figure_caption", offsets[start], offsets[end] - offsets[start])
    in_scope_sentences = 0
    for start, end in sentence_ranges:
        lower, upper = offsets[start], offsets[end]
        if re.search(PATTERNS["citations"], text[start:end]) or any(
            o.offset < upper and o.offset + o.length > lower for o in occurrences
        ):
            in_scope_sentences += 1
    result = {
        "accepted_ref": ref,
        "manuscript_sha256": body_sha,
        "sentence_count": len(sentence_ranges),
        "in_scope_sentence_count": in_scope_sentences,
        "out_of_scope_sentence_count": len(sentence_ranges) - in_scope_sentences,
        "citation_locator_scope": citation_scope,
        "ai_involvement": "unknown",
        "activity_provenance": provenance,
        "unknown_citation_locations": len(citation_table.get("candidate", []))
        if citation_table is not None
        and citation_table.get("version") != CITATION_BINDINGS_VERSION
        else 0,
    }
    return occurrences, result


def _check_occurrence(occurrence: Occurrence, inputs: Inputs) -> None:
    raw, _, _ = _manuscript(occurrence.manuscript_ref, inputs)
    start, end = occurrence.offset, occurrence.offset + occurrence.length
    if (
        sha256_hex(raw) != occurrence.manuscript_sha256
        or end > len(raw)
        or sha256_hex(raw[start:end]) != occurrence.selected_sha256
    ):
        raise ClaimGraphError(
            "digest_mismatch", "occurrence manuscript or selected bytes differ"
        )
    try:
        raw[:start].decode("utf-8")
        raw[start:end].decode("utf-8")
    except UnicodeError as error:
        raise ClaimGraphError(
            "invalid_utf8_span", "occurrence splits a UTF-8 codepoint"
        ) from error
    candidates, _ = _extract(occurrence.manuscript_ref, inputs)
    if not any(o.occurrence_id == occurrence.occurrence_id for o in candidates):
        raise ClaimGraphError(
            "unsupported_occurrence",
            "registered selector is outside extracted MVP occurrences",
        )
    if occurrence.locator_version == "arw.writing-citation-bindings.v2" and not any(
        o.occurrence_id == occurrence.occurrence_id
        and o.locator_version == occurrence.locator_version
        for o in candidates
    ):
        raise ClaimGraphError(
            "invalid_locator_version",
            "occurrence does not match retained citation spans",
        )


def _evaluate_registration(
    record: ClaimRegistration, inputs: Inputs
) -> tuple[list[dict], str]:
    evidence = []
    dependency_evidence = []
    for binding in sorted(record.evidence, key=lambda e: e.evidence_id):
        result = _resolve(binding.original, inputs, binding.adapter)
        item = {
            "evidence_id": binding.evidence_id,
            "node_kind": binding.node_kind,
            "original": binding.original,
            **_resolution(result),
            "checks": [],
            "registered_check_assertions": [
                c.model_dump(mode="json") for c in binding.checks
            ],
        }
        # Registrations preserve assertions. Trusted check results come only
        # from canonical accepted receipts via their existing validators.
        if result.status == "resolved" and result.raw_bytes is not None:
            item["checks"] = _receipt_checks(result.raw_bytes)
        dependency_item = {**item, "checks": list(item["checks"])}
        if binding.node_kind == "Figure":
            # Preserve the existing v1 dependency formula and retained
            # declarations when adding an optional read-side verifier.
            dependency_item["figure_adapter"] = {
                "status": "unsupported",
                "reason": "result_plot_adapter_pending",
            }
            item["figure_adapter"] = _figure_details(
                inputs,
                result.ref.model_dump(mode="json") if result.ref else binding.original,
                result,
            )
            item["checks"] += item["figure_adapter"].get("checks", [])
        evidence.append(item)
        dependency_evidence.append(dependency_item)
    dependency = sha256_hex(
        canonical_json_bytes(
            {
                "evidence": dependency_evidence,
                "relations": [r.model_dump(mode="json") for r in record.relations],
                "assessments": [a.model_dump(mode="json") for a in record.assessments],
            }
        )
    )
    return evidence, dependency


def _receipt_checks(raw: bytes) -> list[dict]:
    try:
        value = strict_json_loads(raw)
    except ValueError:
        return []
    if not isinstance(value, dict):
        return []
    if value.get("schema_version") == "arw.citation-check.v1":
        from arw.kernel.policy.citations import CheckReceipt

        receipt = CheckReceipt.model_validate_json(raw)
        status = (
            "passed"
            if receipt.status == "verified"
            else "failed"
            if receipt.status in {"not_found", "retracted"}
            else "not_checked"
        )
        return [
            {
                "method": "doi_metadata",
                "version": receipt.parser_version,
                "status": status,
                "scope": "bibliographic_metadata_only",
                "receipt_sha256": receipt.receipt_sha256,
            }
        ]
    if value.get("schema_version") == "arw.experiment-acceptance.v1":
        from arw.kernel.artifacts.experiment_acceptance import (
            ExperimentAcceptanceResult,
        )

        result = ExperimentAcceptanceResult.model_validate_json(raw)
        mapping = {
            "passed": "passed",
            "failed": "failed",
            "evidence_missing": "not_checked",
            "invalid_contract": "failed",
            "invalid_artifact": "failed",
            "unsupported": "unsupported",
        }
        return [
            {
                "method": c.kind,
                "version": result.evaluator_version,
                "status": mapping.get(c.status, "not_checked"),
                "scope": result.scope,
                "check_id": c.check_id,
                "legacy_observed_display": c.observed,
            }
            for c in result.checks
        ]
    return []


def _attestations(
    record: ClaimRegistration,
    dependency: str,
    inputs: Inputs,
    evaluation_time: str | None = None,
) -> list[dict]:
    items = []
    for event in inputs.journal:
        if (
            event["kind"] != "claim.attested"
            or event["payload"]["claim_id"] != record.claim.claim_id
        ):
            continue
        from arw.kernel.state.claim_authentication import parse_attestation

        att = parse_attestation(event["payload"])
        # Independently reconstruct the exact predecessor vector; declarations
        # do not assert permission and never acquire an authenticated label.
        historical = _read_inputs(
            inputs.root,
            tuple(inputs.runs[r.run_id][0] for r in att.snapshot_manifest.runs),
            att.snapshot_manifest,
            figure_verifier=inputs.figure_verifier,
            held_lock_roots=inputs.held_lock_roots,
        )
        _closure(historical)
        old = _registrations(historical.journal).get(att.claim_id)
        valid = old is not None and old.claim.sha256 == att.claim_sha256
        old_dependency = _evaluate_registration(old, historical)[1] if old else None
        valid = valid and old_dependency == att.evidence_dependency_sha256
        status = (
            "declared"
            if valid
            and att.claim_sha256 == record.claim.sha256
            and att.evidence_dependency_sha256 == dependency
            else "stale"
        )
        verified = {"historical_authorized": False, "current_applicability": status}
        if att.authority.kind == "authenticated":
            from arw.kernel.ledger.claim_authority import verify_authenticated_record

            verified = verify_authenticated_record(
                inputs,
                historical,
                event,
                att,
                claim_current=att.claim_sha256 == record.claim.sha256,
                evidence_current=att.evidence_dependency_sha256 == dependency,
                dependencies_valid=valid,
                evaluation_time=evaluation_time,
            )
            status = verified.pop("status")
        items.append(
            {
                "status": status,
                "authority": att.authority.model_dump(mode="json"),
                **verified,
                "claim_revision": att.claim_revision,
                "claim_sha256": att.claim_sha256,
                "statement": att.statement,
                "scope": att.scope,
                "policy_version": att.policy_version,
                "graph_snapshot_sha256": att.graph_snapshot_sha256,
                "evidence_dependency_sha256": att.evidence_dependency_sha256,
                "source": {
                    "sequence": event["sequence"],
                    "event_sha256": event["event_sha256"],
                },
            }
        )
    return items


def _project(inputs: Inputs, *, evaluation_time: str | None = None) -> dict:
    _closure(inputs)
    nodes = []
    edges = []
    manuscript_observations = []
    discovered = {}
    recorded_relations = []
    registrations = _registrations(inputs.journal)
    for run_id, (root, _, replay) in sorted(inputs.runs.items()):
        for event in replay.events:
            if event.event_type in {"artifact.accepted", "research_artifact_accepted"}:
                artifact = load_artifact_manifest(root, event.payload.manifest_sha256)
                ref = _parent_ref(inputs, run_id, event)
                resolved = _resolve(ref, inputs)
                kind = (
                    "ReferenceCheck"
                    if artifact.artifact_kind == "citation-check-receipt"
                    else "ExperimentResult"
                    if artifact.artifact_kind
                    in {"experiment-acceptance", "experiment-acceptance-result"}
                    else "Figure"
                    if artifact.artifact_kind == "research-artifact"
                    else "SelectionContext"
                    if "selection" in artifact.artifact_kind
                    else "LiteratureEvidence"
                    if artifact.artifact_kind
                    in {"source", "source-manifest", "provenance-record"}
                    else "Evidence"
                )
                node = {
                    "id": "accepted:" + event.event_sha256,
                    "node_kind": kind,
                    "artifact_kind": artifact.artifact_kind,
                    "source": ref,
                    **_resolution(resolved),
                    "checks": _receipt_checks(resolved.raw_bytes)
                    if resolved.raw_bytes
                    else [],
                }
                if kind == "Figure":
                    node["figure_adapter"] = _figure_details(inputs, ref, resolved)
                    node["checks"] += node["figure_adapter"].get("checks", [])
                if resolved.raw_bytes is not None:
                    try:
                        retained = strict_json_loads(resolved.raw_bytes)
                    except ValueError:
                        retained = None
                    if (
                        isinstance(retained, dict)
                        and retained.get("schema_version")
                        == "arw.claim-evidence-link.v1"
                    ):
                        from arw.kernel.policy.research_integrity import (
                            ClaimEvidenceLink,
                        )

                        link = ClaimEvidenceLink.model_validate_json(resolved.raw_bytes)
                        target = registrations.get(link.claim_id)
                        bound = (
                            target is not None
                            and target.claim.sha256 == link.claim_sha256
                        )
                        relation = {
                            **link.model_dump(mode="json"),
                            "asserted_by": event.actor_id,
                            "basis": ref,
                            "claim_revision": target.claim.revision if bound else None,
                            "binding_status": "bound"
                            if bound
                            else "unbound_claim_revision",
                        }
                        recorded_relations.append(relation)
                        if bound:
                            edges.append(
                                {
                                    "source": node["id"],
                                    "target": f"claim:{link.claim_id}@{target.claim.revision}",
                                    "relation": link.relation,
                                    "asserted_by": event.actor_id,
                                    "basis": ref,
                                    "evidence_span_sha256": list(
                                        link.evidence_span_sha256
                                    ),
                                }
                            )
                    if (
                        isinstance(retained, dict)
                        and retained.get("schema_version") == "arw.evidence-span.v1"
                    ):
                        node["embedded_evidence_resolution"] = _resolution(
                            _resolve(retained, inputs, "evidence_span")
                        )
                    elif isinstance(retained, dict) and isinstance(
                        retained.get("source_locator"), dict
                    ):
                        node["embedded_evidence_resolution"] = _resolution(
                            _resolve(
                                retained["source_locator"], inputs, "source_locator"
                            )
                        )
                nodes.append(node)
                if artifact.artifact_kind in MANUSCRIPT_KINDS:
                    occurrences, observation = _extract(ref, inputs)
                    manuscript_observations.append(observation)
                    for occurrence in occurrences:
                        discovered[occurrence.occurrence_id] = occurrence
            elif event.event_type in {
                "human_authority.accepted",
                "human_decision.recorded",
                "experiment.contract.accepted",
                "experiment.provenance.accepted",
            }:
                nodes.append(
                    {
                        "id": "event:" + event.event_sha256,
                        "node_kind": "Decision"
                        if event.event_type.startswith("human_")
                        else "ExperimentResult",
                        "integrity": "resolved",
                        "proven_scope": "metadata_only",
                        "checks": [],
                        "source": {
                            "run_id": run_id,
                            "event_id": event.event_id,
                            "event_sha256": event.event_sha256,
                            "sequence": event.sequence,
                            "event_type": event.event_type,
                        },
                    }
                )
    for event in inputs.journal:
        if event["kind"] in {"selected", "approved", "withdrawn"}:
            nodes.append(
                {
                    "id": "journal:" + event["event_sha256"],
                    "node_kind": "Decision",
                    "integrity": "resolved",
                    "proven_scope": "metadata_only",
                    "checks": [],
                    "source": {
                        "scope": "project-journal",
                        "project_id": inputs.manifest.project_id,
                        "sequence": event["sequence"],
                        "event_sha256": event["event_sha256"],
                        "payload_selector": "",
                    },
                    "attestation_scope": "direction_decision_only",
                }
            )
    registrations = _registrations(inputs.journal)
    if len(registrations) > MAX_CLAIMS:
        raise ClaimGraphError("limit_exceeded", "claim count exceeds projection budget")
    registered_occurrences = set()
    occurrence_bindings = {}
    claims = []
    for claim_id, record in sorted(registrations.items()):
        evidence, dependency = _evaluate_registration(record, inputs)
        attestations = _attestations(record, dependency, inputs, evaluation_time)
        for occurrence in record.occurrences:
            _check_occurrence(occurrence, inputs)
            registered_occurrences.add(occurrence.occurrence_id)
            discovered[occurrence.occurrence_id] = occurrence
            occurrence_bindings.setdefault(occurrence.occurrence_id, []).append(
                (claim_id, record.claim.revision, occurrence)
            )
            edges.append(
                {
                    "relation": "expresses",
                    "source": "occurrence:" + occurrence.occurrence_id,
                    "target": f"claim:{claim_id}@{record.claim.revision}",
                }
            )
        claim = {
            "id": f"claim:{claim_id}@{record.claim.revision}",
            "node_kind": "Claim",
            **record.claim.model_dump(mode="json"),
            "claim_sha256": record.claim.sha256,
            "evidence_dependency_sha256": dependency,
            "integrity": [
                {
                    "evidence_id": item["evidence_id"],
                    **{
                        k: item[k]
                        for k in (
                            "integrity",
                            "adapter_status",
                            "proven_scope",
                            "reason",
                        )
                    },
                }
                for item in evidence
            ],
            "checks": [
                {
                    "evidence_id": item["evidence_id"],
                    "results": item["checks"],
                    "registered_assertions": item["registered_check_assertions"],
                }
                for item in evidence
            ],
            "relations": [r.model_dump(mode="json") for r in record.relations],
            "assessments": [
                {**a.model_dump(mode="json"), "advisory": True}
                for a in record.assessments
            ],
            "attestations": attestations,
        }
        nodes.append(claim)
        claims.append(claim)
        for item in evidence:
            evidence_node = {
                "id": f"evidence:{claim_id}@{record.claim.revision}:{item['evidence_id']}",
                **item,
            }
            nodes.append(evidence_node)
        for relation in record.relations:
            edges.append(
                {
                    "source": f"evidence:{claim_id}@{record.claim.revision}:{relation.evidence_id}",
                    "target": claim["id"],
                    **relation.model_dump(mode="json"),
                }
            )
    numeric_sources = _numeric_sources(inputs, nodes)
    for claim in claims:
        record = registrations[claim["claim_id"]]
        claim["numeric_checks"] = [
            {
                "occurrence_id": "occurrence:" + o.occurrence_id,
                **_numeric_check(o, inputs, numeric_sources),
            }
            for o in record.occurrences
            if o.kind == "numeric_token"
        ]
    for key, occurrence in sorted(discovered.items()):
        nodes.append(
            {
                "id": "occurrence:" + key,
                "node_kind": "Occurrence",
                **occurrence.model_dump(mode="json"),
                **(
                    {
                        "numeric_verification": _numeric_check(
                            occurrence, inputs, numeric_sources
                        )
                    }
                    if occurrence.kind == "numeric_token"
                    else {}
                ),
                "registration": "registered"
                if key in registered_occurrences
                else "unknown",
            }
        )
    for node in nodes:
        if node["node_kind"] == "Occurrence" and node["kind"] == "numeric_token":
            bindings = occurrence_bindings.get(
                node["id"].removeprefix("occurrence:"), []
            )
            node["claim_numeric_bindings"] = [
                {
                    "claim_id": c,
                    "claim_revision": rev,
                    "derivation_id": o.derivation_id,
                    "numeric_class": o.numeric_class,
                    "plot_value_id": o.plot_value_id,
                    "plot_revision": o.plot_revision,
                    "verification": _numeric_check(o, inputs, numeric_sources),
                }
                for c, rev, o in bindings
            ]
            if (
                len(
                    {
                        canonical_json_bytes(o.model_dump(mode="json"))
                        for _, _, o in bindings
                    }
                )
                > 1
            ):
                node["numeric_verification"] = {
                    "status": "not_checked",
                    "reason": "multiple_claim_specific_bindings",
                }
    nodes.sort(key=lambda node: node["id"])
    edges.sort(key=canonical_json_bytes)
    coverage = {
        "extraction_scope": MVP_SCOPE,
        "extraction_version": EXTRACTION_VERSION,
        "sentence_segmentation_version": "arw.writing-surface.en-zh.v1",
        "observation_scope": "accepted_manuscripts_in_explicit_run_prefixes_only",
        "observed_manuscript_count": len(manuscript_observations),
        "observed_sentence_count": sum(
            m["sentence_count"] for m in manuscript_observations
        ),
        "in_scope_sentence_count": sum(
            m["in_scope_sentence_count"] for m in manuscript_observations
        ),
        "out_of_scope_sentence_count": sum(
            m["out_of_scope_sentence_count"] for m in manuscript_observations
        ),
        "candidate_occurrence_count": len(discovered),
        "registered_occurrence_count": len(registered_occurrences),
        "registered_claim_count": len(registrations),
        "unknown_occurrence_count": len(set(discovered) - registered_occurrences),
        "unknown_citation_location_count": sum(
            m["unknown_citation_locations"] for m in manuscript_observations
        ),
        "unobserved_claims": "unknown",
        "unsupported_scope": [
            "arbitrary_uncited_prose",
            "table_cells",
            "semantic_auto_extraction",
        ],
        "manuscripts": manuscript_observations,
    }
    advisory = []
    if coverage["unknown_occurrence_count"]:
        advisory.append(
            {
                "code": "unregistered_occurrences",
                "count": coverage["unknown_occurrence_count"],
            }
        )
    if coverage["out_of_scope_sentence_count"]:
        advisory.append(
            {
                "code": "out_of_scope_sentences",
                "count": coverage["out_of_scope_sentence_count"],
            }
        )
    for claim in claims:
        if not claim["integrity"]:
            advisory.append(
                {
                    "code": "missing_evidence",
                    "claim_id": claim["claim_id"],
                    "revision": claim["revision"],
                }
            )
        if not any(
            a["status"] == "declared"
            or (a["historical_authorized"] and a["current_applicability"] == "current")
            for a in claim["attestations"]
        ):
            advisory.append(
                {
                    "code": "claim_confirmation_missing_or_stale",
                    "claim_id": claim["claim_id"],
                    "revision": claim["revision"],
                }
            )
    result = {
        "schema_version": "arw.claim-graph.v1",
        "status": "projected",
        "snapshot_manifest": inputs.manifest.model_dump(mode="json"),
        "snapshot_sha256": inputs.manifest.sha256,
        "nodes": nodes,
        "edges": edges,
        "recorded_relations": sorted(recorded_relations, key=canonical_json_bytes),
        "coverage": coverage,
        "advisory": advisory,
        "hard_checks": {
            "status": "unsupported",
            "reason": "not_requested",
        },
    }
    if len(nodes) > MAX_NODES or len(canonical_json_bytes(result)) > MAX_BYTES:
        raise ClaimGraphError(
            "limit_exceeded", "claim graph exceeds bounded projection budget"
        )
    return result


def graph(
    project_root: Path,
    *,
    run_roots: tuple[Path, ...] = (),
    as_of: SnapshotManifest | dict | None = None,
    expected_head: str | None = None,
    hard_check: bool = False,
    evaluation_time: str | None = None,
    figure_verifier=None,
) -> dict:
    """Rebuild a graph without writes; current views optimistically compare vectors."""
    fixed = SnapshotManifest.model_validate(as_of) if isinstance(as_of, dict) else as_of
    before = _read_inputs(
        project_root, run_roots, fixed, figure_verifier=figure_verifier
    )
    if expected_head is not None and expected_head != before.manifest.sha256:
        raise ClaimGraphError("stale", "expected snapshot manifest digest differs")
    result = (
        _project(before, evaluation_time=evaluation_time)
        if evaluation_time is not None
        else _project(before)
    )
    if hard_check:
        failures = []
        claims = [n for n in result["nodes"] if n["node_kind"] == "Claim"]
        for claim in claims:
            if not any(
                a["historical_authorized"] and a["current_applicability"] == "current"
                for a in claim["attestations"]
            ):
                failures.append(
                    {
                        "code": "authenticated_confirmation_missing_or_stale",
                        "claim_id": claim["claim_id"],
                        "revision": claim["revision"],
                    }
                )
            if not claim["integrity"] or any(
                i["integrity"] != "resolved" for i in claim["integrity"]
            ):
                failures.append(
                    {
                        "code": "evidence_integrity_unresolved",
                        "claim_id": claim["claim_id"],
                    }
                )
            if any(
                check["status"] == "failed"
                for group in claim["checks"]
                for check in group["results"]
            ):
                failures.append(
                    {"code": "specified_check_failed", "claim_id": claim["claim_id"]}
                )
        numeric = [
            n
            for n in result["nodes"]
            if n["node_kind"] == "Occurrence" and n["kind"] == "numeric_token"
        ]
        for claim in claims:
            for check in claim["numeric_checks"]:
                if check["status"] != "passed":
                    failures.append(
                        {
                            "code": "claim_numeric_binding_not_verified",
                            "claim_id": claim["claim_id"],
                            "occurrence_id": check["occurrence_id"],
                            "status": check["status"],
                        }
                    )
        for occurrence in numeric:
            if (
                occurrence["registration"] != "registered"
                and occurrence["numeric_verification"]["status"] != "passed"
            ):
                failures.append(
                    {
                        "code": "numeric_occurrence_not_verified",
                        "occurrence_id": occurrence["id"],
                        "status": occurrence["numeric_verification"]["status"],
                    }
                )
        if any(
            check["status"] in {"unsupported", "not_checked"}
            for claim in claims
            for group in claim["checks"]
            for check in group["results"]
        ):
            failures.append({"code": "specified_check_unavailable"})
        coverage = result["coverage"]
        if (
            coverage["unknown_occurrence_count"]
            or coverage["unknown_citation_location_count"]
        ):
            failures.append({"code": "observed_occurrences_unbound"})
        if not claims or not coverage["observed_manuscript_count"]:
            failures.append({"code": "observation_scope_empty"})
        result["hard_checks"] = {
            "status": "failed" if failures else "passed",
            "scope": "registered_claims_and_observed_mvp_occurrences_only",
            "out_of_scope": "unknown_not_evaluated",
            "policy_version": "arw.claim-hard-coverage.v1",
            "denominator": {
                "observed_occurrences": coverage["candidate_occurrence_count"],
                "registered_occurrences": coverage["registered_occurrence_count"],
                "registered_claims": coverage["registered_claim_count"],
                "out_of_scope_sentences": coverage["out_of_scope_sentence_count"],
            },
            "failures": failures,
        }
    if fixed is None:
        after = _read_inputs(project_root, run_roots)
        if after.manifest != before.manifest:
            raise ClaimGraphError(
                "stale", "a participating log changed during projection"
            )
    return result


def register_claim(
    project_root: Path,
    registration: ClaimRegistration,
    *,
    run_roots: tuple[Path, ...],
    expected_head: str,
    evidence_update: bool = False,
) -> dict:
    """Append an explicit author claim/anchor registration via the existing lock."""
    view = graph(project_root, run_roots=run_roots, expected_head=expected_head)
    snapshot = SnapshotManifest.model_validate(view["snapshot_manifest"])
    inputs = _read_inputs(project_root, run_roots, snapshot)
    for occurrence in registration.occurrences:
        _check_occurrence(occurrence, inputs)
    _evaluate_registration(registration, inputs)
    kind = "claim.evidence.updated" if evidence_update else "claim.registered"
    with narrative._locked(project_root, write=True) as root:
        events, current, _ = narrative._read(root)
        if _read_inputs(root, run_roots).manifest.sha256 != expected_head:
            raise ClaimGraphError("stale", "claim registration snapshot advanced")
        if current is None:
            raise ClaimGraphError(
                "missing_selection", "claim registration requires selected narrative"
            )
        candidate = {"kind": kind, "payload": registration.model_dump(mode="json")}
        validate_claim_journal_event(candidate, events)
        # Validate closure of candidate dependencies before durable publication.
        candidate.update(
            sequence=len(events) + 1, project_id=inputs.manifest.project_id
        )
        _closure(
            Inputs(inputs.root, inputs.manifest, [*events, candidate], inputs.runs)
        )
        event = narrative._append(
            root, events, kind, current.version, registration.model_dump(mode="json")
        )
    return {
        "status": "registered",
        "claim_id": registration.claim.claim_id,
        "claim_revision": registration.claim.revision,
        "claim_sha256": registration.claim.sha256,
        "sequence": event["sequence"],
        "event_sha256": event["event_sha256"],
    }


def attest_declared(
    project_root: Path,
    *,
    run_roots: tuple[Path, ...],
    expected_head: str,
    claim_id: str,
    author_id: str,
    statement: str,
    scope: str,
    policy_version: str,
) -> dict:
    """Append declared confirmation of this exact N-1 claim/evidence snapshot."""
    view = graph(project_root, run_roots=run_roots, expected_head=expected_head)
    claim = next(
        (
            n
            for n in view["nodes"]
            if n["node_kind"] == "Claim" and n["claim_id"] == claim_id
        ),
        None,
    )
    if claim is None:
        raise ClaimGraphError(
            "unknown_claim", "claim is not registered in the supplied snapshot"
        )
    snapshot = SnapshotManifest.model_validate(view["snapshot_manifest"])
    att = DeclaredAttestation(
        claim_id=claim_id,
        claim_revision=claim["revision"],
        claim_sha256=claim["claim_sha256"],
        evidence_dependency_sha256=claim["evidence_dependency_sha256"],
        statement=statement,
        scope=scope,
        policy_version=policy_version,
        graph_snapshot_sha256=snapshot.sha256,
        snapshot_manifest=snapshot,
        authority=DeclaredAuthority(author_id=author_id),
    )
    with narrative._locked(project_root, write=True) as root:
        events, current, _ = narrative._read(root)
        if _read_inputs(root, run_roots).manifest != snapshot:
            raise ClaimGraphError("stale", "attestation predecessor snapshot advanced")
        if current is None:
            raise ClaimGraphError(
                "missing_selection", "attestation requires selected narrative"
            )
        candidate = {
            "kind": "claim.attested",
            "payload": att.model_dump(mode="json"),
            "project_id": snapshot.project_id,
            "sequence": len(events) + 1,
            "previous_sha256": events[-1]["event_sha256"],
        }
        validate_claim_journal_event(candidate, events)
        event = narrative._append(
            root, events, "claim.attested", current.version, att.model_dump(mode="json")
        )
    return {
        "status": "declared",
        "claim_id": claim_id,
        "claim_revision": claim["revision"],
        "graph_snapshot_sha256": snapshot.sha256,
        "sequence": event["sequence"],
        "event_sha256": event["event_sha256"],
    }


def _figure_details(inputs: Inputs, ref: dict, resolved) -> dict:
    if resolved.status != "resolved" or resolved.raw_bytes is None:
        return {"status": "unsupported", "reason": "unresolved_accepted_figure"}
    try:
        body = strict_json_loads(resolved.raw_bytes)
    except ValueError:
        body = None
    if (
        not isinstance(body, dict)
        or body.get("receipt_version") != "arw.result-plot-receipt.v1"
    ):
        return {"status": "unsupported", "reason": "artifact_kind_not_result_plot"}
    if inputs.figure_verifier is None:
        return {
            "status": "unsupported",
            "reason": "result_plot_verifier_unavailable",
            "checks": [
                {
                    "method": "result_plot_integrity",
                    "version": "1",
                    "status": "unsupported",
                    "scope": "figure_source_integrity",
                }
            ],
        }
    key = ("verified_figure", sha256_hex(canonical_json_bytes(ref)))
    if key not in inputs.cache:
        root, _, replay = inputs.runs[ref["run_id"]]
        try:
            receipt = inputs.figure_verifier(
                root,
                replay.events,
                ref["artifact_id"],
                resolution_context=_context(inputs),
            )
        except (ValueError, RuntimeError, OSError) as error:
            raise ClaimGraphError(
                "figure_integrity_failed",
                "original result plot verifier rejected accepted figure",
            ) from error
        inputs.cache[key] = receipt
    receipt = inputs.cache[key]
    if receipt is None:
        return {"status": "unsupported", "reason": "result_plot_verifier_unavailable"}
    statuses = {
        "PASS": "passed",
        "FAIL": "failed",
        "unsupported": "unsupported",
        "unknown": "not_checked",
        "advisory": "not_checked",
    }
    return {
        "status": "verified",
        "scope": "figure_source_integrity_only",
        "rendered_from": receipt.rendered_from.model_dump(mode="json"),
        "plot_values": [v.model_dump(mode="json") for v in receipt.plot_values],
        "checks": [
            {
                "method": c.category,
                "version": "result_plot.v1",
                "status": statuses.get(c.status, "not_checked"),
                "scope": "figure_source_integrity"
                if c.category == "integrity"
                else c.category,
                "code": c.code,
            }
            for c in receipt.checks
        ],
    }


def _numeric_sources(inputs: Inputs, nodes: list[dict]) -> dict:
    from arw.kernel.policy.numeric_core import evaluate_derivation
    from arw.kernel.state.numeric_core import Derivation

    records = {}
    sources = {}
    for node in nodes:
        ref = node.get("source")
        if not isinstance(ref, dict) or ref.get("scope") != "parent-artifact":
            continue
        result = _resolve(ref, inputs)
        if result.status != "resolved" or result.raw_bytes is None:
            continue
        try:
            body = strict_json_loads(result.raw_bytes)
        except ValueError:
            body = None
        if (
            isinstance(body, dict)
            and body.get("schema_version") == "arw.numeric-derivation.v1"
        ):
            try:
                record = Derivation.model_validate_json(result.raw_bytes)
            except ValueError:
                # Generic parent acceptance proves bytes, not that a numeric
                # record's declared identity or exact result is coherent.
                identity = body.get("derivation_id")
                if isinstance(identity, str) and re.fullmatch(r"[0-9a-f]{64}", identity):
                    sources[identity] = {
                        "status": "failed",
                        "reason": "sealed_derivation_replay_mismatch",
                        "source": ref,
                    }
                node["numeric_derivation"] = {
                    "status": "failed",
                    "reason": "invalid_accepted_derivation_record",
                }
                continue
            if (
                record.derivation_id in records
                and records[record.derivation_id] != record
            ):
                raise ClaimGraphError(
                    "numeric_identity_conflict",
                    "accepted derivation identity conflicts",
                )
            records[record.derivation_id] = record
            sources[record.derivation_id] = {"source": ref, "record": record}
        adapter = node.get("figure_adapter", {})
        if adapter.get("status") == "verified":
            for value in adapter["plot_values"]:
                sources.setdefault(value["derivation_id"], {"source": ref}).setdefault(
                    "plot_values", []
                ).append(value)
    for identity, record in records.items():
        actual = evaluate_derivation(record.request, _context(inputs), records)
        if actual != record:
            sources[identity] = {
                "status": "failed",
                "reason": "sealed_derivation_replay_mismatch",
                "source": sources[identity]["source"],
            }
        else:
            sources[identity].update(status=actual.status, exact=actual.exact)
    return sources


def _numeric_check(occurrence: Occurrence, inputs: Inputs, sources: dict) -> dict:
    from arw.kernel.policy.numeric_core import format_exact
    from arw.kernel.state.numeric_core import RationalExact

    kind = occurrence.numeric_class
    if kind in {"identifier", "year", "figure_number", "confidence_level"}:
        return {
            "status": "passed",
            "scope": "selected_byte_integrity_only",
            "classification": kind,
        }
    if kind != "own_result":
        return {
            "status": "not_checked",
            "classification": kind or "unknown",
            "reason": "numeric_origin_unknown"
            if kind in {None, "unknown"}
            else "non_own_result_numeric_scope",
        }
    source = sources.get(occurrence.derivation_id)
    if source is None:
        return {
            "status": "unsupported",
            "reason": "derivation_not_accepted_or_verified",
            "derivation_id": occurrence.derivation_id,
        }
    if source.get("status") == "failed":
        return {
            "status": "failed",
            "reason": source["reason"],
            "derivation_id": occurrence.derivation_id,
        }
    exact = source.get("exact")
    values = source.get("plot_values", [])
    if values:
        if occurrence.figure_ref is None or occurrence.plot_value_id is None:
            return {
                "status": "not_checked",
                "reason": "plot_value_context_binding_missing",
                "derivation_id": occurrence.derivation_id,
            }
        matching = [
            v
            for v in values
            if v["plot_value_id"] == occurrence.plot_value_id
            and v["revision"] == occurrence.plot_revision
        ]
        figure = _resolve(occurrence.figure_ref, inputs)
        details = _figure_details(inputs, occurrence.figure_ref, figure)
        matching = [
            v
            for v in details.get("plot_values", [])
            if v["plot_value_id"] == occurrence.plot_value_id
            and v["revision"] == occurrence.plot_revision
            and v["derivation_id"] == occurrence.derivation_id
        ]
        if len(matching) != 1:
            return {
                "status": "failed",
                "reason": "plot_value_context_mismatch",
                "derivation_id": occurrence.derivation_id,
            }
        exact = RationalExact.model_validate(matching[0]["exact"])
    if exact is None:
        return {
            "status": "unsupported",
            "reason": "derivation_not_scalar_exact",
            "derivation_id": occurrence.derivation_id,
        }
    if occurrence.presentation is None:
        return {
            "status": "not_checked",
            "reason": "numeric_presentation_missing",
            "derivation_id": occurrence.derivation_id,
        }
    expected = format_exact(exact, occurrence.presentation)
    raw, _, _ = _manuscript(occurrence.manuscript_ref, inputs)
    observed = raw[occurrence.offset : occurrence.offset + occurrence.length].decode(
        "utf-8"
    )
    return {
        "status": "passed" if observed == expected else "failed",
        "scope": "exact_derivation_and_explicit_display",
        "derivation_id": occurrence.derivation_id,
        "exact": exact.model_dump(mode="json"),
        "expected_display": expected,
        "observed_display": observed,
        "source": source["source"],
    }
