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
    _replay_unlocked,
    _read_manifest,
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
    attestation = DeclaredAttestation.model_validate(event["payload"])
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
    root: Path, run_roots, fixed: SnapshotManifest | None = None
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
                replay = replay_run_prefix(
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
        return Inputs(root, vector, events, runs)
    except ClaimGraphError:
        raise
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        raise ClaimGraphError(
            "corrupt_log", "snapshot prefix cannot be validated"
        ) from error


def _context(inputs: Inputs):
    from arw.kernel.ledger.accepted_refs import (
        ResolutionContext,
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
    )


def _closure(inputs: Inputs) -> None:
    """Every explicitly recorded cross-log reference belongs to this vector."""
    parent_events = {
        run_id: {e.event_id: e for e in item[2].events}
        for run_id, item in inputs.runs.items()
    }
    all_events = [e for item in inputs.runs.values() for e in item[2].events]
    journal_events = {e["sequence"]: e for e in inputs.journal}

    def walk(value, referring_sequence):
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
                walk(child, referring_sequence)
        elif isinstance(value, (list, tuple)):
            for child in value:
                walk(child, referring_sequence)

    for event in inputs.journal:
        walk(event["payload"], event["sequence"])


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
        if binding.node_kind == "Figure":
            item["figure_adapter"] = {
                "status": "unsupported",
                "reason": "result_plot_adapter_pending",
            }
        evidence.append(item)
    dependency = sha256_hex(
        canonical_json_bytes(
            {
                "evidence": [{k: v for k, v in item.items()} for item in evidence],
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
    record: ClaimRegistration, dependency: str, inputs: Inputs
) -> list[dict]:
    items = []
    for event in inputs.journal:
        if (
            event["kind"] != "claim.attested"
            or event["payload"]["claim_id"] != record.claim.claim_id
        ):
            continue
        att = DeclaredAttestation.model_validate(event["payload"])
        # Independently reconstruct the exact predecessor vector; declarations
        # do not assert permission and never acquire an authenticated label.
        historical = _read_inputs(
            inputs.root,
            tuple(inputs.runs[r.run_id][0] for r in att.snapshot_manifest.runs),
            att.snapshot_manifest,
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
        items.append(
            {
                "status": status,
                "authority": att.authority.model_dump(mode="json"),
                "historical_authorized": False,
                "current_applicability": status,
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


def _project(inputs: Inputs) -> dict:
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
                    node["figure_adapter"] = {
                        "status": "unsupported",
                        "reason": "result_plot_adapter_pending",
                    }
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
    claims = []
    for claim_id, record in sorted(registrations.items()):
        evidence, dependency = _evaluate_registration(record, inputs)
        attestations = _attestations(record, dependency, inputs)
        for occurrence in record.occurrences:
            _check_occurrence(occurrence, inputs)
            registered_occurrences.add(occurrence.occurrence_id)
            discovered[occurrence.occurrence_id] = occurrence
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
    for key, occurrence in sorted(discovered.items()):
        nodes.append(
            {
                "id": "occurrence:" + key,
                "node_kind": "Occurrence",
                **occurrence.model_dump(mode="json"),
                "registration": "registered"
                if key in registered_occurrences
                else "unknown",
            }
        )
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
        if not any(a["status"] == "declared" for a in claim["attestations"]):
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
            "reason": "authenticated_confirmation_contract_pending",
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
) -> dict:
    """Rebuild a graph without writes; current views optimistically compare vectors."""
    if hard_check:
        raise ClaimGraphError(
            "hard_check_unavailable", "hard checks require authenticated confirmations"
        )
    fixed = SnapshotManifest.model_validate(as_of) if isinstance(as_of, dict) else as_of
    before = _read_inputs(project_root, run_roots, fixed)
    if expected_head is not None and expected_head != before.manifest.sha256:
        raise ClaimGraphError("stale", "expected snapshot manifest digest differs")
    result = _project(before)
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
