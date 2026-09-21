"""Parent-owned submission workflow service.

The service is intentionally additive: submission values are stored as normal
immutable artifacts and all acceptance/gate events go through the existing
runtime writer.  There is no submission-specific database or event store.
"""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.execution.runtime import CommandOutcome, RuntimeCommandService
from arw.kernel.ledger.journal import replay_run
from arw.kernel.ledger.manifests import (
    ManifestError,
    load_artifact_manifest,
    validate_accepted_event_manifests,
)
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.state.models import (
    ArtifactAcceptanceRequest,
    ArtifactAcceptedPayload,
    EventId,
    GateEvaluatedPayload,
    LifecycleTransitionedPayload,
    LifecycleTransitionRequest,
    RuntimeCommandRequest,
    Sha256,
    StrictModel,
)
from arw.kernel.state.orchestration_models import (
    GateDecision,
    canonical_orchestration_model_bytes,
)
from arw.kernel.state.submission import (
    JournalRequirementsSnapshot,
    ReviewResponse,
    ReviewRound,
    SubmissionArtifactReference,
    SubmissionCheckReport,
    SubmissionPacket,
    SubmissionResultObservation,
    SubmissionVerifierObservation,
    confirmation_gate_id,
    declaration_subject_sha256,
    evaluate_submission_readiness,
    response_subject_sha256,
    submission_input_fingerprint,
)

_MAX_SUBMISSION_JSON_BYTES = 256 * 1024
_MAX_STATUS_BYTES = 64 * 1024
_MAX_STATUS_PAGE = 128

SUBMISSION_ARTIFACT_MODELS: dict[str, type[StrictModel]] = {
    "journal-requirements": JournalRequirementsSnapshot,
    "submission-packet": SubmissionPacket,
    "submission-review-round": ReviewRound,
    "submission-response": ReviewResponse,
    "submission-check-report": SubmissionCheckReport,
    "submission-result-observation": SubmissionResultObservation,
    "submission-verifier-observation": SubmissionVerifierObservation,
}


class SubmissionWorkflowError(RuntimeError):
    """A submission operation failed before or during parent admission."""


@dataclass(frozen=True, slots=True)
class AcceptedSubmissionArtifact:
    kind: str
    artifact_id: str
    event_id: EventId
    sequence: int
    manifest_sha256: Sha256
    content_sha256: Sha256
    value: StrictModel

    @property
    def reference(self) -> SubmissionArtifactReference:
        return SubmissionArtifactReference(
            artifact_id=self.artifact_id,
            manifest_sha256=self.manifest_sha256,
            content_sha256=self.content_sha256,
            accepting_event_id=self.event_id,
        )


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _uuid4_shape(seed: str) -> str:
    value = uuid.uuid5(uuid.NAMESPACE_URL, f"arw-submission:{seed}")
    value = uuid.UUID(bytes=value.bytes, version=4)
    return str(value)


def _event_id(seed: str) -> str:
    value = _uuid4_shape(f"event:{seed}")
    return f"evt-{value[:8]}-{value[9:13]}-{value[14:18]}-{value[19:23]}-{value[24:]}"


def _command_id(seed: str) -> str:
    value = _uuid4_shape(f"command:{seed}")
    return f"cmd-{value[:8]}-{value[9:13]}-{value[14:18]}-{value[19:23]}-{value[24:]}"


def _as_relative(root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(root) if path.is_absolute() else path
    except ValueError as error:
        raise SubmissionWorkflowError("submission input must be inside the run root") from error
    value = relative.as_posix()
    if not value or value.startswith("/") or any(part in {"", ".", ".."} for part in relative.parts):
        raise SubmissionWorkflowError("submission input path is not normalized")
    return value


def _model_for_kind(kind: str) -> type[StrictModel]:
    try:
        return SUBMISSION_ARTIFACT_MODELS[kind]
    except KeyError as error:
        raise SubmissionWorkflowError(f"unsupported submission artifact kind: {kind}") from error


def validate_submission_payload(kind: str, raw: bytes) -> StrictModel:
    if len(raw) > _MAX_SUBMISSION_JSON_BYTES:
        raise SubmissionWorkflowError("submission JSON exceeds the 256 KiB limit")
    model = _model_for_kind(kind)
    try:
        value = model.model_validate_json(raw, strict=True)
    except (TypeError, ValueError) as error:
        raise SubmissionWorkflowError(f"invalid {kind} payload: {error}") from error
    return value


class SubmissionWorkflowService:
    """Parent service for preparation, admission, readiness and observations."""

    def __init__(self, run_root: Path, *, lock_timeout: float = 0.2) -> None:
        self.run_root = run_root
        self.runtime = RuntimeCommandService(run_root, lock_timeout=lock_timeout)
        self.lock_timeout = lock_timeout

    def prepare(self, kind: str, raw: bytes) -> dict[str, Any]:
        value = validate_submission_payload(kind, raw)
        return {
            "schema_version": "arw.submission-preparation.v1",
            "status": "prepared",
            "artifact_kind": kind,
            "content_sha256": sha256_hex(raw),
            "candidate": value.model_dump(mode="json"),
            "canonical_bytes_sha256": sha256_hex(
                canonical_json_bytes(value.model_dump(mode="json"))
            ),
            "canonical_admission": "parent_required",
        }

    def record(self, kind: str, raw: bytes, request: ArtifactAcceptanceRequest) -> dict[str, Any]:
        value = validate_submission_payload(kind, raw)
        expected_run_id = getattr(value, "run_id", request.run_id)
        if expected_run_id != request.run_id:
            raise SubmissionWorkflowError("submission payload run_id differs from request")
        if request.artifact_kind != kind:
            raise SubmissionWorkflowError("artifact kind does not match the submission payload")
        content_sha256 = sha256_hex(raw)
        if request.content_sha256 != content_sha256:
            raise SubmissionWorkflowError("submission content digest differs from the request")
        existing = self._existing_artifact_outcome(request, kind, content_sha256)
        if existing is not None:
            return existing
        outcome = self.runtime.accept_artifact(request)
        return self._outcome_json(outcome, kind=kind)

    def check(
        self,
        submission_id: str,
        *,
        as_of: str | None = None,
        cursor: str | None = None,
        limit: int = 64,
    ) -> dict[str, Any]:
        if not 1 <= limit <= _MAX_STATUS_PAGE:
            raise SubmissionWorkflowError("submission status page limit is out of bounds")
        try:
            head = replay_run(self.run_root, lock_timeout=self.lock_timeout).last_event_sha256
        except (OSError, RuntimeError) as error:
            raise SubmissionWorkflowError(f"cannot replay submission run: {error}") from error
        offset = self._decode_cursor(cursor, head)
        records = self._accepted()
        packets = [
            item
            for item in records
            if item.kind == "submission-packet"
            and isinstance(item.value, SubmissionPacket)
            and item.value.submission_id == submission_id
        ]
        if not packets:
            raise SubmissionWorkflowError("submission packet is not accepted")
        packet_record = max(
            packets, key=lambda item: (item.value.packet_version, item.sequence)
        )
        packet = packet_record.value
        reports = [
            item
            for item in records
            if item.kind == "submission-check-report"
            and isinstance(item.value, SubmissionCheckReport)
            and item.value.submission_id == submission_id
            and item.value.packet_manifest_sha256 == packet_record.manifest_sha256
        ]
        report = max(reports, key=lambda item: item.sequence).value if reports else None
        checks = tuple(report.checks) if report is not None else ()
        evaluation_time = as_of or _now()
        if report is not None:
            checks = tuple(
                check.model_copy(update={"status": "STALE"})
                if check.valid_until is not None and evaluation_time > check.valid_until
                else check
                for check in checks
            )
        response_by_comment: dict[str, ReviewResponse] = {}
        for item in sorted(records, key=lambda item: item.sequence):
            if (
                item.kind == "submission-response"
                and isinstance(item.value, ReviewResponse)
                and item.value.submission_id == submission_id
            ):
                response_by_comment[item.value.comment_id] = item.value
        responses = tuple(response_by_comment.values())
        expected_comment_ids = tuple(
            dict.fromkeys(
                comment.comment_id
                for item in records
                if item.kind == "submission-review-round"
                and isinstance(item.value, ReviewRound)
                and item.value.submission_id == submission_id
                for comment in item.value.comments
            )
        )
        state = self.runtime.read_state()
        dependency_sha256 = self._dependency_hashes(
            packet_record, records, submission_id, state=state
        )
        dependency_categories = self._dependency_fingerprints(
            packet_record, records, submission_id, state=state
        )
        current_input_fingerprint = submission_input_fingerprint(
            packet, dependency_sha256=dependency_sha256
        )
        evaluation = evaluate_submission_readiness(
            packet,
            packet_manifest_sha256=packet_record.manifest_sha256,
            checks=checks,
            responses=responses,
            expected_comment_ids=expected_comment_ids,
            dependency_sha256=dependency_sha256,
            valid_input_sha256=(current_input_fingerprint, *dependency_sha256),
            dependency_categories=dependency_categories,
            evaluated_at=evaluation_time,
        )
        decisions = {item.decision_id: item for item in state.human_decision_history}
        gates = {item.gate_id: item for item in state.gates}

        def decision_is_current_approval(decision, gate_id: str, subject_sha256: str) -> bool:
            gate = gates.get(gate_id)
            return bool(
                decision.decision_kind == "approval"
                and decision.gate_id == gate_id
                and decision.subject_sha256 == subject_sha256
                and gate is not None
                and gate.verdict == "PASS"
                and gate.subject_sha256 == subject_sha256
                and (
                    gate.decision.fresh_until is None
                    or evaluation_time <= gate.decision.fresh_until
                )
            )

        missing_author_decisions: set[str] = set()
        invalid_author_decisions: set[str] = set()
        for author in packet.authors:
            for field_name in ("funding", "conflicts", "ethics", "data", "ai_use"):
                field = getattr(author, field_name)
                if field.status != "confirmed" or field.human_decision_id is None:
                    continue
                decision = decisions.get(field.human_decision_id)
                if decision is None:
                    missing_author_decisions.add(field.human_decision_id)
                    continue
                if (
                    decision.scope
                    != f"submission:{submission_id}:author:{author.person_id}:{field_name}"
                    or decision.gate_id
                    != confirmation_gate_id(
                        f"submission:{submission_id}:author:{author.person_id}:{field_name}"
                    )
                    or decision.subject_sha256
                    != declaration_subject_sha256(
                        submission_id, author.person_id, field_name, field
                    )
                    or not decision_is_current_approval(
                        decision,
                        confirmation_gate_id(
                            f"submission:{submission_id}:author:{author.person_id}:{field_name}"
                        ),
                        declaration_subject_sha256(
                            submission_id, author.person_id, field_name, field
                        ),
                    )
                ):
                    invalid_author_decisions.add(field.human_decision_id)
        invalid_response_decisions = {
            item.author_decision_id
            for item in responses
            if item.status in {"addressed", "not_adopted"}
            and (
                item.author_decision_id is None
                or item.author_decision_id not in decisions
                or decisions[item.author_decision_id].scope
                != f"submission:{submission_id}:response:{item.comment_id}"
                or decisions[item.author_decision_id].gate_id
                != confirmation_gate_id(
                    f"submission:{submission_id}:response:{item.comment_id}"
                )
                or decisions[item.author_decision_id].subject_sha256
                != response_subject_sha256(item)
                or not decision_is_current_approval(
                    decisions[item.author_decision_id],
                    confirmation_gate_id(
                        f"submission:{submission_id}:response:{item.comment_id}"
                    ),
                    response_subject_sha256(item),
                )
            )
        }
        invalid_response_decisions.discard(None)
        if missing_author_decisions:
            evaluation = evaluation.model_copy(
                update={
                    "readiness": "BLOCKED",
                    "reason_codes": tuple(evaluation.reason_codes)
                    + ("author_decision_missing",),
                }
            )
        if invalid_author_decisions:
            evaluation = evaluation.model_copy(
                update={
                    "readiness": "BLOCKED",
                    "reason_codes": tuple(evaluation.reason_codes)
                    + ("author_decision_scope_invalid",),
                }
            )
        if invalid_response_decisions:
            evaluation = evaluation.model_copy(
                update={
                    "readiness": "BLOCKED",
                    "reason_codes": tuple(evaluation.reason_codes)
                    + ("response_author_decision_invalid",),
                }
            )
        if report is not None and report.input_fingerprint != evaluation.input_fingerprint:
            evaluation = evaluation.model_copy(
                update={
                    "readiness": "STALE",
                    "reason_codes": tuple(evaluation.reason_codes) + ("report_fingerprint_stale",),
                }
            )
        if report is not None and report.valid_until is not None and evaluation_time > report.valid_until:
            evaluation = evaluation.model_copy(
                update={
                    "readiness": "STALE",
                    "reason_codes": tuple(evaluation.reason_codes) + ("report_expired",),
                }
            )
        page = [
            {
                "artifact_id": item.artifact_id,
                "kind": item.kind,
                "manifest_sha256": item.manifest_sha256,
                "content_sha256": item.content_sha256,
                "sequence": item.sequence,
            }
            for item in records
            if getattr(item.value, "submission_id", None) == submission_id
        ]
        page_items = page[offset : offset + limit]
        next_cursor = (
            self._encode_cursor(head, offset + limit)
            if offset + limit < len(page)
            else None
        )
        result = {
            "schema_version": "arw.submission-status.v1",
            "submission_id": submission_id,
            "ledger_head_sha256": head,
            "packet": self._redacted_packet(packet),
            "packet_manifest_sha256": packet_record.manifest_sha256,
            "latest_check_report": (
                self._redacted_report(report) if report is not None else None
            ),
            "readiness": evaluation.model_dump(mode="json"),
            "response_count": len(responses),
            "accepted_artifacts": page_items,
            "next_cursor": next_cursor,
        }
        if len(canonical_json_bytes(result)) > _MAX_STATUS_BYTES:
            raise SubmissionWorkflowError("submission status output exceeds the 64 KiB limit")
        return result

    def qualify(
        self,
        report: SubmissionCheckReport,
        request: ArtifactAcceptanceRequest,
    ) -> dict[str, Any]:
        raw = canonical_json_bytes(report.model_dump(mode="json"))
        recorded = self.record("submission-check-report", raw, request)
        if not recorded.get("accepted"):
            return recorded
        event = recorded["event"]
        report_manifest = event["payload"]["manifest_sha256"]
        report_state = recorded["state"]
        evaluation = self.check(report.submission_id, as_of=report.evaluated_at)
        readiness = evaluation["readiness"]
        gate_request = RuntimeCommandRequest(
            schema_version=request.schema_version,
            run_id=request.run_id,
            event_id=_event_id(f"gate:{request.command_id}"),
            command_id=_command_id(f"gate:{request.command_id}"),
            expected_revision=report_state["accepted_revision"],
            occurred_at=request.occurred_at,
            actor_id=request.actor_id,
            actor_role=request.actor_role,
        )
        decision = GateDecision(
            schema_version="arw.gate-decision.v1",
            gate_id=f"gate.submission.{report.submission_id}.{report.report_id}",
            subject_sha256=report.input_fingerprint,
            evidence_sha256=(report.packet_manifest_sha256, report_manifest),
            verdict="PASS" if readiness["readiness"] == "READY_FOR_HUMAN_SUBMIT" else "BLOCKED",
            rationale="; ".join(readiness["reason_codes"]) or "submission readiness evaluated",
            fresh_until=report.valid_until,
            required=True,
            human_decision=None,
        )
        gate_payload = GateEvaluatedPayload(
            decision=decision,
            decision_sha256=sha256_hex(canonical_orchestration_model_bytes(decision)),
        )
        gate_outcome = self._existing_gate_outcome(gate_request, gate_payload)
        if gate_outcome is None:
            gate_outcome = self.runtime.append_phase4_event(
                gate_request,
                event_type="gate.evaluated",
                payload=gate_payload,
                prevalidate=lambda state, _replayed: self._validate_gate_inputs(
                    state,
                    _replayed,
                    report,
                    report_manifest,
                    evaluation,
                ),
            )
        return {
            "schema_version": "arw.submission-qualification.v1",
            "artifact": recorded,
            "gate": (
                gate_outcome.model_dump(mode="json")
                if isinstance(gate_outcome, CommandOutcome)
                else gate_outcome
            ),
            "final_submit": "human_only",
        }

    def transition_ready(
        self,
        submission_id: str,
        request: LifecycleTransitionRequest,
    ) -> CommandOutcome:
        """Run the registered completion transition only for a fresh submission.

        The validation callback executes inside the runtime writer lock.  A
        caller cannot turn a previously observed PASS into a transition after
        changing the packet, response heads, scoped decisions, or aggregate
        gate between two independent reads.
        """

        if request.transition_id != "complete":
            raise SubmissionWorkflowError(
                "submission ready transition must use the registered complete transition"
            )
        existing = self._existing_transition_outcome(request)
        if existing is not None:
            return existing

        def validate(state, replayed):
            records = self._accepted(replayed=replayed)
            packets = [
                item
                for item in records
                if item.kind == "submission-packet"
                and isinstance(item.value, SubmissionPacket)
                and item.value.submission_id == submission_id
            ]
            packet_record = max(
                packets,
                key=lambda item: (item.value.packet_version, item.sequence),
                default=None,
            )
            if packet_record is None:
                return "submission-packet-unknown", "submission packet is not accepted"
            reports = [
                item
                for item in records
                if item.kind == "submission-check-report"
                and isinstance(item.value, SubmissionCheckReport)
                and item.value.submission_id == submission_id
                and item.value.packet_manifest_sha256 == packet_record.manifest_sha256
            ]
            report_record = max(reports, key=lambda item: item.sequence, default=None)
            if report_record is None:
                return "submission-report-unknown", "a current readiness report is required"
            report = report_record.value
            assert isinstance(report, SubmissionCheckReport)
            responses_by_comment: dict[str, ReviewResponse] = {}
            for item in sorted(records, key=lambda value: value.sequence):
                if (
                    item.kind == "submission-response"
                    and isinstance(item.value, ReviewResponse)
                    and item.value.submission_id == submission_id
                ):
                    responses_by_comment[item.value.comment_id] = item.value
            expected_comment_ids = tuple(
                dict.fromkeys(
                    comment.comment_id
                    for item in records
                    if item.kind == "submission-review-round"
                    and isinstance(item.value, ReviewRound)
                    and item.value.submission_id == submission_id
                    for comment in item.value.comments
                )
            )
            dependency_sha256 = self._dependency_hashes(
                packet_record,
                records,
                submission_id,
                state=state,
            )
            dependency_categories = self._dependency_fingerprints(
                packet_record,
                records,
                submission_id,
                state=state,
            )
            current_fingerprint = submission_input_fingerprint(
                packet_record.value,
                dependency_sha256=dependency_sha256,
            )
            if report.input_fingerprint != current_fingerprint:
                return "submission-report-stale", "readiness report fingerprint is stale"
            evaluation = evaluate_submission_readiness(
                packet_record.value,
                packet_manifest_sha256=packet_record.manifest_sha256,
                checks=tuple(report.checks),
                responses=tuple(responses_by_comment.values()),
                expected_comment_ids=expected_comment_ids,
                dependency_sha256=dependency_sha256,
                valid_input_sha256=(current_fingerprint, *dependency_sha256),
                dependency_categories=dependency_categories,
                evaluated_at=request.occurred_at,
            )
            if evaluation.readiness != "READY_FOR_HUMAN_SUBMIT":
                return "submission-not-ready", "current readiness is not READY_FOR_HUMAN_SUBMIT"
            if report.readiness != "READY_FOR_HUMAN_SUBMIT":
                return "submission-report-not-ready", "accepted readiness report is not ready"
            gate_id = f"gate.submission.{submission_id}.{report.report_id}"
            gate = next((item for item in state.gates if item.gate_id == gate_id), None)
            if (
                gate is None
                or gate.verdict != "PASS"
                or gate.subject_sha256 != report.input_fingerprint
                or (
                    gate.decision.fresh_until is not None
                    and request.occurred_at > gate.decision.fresh_until
                )
            ):
                return "submission-gate-stale", "current aggregate readiness gate is not a fresh PASS"
            final_scope = f"submission:{submission_id}:ready"
            if not any(
                item.decision_kind == "approval"
                and item.applicable_transition == request.transition_id
                and item.gate_id == gate_id
                and item.subject_sha256 == report.input_fingerprint
                and item.scope == final_scope
                for item in state.human_decision_history
            ):
                return "submission-human-approval-required", "current packet requires an authenticated human approval"
            return None

        return self.runtime.execute_transition(
            request,
            additional_prevalidate=validate,
        )

    def qualify_confirmation(
        self,
        submission_id: str,
        subject_scope: str,
        subject_sha256: str,
        request: RuntimeCommandRequest,
    ) -> dict[str, Any]:
        """Record a narrow eligibility gate before an actual human decision.

        This event attests only that the exact field/response subject is
        current and complete enough to show to an accountable human.  It does
        not record agreement and cannot make aggregate readiness PASS.
        """

        if not 1 <= len(subject_scope) <= 256 or any(
            character in subject_scope for character in "\r\n\x00"
        ):
            raise SubmissionWorkflowError("confirmation subject scope is invalid")
        if len(subject_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in subject_sha256
        ):
            raise SubmissionWorkflowError("confirmation subject digest is invalid")
        records = self._accepted()
        packets = [
            item
            for item in records
            if item.kind == "submission-packet"
            and isinstance(item.value, SubmissionPacket)
            and item.value.submission_id == submission_id
        ]
        packet_record = max(
            packets, key=lambda item: (item.value.packet_version, item.sequence), default=None
        )
        if packet_record is None:
            raise SubmissionWorkflowError("submission packet is not accepted")
        subjects = self._confirmation_subjects(packet_record, records, submission_id)
        expected = subjects.get(subject_scope)
        valid = expected is not None and expected[0] == subject_sha256
        evidence = (packet_record.manifest_sha256, *(expected[1] if expected else ()))
        gate_id = confirmation_gate_id(subject_scope)
        decision = GateDecision(
            schema_version="arw.gate-decision.v1",
            gate_id=gate_id,
            subject_sha256=subject_sha256,
            evidence_sha256=tuple(dict.fromkeys(evidence)),
            verdict="PASS" if valid else "BLOCKED",
            rationale=(
                "confirmation subject is current and bound"
                if valid
                else "confirmation subject is unknown or stale"
            ),
            fresh_until=None,
            required=True,
            human_decision=None,
        )
        gate_request = RuntimeCommandRequest(
            schema_version=request.schema_version,
            run_id=request.run_id,
            event_id=_event_id(f"confirmation-gate:{request.command_id}:{subject_scope}"),
            command_id=_command_id(f"confirmation-gate:{request.command_id}:{subject_scope}"),
            expected_revision=request.expected_revision,
            occurred_at=request.occurred_at,
            actor_id=request.actor_id,
            actor_role=request.actor_role,
        )
        payload = GateEvaluatedPayload(
            decision=decision,
            decision_sha256=sha256_hex(canonical_orchestration_model_bytes(decision)),
        )
        gate_outcome = self._existing_gate_outcome(gate_request, payload)
        if gate_outcome is None:
            gate_outcome = self.runtime.append_phase4_event(
                gate_request,
                event_type="gate.evaluated",
                payload=payload,
                prevalidate=lambda state, _replayed: (
                    None
                    if packet_record.manifest_sha256 in state.accepted_artifact_manifest_sha256
                    else ("submission-packet-stale", "confirmation packet head is no longer accepted")
                ),
            )
        return {
            "schema_version": "arw.submission-confirmation-qualification.v1",
            "submission_id": submission_id,
            "subject_scope": subject_scope,
            "subject_sha256": subject_sha256,
            "gate": (
                gate_outcome.model_dump(mode="json")
                if isinstance(gate_outcome, CommandOutcome)
                else gate_outcome
            ),
            "human_decision_required": True,
            "final_submit": "human_only",
        }

    def record_result(
        self,
        observation: SubmissionResultObservation,
        request: ArtifactAcceptanceRequest,
    ) -> dict[str, Any]:
        return self.record(
            "submission-result-observation",
            canonical_json_bytes(observation.model_dump(mode="json")),
            request,
        )

    @staticmethod
    def _confirmation_subjects(
        packet_record: AcceptedSubmissionArtifact,
        records: tuple[AcceptedSubmissionArtifact, ...],
        submission_id: str,
    ) -> dict[str, tuple[str, tuple[str, ...]]]:
        packet = packet_record.value
        assert isinstance(packet, SubmissionPacket)
        subjects: dict[str, tuple[str, tuple[str, ...]]] = {}
        for author in packet.authors:
            for field_name in ("funding", "conflicts", "ethics", "data", "ai_use"):
                field = getattr(author, field_name)
                scope = f"submission:{submission_id}:author:{author.person_id}:{field_name}"
                subjects[scope] = (
                    declaration_subject_sha256(
                        submission_id, author.person_id, field_name, field
                    ),
                    (),
                )
        latest_response: dict[str, AcceptedSubmissionArtifact] = {}
        for item in sorted(records, key=lambda value: value.sequence):
            if (
                item.kind == "submission-response"
                and isinstance(item.value, ReviewResponse)
                and item.value.submission_id == submission_id
            ):
                latest_response[item.value.comment_id] = item
        for item in latest_response.values():
            response = item.value
            assert isinstance(response, ReviewResponse)
            scope = f"submission:{submission_id}:response:{response.comment_id}"
            subjects[scope] = (response_subject_sha256(response), (item.manifest_sha256,))
        return subjects

    def _accepted(self, *, replayed=None) -> tuple[AcceptedSubmissionArtifact, ...]:
        if replayed is None:
            try:
                replayed = replay_run(self.run_root, lock_timeout=self.lock_timeout)
            except (OSError, RuntimeError) as error:
                raise SubmissionWorkflowError(f"cannot replay submission run: {error}") from error
        try:
            validate_accepted_event_manifests(self.run_root, replayed.events)
        except ManifestError as error:
            raise SubmissionWorkflowError("accepted submission manifests are invalid") from error
        records: list[AcceptedSubmissionArtifact] = []
        for event in replayed.events:
            if event.event_type != "artifact.accepted" or not isinstance(
                event.payload, ArtifactAcceptedPayload
            ):
                continue
            try:
                manifest = load_artifact_manifest(self.run_root, event.payload.manifest_sha256)
            except ManifestError:
                continue
            model = SUBMISSION_ARTIFACT_MODELS.get(manifest.artifact_kind)
            if model is None:
                continue
            try:
                raw = read_retained_bytes(
                    self.run_root,
                    manifest.content_path,
                    max_bytes=_MAX_SUBMISSION_JSON_BYTES,
                )
                if sha256_hex(raw) != event.payload.artifact_sha256:
                    raise SubmissionWorkflowError(
                        "accepted submission artifact content digest mismatch"
                    )
                value = model.model_validate_json(raw, strict=True)
            except SubmissionWorkflowError:
                raise
            except (OSError, UnicodeError, ValueError):
                continue
            records.append(
                AcceptedSubmissionArtifact(
                    kind=manifest.artifact_kind,
                    artifact_id=event.payload.artifact_id,
                    event_id=event.event_id,
                    sequence=event.sequence,
                    manifest_sha256=event.payload.manifest_sha256,
                    content_sha256=event.payload.artifact_sha256,
                    value=value,
                )
            )
        return tuple(records)

    def _existing_artifact_outcome(
        self,
        request: ArtifactAcceptanceRequest,
        kind: str,
        content_sha256: str,
    ) -> dict[str, Any] | None:
        """Resume an exact artifact command without appending a duplicate event."""

        try:
            replayed = replay_run(self.run_root, lock_timeout=self.lock_timeout)
        except (OSError, RuntimeError) as error:
            raise SubmissionWorkflowError(f"cannot replay submission run: {error}") from error
        event = next(
            (item for item in replayed.events if item.command_id == request.command_id),
            None,
        )
        if event is None:
            return None
        state = self.runtime.read_state()
        if event.event_type != "artifact.accepted" or not isinstance(
            event.payload, ArtifactAcceptedPayload
        ):
            return {
                "accepted": False,
                "event": None,
                "rejection": {
                    "code": "duplicate-command-conflict",
                    "message": "command ID is already bound to another operation",
                },
                "state": state.model_dump(mode="json"),
                "artifact_kind": kind,
            }
        try:
            manifest = load_artifact_manifest(self.run_root, event.payload.manifest_sha256)
        except ManifestError as error:
            raise SubmissionWorkflowError("existing artifact command has an invalid manifest") from error
        exact = (
            event.event_id == request.event_id
            and event.payload.artifact_id == request.artifact_id
            and event.payload.artifact_sha256 == content_sha256
            and manifest.artifact_kind == kind
        )
        if not exact:
            return {
                "accepted": False,
                "event": None,
                "rejection": {
                    "code": "duplicate-command-conflict",
                    "message": "command identity was reused with changed submission input",
                },
                "state": state.model_dump(mode="json"),
                "artifact_kind": kind,
            }
        return {
            "accepted": True,
            "event": event.model_dump(mode="json"),
            "rejection": None,
            "state": state.model_dump(mode="json"),
            "artifact_kind": kind,
        }

    def _existing_gate_outcome(
        self, request: RuntimeCommandRequest, payload: GateEvaluatedPayload
    ) -> dict[str, Any] | None:
        try:
            replayed = replay_run(self.run_root, lock_timeout=self.lock_timeout)
        except (OSError, RuntimeError) as error:
            raise SubmissionWorkflowError(f"cannot replay submission run: {error}") from error
        event = next(
            (item for item in replayed.events if item.command_id == request.command_id),
            None,
        )
        if event is None:
            return None
        state = self.runtime.read_state()
        if event.event_type != "gate.evaluated" or not isinstance(
            event.payload, GateEvaluatedPayload
        ) or event.event_id != request.event_id:
            return {
                "accepted": False,
                "event": None,
                "rejection": {
                    "code": "duplicate-command-conflict",
                    "message": "gate command identity is already bound to another operation",
                },
                "state": state.model_dump(mode="json"),
            }
        if event.payload.decision_sha256 != payload.decision_sha256:
            return {
                "accepted": False,
                "event": None,
                "rejection": {
                    "code": "duplicate-command-conflict",
                    "message": "gate command was retried with changed readiness input",
                },
                "state": state.model_dump(mode="json"),
            }
        return {
            "accepted": True,
            "event": event.model_dump(mode="json"),
            "rejection": None,
            "state": state.model_dump(mode="json"),
        }

    def _existing_transition_outcome(
        self, request: LifecycleTransitionRequest
    ) -> CommandOutcome | None:
        try:
            replayed = replay_run(self.run_root, lock_timeout=self.lock_timeout)
        except (OSError, RuntimeError) as error:
            raise SubmissionWorkflowError(f"cannot replay submission run: {error}") from error
        event = next(
            (item for item in replayed.events if item.command_id == request.command_id),
            None,
        )
        if event is None:
            return None
        state = self.runtime.read_state()
        if (
            event.event_type != "lifecycle.transitioned"
            or not isinstance(event.payload, LifecycleTransitionedPayload)
            or event.event_id != request.event_id
            or event.payload.transition_id != request.transition_id
            or event.payload.from_stage != request.from_stage
        ):
            return self.runtime._rejection(
                state,
                "duplicate-command-conflict",
                "ready transition command identity is already bound to another operation",
            )
        return CommandOutcome(accepted=True, state=state, event=event)

    def _validate_gate_inputs(
        self, state, replayed, report, report_manifest: str, evaluation: dict[str, Any]
    ):
        if report.packet_manifest_sha256 not in state.accepted_artifact_manifest_sha256:
            return "submission-packet-unknown", "packet manifest is not accepted"
        if report_manifest not in state.accepted_artifact_manifest_sha256:
            return "submission-report-unknown", "check report manifest is not accepted"
        records = self._accepted(replayed=replayed)
        packets = [
            item
            for item in records
            if item.kind == "submission-packet"
            and isinstance(item.value, SubmissionPacket)
            and item.value.submission_id == report.submission_id
        ]
        current = max(packets, key=lambda item: (item.value.packet_version, item.sequence), default=None)
        if current is None or current.manifest_sha256 != report.packet_manifest_sha256:
            return "submission-packet-stale", "qualification report is not bound to the current packet head"
        if evaluation["readiness"]["input_fingerprint"] != report.input_fingerprint:
            return "submission-report-stale", "qualification report fingerprint is stale"
        return None

    @staticmethod
    def _dependency_hashes(
        packet_record: AcceptedSubmissionArtifact,
        records: tuple[AcceptedSubmissionArtifact, ...],
        submission_id: str,
        *,
        state=None,
    ) -> tuple[str, ...]:
        packet = packet_record.value
        assert isinstance(packet, SubmissionPacket)
        values = [
            packet_record.manifest_sha256,
            packet.manuscript.manifest_sha256,
            packet.manuscript.content_sha256,
            packet.policy_snapshot.manifest_sha256,
            packet.policy_snapshot.content_sha256,
            *(item.artifact.manifest_sha256 for item in packet.components),
            *(item.artifact.content_sha256 for item in packet.components),
            *(item.manifest_sha256 for item in packet.audit_evidence),
            *(item.manifest_sha256 for item in packet.response_evidence),
        ]
        values.extend(
            item.manifest_sha256
            for item in records
            if getattr(item.value, "submission_id", None) == submission_id
            and item.kind in {"submission-review-round", "submission-response"}
        )
        if state is not None:
            values.extend(
                item.decision_sha256
                for item in state.human_decision_history
                if item.scope.startswith(f"submission:{submission_id}:")
                and item.scope != f"submission:{submission_id}:ready"
            )
        values.extend(
            SubmissionWorkflowService._dependency_fingerprints(
                packet_record,
                records,
                submission_id,
                state=state,
            ).values()
        )
        return tuple(dict.fromkeys(values))

    @staticmethod
    def _dependency_fingerprints(
        packet_record: AcceptedSubmissionArtifact,
        records: tuple[AcceptedSubmissionArtifact, ...],
        submission_id: str,
        *,
        state=None,
    ) -> dict[str, str]:
        """Build category-level fingerprints for conservative check reuse.

        A check may bind its ``input_sha256`` to one category digest instead
        of the aggregate fingerprint.  That lets an unchanged scientific
        check remain historically useful when, for example, only an author
        disclosure changes; the aggregate readiness result still becomes
        stale until a new report is recorded.
        """

        packet = packet_record.value
        assert isinstance(packet, SubmissionPacket)
        kind_by_artifact = {item.artifact_id: item.kind for item in records}
        components = tuple(
            {
                "component_id": item.component_id,
                "role": item.role,
                "artifact": item.artifact.model_dump(mode="json"),
                "media_type": item.media_type,
                "byte_length": item.byte_length,
            }
            for item in packet.components
        )
        review_values = tuple(
            item.value.model_dump(mode="json")
            for item in records
            if item.kind in {"submission-review-round", "submission-response"}
            and getattr(item.value, "submission_id", None) == submission_id
        )
        render_values = [
            item.artifact.model_dump(mode="json")
            for item in packet.components
            if "pdf" in item.media_type.lower() or "render" in item.media_type.lower()
        ]
        render_values.extend(
            locator.model_dump(mode="json")
            for item in records
            if item.kind == "submission-response"
            and isinstance(item.value, ReviewResponse)
            and item.value.submission_id == submission_id
            for locator in item.value.locations
            if locator.render_sha256 is not None
        )
        bibliography_values = [
            item.artifact.model_dump(mode="json")
            for item in packet.components
            if "bib" in item.media_type.lower()
            or "bibliograph" in kind_by_artifact.get(item.artifact.artifact_id, "").lower()
        ]
        author_decisions = tuple(
            item.decision_sha256
            for item in (state.human_decision_history if state is not None else ())
            if item.scope.startswith(f"submission:{submission_id}:")
            and item.scope != f"submission:{submission_id}:ready"
        )
        payloads = {
            "manuscript": packet.manuscript.model_dump(mode="json"),
            "bibliography": bibliography_values,
            "render": render_values,
            "policy": packet.policy_snapshot.model_dump(mode="json"),
            "roster": tuple(
                {
                    "person_id": item.person_id,
                    "display_name": item.display_name,
                    "order": item.order,
                    "corresponding": item.corresponding,
                }
                for item in packet.authors
            ),
            "contributions": tuple(
                {"person_id": item.person_id, "contributions": item.contributions}
                for item in packet.authors
            ),
            "disclosures": tuple(
                {
                    "person_id": item.person_id,
                    "funding": item.funding.model_dump(mode="json"),
                    "conflicts": item.conflicts.model_dump(mode="json"),
                    "ethics": item.ethics.model_dump(mode="json"),
                    "data": item.data.model_dump(mode="json"),
                    "ai_use": item.ai_use.model_dump(mode="json"),
                }
                for item in packet.authors
            ),
            "attachments": components,
            "responses": review_values,
            "author_decisions": author_decisions,
        }
        return {
            category: sha256_hex(
                canonical_json_bytes({"category": category, "value": value})
            )
            for category, value in payloads.items()
        }

    @staticmethod
    def _redacted_packet(packet: SubmissionPacket) -> dict[str, Any]:
        result = packet.model_dump(mode="json")
        for author in result.get("authors", []):
            author["display_name"] = "[redacted]"
            for name in ("funding", "conflicts", "ethics", "data", "ai_use"):
                field = author.get(name)
                if isinstance(field, dict):
                    field["value"] = None
                    field["rationale"] = None
        return result

    @staticmethod
    def _redacted_report(report: SubmissionCheckReport) -> dict[str, Any]:
        return {
            "schema_version": report.schema_version,
            "report_id": report.report_id,
            "submission_id": report.submission_id,
            "packet_manifest_sha256": report.packet_manifest_sha256,
            "input_fingerprint": report.input_fingerprint,
            "evaluated_at": report.evaluated_at,
            "valid_until": report.valid_until,
            "readiness": report.readiness,
            "reason_codes": list(report.reason_codes),
            "checks": [
                {
                    "check_id": item.check_id,
                    "check_kind": item.check_kind,
                    "applicability": item.applicability,
                    "status": item.status,
                    "source_identity": item.source_identity,
                    "source_version": item.source_version,
                    "input_sha256": item.input_sha256,
                    "output_sha256": item.output_sha256,
                    "evidence_count": len(item.evidence),
                    "valid_until": item.valid_until,
                }
                for item in report.checks
            ],
        }

    @staticmethod
    def _encode_cursor(head: str, offset: int) -> str:
        raw = canonical_json_bytes({"head": head, "offset": offset})
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str | None, head: str) -> int:
        if cursor is None:
            return 0
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            import json

            value = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
            if value.get("head") != head or not isinstance(value.get("offset"), int):
                raise ValueError
            offset = value["offset"]
            if offset < 0:
                raise ValueError
            return offset
        except (ValueError, TypeError, UnicodeError, KeyError) as error:
            raise SubmissionWorkflowError("submission status cursor is stale or invalid") from error

    @staticmethod
    def _outcome_json(outcome: CommandOutcome, *, kind: str) -> dict[str, Any]:
        result = outcome.model_dump(mode="json")
        result["artifact_kind"] = kind
        return result


__all__ = [
    "SUBMISSION_ARTIFACT_MODELS",
    "SubmissionWorkflowError",
    "SubmissionWorkflowService",
    "validate_submission_payload",
]
