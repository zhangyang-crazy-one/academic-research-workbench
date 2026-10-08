"""Read-only, frozen narrative/venue fit observation."""

from __future__ import annotations

import base64
import io
import os
import re
import stat
import tempfile
from datetime import date, timedelta
from pathlib import Path, PurePosixPath

from arw.kernel.core.canonical import (
    canonical_event_bytes,
    canonical_json_bytes,
    sha256_hex,
    strict_json_loads,
)
from arw.kernel.ledger.journal import replay_run
from arw.kernel.ledger.manifests import load_artifact_manifest
from arw.kernel.ledger.narrative import current as current_narrative
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.policy.narrative_realization import (
    STAGE_KINDS,
    NarrativeRealizationError,
    validate_realization,
)
from arw.kernel.state.models import (
    ArtifactAcceptedPayload,
    ArtifactManifest,
    CanonicalEvent,
    RunManifest,
    RuntimeCommandRequest,
)
from arw.kernel.state.narrative_fit import (
    FitEvidence,
    FitHeuristic,
    FitJudgment,
    FitPredicate,
    FitReport,
    FitSnapshot,
    PublicFitSnapshot,
    VenueFitProfile,
    WritingCandidateReceiptBinding,
)
from arw.kernel.state.narrative_realization import NarrativeRealization

from .preservation import validate_citation_bindings


class NarrativeFitError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _read_local(path: Path, limit: int) -> bytes:
    path = Path(path)
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise NarrativeFitError("unsafe_input", "input path contains a symlink")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise NarrativeFitError(
                "input_too_large", "input is not a bounded regular file"
            )
        chunks = []
        total = 0
        while total <= limit:
            block = os.read(descriptor, min(65536, limit + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
        after = os.fstat(descriptor)
        if (
            total > limit
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
        ):
            raise NarrativeFitError("input_changed", "input changed or exceeded budget")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _decode(value: str, expected: str, label: str) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except ValueError as error:
        raise NarrativeFitError(
            "invalid_frozen_snapshot", f"{label} has invalid base64"
        ) from error
    if sha256_hex(raw) != expected:
        raise NarrativeFitError("frozen_content_mismatch", f"{label} digest differs")
    return raw


def _accepted(root: Path, events, artifact_id: str):
    matches = [
        e
        for e in events
        if e.event_type == "artifact.accepted" and e.payload.artifact_id == artifact_id
    ]
    if len(matches) != 1:
        raise NarrativeFitError(
            "accepted_artifact_missing", f"{artifact_id} is not uniquely accepted"
        )
    event = matches[0]
    manifest = load_artifact_manifest(root, event.payload.manifest_sha256)
    raw = read_retained_bytes(root, manifest.content_path, max_bytes=8_388_608)
    if sha256_hex(raw) != manifest.content_sha256:
        raise NarrativeFitError(
            "accepted_content_mismatch", f"{artifact_id} content changed"
        )
    return event, manifest, raw


def _pdf_pages(raw: bytes) -> int:
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise NarrativeFitError(
            "pdf_page_count_unavailable", "actual accepted PDF could not be counted"
        ) from error
    try:
        return len(PdfReader(io.BytesIO(raw)).pages)
    except Exception as error:  # pypdf raises several unrelated parser errors.
        raise NarrativeFitError(
            "pdf_page_count_unavailable", "actual accepted PDF could not be counted"
        ) from error


def _core_digest(snapshot: FitSnapshot | PublicFitSnapshot) -> str:
    body = snapshot.model_dump(mode="json")
    if isinstance(snapshot, FitSnapshot):
        body["judgment"] = None
    return sha256_hex(canonical_json_bytes(body))


def _event_digest(event) -> str:
    body = event.model_dump(mode="json")
    if event.actor_role is None:
        body.pop("actor_role")
    return sha256_hex(canonical_event_bytes(body))


def _accepted_payload(event: CanonicalEvent) -> ArtifactAcceptedPayload:
    if event.event_type != "artifact.accepted" or not isinstance(
        event.payload, ArtifactAcceptedPayload
    ):
        raise NarrativeFitError(
            "frozen_content_mismatch", "event is not an accepted artifact"
        )
    return event.payload


def _validate_writing_candidate_receipt(
    root: Path,
    events,
    receipt_raw: bytes,
    manuscript: bytes,
    realization_raw: bytes,
    event: CanonicalEvent,
    binding: WritingCandidateReceiptBinding,
    narrative,
    run_id: str,
    artifact_id: str,
) -> dict:
    """Apply one exact receipt, candidate and provenance check at capture/replay."""
    try:
        run_raw = _decode(
            binding.run_manifest_base64, binding.run_manifest_sha256, "run manifest"
        )
        run = RunManifest.model_validate(strict_json_loads(run_raw))
        manifest_raw = _decode(
            binding.accepted_manifest_base64,
            binding.accepted_manifest_sha256,
            "writing manifest",
        )
        manifest = ArtifactManifest.model_validate(strict_json_loads(manifest_raw))
        payload = _accepted_payload(event)
        if (
            run.run_id != run_id
            or run.task_kind != "paper"
            or run.narrative_binding is None
            or run.narrative_binding.project_id != narrative.project_id
            or run.narrative_binding.initial_version > narrative.version
            or (
                run.narrative_binding.initial_version == narrative.version
                and run.narrative_binding.initial_sha256 != narrative.sha256
            )
            or event.run_id != run_id
            or _event_digest(event) != event.event_sha256
            or event.event_id != binding.accepted_event_id
            or event.event_sha256 != binding.accepted_event_sha256
            or payload.artifact_id != artifact_id
            or payload.manifest_sha256 != binding.accepted_manifest_sha256
            or payload.artifact_sha256 != binding.receipt_sha256
            or manifest.run_id != run_id
            or manifest.artifact_id != artifact_id
            or manifest.artifact_kind != "writing-derived"
            or manifest.media_type != "application/json"
            or manifest.content_sha256 != binding.receipt_sha256
            or sha256_hex(receipt_raw) != binding.receipt_sha256
        ):
            raise ValueError("accepted writing provenance differs")
        receipt = strict_json_loads(receipt_raw)
        if not isinstance(receipt, dict) or (
            receipt.get("schema_version") != "arw.writing-candidate.v1"
            or receipt.get("accepted") is not True
            or receipt.get("disposition") != "accepted_after_human_review"
            or receipt.get("controls_effective") is not True
            or not isinstance(receipt.get("candidate"), str)
            or not isinstance(receipt.get("source"), str)
            or not isinstance(receipt.get("verification"), dict)
            or not isinstance(receipt.get("proposal"), dict)
            or not isinstance(receipt.get("narrative_realization"), dict)
        ):
            raise ValueError("accepted writing receipt is incomplete")
        candidate = receipt["candidate"].encode("utf-8")
        source = receipt["source"].encode("utf-8")
        if (
            candidate != manuscript
            or sha256_hex(candidate) != binding.candidate_sha256
            or receipt.get("candidate_sha256") != binding.candidate_sha256
            or receipt.get("candidate_path") != binding.candidate_path
            or binding.candidate_path
            != f"writing/candidate/{binding.candidate_sha256}.md"
            or sha256_hex(source) != receipt.get("source_sha256")
            or sha256_hex(canonical_json_bytes(receipt["verification"]))
            != receipt.get("verification_sha256")
            or sha256_hex(canonical_json_bytes(receipt["proposal"]))
            != receipt.get("proposal_sha256")
        ):
            raise ValueError("writing text or verification digest differs")
        realization = NarrativeRealization.model_validate(
            receipt["narrative_realization"]
        )
        nested_raw = canonical_json_bytes(receipt["narrative_realization"])
        request = RuntimeCommandRequest.model_validate(receipt["request_identity"])
        if (
            nested_raw != realization_raw
            or sha256_hex(nested_raw) != binding.realization_sha256
            or realization.stage != "draft"
            or realization.source_path != binding.candidate_path
            or realization.source_sha256 != binding.candidate_sha256
            or realization.narrative_sha256 != narrative.sha256
            or receipt.get("narrative_binding") != narrative.model_dump(mode="json")
            or receipt["proposal"].get("narrative_sha256") != narrative.sha256
            or request.run_id != run_id
            or request.event_id != event.event_id
            or request.command_id != event.command_id
            or manifest.base_revision != request.expected_revision
            or manifest.producer_id != request.actor_id
        ):
            raise ValueError("writing realization or run identity differs")
        validate_citation_bindings(
            receipt["verification"], receipt["source"], receipt["candidate"]
        )
        for name, expected_kind in (
            ("source_binding", None),
            ("review_binding", "writing-human-review"),
        ):
            reference = receipt.get(name)
            if not isinstance(reference, dict) or not isinstance(
                reference.get("artifact_id"), str
            ):
                raise TypeError(f"{name} is missing")
            source_event, source_manifest, source_raw = _accepted(
                root, events, reference["artifact_id"]
            )
            if (
                source_event.run_id != run_id
                or source_manifest.run_id != run_id
                or reference.get("event_id") != source_event.event_id
                or reference.get("event_sha256") != source_event.event_sha256
                or reference.get("manifest_sha256")
                != source_event.payload.manifest_sha256
                or reference.get("artifact_kind") != source_manifest.artifact_kind
                or (expected_kind is not None and source_manifest.artifact_kind != expected_kind)
            ):
                raise ValueError(f"{name} differs from accepted source")
            if name == "source_binding":
                source_digest = sha256_hex(source_raw)
                if source_manifest.artifact_kind in {
                    "narrative-draft", "paper-draft", "draft", "manuscript", "paper-manuscript"
                }:
                    prior = NarrativeRealization.model_validate(strict_json_loads(source_raw))
                    source_digest = prior.source_sha256
                elif source_manifest.artifact_kind == "writing-derived":
                    prior = strict_json_loads(source_raw)
                    if (
                        not isinstance(prior, dict)
                        or not isinstance(prior.get("source"), str)
                        or not isinstance(prior.get("candidate"), str)
                        or not isinstance(prior.get("verification"), dict)
                        or sha256_hex(prior["candidate"].encode("utf-8"))
                        != prior.get("candidate_sha256")
                    ):
                        raise ValueError("prior writing source is invalid")
                    validate_citation_bindings(
                        prior["verification"], prior["source"], prior["candidate"]
                    )
                    source_digest = sha256_hex(prior["candidate"].encode("utf-8"))
                if reference.get("sha256") != source_digest or source_digest != receipt["source_sha256"]:
                    raise ValueError("writing source digest differs")
            if name == "review_binding":
                if reference.get("sha256") != sha256_hex(source_raw):
                    raise ValueError("writing review digest differs")
                review = strict_json_loads(source_raw)
                if not isinstance(review, dict) or any(
                    review.get(key) != value
                    for key, value in {
                        "schema_version": "arw.writing-review.v1",
                        "decision": "APPROVED",
                        "source_sha256": receipt["source_sha256"],
                        "candidate_sha256": binding.candidate_sha256,
                        "proposal_sha256": receipt["proposal_sha256"],
                        "verification_sha256": receipt["verification_sha256"],
                        "reviewed_dimensions": receipt["verification"].get("unresolved_dimensions"),
                    }.items()
                ) or not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip() or not isinstance(review.get("rationale"), str) or not review["rationale"].strip():
                    raise ValueError("writing review is not bound to this candidate")
        return receipt
    except (KeyError, TypeError, ValueError, OSError, RuntimeError) as error:
        raise NarrativeFitError(
            "writing_receipt_invalid", "accepted writing receipt binding is invalid"
        ) from error


def _proof(root: Path, events, artifact_id: str) -> FitEvidence:
    event, _, raw = _accepted(root, events, artifact_id)
    manifest_raw = read_retained_bytes(
        root,
        f"manifests/artifacts/sha256/{event.payload.manifest_sha256}.json",
        max_bytes=262144,
    )
    if sha256_hex(manifest_raw) != event.payload.manifest_sha256:
        raise NarrativeFitError("manifest_mismatch", "accepted manifest digest differs")
    return FitEvidence(
        event=event,
        manifest_base64=base64.b64encode(manifest_raw).decode("ascii"),
        content_base64=base64.b64encode(raw).decode("ascii"),
    )


def _bundled_profile(target: str) -> bytes:
    relative = Path(
        "skills/academic-research-suite/codex/references/annual_venue_profiles.json"
    )
    candidates = (
        [Path(os.environ["ARW_PLUGIN_ROOT"])]
        if os.environ.get("ARW_PLUGIN_ROOT")
        else []
    )
    candidates.extend(Path(__file__).resolve().parents)
    bundle_path = next(
        (root / relative for root in candidates if (root / relative).is_file()), None
    )
    if bundle_path is None:
        raise NarrativeFitError(
            "bundled_profile_missing",
            "bundled venue registry is unavailable; pass --profile",
        )
    raw = _read_local(bundle_path, 2_097_152)
    document = strict_json_loads(raw)
    venues = document.get("venues", [])
    selected = next((item for item in venues if item.get("id") == target), None)
    if selected is None:
        known = ", ".join(sorted(item["id"] for item in venues if "id" in item))
        raise NarrativeFitError(
            "unknown_target",
            f"target is absent from bundled venue registry; known: {known}",
        )
    verified = date.fromisoformat(document["verified_on"])
    review_due = verified + timedelta(
        days=document["refresh_policy"]["max_age_days_for_planning"]
    )
    digest = sha256_hex(raw)
    rules = []

    def add_rules(scope, index, item):
        for position, statement in enumerate(item.get("hard_gates", [])):
            rules.append(
                {
                    "rule_id": f"official.bundle.{scope}.{position + 1}",
                    "statement": statement,
                    "source_url": "bundle:skills/academic-research-suite/codex/references/annual_venue_profiles.json",
                    "source_sha256": digest,
                    "source_locator": f"/{scope}/{index}/hard_gates/{position}",
                }
            )

    add_rules("venues", venues.index(selected), selected)
    review_id = selected.get("review_system_id")
    for index, system in enumerate(document.get("review_systems", [])):
        if system.get("id") == review_id:
            add_rules("review_systems", index, system)
    payload = {
        "schema_version": "arw.venue-fit-profile.v1",
        "venue_id": target,
        "version": f"bundle:{document['schema_version']}:{document['verified_on']}:{digest[:12]}",
        "verified_on": verified.isoformat(),
        "review_due": review_due.isoformat(),
        "official_hard_requirements": rules,
        "structural_expectations": [],
    }
    return canonical_json_bytes(payload)


def _revalidate(
    snapshot: FitSnapshot, manuscript: bytes, accepted: bytes, realization: bytes
) -> None:
    if _event_digest(snapshot.accepted_event) != snapshot.accepted_event_sha256:
        raise NarrativeFitError(
            "frozen_content_mismatch", "accepted event digest differs"
        )
    accepted_payload = _accepted_payload(snapshot.accepted_event)
    if (
        accepted_payload.artifact_id != snapshot.manuscript_artifact_id
        or accepted_payload.artifact_sha256 != snapshot.accepted_content_sha256
    ):
        raise NarrativeFitError(
            "frozen_content_mismatch", "accepted event binding differs"
        )
    with tempfile.TemporaryDirectory(prefix="arw-fit-replay-") as temporary:
        root = Path(temporary)
        events = []
        for proof in snapshot.evidence:
            event = proof.event
            if _event_digest(event) != event.event_sha256:
                raise NarrativeFitError(
                    "frozen_content_mismatch", "evidence event digest differs"
                )
            payload = _accepted_payload(event)
            digest = payload.manifest_sha256
            manifest_raw = _decode(proof.manifest_base64, digest, "evidence manifest")
            manifest = ArtifactManifest.model_validate(strict_json_loads(manifest_raw))
            if (
                manifest.artifact_id != payload.artifact_id
                or manifest.content_sha256 != payload.artifact_sha256
            ):
                raise NarrativeFitError(
                    "frozen_content_mismatch", "evidence manifest binding differs"
                )
            relative = manifest.content_path
            if (
                PurePosixPath(relative).is_absolute()
                or "\\" in relative
                or any(part in {"", ".", ".."} for part in relative.split("/"))
                or relative.startswith("manifests/")
            ):
                raise NarrativeFitError(
                    "frozen_content_mismatch", "evidence content path is unsafe"
                )
            content = _decode(
                proof.content_base64, manifest.content_sha256, "evidence content"
            )
            manifest_path = root / "manifests/artifacts/sha256" / f"{digest}.json"
            content_path = root / manifest.content_path
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            content_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_bytes(manifest_raw)
            content_path.write_bytes(content)
            events.append(event)
        if snapshot.accepted_binding_kind == "writing_candidate_receipt":
            assert snapshot.writing_candidate_binding is not None
            _validate_writing_candidate_receipt(
                root,
                tuple(events),
                accepted,
                manuscript,
                realization,
                snapshot.accepted_event,
                snapshot.writing_candidate_binding,
                snapshot.narrative,
                snapshot.run_id,
                snapshot.manuscript_artifact_id,
            )
        observed = _validation(
            root, snapshot.realization, snapshot.narrative, tuple(events), manuscript
        )
    if observed != snapshot.validation:
        raise NarrativeFitError(
            "frozen_validation_mismatch", "structural result differs from frozen result"
        )


def _check_snapshot(snapshot: FitSnapshot) -> bytes:
    manuscript = _decode(
        snapshot.manuscript_source_base64,
        snapshot.manuscript_source_sha256,
        "manuscript",
    )
    accepted = _decode(
        snapshot.accepted_content_base64,
        snapshot.accepted_content_sha256,
        "accepted content",
    )
    realization = base64.b64decode(snapshot.realization_base64, validate=True)
    profile = _decode(snapshot.profile_base64, snapshot.profile_sha256, "venue profile")
    if (
        NarrativeRealization.model_validate(strict_json_loads(realization))
        != snapshot.realization
    ):
        raise NarrativeFitError("frozen_content_mismatch", "realization body differs")
    if (
        snapshot.accepted_binding_kind == "realization_sidecar"
        and accepted != realization
    ):
        raise NarrativeFitError(
            "frozen_content_mismatch", "accepted realization differs"
        )
    if snapshot.accepted_binding_kind == "manuscript_source" and accepted != manuscript:
        raise NarrativeFitError(
            "frozen_content_mismatch", "accepted manuscript differs"
        )
    strict_json_loads(profile)
    if VenueFitProfile.model_validate_json(profile) != snapshot.profile:
        raise NarrativeFitError("frozen_content_mismatch", "profile body differs")
    if (
        sha256_hex(
            canonical_json_bytes(
                [h.model_dump(mode="json") for h in snapshot.heuristics]
            )
        )
        != snapshot.heuristic_set_sha256
    ):
        raise NarrativeFitError("frozen_content_mismatch", "heuristic set differs")
    for heuristic in snapshot.heuristics:
        item = heuristic.inspected_record
        if (
            sha256_hex(canonical_json_bytes(item)) != heuristic.inspected_record_sha256
            or item.get("status") != "promoted"
            or item.get("accepted_ledger_event_id") != heuristic.promotion_event_id
            or item.get("heuristic_id", heuristic.heuristic_id)
            != heuristic.heuristic_id
            or item.get("venue_applicability")
            != {"venue_id": heuristic.venue_id, "domain_id": heuristic.domain_id}
        ):
            raise NarrativeFitError(
                "frozen_content_mismatch", "promoted heuristic record differs"
            )
        if (
            item.get("scope") != heuristic.approved_scope
            or item.get("proposed_action") != heuristic.suggested_action
        ):
            raise NarrativeFitError(
                "frozen_content_mismatch", "promoted heuristic display fields differ"
            )
        if heuristic.approved_scope == "run" and item.get("run_id") != snapshot.run_id:
            raise NarrativeFitError(
                "heuristic_not_applicable",
                "run-scoped heuristic belongs to another run",
            )
    if snapshot.pdf_base64 is not None:
        assert snapshot.pdf_sha256 is not None
        pdf = _decode(snapshot.pdf_base64, snapshot.pdf_sha256, "accepted PDF")
        if _pdf_pages(pdf) != snapshot.pdf_page_count:
            raise NarrativeFitError(
                "frozen_content_mismatch", "actual PDF page count differs"
            )
    if snapshot.judgment and snapshot.judgment.input_sha256 != _core_digest(snapshot):
        raise NarrativeFitError(
            "judgment_input_mismatch", "judgment does not bind frozen inputs"
        )
    try:
        manuscript.decode("utf-8")
    except UnicodeError as error:
        raise NarrativeFitError(
            "invalid_frozen_snapshot", "manuscript is not UTF-8"
        ) from error
    _revalidate(snapshot, manuscript, accepted, realization)
    return manuscript


def _validation(root, realization, narrative, events, manuscript):
    try:
        return validate_realization(
            root, realization, narrative, events=events, source_bytes=manuscript,
            # Fit inspects already accepted outputs, retaining v1 report replay.
            # New output admission still uses the default current policy.
            validation_policy="structural-v1",
        )
    except NarrativeRealizationError as error:
        return {
            "mechanical_status": "FAIL",
            "semantic_status": "UNKNOWN",
            "reason_code": error.code,
            "human_review_reason_codes": [],
        }


_LATEX_HEADING = re.compile(
    r"\\(?:part|chapter|(?:sub){0,2}section|(?:sub)?paragraph)\*?"
    r"[ \t]*(?:\[[^\]\n]*\])?[ \t]*\{([^{}\n]*)\}"
)


def _source_format(source_path: str) -> str:
    suffix = Path(source_path).suffix.casefold()
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix in {".tex", ".ltx"}:
        return "latex"
    return "text"


def _predicate(
    predicate: FitPredicate | None,
    text: str,
    pages: int | None,
    source_format: str = "markdown",
) -> dict:
    if predicate is None:
        return {"status": "unknown", "reason": "no_reviewed_typed_predicate"}
    if predicate.kind == "pdf_page_count_at_most":
        if pages is None:
            return {"status": "not_evaluated", "reason": "actual_pdf_required"}
        assert predicate.limit is not None
        return {
            "status": "met" if pages <= predicate.limit else "not_met",
            "observed_page_count": pages,
        }
    assert predicate.value is not None
    if predicate.kind == "heading_present" and source_format == "latex":
        headings = [m.group(1).strip() for m in _LATEX_HEADING.finditer(text)]
        return {
            "status": "met" if predicate.value in headings else "not_met",
            "bounded_to": "latex_sectioning_commands",
        }
    if predicate.kind == "heading_present" and source_format != "markdown":
        return {"status": "not_evaluated", "reason": "heading_format_unsupported"}
    if predicate.kind == "heading_present":
        headings = [
            m.group(1).strip()
            for m in re.finditer(
                r"^ {0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", text, re.MULTILINE
            )
        ]
        present = predicate.value in headings
        return {
            "status": "met" if present else "not_met",
            "bounded_to": "markdown_headings",
        }
    if predicate.kind == "literal_present":
        return {
            "status": "met" if predicate.value in text else "not_met",
            "bounded_to": "exact_utf8_literal",
        }
    # A marker search cannot establish comprehensive anonymity.
    return {
        "status": "bounded_observation",
        "listed_marker_present": predicate.value in text,
        "reason": "anonymity_not_comprehensively_evaluated",
    }


def _public_proof(proof: FitEvidence, run_id: str) -> tuple[ArtifactManifest, bytes]:
    event = proof.event
    payload = _accepted_payload(event)
    if event.run_id != run_id or _event_digest(event) != event.event_sha256:
        raise NarrativeFitError(
            "frozen_content_mismatch", "public accepted event binding differs"
        )
    raw = _decode(proof.manifest_base64, payload.manifest_sha256, "public manifest")
    manifest = ArtifactManifest.model_validate(strict_json_loads(raw))
    if (
        manifest.run_id != run_id
        or manifest.artifact_id != payload.artifact_id
        or manifest.content_sha256 != payload.artifact_sha256
    ):
        raise NarrativeFitError(
            "frozen_content_mismatch", "public manifest binding differs"
        )
    return manifest, _decode(
        proof.content_base64, manifest.content_sha256, "public evidence"
    )


def _public_input(manifest: ArtifactManifest, raw: bytes):
    if manifest.media_type == "application/pdf":
        return "pdf", None
    if manifest.media_type == "application/json":
        from arw.kernel.state.venue_learning import VenueSourceCapsule

        strict_json_loads(raw)
        return "source_capsule", VenueSourceCapsule.model_validate_json(raw)
    if manifest.media_type not in {"text/markdown", "text/plain"}:
        raise NarrativeFitError(
            "public_source_unsupported",
            "public fit needs text, PDF or a typed source capsule",
        )
    raw.decode("utf-8")
    return "markdown" if manifest.media_type == "text/markdown" else "text", None


def _check_public_snapshot(snapshot: PublicFitSnapshot):
    manifest, raw = _public_proof(snapshot.manuscript, snapshot.run_id)
    if manifest.artifact_id != snapshot.manuscript_artifact_id:
        raise NarrativeFitError(
            "frozen_content_mismatch", "public manuscript artifact differs"
        )
    kind, capsule = _public_input(manifest, raw)
    if kind != snapshot.input_kind:
        raise NarrativeFitError("frozen_content_mismatch", "public input kind differs")
    profile = _decode(snapshot.profile_base64, snapshot.profile_sha256, "venue profile")
    strict_json_loads(profile)
    if VenueFitProfile.model_validate_json(profile) != snapshot.profile:
        raise NarrativeFitError("frozen_content_mismatch", "profile body differs")
    if snapshot.pdf:
        pdf_manifest, pdf_raw = _public_proof(snapshot.pdf, snapshot.run_id)
        if (
            pdf_manifest.media_type != "application/pdf"
            or _pdf_pages(pdf_raw) != snapshot.pdf_page_count
        ):
            raise NarrativeFitError(
                "frozen_content_mismatch", "actual public PDF differs"
            )
        if capsule and pdf_manifest.content_sha256 != capsule.provenance.pdf_sha256:
            raise NarrativeFitError(
                "frozen_content_mismatch",
                "accepted PDF differs from capsule reviewed PDF",
            )
        if kind == "pdf" and pdf_manifest.content_sha256 != manifest.content_sha256:
            raise NarrativeFitError(
                "frozen_content_mismatch", "public PDF source differs"
            )
    elif kind == "pdf":
        raise NarrativeFitError(
            "frozen_content_mismatch", "public PDF source needs its actual PDF proof"
        )
    return manifest, raw, capsule


def _freeze_public(run_root, target, artifact_id, profile_path, *, pdf_artifact_id):
    root = Path(run_root).resolve(strict=True)
    state = replay_run(root)
    if state.recovery_health != "healthy":
        raise NarrativeFitError(
            "run_unhealthy", "canonical journal has an unresolved recovery tail"
        )
    run_manifest = RunManifest.model_validate(
        strict_json_loads(
            read_retained_bytes(root, "run-manifest.json", max_bytes=65536)
        )
    )
    if run_manifest.narrative_binding is not None:
        raise NarrativeFitError(
            "selected_narrative_present",
            "use the selected narrative fit path for a bound paper run",
        )
    if not artifact_id:
        raise NarrativeFitError(
            "public_manuscript_required",
            "public fit needs an explicit accepted manuscript artifact ID",
        )
    proof = _proof(root, state.events, artifact_id)
    manifest, raw = _public_proof(proof, state.run_id)
    kind, _ = _public_input(manifest, raw)
    if kind == "pdf" and pdf_artifact_id and pdf_artifact_id != artifact_id:
        raise NarrativeFitError(
            "public_pdf_mismatch", "a PDF source must use the same PDF artifact"
        )
    pdf_id = artifact_id if kind == "pdf" else pdf_artifact_id
    pdf_proof = _proof(root, state.events, pdf_id) if pdf_id else None
    pages = None
    if pdf_proof:
        pdf_manifest, pdf_raw = _public_proof(pdf_proof, state.run_id)
        if pdf_manifest.media_type != "application/pdf":
            raise NarrativeFitError(
                "pdf_required", "page count needs accepted PDF bytes"
            )
        pages = _pdf_pages(pdf_raw)
    profile_raw = (
        _read_local(profile_path, 262144) if profile_path else _bundled_profile(target)
    )
    strict_json_loads(profile_raw)
    profile = VenueFitProfile.model_validate_json(profile_raw)
    if profile.venue_id != target:
        raise NarrativeFitError(
            "target_mismatch", "profile venue differs from --target"
        )
    snapshot = PublicFitSnapshot(
        run_id=state.run_id,
        manuscript_artifact_id=artifact_id,
        manuscript=proof,
        input_kind=kind,
        profile=profile,
        profile_sha256=sha256_hex(profile_raw),
        profile_base64=base64.b64encode(profile_raw).decode("ascii"),
        pdf=pdf_proof,
        pdf_page_count=pages,
    )
    if len(canonical_json_bytes(snapshot.model_dump(mode="json"))) > 64 * 1024 * 1024:
        raise NarrativeFitError("snapshot_too_large", "frozen snapshot exceeds 64 MiB")
    _check_public_snapshot(snapshot)
    return snapshot


def _public_report(snapshot: PublicFitSnapshot) -> dict:
    manifest, raw, capsule = _check_public_snapshot(snapshot)

    def rule_result(rule):
        predicate = rule.predicate
        if (
            predicate
            and predicate.kind != "pdf_page_count_at_most"
            and snapshot.input_kind not in {"markdown", "text"}
        ):
            assessment = {
                "status": "not_evaluated",
                "reason": "actual_manuscript_text_required",
            }
        elif (
            predicate
            and predicate.kind == "heading_present"
            and snapshot.input_kind != "markdown"
        ):
            assessment = {
                "status": "not_evaluated",
                "reason": "actual_markdown_source_required",
            }
        else:
            text = (
                raw.decode("utf-8")
                if snapshot.input_kind in {"markdown", "text"}
                else ""
            )
            assessment = _predicate(predicate, text, snapshot.pdf_page_count)
        result = {
            "rule_id": rule.rule_id,
            "statement": rule.statement,
            "provenance": {
                "source_url": rule.source_url,
                "source_sha256": rule.source_sha256,
                "source_locator": rule.source_locator,
                "reviewed_by": rule.reviewed_by,
            },
            "assessment": assessment,
        }
        if assessment["status"] == "not_met":
            result["minimal_suggestion"] = (
                f"Review the observed mismatch for {rule.rule_id} against its official source."
            )
        return result

    binding = {
        "run_id": snapshot.run_id,
        "manuscript_artifact_id": snapshot.manuscript_artifact_id,
        "accepted_event_sha256": snapshot.manuscript.event.event_sha256,
        "accepted_content_sha256": manifest.content_sha256,
        "manuscript_source_sha256": None if capsule else manifest.content_sha256,
        "retained_source_capsule_sha256": manifest.content_sha256 if capsule else None,
        "external_reviewed_pdf_sha256": capsule.provenance.pdf_sha256
        if capsule
        else None,
        "external_reviewed_pdf_retained": snapshot.pdf is not None if capsule else None,
        "input_kind": snapshot.input_kind,
        "selected_narrative_status": "not_selected",
        "narrative_sha256": None,
        "narrative_version": None,
        "venue_profile_version": snapshot.profile.version,
        "venue_profile_verified_on": snapshot.profile.verified_on.isoformat(),
        "venue_profile_review_due": snapshot.profile.review_due.isoformat(),
        "venue_profile_sha256": snapshot.profile_sha256,
        "official_requirements_status": "available"
        if snapshot.profile.official_hard_requirements
        else "not_evaluated",
        "promoted_heuristic_set_sha256": sha256_hex(canonical_json_bytes([])),
        "judgment_input_sha256": _core_digest(snapshot),
    }
    if snapshot.pdf:
        pdf_manifest, _ = _public_proof(snapshot.pdf, snapshot.run_id)
        binding.update(
            {
                "accepted_pdf_sha256": pdf_manifest.content_sha256,
                "accepted_pdf_artifact_id": pdf_manifest.artifact_id,
            }
        )
    result = {
        "schema_version": "arw.narrative-fit-report.v1",
        "target": snapshot.profile.venue_id,
        "input_binding": binding,
        "official_hard_requirements": [
            rule_result(r) for r in snapshot.profile.official_hard_requirements
        ],
        "structural_expectations": {
            "narrative_realization": {
                "mechanical_status": "UNKNOWN",
                "semantic_status": "UNKNOWN",
                "evaluation_status": "not_evaluated",
                "reason_code": "selected_narrative_not_selected",
            },
            "venue_rules": [
                rule_result(r) for r in snapshot.profile.structural_expectations
            ],
        },
        "empirical_status": "not_evaluated",
        "empirical_patterns": [],
        "judgment_status": "not_supplied",
        "reviewer_judgment": None,
        "limits": [
            "advisory_only",
            "no_acceptance_or_plan_mutation",
            "no_acceptance_probability",
            "selected_narrative_not_selected",
            "unpromoted_corpus_not_evaluated",
            "source_capsule_is_not_full_manuscript",
            "external_pdf_provenance_is_not_retained_pdf_bytes",
            "natural_language_requirements_need_reviewed_typed_predicates",
            "bounded_anonymity_search_is_not_comprehensive",
        ],
    }
    if not snapshot.profile.official_hard_requirements:
        result["limits"].append("official_profile_requirements_not_supplied")
    return FitReport.model_validate(result).model_dump(mode="json")


def report(snapshot: FitSnapshot | PublicFitSnapshot) -> dict:
    if isinstance(snapshot, PublicFitSnapshot):
        return _public_report(snapshot)
    raw = _check_snapshot(snapshot)
    text = raw.decode("utf-8")
    source_format = (
        _source_format(snapshot.realization.source_path)
        if snapshot.predicate_policy == "source-format-v2"
        else "markdown"
    )

    def rule_result(rule):
        return {
            "rule_id": rule.rule_id,
            "statement": rule.statement,
            "provenance": {
                "source_url": rule.source_url,
                "source_sha256": rule.source_sha256,
                "source_locator": rule.source_locator,
                "reviewed_by": rule.reviewed_by,
            },
            "assessment": _predicate(
                rule.predicate, text, snapshot.pdf_page_count, source_format
            ),
        }

    hard = [rule_result(r) for r in snapshot.profile.official_hard_requirements]
    for item in hard:
        if item["assessment"]["status"] == "not_met":
            item["minimal_suggestion"] = (
                f"Review the observed mismatch for {item['rule_id']} against its official source."
            )
    structural = [rule_result(r) for r in snapshot.profile.structural_expectations]
    empirical = []
    for h in snapshot.heuristics:
        conflicts = []
        if h.predicate:
            for rule in snapshot.profile.official_hard_requirements:
                other = rule.predicate
                if (
                    other
                    and other.value == h.predicate.value
                    and {other.kind, h.predicate.kind}
                    == {"literal_present", "bounded_marker_absent"}
                ):
                    conflicts.append(rule.rule_id)
        item = h.inspected_record
        empirical.append(
            {
                "heuristic_id": h.heuristic_id,
                "promotion_event_id": h.promotion_event_id,
                "approved_scope": h.approved_scope,
                "venue_id": h.venue_id,
                "domain_id": h.domain_id,
                "suggested_action": h.suggested_action,
                "inspected_record_sha256": h.inspected_record_sha256,
                "supporting": item.get("supporting_observation_ids", []),
                "counterexample": item.get("counterexample_observation_ids", []),
                "unknown": item.get("unknown", []),
                "evaluation_counts": item.get("evaluation", {})
                .get("metrics", {})
                .get("counts"),
                "assessment": _predicate(
                    h.predicate, text, snapshot.pdf_page_count, source_format
                ),
                "reviewed_by": h.reviewed_by,
                "typed_official_conflicts": sorted(conflicts),
                "selected_narrative_conflict": "unknown_requires_reviewer",
            }
        )
    result = {
        "schema_version": "arw.narrative-fit-report.v1",
        "target": snapshot.profile.venue_id,
        "input_binding": {
            "run_id": snapshot.run_id,
            "manuscript_artifact_id": snapshot.manuscript_artifact_id,
            "accepted_event_sha256": snapshot.accepted_event_sha256,
            "accepted_content_sha256": snapshot.accepted_content_sha256,
            "manuscript_source_sha256": snapshot.manuscript_source_sha256,
            "narrative_sha256": snapshot.narrative.sha256,
            "narrative_version": snapshot.narrative.version,
            "venue_profile_version": snapshot.profile.version,
            "venue_profile_verified_on": snapshot.profile.verified_on.isoformat(),
            "venue_profile_review_due": snapshot.profile.review_due.isoformat(),
            "venue_profile_sha256": snapshot.profile_sha256,
            "promoted_heuristic_set_sha256": snapshot.heuristic_set_sha256,
            "judgment_input_sha256": _core_digest(snapshot),
        },
        "official_hard_requirements": hard,
        "structural_expectations": {
            "narrative_realization": snapshot.validation,
            "venue_rules": structural,
        },
        "empirical_status": "evaluated_selected"
        if snapshot.heuristics
        else "not_evaluated",
        "empirical_patterns": empirical,
        "judgment_status": "supplied" if snapshot.judgment else "not_supplied",
        "reviewer_judgment": snapshot.judgment.model_dump(mode="json")
        if snapshot.judgment
        else None,
        "limits": [
            "advisory_only",
            "no_acceptance_or_plan_mutation",
            "no_acceptance_probability",
            "natural_language_requirements_need_reviewed_typed_predicates",
            "bounded_anonymity_search_is_not_comprehensive",
        ],
    }
    if snapshot.writing_candidate_binding is not None:
        binding = snapshot.writing_candidate_binding
        result["input_binding"]["accepted_binding_kind"] = "writing_candidate_receipt"
        result["input_binding"]["writing_candidate_receipt"] = {
            "receipt_sha256": binding.receipt_sha256,
            "candidate_path": binding.candidate_path,
            "candidate_sha256": binding.candidate_sha256,
            "realization_sha256": binding.realization_sha256,
            "accepted_manifest_sha256": binding.accepted_manifest_sha256,
            "accepted_event_sha256": binding.accepted_event_sha256,
            "run_manifest_sha256": binding.run_manifest_sha256,
        }
    return FitReport.model_validate(result).model_dump(mode="json")


def freeze(
    run_root: Path,
    target: str,
    manuscript_artifact_id: str | None = None,
    profile_path: Path | None = None,
    *,
    heuristic_ids=(),
    domain_id: str | None = None,
    pdf_artifact_id: str | None = None,
    judgment_path: Path | None = None,
    realization_path: Path | None = None,
    heuristic_annotations_path: Path | None = None,
    without_selected_narrative: bool = False,
) -> FitSnapshot | PublicFitSnapshot:
    if without_selected_narrative:
        if (
            realization_path
            or heuristic_ids
            or heuristic_annotations_path
            or judgment_path
        ):
            raise NarrativeFitError(
                "public_fit_options_invalid",
                "unbound public fit does not accept a realization, heuristic selection or judgment",
            )
        return _freeze_public(
            run_root,
            target,
            manuscript_artifact_id,
            profile_path,
            pdf_artifact_id=pdf_artifact_id,
        )
    run_root = Path(run_root).resolve(strict=True)
    state = replay_run(run_root)
    if state.recovery_health != "healthy":
        raise NarrativeFitError(
            "run_unhealthy", "canonical journal has an unresolved recovery tail"
        )
    manifest_raw = read_retained_bytes(run_root, "run-manifest.json", max_bytes=65536)
    manifest = RunManifest.model_validate(strict_json_loads(manifest_raw))
    if manifest.narrative_binding is None:
        raise NarrativeFitError(
            "paper_run_required", "fit needs a paper run narrative binding"
        )
    project_root = (
        run_root / manifest.narrative_binding.project_relative_path
    ).resolve(strict=True)
    if not run_root.is_relative_to(project_root):
        raise NarrativeFitError("project_run_mismatch", "run is outside bound project")
    narrative = current_narrative(project_root)
    if manuscript_artifact_id is None:
        drafts = []
        for accepted_event in state.events:
            if accepted_event.event_type != "artifact.accepted":
                continue
            payload = _accepted_payload(accepted_event)
            candidate = load_artifact_manifest(run_root, payload.manifest_sha256)
            if STAGE_KINDS.get(candidate.artifact_kind) == "draft":
                drafts.append(payload.artifact_id)
        if not drafts:
            raise NarrativeFitError(
                "accepted_manuscript_missing",
                "no accepted draft in run; pass --manuscript-artifact-id",
            )
        manuscript_artifact_id = drafts[-1]
    assert manuscript_artifact_id is not None
    event, accepted, accepted_raw = _accepted(
        run_root, state.events, manuscript_artifact_id
    )
    writing_receipt = None
    writing_binding = None
    if accepted.artifact_kind == "writing-derived":
        try:
            writing_receipt = strict_json_loads(accepted_raw)
            if not isinstance(writing_receipt, dict) or not isinstance(
                writing_receipt.get("narrative_realization"), dict
            ):
                raise TypeError("nested realization is missing")
            realization_raw = canonical_json_bytes(
                writing_receipt["narrative_realization"]
            )
        except (ValueError, TypeError) as error:
            raise NarrativeFitError(
                "writing_receipt_invalid", "accepted writing realization is malformed"
            ) from error
        if realization_path is not None:
            if Path(realization_path).is_absolute():
                raise NarrativeFitError(
                    "realization_path_invalid",
                    "realization path must be relative to run root",
                )
            sidecar_raw = read_retained_bytes(
                run_root, Path(realization_path).as_posix(), max_bytes=1_048_576
            )
            try:
                if canonical_json_bytes(strict_json_loads(sidecar_raw)) != realization_raw:
                    raise ValueError("explicit realization differs from accepted receipt")
            except (ValueError, TypeError) as error:
                raise NarrativeFitError(
                    "writing_receipt_invalid",
                    "explicit realization differs from accepted writing receipt",
                ) from error
        binding_kind = "writing_candidate_receipt"
    elif realization_path is None:
        if STAGE_KINDS.get(accepted.artifact_kind) != "draft":
            raise NarrativeFitError(
                "draft_required", "accepted artifact is not a manuscript draft"
            )
        realization_raw = accepted_raw
        binding_kind = "realization_sidecar"
    else:
        if Path(realization_path).is_absolute():
            raise NarrativeFitError(
                "realization_path_invalid",
                "realization path must be relative to run root",
            )
        realization_raw = read_retained_bytes(
            run_root, Path(realization_path).as_posix(), max_bytes=1_048_576
        )
        binding_kind = "manuscript_source"
    realization = NarrativeRealization.model_validate(
        strict_json_loads(realization_raw)
    )
    if realization.stage != "draft":
        raise NarrativeFitError("draft_required", "accepted realization is not a draft")
    manuscript = read_retained_bytes(
        run_root, realization.source_path, max_bytes=8_388_608
    )
    if writing_receipt is not None:
        manifest_bytes = read_retained_bytes(
            run_root,
            f"manifests/artifacts/sha256/{event.payload.manifest_sha256}.json",
            max_bytes=262144,
        )
        writing_binding = WritingCandidateReceiptBinding(
            run_manifest_sha256=sha256_hex(manifest_raw),
            run_manifest_base64=base64.b64encode(manifest_raw).decode("ascii"),
            accepted_manifest_sha256=event.payload.manifest_sha256,
            accepted_manifest_base64=base64.b64encode(manifest_bytes).decode("ascii"),
            accepted_event_id=event.event_id,
            accepted_event_sha256=event.event_sha256,
            receipt_sha256=sha256_hex(accepted_raw),
            candidate_path=writing_receipt.get("candidate_path", ""),
            candidate_sha256=writing_receipt.get("candidate_sha256", ""),
            realization_sha256=sha256_hex(realization_raw),
        )
        _validate_writing_candidate_receipt(
            run_root,
            state.events,
            accepted_raw,
            manuscript,
            realization_raw,
            event,
            writing_binding,
            narrative,
            state.run_id,
            manuscript_artifact_id,
        )
    if binding_kind == "manuscript_source" and (
        accepted.content_sha256 != realization.source_sha256
        or accepted_raw != manuscript
    ):
        raise NarrativeFitError(
            "accepted_content_mismatch",
            "proposed realization must bind accepted manuscript bytes",
        )
    validation = _validation(run_root, realization, narrative, state.events, manuscript)
    profile_raw = (
        _read_local(profile_path, 262144)
        if profile_path is not None
        else _bundled_profile(target)
    )
    strict_json_loads(profile_raw)
    profile = VenueFitProfile.model_validate_json(profile_raw)
    if profile.venue_id != target:
        raise NarrativeFitError(
            "target_mismatch", "profile venue differs from --target"
        )
    annotations = {}
    if heuristic_annotations_path is not None:
        annotation_raw = _read_local(heuristic_annotations_path, 65536)
        annotations = strict_json_loads(annotation_raw)
        if not isinstance(annotations, dict) or set(annotations) - set(heuristic_ids):
            raise NarrativeFitError(
                "annotations_invalid", "annotations must name selected heuristic IDs"
            )
    heuristics = []
    if heuristic_ids:
        if not domain_id:
            raise NarrativeFitError(
                "domain_required", "promoted heuristic lookup needs a domain ID"
            )
        from arw_research_learning.service import ResearchLearningService

        learning = ResearchLearningService(project_root, run_root=run_root)
        for heuristic_id in heuristic_ids:
            item = learning.inspect(heuristic_id)
            venue = item.get("venue_applicability")
            if item.get("status") != "promoted" or venue != {
                "domain_id": domain_id,
                "venue_id": target,
            }:
                raise NarrativeFitError(
                    "heuristic_not_applicable",
                    "heuristic is not promoted for this venue/domain",
                )
            if item.get("scope") == "run" and item.get("run_id") != state.run_id:
                raise NarrativeFitError(
                    "heuristic_not_applicable",
                    "run-scoped heuristic belongs to another run",
                )
            annotation = annotations.get(heuristic_id, {})
            if not isinstance(annotation, dict) or set(annotation) - {
                "predicate",
                "reviewed_by",
            }:
                raise NarrativeFitError(
                    "annotations_invalid", "heuristic annotation fields are invalid"
                )
            predicate = (
                FitPredicate.model_validate(annotation["predicate"])
                if "predicate" in annotation
                else None
            )
            heuristics.append(
                FitHeuristic(
                    heuristic_id=heuristic_id,
                    promotion_event_id=item["accepted_ledger_event_id"],
                    venue_id=target,
                    domain_id=domain_id,
                    suggested_action=item["proposed_action"],
                    approved_scope=item["scope"],
                    inspected_record_sha256=sha256_hex(canonical_json_bytes(item)),
                    inspected_record=item,
                    predicate=predicate,
                    reviewed_by=annotation.get("reviewed_by"),
                )
            )
    if len({h.heuristic_id for h in heuristics}) != len(heuristics):
        raise NarrativeFitError("duplicate_heuristic", "heuristic IDs repeat")
    heuristics.sort(key=lambda h: h.heuristic_id)
    pdf_count = pdf_sha = pdf_base64 = None
    pdf_raw = b""
    if pdf_artifact_id:
        _, pdf_manifest, pdf_raw = _accepted(run_root, state.events, pdf_artifact_id)
        if pdf_manifest.media_type != "application/pdf":
            raise NarrativeFitError(
                "pdf_required", "page count needs accepted PDF bytes"
            )
        pdf_count, pdf_sha = _pdf_pages(pdf_raw), pdf_manifest.content_sha256
        pdf_base64 = base64.b64encode(pdf_raw).decode("ascii")
    dependencies = {
        value
        for value in (
            realization.predecessor_artifact_id,
            *(n.evidence_source_artifact_id for n in realization.nodes),
            *(n.hypothesis_history_ref for n in realization.nodes),
        )
        if value is not None
    }
    if writing_receipt is not None:
        dependencies.update(
            writing_receipt[name]["artifact_id"]
            for name in ("source_binding", "review_binding")
        )
    evidence_items = []
    evidence_bytes = (
        len(manuscript)
        + len(accepted_raw)
        + len(profile_raw)
        + (len(pdf_raw) if pdf_artifact_id else 0)
    )
    for artifact_id in sorted(dependencies):
        proof = _proof(run_root, state.events, artifact_id)
        evidence_bytes += len(proof.manifest_base64) + len(proof.content_base64)
        if evidence_bytes > 48 * 1024 * 1024:
            raise NarrativeFitError(
                "snapshot_too_large", "frozen evidence exceeds its budget"
            )
        evidence_items.append(proof)
    evidence = tuple(evidence_items)
    snapshot = FitSnapshot(
        run_id=state.run_id,
        manuscript_artifact_id=manuscript_artifact_id,
        accepted_event_sha256=event.event_sha256,
        accepted_event=event,
        accepted_content_sha256=accepted.content_sha256,
        accepted_content_base64=base64.b64encode(accepted_raw).decode("ascii"),
        accepted_binding_kind=binding_kind,
        writing_candidate_binding=writing_binding,
        realization_base64=base64.b64encode(realization_raw).decode("ascii"),
        manuscript_source_sha256=realization.source_sha256,
        manuscript_source_base64=base64.b64encode(manuscript).decode("ascii"),
        realization=realization,
        narrative=narrative,
        profile=profile,
        profile_sha256=sha256_hex(profile_raw),
        profile_base64=base64.b64encode(profile_raw).decode("ascii"),
        heuristics=tuple(heuristics),
        heuristic_set_sha256=sha256_hex(
            canonical_json_bytes([h.model_dump(mode="json") for h in heuristics])
        ),
        validation=validation,
        evidence=evidence,
        pdf_page_count=pdf_count,
        pdf_artifact_id=pdf_artifact_id,
        pdf_sha256=pdf_sha,
        pdf_base64=pdf_base64,
        predicate_policy="source-format-v2",
    )
    if judgment_path:
        raw = _read_local(judgment_path, 16384)
        judgment = FitJudgment.model_validate(strict_json_loads(raw))
        snapshot = snapshot.model_copy(update={"judgment": judgment})
    if len(canonical_json_bytes(snapshot.model_dump(mode="json"))) > 64 * 1024 * 1024:
        raise NarrativeFitError("snapshot_too_large", "frozen snapshot exceeds 64 MiB")
    _check_snapshot(snapshot)
    return snapshot


def freshness(
    run_root: Path,
    snapshot: FitSnapshot | PublicFitSnapshot,
    profile_path: Path | None = None,
    *,
    as_of: date,
) -> dict:
    """Live comparison is deliberately outside the deterministic fit report."""
    if isinstance(snapshot, PublicFitSnapshot):
        source_status, narrative_status = "unavailable", "unavailable"
        try:
            root = Path(run_root).resolve(strict=True)
            live_manifest = RunManifest.model_validate(
                strict_json_loads(
                    read_retained_bytes(root, "run-manifest.json", max_bytes=65536)
                )
            )
            narrative_status = (
                "not_selected" if live_manifest.narrative_binding is None else "stale"
            )
            state = replay_run(root)
            if state.run_id == snapshot.run_id and state.recovery_health == "healthy":
                live = _proof(root, state.events, snapshot.manuscript_artifact_id)
                source_status = "current" if live == snapshot.manuscript else "stale"
                if snapshot.pdf:
                    pdf_id = _accepted_payload(snapshot.pdf.event).artifact_id
                    if _proof(root, state.events, pdf_id) != snapshot.pdf:
                        source_status = "stale"
        except (ValueError, RuntimeError, OSError):
            pass
        profile_status = "not_checked"
        if profile_path is not None or snapshot.profile.version.startswith("bundle:"):
            raw = (
                _read_local(profile_path, 262144)
                if profile_path
                else _bundled_profile(snapshot.profile.venue_id)
            )
            profile_status = (
                "current" if sha256_hex(raw) == snapshot.profile_sha256 else "stale"
            )
        overdue = as_of > snapshot.profile.review_due
        statuses = (source_status, narrative_status, profile_status)
        return {
            "status": "stale"
            if "stale" in statuses
            else "unavailable"
            if "unavailable" in statuses
            else "needs_recheck"
            if overdue or "not_checked" in statuses
            else "current",
            "narrative": narrative_status,
            "manuscript": source_status,
            "venue_profile": profile_status,
            "venue_profile_time": "needs_recheck"
            if overdue
            else "within_review_window",
            "as_of": as_of.isoformat(),
            "heuristics": "not_evaluated",
        }
    run_root = Path(run_root).resolve(strict=True)
    manifest = RunManifest.model_validate(
        strict_json_loads(
            read_retained_bytes(run_root, "run-manifest.json", max_bytes=65536)
        )
    )
    if manifest.narrative_binding is None:
        return {"status": "unavailable", "reason": "paper_run_required"}
    project_root = (
        run_root / manifest.narrative_binding.project_relative_path
    ).resolve(strict=True)
    current = current_narrative(project_root)
    narrative_status = (
        "current" if current.sha256 == snapshot.narrative.sha256 else "stale"
    )
    profile_status = "not_checked"
    if profile_path is not None or snapshot.profile.version.startswith("bundle:"):
        current_profile = (
            _read_local(profile_path, 262144)
            if profile_path is not None
            else _bundled_profile(snapshot.profile.venue_id)
        )
        profile_status = (
            "current"
            if sha256_hex(current_profile) == snapshot.profile_sha256
            else "stale"
        )
    profile_time_status = (
        "needs_recheck"
        if as_of > snapshot.profile.review_due
        else "within_review_window"
    )
    heuristic_status = "not_applicable"
    if snapshot.heuristics:
        try:
            from arw_research_learning.service import ResearchLearningService

            learning = ResearchLearningService(project_root, run_root=run_root)
            heuristic_status = "current"
            for heuristic in snapshot.heuristics:
                item = learning.inspect(heuristic.heuristic_id)
                if (
                    item.get("status") != "promoted"
                    or sha256_hex(canonical_json_bytes(item))
                    != heuristic.inspected_record_sha256
                ):
                    heuristic_status = "stale"
                    break
        except (ImportError, ValueError, RuntimeError, OSError):
            heuristic_status = "unavailable"
    return {
        "status": "stale"
        if "stale" in (narrative_status, profile_status, heuristic_status)
        else "needs_recheck"
        if profile_time_status == "needs_recheck"
        else "current",
        "narrative": narrative_status,
        "venue_profile": profile_status,
        "venue_profile_time": profile_time_status,
        "as_of": as_of.isoformat(),
        "heuristics": heuristic_status,
    }


class WritingNarrativeFitService:
    def __init__(self, run_root: Path):
        self.run_root = Path(run_root)

    def freeze(
        self,
        target: str,
        manuscript_artifact_id: str | None = None,
        profile_path: Path | None = None,
        **kwargs,
    ):
        return freeze(
            self.run_root, target, manuscript_artifact_id, profile_path, **kwargs
        )

    def report(self, snapshot: FitSnapshot | PublicFitSnapshot):
        return report(snapshot)

    def freshness(
        self,
        snapshot: FitSnapshot | PublicFitSnapshot,
        profile_path: Path | None = None,
        *,
        as_of: date,
    ):
        return freshness(self.run_root, snapshot, profile_path, as_of=as_of)
