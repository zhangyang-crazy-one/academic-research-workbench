"""Actual accepted parent/journal bytes and adapter proof boundaries."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from pathlib import Path

import jsonschema
import pytest

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger.accepted_refs import (
    ResolutionContext,
    RunPrefix,
    resolve_ref,
    to_accepted_ref,
)
from arw.kernel.ledger.journal import initialize_run, replay_run
from arw.kernel.ledger.narrative import register, select
from arw.kernel.ledger.workflows import CORE_WORKFLOW
from arw.kernel.state.accepted_ref import JournalEventRef, accepted_ref_schema_documents
from arw.kernel.state.models import ArtifactAcceptanceRequest
from arw.kernel.state.provenance import ByteChunk, SourceLocator
from arw.kernel.state.research_artifact import ResearchBinding
from arw.kernel.state.research_memory import MemoryLink
from arw.kernel.state.submission import SubmissionArtifactReference
from arw.kernel.state.venue_learning import VenueSourceCapsule
from tests.unit.test_narrative import plan, project, run_request
from tests.unit.test_research_integrity import _source, _span
from tests.unit.test_venue_learning import capsule_v2_documents


def accepted_fixture(
    tmp_path: Path, raw: bytes, *, artifact_id="artifact.data", run_index=1
):
    base = tmp_path / f"fixture-{run_index}"
    base.mkdir()
    root = project(base)
    request = run_request(root)
    request = request.model_copy(
        update={
            "run_id": f"run-00000000-0000-4000-8000-{run_index:012d}",
            "workflow_definition_id": CORE_WORKFLOW.definition_id,
            "workflow_definition_sha256": CORE_WORKFLOW.sha256,
            "journal_layout": "segmented-v1",
        }
    )
    run = root / "runs/one"
    initialize_run(run, request)
    (run / "data.json").write_bytes(raw)
    command = ArtifactAcceptanceRequest(
        schema_version="1.0.0",
        run_id=request.run_id,
        event_id=f"evt-{uuid.uuid4()}",
        command_id=f"cmd-{uuid.uuid4()}",
        expected_revision=1,
        occurred_at="2026-07-13T00:01:00Z",
        actor_id="parent.runtime",
        actor_role="parent_control_plane",
        artifact_id=artifact_id,
        artifact_kind="test.data",
        media_type="application/json",
        content_path="data.json",
        content_sha256=sha256_hex(raw),
        base_revision=1,
        consumed_sha256=[],
    )
    result = RuntimeCommandService(run).accept_artifact(command)
    assert result.accepted, result.model_dump(mode="json")
    event = replay_run(run).events[-1]
    context = ResolutionContext("project-paper-tests", (run,), root)
    binding = ResearchBinding(
        binding_id="binding.data",
        artifact_id=artifact_id,
        sha256=sha256_hex(raw),
        ledger_event_id=event.event_id,
        ledger_event_sha256=event.event_sha256,
        json_pointer="",
    )
    resolution = to_accepted_ref(binding, context)
    assert resolution.status == "resolved", resolution
    return run, context, resolution.ref, event


def test_real_parent_identity_selector_and_tamper(tmp_path):
    run, context, ref, event = accepted_fixture(
        tmp_path, '{"value":0.831,"candidate":"中文稿件"}\n'.encode()
    )
    selected = resolve_ref(ref.model_copy(update={"selector": "/candidate"}), context)
    assert (
        selected.selected_value == "中文稿件"
        and selected.proven_scope == "selected_bytes"
    )
    assert selected.raw_bytes == (run / "data.json").read_bytes()
    for field in ("run_manifest_sha256", "accepting_event_sha256", "content_sha256"):
        assert (
            resolve_ref(ref.model_copy(update={field: "f" * 64}), context).status
            == "unresolved"
        )
    original = SubmissionArtifactReference(
        artifact_id=ref.artifact_id,
        manifest_sha256=event.payload.manifest_sha256,
        content_sha256=ref.content_sha256,
        accepting_event_id=ref.accepting_event_id,
    )
    result = to_accepted_ref(original, context)
    assert result.original is original and result.status == "resolved"
    assert (
        to_accepted_ref(
            original.model_copy(update={"manifest_sha256": "f" * 64}), context
        ).reason
        == "digest_mismatch"
    )
    (run / "data.json").write_bytes(b'{"value":0.832}\n')
    assert resolve_ref(ref, context).reason == "digest_mismatch"


def test_cross_run_ambiguity_and_nonaccepted_memory_and_edges(tmp_path):
    _, first, ref, event = accepted_fixture(tmp_path, b'{"value":1}\n')
    second_run, _, _, _ = accepted_fixture(tmp_path, b'{"value":2}\n', run_index=2)
    context = replace(first, run_roots=(*first.run_roots, second_run))
    binding = ResearchBinding(
        binding_id="binding.data",
        artifact_id=ref.artifact_id,
        sha256=ref.content_sha256,
        ledger_event_id=event.event_id,
        ledger_event_sha256=event.event_sha256,
        json_pointer="",
    )
    assert to_accepted_ref(binding, context).reason == "ambiguous_run"
    assert resolve_ref(ref, context).status == "resolved"
    for link in (
        MemoryLink(kind="artifact", target_id=ref.artifact_id),
        MemoryLink(
            kind="file",
            target_id="path",
            sha256=ref.content_sha256,
            event_id=event.event_id,
        ),
    ):
        assert to_accepted_ref(link, first).status == "unsupported"
    good = MemoryLink(
        kind="artifact",
        target_id=ref.artifact_id,
        sha256=ref.content_sha256,
        event_id=event.event_id,
    )
    assert to_accepted_ref(good, first).status == "resolved"
    from arw.kernel.policy.research_integrity import build_claim_evidence_link

    edge = build_claim_evidence_link(
        (_span(_source()),),
        claim_link_id="link.claim",
        claim_id="claim.paper",
        claim_sha256="a" * 64,
        relation="contradicts",
    )
    assert to_accepted_ref(edge, first).reason == "edge_not_ref"


def test_locator_selected_digest_activity_and_original_validator(tmp_path):
    raw = "证据\n全文\n".encode()
    run, context, ref, event = accepted_fixture(tmp_path, raw)
    locator = SourceLocator(
        schema_version="arw.source-locator.v1",
        source_artifact_id=ref.artifact_id,
        source_sha256=ref.content_sha256,
        source_event_id=event.event_id,
        source_event_sha256=event.event_sha256,
        producing_activity_id="activity.extraction",
        location=ByteChunk(kind="byte_chunk", start=0, end=7),
        quote_sha256=sha256_hex(raw[:7]),
    )
    result = to_accepted_ref(locator, context)
    assert result.status == "resolved" and result.original is locator
    assert (
        result.proven_scope == "selected_bytes"
        and result.ref.selected_sha256 == locator.quote_sha256
    )
    assert result.ref.producing_activity_id == locator.producing_activity_id
    assert result.selected_value == raw[:7]
    assert (
        to_accepted_ref(
            locator.model_copy(update={"quote_sha256": "f" * 64}), context
        ).reason
        == "digest_mismatch"
    )
    forged = result.ref.model_copy(update={"producing_activity_id": "activity.other"})
    assert resolve_ref(forged, context).reason == "digest_mismatch"
    (run / "data.json").unlink()
    (run / "data.json").symlink_to(tmp_path / "outside")
    assert resolve_ref(result.ref, context).status == "unresolved"


def test_evidence_span_requires_acceptance_and_preserves_metadata_scope(tmp_path):
    source = _source()
    span = _span(source)
    _, context, _, _ = accepted_fixture(
        tmp_path, canonical_json_bytes(source.model_dump(mode="json"))
    )
    result = to_accepted_ref(span, context)
    assert result.status == "resolved" and result.original is span
    assert result.proven_scope == "metadata_only"
    assert (
        to_accepted_ref(
            span.model_copy(update={"source_sha256": "f" * 64}), context
        ).status
        == "unresolved"
    )
    assert (
        to_accepted_ref(span, replace(context, run_roots=())).reason
        == "no_accepting_event"
    )


def test_capsule_verifies_structure_without_missing_original_pdf(tmp_path):
    capsule, _, _ = capsule_v2_documents()
    _, context, ref, _ = accepted_fixture(tmp_path, canonical_json_bytes(capsule))
    result = to_accepted_ref(capsule, context)
    assert result.status == "resolved" and result.proven_scope == "structural_capsule"
    assert result.original is capsule
    assert resolve_ref(ref, context).proven_scope == "structural_capsule"
    assert not list(tmp_path.rglob("*.pdf"))
    bad = {**capsule, "title": "tampered"}
    assert to_accepted_ref(bad, context).status == "unresolved"
    assert VenueSourceCapsule.model_validate_json(canonical_json_bytes(capsule))


def test_actual_journal_payload_and_hash_tamper(tmp_path):
    root = project(tmp_path)
    register(root)
    selected = select(root, plan())
    context = ResolutionContext("project-paper-tests", (), root)
    ref = JournalEventRef(
        project_id=context.project_id,
        sequence=2,
        event_sha256=selected.sha256,
        payload_selector="/plan/route",
    )
    resolved = resolve_ref(ref, context)
    assert resolved.status == "resolved" and resolved.selected_value == "method_rq"
    assert resolved.proven_scope == "metadata_only"
    assert (
        resolve_ref(ref.model_copy(update={"event_sha256": "f" * 64}), context).reason
        == "digest_mismatch"
    )
    history = root / ".arw/narrative/events.jsonl"
    history.write_bytes(history.read_bytes().replace(b"method_rq", b"tampered"))
    assert resolve_ref(ref, context).status == "unresolved"


def test_fixed_run_prefix_survives_unrelated_torn_tail(tmp_path):
    run, context, ref, _ = accepted_fixture(tmp_path, b'{"value":1}\n')
    replay = replay_run(run)
    historical = replace(
        context,
        run_prefixes=(
            RunPrefix(
                ref.run_id,
                replay.revision,
                replay.last_event_sha256,
                ref.run_manifest_sha256,
            ),
        ),
    )
    (run / replay.segments[-1].relative_path).open("ab").write(b"{broken tail")
    assert resolve_ref(ref, historical).status == "resolved"
    assert (
        resolve_ref(
            ref,
            replace(
                historical,
                run_prefixes=(
                    RunPrefix(
                        ref.run_id,
                        1,
                        replay.events[0].event_sha256,
                        ref.run_manifest_sha256,
                    ),
                ),
            ),
        ).reason
        == "no_accepting_event"
    )


def test_reference_schemas_and_strict_boundaries():
    for name, schema in accepted_ref_schema_documents().items():
        jsonschema.Draft202012Validator.check_schema(schema)
        assert (
            json.loads(
                (Path(__file__).resolve().parents[2] / "schemas/v1" / name).read_bytes()
            )
            == schema
        )
    with pytest.raises(ValueError):
        JournalEventRef(project_id="project.tests", sequence="1", event_sha256="a" * 64)
