"""Parent-owned Phase 4 orchestration lifecycle.

The service in this module is deliberately a coordinator, not a second
ledger.  It creates immutable manifests and turns observations into typed
requests for :class:`arw.runtime.RuntimeCommandService`; only that runtime
service can append canonical events.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex, strict_json_loads
from arw.execution import (
    DEFAULT_EXECUTION_POLICY,
    DispatchSpec,
    ExecutionAdapter,
    ExecutionPolicySnapshot,
    HostResult,
    RepairableEnvelopeFailure,
    StaleAttempt,
)
from arw.kernel.core.faults import inject
from arw.kernel.ledger.journal import replay_run
from arw.kernel.ledger.manifests import (
    ManifestError,
    admit_raw_proposal,
    install_assignment_manifest,
    materialize_attempt_tree,
)
from arw.kernel.state.models import (
    AssignmentPreparedPayload,
    AssignmentSupersededPayload,
    AttemptLifecyclePayload,
    AttemptPreparedPayload,
    ExecutionModeSelectedPayload,
    ExecutionRoleMode,
    GateEvaluatedPayload,
    HostIdentityAcceptedPayload,
    HookObservedPayload,
    HumanAuthorityAcceptedPayload,
    HumanDecisionRecordedPayload,
    LifecycleTransitionRequest,
    PanelPreparedPayload,
    ProposalAcceptedPayload,
    ProposalRejectedPayload,
    ReviewReportAcceptedPayload,
    ReviewSynthesisAcceptedPayload,
    RuntimeCommandRequest,
    RunManifest,
    StrictModel,
)
from arw.kernel.state.orchestration_models import (
    AttemptDescriptor,
    AttemptStatus,
    AssignmentKey,
    BlindReviewConstraints,
    CompletionContract,
    ExecutionMode,
    GateDecision,
    FORMAL_REVIEW_ROLE_IDS,
    HookObservation as CanonicalHookObservation,
    HostIdentityReceipt,
    HumanAuthority,
    HumanDecisionRecord,
    ImmutableAssignment,
    OutputPolicy,
    PanelManifest,
    PanelSeat,
    ReviewFindingMatrix,
    ReviewReport as WireReviewReport,
    RetryReason,
    WorkerProposal,
    canonical_orchestration_model_bytes,
    locked_role_catalog,
)
from arw.kernel.ledger.reducer import RuntimeState
from arw.review import FormalPanelPolicy, PanelPlan, ReviewerIdentity
from arw.runtime import CommandOutcome, RuntimeCommandService
from arw.scheduler import AttemptOutcome, DeterministicScheduler, ScheduledOutcome
from arw.kernel.ledger.workflows import PHASE4_WORKFLOW_ID


class OrchestrationError(RuntimeError):
    """A parent lifecycle request could not be prepared or admitted."""


def _deterministic_uuid(seed: str) -> str:
    value = uuid.uuid5(uuid.NAMESPACE_URL, f"arw-phase4:{seed}")
    # The wire contracts use UUID4-shaped identifiers, while the bytes remain
    # deterministic for replay and fixture generation.
    value = uuid.UUID(bytes=value.bytes, version=4)
    return value.hex


def _event_id(seed: str) -> str:
    value = _deterministic_uuid(f"event:{seed}")
    return f"evt-{value[:8]}-{value[8:12]}-{value[12:16]}-{value[16:20]}-{value[20:]}"


def _command_id(seed: str) -> str:
    value = _deterministic_uuid(f"command:{seed}")
    return f"cmd-{value[:8]}-{value[8:12]}-{value[12:16]}-{value[16:20]}-{value[20:]}"


def _utc_after(value: str, seconds: float) -> str:
    instant = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return (instant + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _schema_digest(name: str) -> str:
    from arw.kernel.state.orchestration_models import generate_phase4_schema_documents

    document = generate_phase4_schema_documents()[name]
    return sha256_hex(canonical_json_bytes(document))


@dataclass(frozen=True, slots=True)
class AssignmentSpec:
    """The small, parent-authored input from which an assignment is frozen."""

    assignment_id: str
    stage_id: str
    task_id: str
    role_id: str
    worker_identity_id: str
    acceptance_key: tuple[int, int]
    input_sha256: tuple[str, ...] = ()
    capability_ids: tuple[str, ...] = ("files.read",)
    allowed_read_root_ids: tuple[str, ...] = ("research-root",)
    independence_eligible: bool | None = None
    blind_review_required: bool = False
    subject_sha256: str | None = None
    rubric_sha256: str | None = None
    forbidden_peer_role_ids: tuple[str, ...] = ()
    required_artifact_kinds: tuple[str, ...] = ("proposal",)
    requires_human_gate: bool = False
    supersedes_assignment_id: str | None = None

    def __post_init__(self) -> None:
        if len(self.acceptance_key) != 2 or any(
            not isinstance(value, int) or value < 0 for value in self.acceptance_key
        ):
            raise ValueError("acceptance_key must be two non-negative integers")
        if len(set(self.input_sha256)) != len(self.input_sha256):
            raise ValueError("assignment inputs must be unique")
        if len(set(self.capability_ids)) != len(self.capability_ids):
            raise ValueError("assignment capabilities must be unique")


@dataclass(frozen=True, slots=True)
class PreparedRun:
    state: RuntimeState
    assignments: tuple[ImmutableAssignment, ...]
    role_catalog_sha256: str
    policy_sha256: str
    dag_sha256: str
    execution_mode: ExecutionMode


@dataclass(frozen=True, slots=True)
class DispatchReport:
    state: RuntimeState
    outcomes: tuple[ScheduledOutcome, ...]


class OrchestrationService:
    """Freeze, dispatch, and admit Phase 4 work through the sole writer."""

    def __init__(
        self,
        run_root: Path,
        *,
        adapter: ExecutionAdapter,
        policy: ExecutionPolicySnapshot = DEFAULT_EXECUTION_POLICY,
        lock_timeout: float = 0.2,
    ) -> None:
        self.run_root = run_root
        self.runtime = RuntimeCommandService(run_root, lock_timeout=lock_timeout)
        self.adapter = adapter
        self.policy = policy
        self.scheduler = DeterministicScheduler(adapter, policy=policy)

    def _manifest(self) -> RunManifest:
        path = self.run_root / "run-manifest.json"
        if path.is_symlink() or not path.is_file():
            raise OrchestrationError("run manifest is missing or unsafe")
        try:
            raw = path.read_bytes()
            manifest = RunManifest.model_validate(strict_json_loads(raw))
        except (OSError, UnicodeError, ValueError) as error:
            raise OrchestrationError(f"run manifest is invalid: {error}") from error
        if canonical_json_bytes(manifest.model_dump(mode="json", exclude_none=True)) != raw:
            raise OrchestrationError("run manifest is not canonical")
        return manifest

    @staticmethod
    def _child_request(
        base: RuntimeCommandRequest,
        *,
        revision: int,
        label: str,
        model: type[RuntimeCommandRequest] = RuntimeCommandRequest,
        **extra: object,
    ) -> RuntimeCommandRequest:
        payload = {
            key: getattr(base, key)
            for key in (
                "schema_version",
                "run_id",
                "occurred_at",
                "actor_id",
                "actor_role",
            )
        }
        payload.update(
            {
            "event_id": _event_id(f"{base.run_id}:{label}:{revision}"),
            "command_id": _command_id(f"{base.run_id}:{label}:{revision}"),
            "expected_revision": revision,
            **extra,
            }
        )
        return model.model_validate(payload)

    @staticmethod
    def _require_parent(request: RuntimeCommandRequest) -> None:
        if request.actor_role != "parent_control_plane":
            raise OrchestrationError("Phase 4 orchestration commands require parent_control_plane")

    @staticmethod
    def _write_immutable(path: Path, raw: bytes) -> None:
        """Install an evidence envelope once without making it canonical state."""

        if path.is_symlink():
            raise OrchestrationError(f"immutable evidence path is a symlink: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != raw:
                raise OrchestrationError(f"immutable evidence was changed: {path}")
            return
        path.write_bytes(raw)

    def _append_gate_decision(
        self, request: RuntimeCommandRequest, decision: GateDecision
    ) -> CommandOutcome:
        return self.runtime.append_phase4_event(
            request,
            event_type="gate.evaluated",
            payload=GateEvaluatedPayload(
                decision=decision,
                decision_sha256=sha256_hex(canonical_orchestration_model_bytes(decision)),
            ),
        )

    def record_host_identity(
        self,
        request: RuntimeCommandRequest,
        receipt: HostIdentityReceipt,
    ) -> CommandOutcome:
        """Accept retained host identity evidence through the sole writer."""

        self._require_parent(request)

        def validate(state: RuntimeState, _replayed):
            if any(
                digest not in self._known_evidence(state)
                for digest in receipt.evidence_sha256
            ):
                return "host-evidence-unknown", "host identity evidence is not canonical"
            return None

        return self.runtime.append_phase4_event(
            request,
            event_type="host_identity.accepted",
            payload=HostIdentityAcceptedPayload(
                receipt=receipt,
                receipt_sha256=receipt.receipt_sha256,
            ),
            prevalidate=validate,
        )

    def record_human_authority(
        self,
        request: RuntimeCommandRequest,
        authority: HumanAuthority,
    ) -> CommandOutcome:
        """Accept an authenticated authority envelope before any decision."""

        self._require_parent(request)

        def validate(state: RuntimeState, _replayed):
            if authority.validated_by_actor_id != request.actor_id:
                return "authority-validator-mismatch", "authority validator differs from parent"
            if not (
                authority.authenticated_at <= request.occurred_at <= authority.expires_at
            ):
                return "authority-expired", "authority is outside its authentication window"
            if any(
                digest not in self._known_evidence(state)
                for digest in authority.evidence_sha256
            ):
                return "authority-evidence-unknown", "authority evidence is not canonical"
            return None

        return self.runtime.append_phase4_event(
            request,
            event_type="human_authority.accepted",
            payload=HumanAuthorityAcceptedPayload(
                authority=authority,
                authority_sha256=authority.authority_sha256,
            ),
            prevalidate=validate,
        )

    def prepare_formal_panel(
        self,
        request: RuntimeCommandRequest,
        *,
        panel_id: str,
        subject_sha256: str,
        rubric_sha256: str,
        reviewer_identities: Mapping[str, ReviewerIdentity | Mapping[str, object]],
        synthesizer_identity: ReviewerIdentity | Mapping[str, object] | None,
        policy: FormalPanelPolicy | None = None,
        execution_mode: ExecutionMode = "assignment_injected_subagent",
    ) -> PanelPlan:
        """Freeze a formal panel envelope before any report can be admitted."""

        self._require_parent(request)
        if "/" in panel_id or "\\" in panel_id:
            raise OrchestrationError("panel ID must be a single safe path component")
        state = self.runtime.read_state()
        if state.accepted_revision != request.expected_revision:
            raise OrchestrationError("formal panel request revision is stale")
        receipts = {
            item.receipt_sha256: item.receipt for item in state.host_identity_receipts
        }
        validated_reviewers: dict[str, ReviewerIdentity] = {}
        for role, claimed in reviewer_identities.items():
            digest = (
                claimed.identity_receipt_sha256
                if isinstance(claimed, ReviewerIdentity)
                else claimed.get("identity_receipt_sha256")
            )
            receipt = receipts.get(str(digest)) if digest is not None else None
            if receipt is None or receipt.role_id != role:
                continue
            validated_reviewers[role] = ReviewerIdentity(
                worker_identity_id=receipt.worker_identity_id,
                host_agent_id=receipt.host_agent_id,
                isolated=receipt.isolation_proven and receipt.peer_isolation_proven,
                role_ids=(role,),
                identity_receipt_sha256=str(digest),
            )
        validated_synthesizer: ReviewerIdentity | None = None
        if synthesizer_identity is not None:
            digest = (
                synthesizer_identity.identity_receipt_sha256
                if isinstance(synthesizer_identity, ReviewerIdentity)
                else synthesizer_identity.get("identity_receipt_sha256")
            )
            receipt = receipts.get(str(digest)) if digest is not None else None
            if receipt is not None and receipt.role_id == "editorial_synthesizer":
                validated_synthesizer = ReviewerIdentity(
                    worker_identity_id=receipt.worker_identity_id,
                    host_agent_id=receipt.host_agent_id,
                    isolated=receipt.isolation_proven and receipt.peer_isolation_proven,
                    role_ids=("editorial_synthesizer",),
                    identity_receipt_sha256=str(digest),
                )
        panel = (policy or FormalPanelPolicy()).prepare_panel(
            panel_id=panel_id,
            subject_sha256=subject_sha256,
            rubric_sha256=rubric_sha256,
            reviewer_identities=validated_reviewers,
            synthesizer_identity=validated_synthesizer,
            execution_mode=execution_mode,
            isolated_assignments=True,
        )
        panel_root = self.run_root / "panels" / panel_id / "reviewers"
        for assignment in panel.reviewer_assignments:
            self._write_immutable(
                panel_root / f"{assignment.assignment_id}.json",
                canonical_json_bytes(assignment.visible_payload),
            )
        manifest = PanelManifest(
            schema_version="arw.panel-manifest.v1",
            panel_id=panel.panel_id,
            subject_sha256=panel.subject_sha256,
            rubric_sha256=panel.rubric_sha256,
            policy_sha256=panel.policy_sha256,
            execution_mode=(execution_mode if panel.status == "ready" else "blocked"),
            status=panel.status,
            reviewer_seats=tuple(
                PanelSeat(
                    assignment_id=assignment.assignment_id,
                    attempt_id=assignment.attempt_id,
                    role_id=assignment.role_id,
                    worker_identity_id=assignment.worker_identity_id,
                    host_agent_id=assignment.host_agent_id,
                    identity_receipt_sha256=assignment.identity_receipt_sha256,
                    acceptance_key=assignment.acceptance_key,
                    blind_envelope_sha256=assignment.blind_envelope.envelope_sha256,
                    required=assignment.required,
                    round_number=assignment.round_number,
                    synthesizer=False,
                )
                for assignment in panel.reviewer_assignments
            ),
            synthesizer_seat=(
                PanelSeat(
                    assignment_id=panel.synthesizer_assignment.assignment_id,
                    attempt_id=panel.synthesizer_assignment.attempt_id,
                    role_id=panel.synthesizer_assignment.role_id,
                    worker_identity_id=panel.synthesizer_assignment.worker_identity_id,
                    host_agent_id=panel.synthesizer_assignment.host_agent_id,
                    identity_receipt_sha256=panel.synthesizer_assignment.identity_receipt_sha256,
                    acceptance_key=panel.synthesizer_assignment.acceptance_key,
                    blind_envelope_sha256=panel.synthesizer_assignment.blind_envelope.envelope_sha256,
                    required=True,
                    round_number=panel.synthesizer_assignment.round_number,
                    synthesizer=True,
                )
                if panel.synthesizer_assignment is not None
                else None
            ),
            required_report_roles=tuple(sorted(FORMAL_REVIEW_ROLE_IDS)),
            blockers=panel.blockers,
            limitations=panel.limitations,
        )
        prepared_panel = self.runtime.append_phase4_event(
            request,
            event_type="panel.prepared",
            payload=PanelPreparedPayload(
                manifest=manifest,
                manifest_sha256=manifest.manifest_sha256,
            ),
        )
        self._require_accepted(prepared_panel, "formal panel manifest")
        panel = replace(panel, manifest_sha256=manifest.manifest_sha256)
        if panel.status == "blocked":
            decision = GateDecision(
                schema_version="arw.gate-decision.v1",
                gate_id=f"gate.{panel_id}",
                subject_sha256=subject_sha256,
                evidence_sha256=(manifest.manifest_sha256,),
                verdict="BLOCKED",
                rationale="formal panel blocked: " + "; ".join(panel.blockers),
                fresh_until=None,
                required=True,
                human_decision=None,
            )
            outcome = self._append_gate_decision(
                self._child_request(
                    request,
                    revision=prepared_panel.state.accepted_revision,
                    label=f"panel-blocked:{panel_id}",
                ),
                decision,
            )
            self._require_accepted(outcome, "formal panel blocker")
        return panel

    @staticmethod
    def _panel_reviewer(panel: PanelPlan, role_id: str):
        return next(
            (item for item in panel.reviewer_assignments if item.role_id == role_id),
            None,
        )

    def admit_review_report(
        self,
        request: RuntimeCommandRequest,
        *,
        panel: PanelPlan,
        report: WireReviewReport,
    ) -> CommandOutcome:
        """Admit one parent-validated report, never a reviewer-authored event."""

        self._require_parent(request)
        if panel.status != "ready":
            raise OrchestrationError("blocked formal panels cannot admit reports")
        if panel.manifest_sha256 is None:
            raise OrchestrationError("panel has no canonical manifest binding")
        current = self.runtime.read_state()
        manifest = next(
            (
                item
                for item in current.panel_manifests
                if item.manifest_sha256 == panel.manifest_sha256
            ),
            None,
        )
        if manifest is None or manifest.status != "ready":
            raise OrchestrationError("panel manifest is not canonical and ready")
        assignment = next(
            (
                item
                for item in manifest.reviewer_seats
                if item.assignment_id == report.assignment_id
            ),
            None,
        )
        if assignment is None:
            raise OrchestrationError("report assignment is not a canonical panel seat")
        if (
            report.worker_identity_id != assignment.worker_identity_id
            or report.host_agent_id != assignment.host_agent_id
            or report.role_id != assignment.role_id
            or report.attempt_id != assignment.attempt_id
            or report.identity_receipt_sha256 != assignment.identity_receipt_sha256
            or report.panel_manifest_sha256 != panel.manifest_sha256
            or report.subject_sha256 != manifest.subject_sha256
            or report.rubric_sha256 != manifest.rubric_sha256
        ):
            raise OrchestrationError("formal report identity or frozen snapshot does not echo assignment")
        if report.role_id not in FORMAL_REVIEW_ROLE_IDS:
            raise OrchestrationError("only the four required formal reviewer roles may report")
        if any(item.report_id == report.report_id for item in current.panel_reports):
            raise OrchestrationError("formal report ID was already admitted")
        return self.runtime.append_phase4_event(
            request,
            event_type="review.report_accepted",
            payload=ReviewReportAcceptedPayload(
                report=report,
                report_sha256=report.report_sha256,  # type: ignore[arg-type]
            ),
        )

    def admit_review_synthesis(
        self,
        request: RuntimeCommandRequest,
        *,
        panel: PanelPlan,
        finding_matrix: ReviewFindingMatrix,
    ) -> CommandOutcome:
        """Admit editorial synthesis only after all four reports are canonical."""

        self._require_parent(request)
        if panel.status != "ready" or panel.synthesizer_assignment is None:
            raise OrchestrationError("blocked formal panels cannot admit synthesis")
        if panel.manifest_sha256 is None:
            raise OrchestrationError("panel has no canonical manifest binding")
        if (
            finding_matrix.panel_id != panel.panel_id
            or finding_matrix.panel_manifest_sha256 != panel.manifest_sha256
        ):
            raise OrchestrationError("finding matrix panel ID is stale")
        current = self.runtime.read_state()
        manifest = next(
            (
                item
                for item in current.panel_manifests
                if item.manifest_sha256 == panel.manifest_sha256
            ),
            None,
        )
        if manifest is None or manifest.status != "ready":
            raise OrchestrationError("panel manifest is not canonical and ready")
        accepted_reports = {
            item.report_sha256: item
            for item in current.panel_reports
            if item.panel_manifest_sha256 == panel.manifest_sha256
        }
        required = set(finding_matrix.synthesis.source_report_sha256)
        if required != set(accepted_reports):
            raise OrchestrationError("synthesis requires all four accepted source reports")
        if {
            item.report_sha256 for item in finding_matrix.reports
        } != set(accepted_reports):
            raise OrchestrationError("synthesis report bodies differ from canonical reports")
        expected_roles = {item.role_id for item in manifest.reviewer_seats}
        if {item.role_id for item in finding_matrix.reports} != expected_roles:
            raise OrchestrationError("synthesis does not cover the frozen four-role panel")
        synth = manifest.synthesizer_seat
        if synth is None:
            raise OrchestrationError("canonical panel has no synthesizer seat")
        if (
            finding_matrix.synthesis.worker_identity_id != synth.worker_identity_id
            or finding_matrix.synthesis.host_agent_id != synth.host_agent_id
            or finding_matrix.synthesis.identity_receipt_sha256
            != synth.identity_receipt_sha256
        ):
            raise OrchestrationError("editorial synthesis identity is not independent")
        self._write_immutable(
            self.run_root
            / "panels"
            / panel.panel_id
            / "synthesis.json",
            canonical_json_bytes(
                {
                    "panel_id": panel.panel_id,
                    "assignment_id": synth.assignment_id,
                    "role_id": synth.role_id,
                    "subject_sha256": manifest.subject_sha256,
                    "rubric_sha256": manifest.rubric_sha256,
                    "policy_sha256": manifest.policy_sha256,
                    "accepted_report_sha256": finding_matrix.synthesis.source_report_sha256,
                }
            ),
        )
        return self.runtime.append_phase4_event(
            request,
            event_type="review.synthesis_accepted",
            payload=ReviewSynthesisAcceptedPayload(
                finding_matrix=finding_matrix,
                finding_matrix_sha256=sha256_hex(
                    canonical_orchestration_model_bytes(finding_matrix)
                ),
            ),
        )

    def record_hook_observation(
        self,
        request: RuntimeCommandRequest,
        observation: CanonicalHookObservation | object,
    ) -> CommandOutcome:
        """Record a hook observation; continuation authority remains with the parent."""

        self._require_parent(request)
        if hasattr(observation, "to_orchestration_observation"):
            observation = observation.to_orchestration_observation()  # type: ignore[union-attr]
        if not isinstance(observation, CanonicalHookObservation):
            raise OrchestrationError("hook output is not a canonical observation")
        return self.runtime.append_phase4_event(
            request,
            event_type="hook.observed",
            payload=HookObservedPayload(
                observation=observation,
                observation_sha256=observation.observation_sha256,
            ),
        )

    @staticmethod
    def _known_evidence(state: RuntimeState) -> set[str]:
        evidence = {
            state.ledger_head_sha256,
            *state.canonical_event_sha256,
            *state.accepted_evidence_sha256,
            *state.accepted_proposal_sha256,
            *state.accepted_artifact_manifest_sha256,
            *state.accepted_passport_sha256,
        }
        evidence.update(
            getattr(item, "report_sha256")
            for item in state.panel_reports
            if getattr(item, "report_sha256", None)
        )
        return evidence

    def evaluate_gate(
        self,
        request: RuntimeCommandRequest,
        decision: GateDecision,
    ) -> CommandOutcome:
        """Evaluate a gate from current evidence and fail closed on stale inputs."""

        self._require_parent(request)
        if decision.human_decision is not None:
            raise OrchestrationError("human decisions must use the append-only decision route")
        state = self.runtime.read_state()
        unknown = tuple(item for item in decision.evidence_sha256 if item not in self._known_evidence(state))
        stale = (
            decision.fresh_until is not None
            and request.occurred_at > decision.fresh_until
        )
        blockers = tuple(item.code for item in state.blockers)
        reasons: list[str] = []
        if unknown:
            reasons.append("evidence is not accepted by the parent")
        if stale:
            reasons.append("evidence freshness window has expired")
        if decision.verdict == "PASS" and blockers:
            reasons.append("existing runtime blockers: " + ", ".join(blockers))
        if reasons:
            decision = decision.model_copy(
                update={
                    "verdict": "BLOCKED",
                    "rationale": decision.rationale + " blocked: " + "; ".join(reasons),
                }
            )
        return self._append_gate_decision(request, decision)

    def record_human_decision(
        self,
        request: RuntimeCommandRequest,
        decision: HumanDecisionRecord,
    ) -> CommandOutcome:
        """Append a scoped human action without rewriting a gate or its evidence."""

        self._require_parent(request)

        def validate(state: RuntimeState, _replayed):
            gate = next((item for item in state.gates if item.gate_id == decision.gate_id), None)
            if gate is None:
                return "unknown-gate", "human decision references an unknown gate"
            if gate.subject_sha256 != decision.subject_sha256:
                return "subject-mismatch", "human decision subject differs from the gate"
            if gate.decision_sha256 != decision.prior_verdict_sha256:
                return "prior-verdict-mismatch", "human decision does not bind the exact gate hash"
            authority_state = next(
                (
                    item
                    for item in state.human_authorities
                    if item.authority_sha256 == decision.authority_sha256
                ),
                None,
            )
            if authority_state is None:
                return "authority-unknown", "human decision authority is not canonical"
            authority = authority_state.authority
            if (
                authority.validated_by_actor_id != request.actor_id
                or authority.authenticated_actor_id != decision.accountable_actor_id
                or authority.accountable_role != decision.accountable_role
                or decision.decision_kind not in authority.allowed_decision_kinds
                or decision.gate_id not in authority.allowed_gate_ids
                or decision.scope not in authority.allowed_scopes
                or request.occurred_at > authority.expires_at
            ):
                return "authority-scope-mismatch", "human decision exceeds authenticated authority"
            if any(item not in self._known_evidence(state) for item in decision.evidence_sha256):
                return "human-evidence-unknown", "human decision evidence is not accepted"
            if decision.decision_kind == "approval":
                if gate.verdict != "PASS":
                    return "approval-blocked", "approval requires a fresh PASS gate"
                if decision.applicable_transition not in state.legal_next_transitions:
                    return "invalid-decision-transition", "approval names a non-legal transition"
                if gate.decision.fresh_until and request.occurred_at > gate.decision.fresh_until:
                    return "evidence-expired", "approval evidence is stale"
            elif decision.decision_kind == "waiver":
                if (
                    gate.verdict != "BLOCKED"
                    or decision.scope != decision.gate_id
                    or decision.blocker_action != "release"
                    or decision.blocker_code != decision.gate_id
                    or decision.accountable_role != "review_authority"
                ):
                    return "invalid-waiver-scope", "waiver must address one non-PASS gate"
            elif decision.decision_kind == "correction":
                prior = next(
                    (
                        item
                        for item in state.human_decision_history
                        if item.decision_id == decision.supersedes_decision_id
                    ),
                    None,
                )
                latest = next(
                    (
                        item
                        for item in reversed(state.human_decision_history)
                        if item.gate_id == decision.gate_id
                        and item.scope == decision.scope
                    ),
                    None,
                )
                if prior is None or prior != latest:
                    return "unknown-correction-predecessor", "correction predecessor is not recorded"
                if decision.blocker_action == "restore" and (
                    decision.blocker_code != prior.decision.blocker_code
                    or prior.decision.blocker_action != "release"
                ):
                    return "invalid-correction-action", "correction restore does not match prior release"
            elif decision.decision_kind in {
                "access_decision",
                "capability_escalation",
                "root_escalation",
            } and decision.accountable_role != "access_authority":
                return "invalid-access-authority", "access decisions require access_authority"
            return None

        return self.runtime.append_phase4_event(
            request,
            event_type="human_decision.recorded",
            payload=HumanDecisionRecordedPayload(
                decision=decision,
                decision_sha256=sha256_hex(canonical_orchestration_model_bytes(decision)),
                authority_sha256=decision.authority_sha256,
            ),
            prevalidate=validate,
        )

    def _build_assignments(
        self,
        *,
        state: RuntimeState,
        manifest: RunManifest,
        specs: tuple[AssignmentSpec, ...],
        execution_mode: ExecutionMode,
        execution_provenance: str,
        policy_sha256: str,
        context_manifest_sha256: str,
        base_revision: int,
        occurred_at: str,
    ) -> tuple[ImmutableAssignment, ...]:
        catalog = locked_role_catalog()
        role_by_id = {role.role_id: role for role in catalog.roles}
        default_input = manifest.immutable_input.sha256
        output_schema_sha256 = _schema_digest("worker-proposal.schema.json")
        assignments: list[ImmutableAssignment] = []
        for spec in specs:
            role = role_by_id.get(spec.role_id)
            if role is None:
                raise OrchestrationError(f"role is not in the locked catalog: {spec.role_id}")
            if execution_mode not in role.allowed_execution_modes:
                raise OrchestrationError(
                    f"execution mode {execution_mode} is not allowed for role {spec.role_id}"
                )
            independence = (
                role.independence_eligible
                if spec.independence_eligible is None
                else spec.independence_eligible
            )
            if independence != role.independence_eligible:
                raise OrchestrationError("assignment cannot override role independence policy")
            input_hashes = spec.input_sha256 or (default_input,)
            blind = BlindReviewConstraints(
                required=spec.blind_review_required,
                subject_sha256=spec.subject_sha256,
                rubric_sha256=spec.rubric_sha256,
                forbidden_peer_role_ids=spec.forbidden_peer_role_ids,
            )
            assignment = ImmutableAssignment(
                schema_version="arw.assignment.v1",
                protocol_version="1.0.0",
                assignment_id=spec.assignment_id,
                supersedes_assignment_id=spec.supersedes_assignment_id,
                run_id=state.run_id,
                stage_id=spec.stage_id,
                task_id=spec.task_id,
                role_id=spec.role_id,
                worker_identity_id=spec.worker_identity_id,
                execution_mode=execution_mode,
                execution_provenance=execution_provenance,
                independence_eligible=independence,
                base_revision=base_revision,
                input_sha256=input_hashes,
                capability_ids=spec.capability_ids,
                allowed_read_root_ids=spec.allowed_read_root_ids,
                scratch_path_template="attempts/{attempt_id}/scratch",
                result_path_template="attempts/{attempt_id}/result",
                output_policy=OutputPolicy(
                    schema_id="arw.worker-proposal.v1",
                    schema_sha256=output_schema_sha256,
                    max_bytes=self.policy.proposal_max_bytes,
                    max_artifacts=32,
                ),
                policy_sha256=policy_sha256,
                context_manifest_sha256=context_manifest_sha256,
                blind_review=blind,
                deadline_at=_utc_after(occurred_at, self.policy.attempt_timeout_s),
                completion_contract=CompletionContract(
                    requires_completed_proposal=True,
                    required_artifact_kinds=spec.required_artifact_kinds,
                    requires_human_gate=spec.requires_human_gate,
                ),
                acceptance_key=AssignmentKey(
                    topological_layer=spec.acceptance_key[0],
                    task_ordinal=spec.acceptance_key[1],
                    assignment_id=spec.assignment_id,
                ),
            )
            assignments.append(assignment)
        return tuple(assignments)

    def prepare(
        self,
        request: LifecycleTransitionRequest,
        *,
        assignments: Iterable[AssignmentSpec],
        execution_mode: ExecutionMode = "assignment_injected_subagent",
        execution_provenance: str | None = None,
    ) -> PreparedRun:
        """Freeze one crash-resumable preparation saga before dispatch.

        The original ``prepare`` command is the saga identity.  Re-entering
        with that exact request may only append a missing suffix whose
        full-intent digest and immutable assignment bytes still match.
        """

        self._require_parent(request)
        if request.transition_id != "prepare" or request.from_stage != "initialized":
            raise OrchestrationError("prepare must start from initialized with transition 'prepare'")
        specs = tuple(assignments)
        if not specs:
            raise OrchestrationError("at least one assignment is required")
        ids = [spec.assignment_id for spec in specs]
        keys = [(spec.acceptance_key, spec.assignment_id) for spec in specs]
        if len(ids) != len(set(ids)):
            raise OrchestrationError("assignment IDs must be unique")
        if len(keys) != len(set(keys)):
            raise OrchestrationError("assignment acceptance keys must be unique")
        if execution_provenance is None:
            execution_provenance = {
                "native_profile": "native_profile",
                "assignment_injected_subagent": "assignment_injected_subagent",
                "degraded_inline": "degraded_inline",
                "blocked": "unavailable",
            }[execution_mode]
        if execution_mode == "blocked" and execution_provenance != "unavailable":
            raise OrchestrationError("blocked execution requires unavailable provenance")
        if (
            execution_mode in {"native_profile", "assignment_injected_subagent"}
            and execution_provenance != execution_mode
        ):
            raise OrchestrationError("formal execution mode and provenance must match")

        state = self.runtime.read_state()
        if state.workflow_definition_id != PHASE4_WORKFLOW_ID:
            raise OrchestrationError("orchestration requires the Phase 4 workflow definition")
        replayed = replay_run(self.run_root, lock_timeout=self.runtime.lock_timeout)
        prepare_event = next(
            (
                event
                for event in replayed.events
                if event.command_id == request.command_id
                and event.event_type == "lifecycle.transitioned"
                and event.payload.transition_id == "prepare"
            ),
            None,
        )
        if state.stage == "initialized":
            if state.accepted_revision != request.expected_revision:
                raise OrchestrationError("prepare request revision is stale")
        elif state.stage not in {"preparing", "prepared"}:
            raise OrchestrationError("prepare saga cannot resume from the current stage")
        elif prepare_event is None:
            raise OrchestrationError("partial preparation is not owned by this command")
        elif (
            prepare_event.event_id != request.event_id
            or prepare_event.expected_revision != request.expected_revision
            or prepare_event.occurred_at != request.occurred_at
            or prepare_event.actor_id != request.actor_id
            or prepare_event.actor_role != request.actor_role
        ):
            raise OrchestrationError("prepare saga identity differs from the accepted command")

        manifest = self._manifest()
        catalog = locked_role_catalog()
        catalog_sha256 = sha256_hex(canonical_orchestration_model_bytes(catalog))
        policy_sha256 = self.policy.policy_sha256
        ordered_specs = tuple(
            sorted(specs, key=lambda item: (item.acceptance_key, item.assignment_id))
        )
        intent = {
            "assignment_specs": tuple(asdict(spec) for spec in ordered_specs),
            "execution_mode": execution_mode,
            "execution_provenance": execution_provenance,
            "policy_sha256": policy_sha256,
            "role_catalog_sha256": catalog_sha256,
        }
        dag_sha256 = sha256_hex(canonical_json_bytes(intent))
        context_sha256 = sha256_hex(
            canonical_json_bytes(
                {
                    "immutable_input": manifest.immutable_input.model_dump(mode="json"),
                    "preparation_intent_sha256": dag_sha256,
                    "role_catalog_sha256": catalog_sha256,
                }
            )
        )
        role_modes = tuple(
            ExecutionRoleMode(
                role_id=spec.role_id,
                execution_mode=execution_mode,
                execution_provenance=execution_provenance,
                independence_eligible=next(
                    role.independence_eligible
                    for role in catalog.roles
                    if role.role_id == spec.role_id
                ),
                worker_identity_id=spec.worker_identity_id,
            )
            for spec in specs
        )
        expected_mode = ExecutionModeSelectedPayload(
            execution_mode=execution_mode,
            execution_provenance=execution_provenance,
            role_modes=role_modes,
            role_catalog_sha256=catalog_sha256,
            policy_sha256=policy_sha256,
            dag_sha256=dag_sha256,
            rationale="parent-frozen Phase 4 execution policy and assignment-set intent",
        )

        # Validate every immutable assignment before the first mutation.  The
        # selected-mode event is always the second saga event, so its
        # resulting revision is stable across restarts.
        predicted_mode_revision = request.expected_revision + 2
        assignments_ready = self._build_assignments(
            state=state,
            manifest=manifest,
            specs=specs,
            execution_mode=execution_mode,
            execution_provenance=execution_provenance,
            policy_sha256=policy_sha256,
            context_manifest_sha256=context_sha256,
            base_revision=predicted_mode_revision,
            occurred_at=request.occurred_at,
        )

        current = state
        if current.stage == "initialized":
            prepared = self.runtime.execute_transition(request)
            self._require_accepted(prepared, "prepare")
            current = prepared.state

        replayed = replay_run(self.run_root, lock_timeout=self.runtime.lock_timeout)
        mode_event = next(
            (event for event in replayed.events if event.event_type == "execution.mode_selected"),
            None,
        )
        if mode_event is None:
            selected = self.runtime.append_phase4_event(
                self._child_request(
                    request, revision=current.accepted_revision, label="mode"
                ),
                event_type="execution.mode_selected",
                payload=expected_mode,
            )
            self._require_accepted(selected, "execution mode")
            current = selected.state
            mode_revision = selected.state.accepted_revision
        else:
            if canonical_orchestration_model_bytes(mode_event.payload) != canonical_orchestration_model_bytes(expected_mode):
                raise OrchestrationError("accepted preparation intent differs from this request")
            mode_revision = mode_event.resulting_revision
            if mode_revision != predicted_mode_revision:
                raise OrchestrationError("preparation mode revision is not the canonical saga prefix")
            current = self.runtime.read_state()

        if any(assignment.base_revision != mode_revision for assignment in assignments_ready):
            assignments_ready = self._build_assignments(
                state=current,
                manifest=manifest,
                specs=specs,
                execution_mode=execution_mode,
                execution_provenance=execution_provenance,
                policy_sha256=policy_sha256,
                context_manifest_sha256=context_sha256,
                base_revision=mode_revision,
                occurred_at=request.occurred_at,
            )
        expected_by_id = {
            assignment.assignment_id: assignment for assignment in assignments_ready
        }
        existing_by_id = {item.assignment_id: item for item in current.assignments}
        if not set(existing_by_id) <= set(expected_by_id):
            raise OrchestrationError("canonical preparation contains an unexpected assignment")
        for assignment_id, existing in existing_by_id.items():
            if existing.assignment_sha256 != expected_by_id[assignment_id].canonical_sha256():
                raise OrchestrationError("canonical assignment differs from preparation intent")

        for index, assignment in enumerate(assignments_ready):
            try:
                install_assignment_manifest(self.run_root, assignment)
            except ManifestError as error:
                raise OrchestrationError(str(error)) from error
            if assignment.assignment_id in existing_by_id:
                continue
            payload: StrictModel = AssignmentPreparedPayload(
                assignment=assignment,
                assignment_sha256=assignment.canonical_sha256(),
            )
            event_type = "assignment.prepared"
            if assignment.supersedes_assignment_id is not None:
                predecessor = next(
                    item
                    for item in current.assignments
                    if item.assignment_id == assignment.supersedes_assignment_id
                )
                payload = AssignmentSupersededPayload(
                    assignment=assignment,
                    assignment_sha256=assignment.canonical_sha256(),
                    predecessor_assignment_id=predecessor.assignment_id,
                    predecessor_assignment_sha256=predecessor.assignment_sha256,
                )
                event_type = "assignment.superseded"
            outcome = self.runtime.append_phase4_event(
                self._child_request(
                    request,
                    revision=current.accepted_revision,
                    label=f"assignment:{index}:{assignment.assignment_id}",
                ),
                event_type=event_type,
                payload=payload,
            )
            self._require_accepted(outcome, f"assignment {assignment.assignment_id}")
            current = outcome.state
            existing_by_id[assignment.assignment_id] = next(
                item
                for item in current.assignments
                if item.assignment_id == assignment.assignment_id
            )

        if current.stage == "preparing":
            frozen = self.runtime.execute_transition(
                self._child_request(
                    request,
                    revision=current.accepted_revision,
                    label="freeze",
                    model=LifecycleTransitionRequest,
                    transition_id="freeze",
                    from_stage="preparing",
                )  # type: ignore[arg-type]
            )
            self._require_accepted(frozen, "freeze")
            current = frozen.state
        if current.stage != "prepared":
            raise OrchestrationError("preparation saga did not reach the prepared stage")
        return PreparedRun(
            state=current,
            assignments=assignments_ready,
            role_catalog_sha256=catalog_sha256,
            policy_sha256=policy_sha256,
            dag_sha256=dag_sha256,
            execution_mode=execution_mode,
        )

    @staticmethod
    def _require_accepted(outcome: CommandOutcome, label: str) -> None:
        if not outcome.accepted:
            message = outcome.rejection.message if outcome.rejection else "unknown rejection"
            raise OrchestrationError(f"{label} was rejected: {message}")

    def prepare_attempt(
        self,
        request: RuntimeCommandRequest,
        *,
        assignment: ImmutableAssignment,
        attempt: AttemptDescriptor,
    ) -> CommandOutcome:
        """Publish one immutable attempt tree and its parent event."""

        self._require_parent(request)
        if attempt.assignment_id != assignment.assignment_id:
            raise OrchestrationError("attempt does not bind assignment")
        if attempt.status != "prepared" or attempt.retry_reason is not None or attempt.retry_eligible:
            raise OrchestrationError("attempt.prepared requires a fresh prepared descriptor")
        try:
            materialize_attempt_tree(self.run_root, assignment, attempt)
        except ManifestError as error:
            raise OrchestrationError(str(error)) from error
        return self.runtime.append_phase4_event(
            request,
            event_type="attempt.prepared",
            payload=AttemptPreparedPayload(
                assignment_id=assignment.assignment_id,
                assignment_sha256=assignment.canonical_sha256(),
                attempt=attempt,
                attempt_sha256=sha256_hex(canonical_orchestration_model_bytes(attempt)),
            ),
        )

    def record_attempt_lifecycle(
        self,
        request: RuntimeCommandRequest,
        *,
        assignment: ImmutableAssignment,
        attempt: AttemptDescriptor,
        status: AttemptStatus,
        retry_reason: RetryReason | None = None,
        retry_eligible: bool = False,
        proposal_sha256: str | None = None,
        host_agent_id: str | None = None,
        cancellation_deadline_at: str | None = None,
    ) -> CommandOutcome:
        """Record a bounded parent observation for an already prepared attempt."""

        return self.runtime.append_phase4_event(
            request,
            event_type="attempt.lifecycle",
            payload=AttemptLifecyclePayload(
                assignment_id=assignment.assignment_id,
                assignment_sha256=assignment.canonical_sha256(),
                attempt_id=attempt.attempt_id,
                attempt_number=attempt.attempt_number,
                status=status,
                retry_reason=retry_reason,
                retry_eligible=retry_eligible,
                host_agent_id=host_agent_id or attempt.host_agent_id,
                cancellation_deadline_at=cancellation_deadline_at,
                proposal_nonce=attempt.proposal_nonce,
                proposal_sha256=proposal_sha256,
            ),
        )

    @staticmethod
    def _raw_proposal_digest(root: Path, attempt_id: str) -> tuple[str, bool]:
        path = root / "attempts" / attempt_id / "result" / "proposal.json"
        try:
            return sha256_hex(path.read_bytes()), True
        except OSError:
            return "0" * 64, False

    def admit_proposal(
        self,
        request: RuntimeCommandRequest,
        *,
        assignment: ImmutableAssignment,
        attempt: AttemptDescriptor,
        expected_sha256: str | None = None,
    ) -> CommandOutcome:
        """Validate raw bytes and append only an accepted/rejected parent event."""

        self._require_parent(request)
        if attempt.assignment_id != assignment.assignment_id:
            raise OrchestrationError("proposal attempt does not bind assignment")
        current = self.runtime.read_state()
        latest = next(
            (
                item
                for item in reversed(current.attempts)
                if item.attempt_id == attempt.attempt_id
            ),
            None,
        )
        if latest is not None and latest.status in {
            "interrupted",
            "force_terminated",
            "cancelled",
            "rejected_stale",
            "superseded",
            "blocked",
        }:
            digest, retained = self._raw_proposal_digest(self.run_root, attempt.attempt_id)
            return self.runtime.append_phase4_event(
                request,
                event_type="proposal.rejected",
                payload=ProposalRejectedPayload(
                    assignment_id=assignment.assignment_id,
                    assignment_sha256=assignment.canonical_sha256(),
                    attempt_id=attempt.attempt_id,
                    proposal_sha256=digest,
                    outcome="rejected_stale",
                    reason_code="stale-attempt",
                    acceptance_key=assignment.acceptance_key.value,
                    raw_bytes_retained=retained,
                ),
            )
        try:
            evidence = admit_raw_proposal(
                self.run_root,
                assignment=assignment,
                attempt=attempt,
                max_bytes=min(self.policy.proposal_max_bytes, 1_048_576),
                expected_sha256=expected_sha256,
            )
        except ManifestError as error:
            digest, retained = self._raw_proposal_digest(self.run_root, attempt.attempt_id)
            if not retained:
                digest = sha256_hex(
                    f"missing:{assignment.assignment_id}:{attempt.attempt_id}".encode()
                )
            reason = "proposal-invalid"
            text = str(error).lower()
            if "stale" in text or "replaced" in text or "digest" in text:
                reason = "proposal-stale"
            elif "symlink" in text or "direct" in text or "path" in text:
                reason = "proposal-path-invalid"
            elif "limit" in text or "exceed" in text:
                reason = "proposal-oversized"
            return self.runtime.append_phase4_event(
                request,
                event_type="proposal.rejected",
                payload=ProposalRejectedPayload(
                    assignment_id=assignment.assignment_id,
                    assignment_sha256=assignment.canonical_sha256(),
                    attempt_id=attempt.attempt_id,
                    proposal_sha256=digest,
                    outcome="rejected_stale" if reason == "proposal-stale" else "rejected_invalid",
                    reason_code=reason,
                    acceptance_key=assignment.acceptance_key.value,
                    raw_bytes_retained=retained,
                ),
            )
        proposal = evidence.proposal
        return self.runtime.append_phase4_event(
            request,
            event_type="proposal.accepted",
            payload=ProposalAcceptedPayload(
                assignment_id=assignment.assignment_id,
                assignment_sha256=assignment.canonical_sha256(),
                attempt_id=attempt.attempt_id,
                proposal=proposal,
                proposal_sha256=evidence.sha256,
                acceptance_key=assignment.acceptance_key.value,
                source_host_agent_id=attempt.host_agent_id,
                source_evidence_sha256=(evidence.sha256,),
            ),
        )

    async def dispatch(
        self,
        request: RuntimeCommandRequest,
        prepared: PreparedRun,
    ) -> DispatchReport:
        """Dispatch prepared assignments and admit outcomes in frozen order."""

        self._require_parent(request)
        current = self.runtime.read_state()
        if current.accepted_revision != request.expected_revision:
            raise OrchestrationError("dispatch request revision is stale")
        if prepared.policy_sha256 != self.policy.policy_sha256:
            raise OrchestrationError("prepared run policy differs from the active coordinator")
        if current.policy_sha256 != prepared.policy_sha256:
            raise OrchestrationError("canonical policy differs from the prepared run")
        assignment_by_id = {
            assignment.assignment_id: assignment for assignment in prepared.assignments
        }
        if set(assignment_by_id) != {item.assignment_id for item in current.assignments}:
            raise OrchestrationError("prepared assignment set differs from canonical state")

        first_specs: list[DispatchSpec] = []
        descriptors: dict[str, AttemptDescriptor] = {}
        for assignment in prepared.assignments:
            attempt_id = f"attempt.{assignment.assignment_id}.001"
            attempt = AttemptDescriptor(
                schema_version="arw.attempt-descriptor.v1",
                assignment_id=assignment.assignment_id,
                attempt_id=attempt_id,
                attempt_number=1,
                proposal_nonce=f"nonce.{assignment.assignment_id}.001",
                status="prepared",
                retry_reason=None,
                retry_eligible=False,
                continuation_count=0,
                host_agent_id=None,
                cancellation_deadline_at=None,
            )
            outcome = self.prepare_attempt(
                self._child_request(
                    request,
                    revision=current.accepted_revision,
                    label=f"attempt:{assignment.assignment_id}",
                ),
                assignment=assignment,
                attempt=attempt,
            )
            self._require_accepted(outcome, f"attempt {attempt_id}")
            current = outcome.state
            descriptors[attempt.attempt_id] = attempt
            first_specs.append(
                DispatchSpec(
                    assignment_id=assignment.assignment_id,
                    attempt_id=attempt_id,
                    acceptance_key=assignment.acceptance_key.value,
                    assignment_path=self.run_root / "assignments" / f"{assignment.assignment_id}.json",
                    attempt_root=self.run_root / "attempts" / attempt_id,
                    policy_snapshot=self.policy,
                    proposal_nonce=attempt.proposal_nonce,
                )
            )

        canonical_event_lock = asyncio.Lock()

        async def record_cancel_request(spec: DispatchSpec, _deadline_monotonic: float) -> None:
            # Scheduler callbacks can race across assignments.  The parent
            # serializes the canonical cancel record before the adapter signal.
            async with canonical_event_lock:
                assignment = assignment_by_id[spec.assignment_id]
                attempt = descriptors[spec.attempt_id]
                state = self.runtime.read_state()
                deadline = _utc_after(
                    request.occurred_at,
                    spec.attempt_number
                    * (
                        spec.effective_timeout_seconds
                        + spec.effective_cancellation_grace_seconds
                    ),
                )
                marked = self.record_attempt_lifecycle(
                    self._child_request(
                        request,
                        revision=state.accepted_revision,
                        label=f"cancel-request:{attempt.attempt_id}",
                    ),
                    assignment=assignment,
                    attempt=attempt,
                    status="cancel_requested",
                    cancellation_deadline_at=deadline,
                )
                self._require_accepted(marked, f"cancel request {attempt.attempt_id}")
                updated = AttemptDescriptor(
                    **{
                        **attempt.model_dump(mode="json"),
                        "status": "cancel_requested",
                        "cancellation_deadline_at": deadline,
                    }
                )
                descriptors[spec.attempt_id] = updated

        async def validate_host_result(spec: DispatchSpec, result: HostResult) -> None:
            """Retain and validate raw proposal bytes before retry selection.

            This callback never accepts a proposal and never trusts stdout. A
            schema/canonical-envelope defect is repairable once; identity,
            digest, policy, confinement, and size defects fail closed without
            spending the retry budget.
            """

            # This is an observation boundary, not an authority write.  The
            # parent can retain the host result and classify a deterministic
            # failure before any proposal is admitted.
            inject("phase7.result-acceptance")

            assignment = assignment_by_id[spec.assignment_id]
            base_attempt = descriptors[spec.attempt_id]
            expected_path = (
                self.run_root
                / "attempts"
                / base_attempt.attempt_id
                / "result"
                / "proposal.json"
            )
            if result.proposal_path != expected_path:
                raise StaleAttempt("host proposal path differs from the frozen result channel")
            if (
                result.execution_mode in {"native_profile", "assignment_injected_subagent"}
                and not (
                    result.formal_independence
                    and result.assignment_mapping_proven
                    and result.isolation_proven
                )
            ) or result.execution_mode in {"degraded_inline", "blocked"}:
                raise StaleAttempt("host qualification does not bind the assignment and isolation")
            observed_attempt = AttemptDescriptor(
                **{
                    **base_attempt.model_dump(mode="json"),
                    "status": "completed",
                    "host_agent_id": result.host_agent_id,
                }
            )
            try:
                admit_raw_proposal(
                    self.run_root,
                    assignment=assignment,
                    attempt=observed_attempt,
                    max_bytes=min(self.policy.proposal_max_bytes, 1_048_576),
                )
            except ManifestError as error:
                text = str(error).lower()
                non_repairable = (
                    "digest" in text
                    or "replaced" in text
                    or "symlink" in text
                    or "exceed" in text
                    or "echo the immutable assignment" in text
                )
                if non_repairable:
                    raise StaleAttempt(str(error)) from error
                raise RepairableEnvelopeFailure(str(error)) from error

        scheduler = DeterministicScheduler(
            self.adapter,
            policy=self.policy,
            cancel_observer=record_cancel_request,
            result_validator=validate_host_result,
        )

        def mark_generation_dispatched(specs: Sequence[DispatchSpec]) -> None:
            """Append the parent dispatch request before any host call."""

            state = self.runtime.read_state()
            revision = state.accepted_revision
            for spec in sorted(specs, key=lambda item: item.frozen_order_key):
                dispatched = self.record_attempt_lifecycle(
                    self._child_request(
                        request,
                        revision=revision,
                        label=f"dispatch:{spec.attempt_id}",
                    ),
                    assignment=assignment_by_id[spec.assignment_id],
                    attempt=descriptors[spec.attempt_id],
                    status="active",
                )
                self._require_accepted(dispatched, f"dispatch {spec.attempt_id}")
                # Same-saga adjacent appends: the just-appended outcome carries
                # the new accepted revision, so the next child request can be
                # derived without another full ledger replay.
                revision = dispatched.state.accepted_revision

        mark_generation_dispatched(first_specs)
        first_generation = await scheduler.run(tuple(first_specs))
        first_by_assignment = {
            outcome.assignment_id: outcome.attempts[0] for outcome in first_generation
        }

        def terminal_status(outcome: AttemptOutcome) -> AttemptStatus:
            if outcome.status == "force_terminated":
                return "force_terminated"
            if outcome.status == "interrupted":
                return "interrupted"
            if outcome.status == "cancelled":
                return "cancelled"
            return "failed"

        def retained_digest(outcome: AttemptOutcome) -> tuple[str | None, bool]:
            digest, retained = self._raw_proposal_digest(
                self.run_root, outcome.attempt_id
            )
            if retained:
                return digest, True
            if outcome.result is not None and outcome.result.observation_sha256:
                return outcome.result.observation_sha256, False
            return None, False

        # Parent-owned retry admission.  The predecessor terminal event and
        # the fresh attempt manifest/event are both canonical before any
        # second-generation host process can start.
        retry_specs: list[DispatchSpec] = []
        retry_descriptors: dict[str, AttemptDescriptor] = {}
        state = self.runtime.read_state()
        revision = state.accepted_revision
        for spec in sorted(first_specs, key=lambda item: item.frozen_order_key):
            outcome = first_by_assignment[spec.assignment_id]
            if not outcome.retry_eligible:
                continue
            assignment = assignment_by_id[spec.assignment_id]
            first_attempt = descriptors[spec.attempt_id]
            proposal_sha256, _ = retained_digest(outcome)
            terminal = self.record_attempt_lifecycle(
                self._child_request(
                    request,
                    revision=revision,
                    label=f"retry-failure:{first_attempt.attempt_id}",
                ),
                assignment=assignment,
                attempt=first_attempt,
                status=terminal_status(outcome),
                retry_reason=outcome.failure_reason,  # type: ignore[arg-type]
                retry_eligible=True,
                proposal_sha256=proposal_sha256,
                host_agent_id=(outcome.result.host_agent_id if outcome.result else None),
                cancellation_deadline_at=first_attempt.cancellation_deadline_at,
            )
            self._require_accepted(terminal, f"retry failure {first_attempt.attempt_id}")
            # Same-saga adjacent appends: carry the accepted revision forward
            # from the terminal outcome instead of replaying the ledger.
            revision = terminal.state.accepted_revision
            retry_spec = spec.for_retry(2)
            retry_attempt = AttemptDescriptor(
                schema_version="arw.attempt-descriptor.v1",
                assignment_id=assignment.assignment_id,
                attempt_id=retry_spec.attempt_id,
                attempt_number=2,
                proposal_nonce=retry_spec.proposal_nonce
                or f"nonce.{assignment.assignment_id}.001.retry-2",
                status="prepared",
                retry_reason=None,
                retry_eligible=False,
                continuation_count=0,
                host_agent_id=None,
                cancellation_deadline_at=None,
            )
            prepared_retry = self.prepare_attempt(
                self._child_request(
                    request,
                    revision=terminal.state.accepted_revision,
                    label=f"retry-attempt:{retry_attempt.attempt_id}",
                ),
                assignment=assignment,
                attempt=retry_attempt,
            )
            self._require_accepted(prepared_retry, f"retry {retry_attempt.attempt_id}")
            descriptors[retry_attempt.attempt_id] = retry_attempt
            retry_descriptors[assignment.assignment_id] = retry_attempt
            retry_specs.append(retry_spec)

        if retry_specs:
            mark_generation_dispatched(retry_specs)
            retry_generation = await scheduler.run(tuple(retry_specs))
        else:
            retry_generation = ()
        retry_by_assignment = {
            outcome.assignment_id: outcome.attempts[0] for outcome in retry_generation
        }

        combined: list[ScheduledOutcome] = []
        current = self.runtime.read_state()
        for first_scheduled in first_generation:
            assignment = assignment_by_id[first_scheduled.assignment_id]
            first_outcome = first_by_assignment[assignment.assignment_id]
            final_outcome = retry_by_assignment.get(
                assignment.assignment_id, first_outcome
            )
            history = (
                (first_outcome, final_outcome)
                if final_outcome is not first_outcome
                else (first_outcome,)
            )
            final_attempt = descriptors[final_outcome.attempt_id]
            host_id = (
                final_outcome.result.host_agent_id if final_outcome.result else None
            )
            if final_outcome.status == "completed" and final_outcome.result is not None:
                completed_attempt = final_attempt.model_copy(
                    update={"status": "completed", "host_agent_id": host_id}
                )
                admitted = self.admit_proposal(
                    self._child_request(
                        request,
                        revision=current.accepted_revision,
                        label=(
                            f"proposal:{assignment.assignment_id}:"
                            f"{final_attempt.attempt_number}"
                        ),
                    ),
                    assignment=assignment,
                    attempt=completed_attempt,
                )
                self._require_accepted(admitted, f"admit proposal {final_attempt.attempt_id}")
                current = admitted.state
                if admitted.event is not None and admitted.event.event_type == "proposal.rejected":
                    closed = self.record_attempt_lifecycle(
                        self._child_request(
                            request,
                            revision=current.accepted_revision,
                            label=f"admission-race:{final_attempt.attempt_id}",
                        ),
                        assignment=assignment,
                        attempt=final_attempt,
                        status="failed",
                        proposal_sha256=current.rejected_proposals[-1].proposal_sha256,
                        host_agent_id=host_id,
                    )
                    self._require_accepted(closed, f"close invalid {final_attempt.attempt_id}")
                    current = closed.state
            else:
                # A retryable first attempt was already closed before its
                # successor was prepared.  Every other terminal observation
                # is recorded here exactly once.
                if not (
                    final_outcome is first_outcome and first_outcome.retry_eligible
                ):
                    proposal_sha256, retained = retained_digest(final_outcome)
                    terminal = self.record_attempt_lifecycle(
                        self._child_request(
                            request,
                            revision=current.accepted_revision,
                            label=f"lifecycle:{final_attempt.attempt_id}",
                        ),
                        assignment=assignment,
                        attempt=final_attempt,
                        status=terminal_status(final_outcome),
                        retry_reason=None,
                        retry_eligible=False,
                        proposal_sha256=proposal_sha256,
                        host_agent_id=host_id,
                        cancellation_deadline_at=final_attempt.cancellation_deadline_at,
                    )
                    self._require_accepted(terminal, f"close attempt {final_attempt.attempt_id}")
                    current = terminal.state
                    digest = proposal_sha256 or sha256_hex(
                        (
                            f"failure:{assignment.assignment_id}:"
                            f"{final_attempt.attempt_id}:{final_outcome.failure_reason}"
                        ).encode()
                    )
                    rejected = self.runtime.append_phase4_event(
                        self._child_request(
                            request,
                            revision=current.accepted_revision,
                            label=f"rejected:{final_attempt.attempt_id}",
                        ),
                        event_type="proposal.rejected",
                        payload=ProposalRejectedPayload(
                            assignment_id=assignment.assignment_id,
                            assignment_sha256=assignment.canonical_sha256(),
                            attempt_id=final_attempt.attempt_id,
                            proposal_sha256=digest,
                            outcome=(
                                "rejected_stale"
                                if final_outcome.classification == "rejected_stale"
                                else "rejected_invalid"
                            ),
                            reason_code=final_outcome.failure_reason
                            or "process-failure",
                            acceptance_key=assignment.acceptance_key.value,
                            raw_bytes_retained=retained,
                        ),
                    )
                    self._require_accepted(rejected, f"reject attempt {final_attempt.attempt_id}")
                    current = rejected.state
                    blocked = self.record_attempt_lifecycle(
                        self._child_request(
                            request,
                            revision=current.accepted_revision,
                            label=f"blocked:{final_attempt.attempt_id}",
                        ),
                        assignment=assignment,
                        attempt=final_attempt,
                        status="blocked",
                        proposal_sha256=digest,
                        host_agent_id=host_id,
                    )
                    self._require_accepted(blocked, f"block attempt {final_attempt.attempt_id}")
                    current = blocked.state
            combined.append(
                ScheduledOutcome(
                    assignment_id=assignment.assignment_id,
                    acceptance_key=assignment.acceptance_key.value,
                    status=final_outcome.status,
                    result=final_outcome.result,
                    attempts=history,
                    retry_reason=first_outcome.failure_reason,
                    retry_eligible=final_outcome.retry_eligible,
                    classification=final_outcome.classification,
                    late_result=final_outcome.late_result,
                    error=final_outcome.error,
                    cancellation_requested=final_outcome.cancellation_requested,
                    force_termination_requested=final_outcome.force_termination_requested,
                )
            )
        return DispatchReport(state=current, outcomes=tuple(combined))

    def recover_orphans(
        self,
        request: RuntimeCommandRequest,
    ) -> RuntimeState:
        """Reconcile every replay-visible dispatch crash gap idempotently."""

        self._require_parent(request)
        current = self.runtime.read_state()
        if current.accepted_revision != request.expected_revision:
            raise OrchestrationError("recovery request revision is stale")
        if current.policy_sha256 != self.policy.policy_sha256:
            raise OrchestrationError("recovery policy differs from the frozen run policy")
        assignments = {item.assignment_id: item for item in current.assignments}

        def prepare_retry(history) -> None:
            nonlocal current
            if any(
                item.assignment_id == history.assignment_id
                and item.attempt_number == 2
                for item in current.attempts
            ):
                return
            assignment = assignments[history.assignment_id].assignment
            retry_attempt = AttemptDescriptor(
                schema_version="arw.attempt-descriptor.v1",
                assignment_id=history.assignment_id,
                attempt_id=f"{history.attempt_id}.retry-2",
                attempt_number=2,
                proposal_nonce=f"recovered.{history.attempt_id}.retry-2",
                status="prepared",
                retry_reason=None,
                retry_eligible=False,
                continuation_count=0,
                host_agent_id=None,
                cancellation_deadline_at=None,
            )
            retry = self.prepare_attempt(
                self._child_request(
                    request,
                    revision=current.accepted_revision,
                    label=f"requeue:{history.attempt_id}",
                ),
                assignment=assignment,
                attempt=retry_attempt,
            )
            self._require_accepted(retry, f"requeue {history.attempt_id}")
            current = retry.state

        def finalize_exhausted(history) -> None:
            nonlocal current
            assignment = assignments[history.assignment_id].assignment
            if not any(
                item.attempt_id == history.attempt_id for item in current.proposals
            ):
                digest, retained = self._raw_proposal_digest(
                    self.run_root, history.attempt_id
                )
                if not retained:
                    digest = history.proposal_sha256 or sha256_hex(
                        f"recovery:{history.assignment_id}:{history.attempt_id}".encode()
                    )
                rejected = self.runtime.append_phase4_event(
                    self._child_request(
                        request,
                        revision=current.accepted_revision,
                        label=f"recovery-reject:{history.attempt_id}",
                    ),
                    event_type="proposal.rejected",
                    payload=ProposalRejectedPayload(
                        assignment_id=history.assignment_id,
                        assignment_sha256=assignment.canonical_sha256(),
                        attempt_id=history.attempt_id,
                        proposal_sha256=digest,
                        outcome="rejected_invalid",
                        reason_code=history.retry_reason or "process-failure",
                        acceptance_key=assignment.acceptance_key.value,
                        raw_bytes_retained=retained,
                    ),
                )
                self._require_accepted(rejected, f"recovery reject {history.attempt_id}")
                current = rejected.state
            blocker_code = f"attempt-blocked.{history.attempt_id}"
            if not any(item.code == blocker_code for item in current.blockers):
                blocked = self.record_attempt_lifecycle(
                    self._child_request(
                        request,
                        revision=current.accepted_revision,
                        label=f"recovery-block:{history.attempt_id}",
                    ),
                    assignment=assignment,
                    attempt=AttemptDescriptor(
                        schema_version="arw.attempt-descriptor.v1",
                        assignment_id=history.assignment_id,
                        attempt_id=history.attempt_id,
                        attempt_number=history.attempt_number,
                        proposal_nonce=f"recovered.{history.attempt_id}",
                        status="blocked",
                        retry_reason=None,
                        retry_eligible=False,
                        continuation_count=0,
                        host_agent_id=None,
                        cancellation_deadline_at=None,
                    ),
                    status="blocked",
                    proposal_sha256=next(
                        (
                            item.proposal_sha256
                            for item in current.proposals
                            if item.attempt_id == history.attempt_id
                        ),
                        history.proposal_sha256,
                    ),
                )
                self._require_accepted(blocked, f"recovery block {history.attempt_id}")
                current = blocked.state

        active = tuple(current.active_attempts)
        for active_attempt in active:
            history = next(
                (
                    item
                    for item in reversed(current.attempts)
                    if item.attempt_id == active_attempt.attempt_id
                ),
                None,
            )
            if history is None or history.assignment_id not in assignments:
                continue
            if history.status not in {"active", "cancel_requested"}:
                # Merely prepared means the canonical host request has not
                # been issued; it is safe for a caller to resume dispatch.
                continue
            assignment = assignments[history.assignment_id].assignment
            if assignment.policy_sha256 != self.policy.policy_sha256:
                raise OrchestrationError("active attempt policy differs from the frozen run")
            retry_eligible = (
                history.attempt_number < self.policy.max_attempts_per_assignment
            )
            interrupted = self.record_attempt_lifecycle(
                self._child_request(
                    request,
                    revision=current.accepted_revision,
                    label=f"interrupt:{history.attempt_id}",
                ),
                assignment=assignment,
                attempt=AttemptDescriptor(
                    schema_version="arw.attempt-descriptor.v1",
                    assignment_id=history.assignment_id,
                    attempt_id=history.attempt_id,
                    attempt_number=history.attempt_number,
                    proposal_nonce=getattr(active_attempt, "proposal_nonce", None)
                    or f"recovered.{history.attempt_id}",
                    status="interrupted",
                    retry_reason="process_failure" if retry_eligible else None,
                    retry_eligible=retry_eligible,
                    continuation_count=0,
                    host_agent_id=None,
                    cancellation_deadline_at=None,
                ),
                status="interrupted",
                retry_reason="process_failure" if retry_eligible else None,
                retry_eligible=retry_eligible,
            )
            self._require_accepted(interrupted, f"interrupt {history.attempt_id}")
            current = interrupted.state
            terminal = next(
                item
                for item in reversed(current.attempts)
                if item.attempt_id == history.attempt_id
            )
            if retry_eligible:
                prepare_retry(terminal)
            else:
                finalize_exhausted(terminal)

        # A crash may occur after the retry-eligible terminal event but before
        # the successor event, or after an exhausted terminal event but before
        # its final rejection/blocker.  Reconcile both gaps from cold replay.
        latest_by_attempt = {}
        for history in current.attempts:
            latest_by_attempt[history.attempt_id] = history
        for history in tuple(latest_by_attempt.values()):
            if history.assignment_id not in assignments:
                continue
            if history.retry_eligible and history.attempt_number == 1:
                prepare_retry(history)
            elif history.status in {
                "failed",
                "cancelled",
                "force_terminated",
                "interrupted",
            } and not history.retry_eligible:
                finalize_exhausted(history)
        return current
