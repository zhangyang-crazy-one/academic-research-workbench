"""Pure formal blind-panel policy and dissent-preserving synthesis.

Reviewers produce observations; this module only constructs immutable
assignments and synthesis records.  It never accepts a report into the
canonical ledger and it treats unavailable isolation as an explicit blocker.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal, Self

from arw.orchestration_models import (
    FORMAL_REVIEW_ROLE_IDS,
    ReviewFinding as OrchestrationReviewFinding,
    ReviewFindingMatrix as OrchestrationReviewFindingMatrix,
    ReviewReport as OrchestrationReviewReport,
    ReviewSynthesis as OrchestrationReviewSynthesis,
)


FORMAL_REVIEW_ROLES: tuple[str, ...] = tuple(sorted(FORMAL_REVIEW_ROLE_IDS))
SYNTHESIS_ROLE = "editorial_synthesizer"
FindingClassification = Literal["consensus", "majority", "split", "DA-critical"]
GateVerdict = Literal["PASS", "BLOCKED"]


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class ReviewerIdentity:
    """Parent-observed identity and isolation proof for one formal seat."""

    worker_identity_id: str
    host_agent_id: str
    isolated: bool = True
    role_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.worker_identity_id or not self.host_agent_id:
            raise ValueError("formal reviewer identity requires worker and host IDs")
        if not isinstance(self.isolated, bool):
            raise TypeError("isolated must be a boolean proof")
        roles = tuple(self.role_ids)
        if len(roles) != len(set(roles)):
            raise ValueError("identity role IDs must be unique")
        object.__setattr__(self, "role_ids", roles)


@dataclass(frozen=True, slots=True)
class BlindReviewEnvelope:
    """The exact fields visible to one first-round reviewer."""

    panel_id: str
    assignment_id: str
    role_id: str
    subject_sha256: str
    rubric_sha256: str
    policy_sha256: str
    synthesizer: bool = False
    accepted_report_sha256: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        reports = tuple(self.accepted_report_sha256)
        if len(reports) != len(set(reports)):
            raise ValueError("synthesis report bindings must be unique")
        object.__setattr__(self, "accepted_report_sha256", reports)

    @property
    def visible_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "panel_id": self.panel_id,
            "assignment_id": self.assignment_id,
            "role_id": self.role_id,
            "subject_sha256": self.subject_sha256,
            "rubric_sha256": self.rubric_sha256,
            "policy_sha256": self.policy_sha256,
        }
        if self.synthesizer:
            payload["accepted_report_sha256"] = self.accepted_report_sha256
        return payload

    @property
    def envelope_sha256(self) -> str:
        return _digest(self.visible_payload)

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.visible_payload)


@dataclass(frozen=True, slots=True)
class PanelAssignment:
    """One isolated assignment, including the reviewer-visible envelope."""

    panel_id: str
    assignment_id: str
    attempt_id: str
    role_id: str
    worker_identity_id: str
    host_agent_id: str
    subject_sha256: str
    rubric_sha256: str
    acceptance_key: tuple[int, int, str]
    blind_envelope: BlindReviewEnvelope
    required: bool = True
    round_number: int = 1
    execution_mode: Literal[
        "native_profile", "assignment_injected_subagent", "blocked"
    ] = "native_profile"
    execution_provenance: Literal[
        "native_profile", "assignment_injected_subagent", "unavailable"
    ] = "native_profile"
    isolation_proven: bool = True
    cross_review_of_assignment_id: str | None = None

    @property
    def is_formal(self) -> bool:
        return (
            self.execution_mode in {"native_profile", "assignment_injected_subagent"}
            and self.execution_provenance == self.execution_mode
            and self.isolation_proven
        )

    @property
    def visible_payload(self) -> dict[str, object]:
        return self.blind_envelope.visible_payload

    def for_cross_review(
        self,
        *,
        reviewer_identity: ReviewerIdentity,
        round_number: int,
    ) -> Self:
        if round_number <= self.round_number:
            raise ValueError("cross-review round must create a new assignment")
        assignment_id = f"{self.assignment_id}.cross-{round_number}"
        envelope = BlindReviewEnvelope(
            panel_id=self.panel_id,
            assignment_id=assignment_id,
            role_id=self.role_id,
            subject_sha256=self.subject_sha256,
            rubric_sha256=self.rubric_sha256,
            policy_sha256=self.blind_envelope.policy_sha256,
        )
        return type(self)(
            panel_id=self.panel_id,
            assignment_id=assignment_id,
            attempt_id=f"{assignment_id}.attempt-1",
            role_id=self.role_id,
            worker_identity_id=reviewer_identity.worker_identity_id,
            host_agent_id=reviewer_identity.host_agent_id,
            subject_sha256=self.subject_sha256,
            rubric_sha256=self.rubric_sha256,
            acceptance_key=(round_number, self.acceptance_key[1], assignment_id),
            blind_envelope=envelope,
            required=self.required,
            round_number=round_number,
            execution_mode=self.execution_mode if reviewer_identity.isolated else "blocked",
            execution_provenance=(
                self.execution_provenance if reviewer_identity.isolated else "unavailable"
            ),
            isolation_proven=reviewer_identity.isolated,
            cross_review_of_assignment_id=self.assignment_id,
        )


@dataclass(frozen=True, slots=True)
class FindingObservation:
    """One report's verbatim stance and evidence for one finding item."""

    finding_id: str
    stance: str
    evidence_sha256: tuple[str, ...]
    severity: Literal["low", "moderate", "high", "critical"]
    confidence: float
    rationale: str
    resolved: bool = True

    def __post_init__(self) -> None:
        if not self.finding_id or not self.stance or not self.rationale:
            raise ValueError("finding observations require IDs, stance, and rationale")
        evidence = tuple(self.evidence_sha256)
        if not evidence or len(evidence) != len(set(evidence)):
            raise ValueError("finding evidence must be non-empty and unique")
        if self.severity not in {"low", "moderate", "high", "critical"}:
            raise ValueError("unknown finding severity")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("finding confidence must be between zero and one")
        object.__setattr__(self, "evidence_sha256", evidence)

    def to_dict(self) -> dict[str, object]:
        return {
            "confidence": self.confidence,
            "evidence_sha256": self.evidence_sha256,
            "finding_id": self.finding_id,
            "rationale": self.rationale,
            "resolved": self.resolved,
            "severity": self.severity,
            "stance": self.stance,
        }


@dataclass(frozen=True, slots=True)
class ReviewerReport:
    """An immutable report observation delivered by one panel seat."""

    report_id: str
    role_id: str
    worker_identity_id: str
    host_agent_id: str
    subject_sha256: str
    rubric_sha256: str
    findings: tuple[FindingObservation, ...]
    isolated: bool = True
    execution_mode: Literal[
        "native_profile", "assignment_injected_subagent", "degraded_inline", "blocked"
    ] = "native_profile"
    report_sha256: str | None = None

    def __post_init__(self) -> None:
        findings = tuple(self.findings)
        ids = tuple(finding.finding_id for finding in findings)
        if not findings or len(ids) != len(set(ids)):
            raise ValueError("review reports require unique non-empty finding observations")
        object.__setattr__(self, "findings", findings)
        if self.report_sha256 is None:
            object.__setattr__(
                self,
                "report_sha256",
                _digest(
                    {
                        "findings": tuple(finding.to_dict() for finding in findings),
                        "host_agent_id": self.host_agent_id,
                        "report_id": self.report_id,
                        "role_id": self.role_id,
                        "rubric_sha256": self.rubric_sha256,
                        "subject_sha256": self.subject_sha256,
                        "worker_identity_id": self.worker_identity_id,
                    }
                ),
            )


@dataclass(frozen=True, slots=True)
class FindingMatrixCell:
    """One item-level synthesis cell; all source observations remain attached."""

    finding_id: str
    source_report_ids: tuple[str, ...]
    source_report_sha256: tuple[str, ...]
    evidence_sha256: tuple[str, ...]
    severity: Literal["low", "moderate", "high", "critical"]
    confidence: float
    classification: FindingClassification
    resolution: Literal["resolved", "unresolved"]
    observations: tuple[FindingObservation, ...]
    dissent: tuple[FindingObservation, ...]

    def __post_init__(self) -> None:
        if not self.source_report_ids or not self.source_report_sha256:
            raise ValueError("finding matrix cells require source report bindings")
        if len(self.source_report_ids) != len(set(self.source_report_ids)):
            raise ValueError("finding matrix source report IDs must be unique")
        if len(self.source_report_sha256) != len(set(self.source_report_sha256)):
            raise ValueError("finding matrix source report hashes must be unique")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("finding matrix confidence must be bounded")


@dataclass(frozen=True, slots=True)
class SynthesisRecord:
    """Separate editorial identity and the complete finding matrix."""

    synthesis_id: str
    worker_identity_id: str
    host_agent_id: str
    source_reports: tuple[ReviewerReport, ...]
    finding_matrix: tuple[FindingMatrixCell, ...]
    limitations: tuple[str, ...]
    gate_verdict: GateVerdict

    @property
    def source_report_sha256(self) -> tuple[str, ...]:
        return tuple(report.report_sha256 or "" for report in self.source_reports)

    @property
    def unresolved_critical(self) -> bool:
        return any(
            cell.resolution == "unresolved"
            and (cell.severity == "critical" or cell.classification == "DA-critical")
            for cell in self.finding_matrix
        )


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    status: Literal["accepted", "blocked"]
    synthesis: SynthesisRecord | None
    synthesis_assignment: PanelAssignment | None
    blockers: tuple[str, ...]
    limitations: tuple[str, ...]

    @property
    def finding_matrix(self) -> tuple[FindingMatrixCell, ...]:
        return self.synthesis.finding_matrix if self.synthesis is not None else ()


@dataclass(frozen=True, slots=True)
class PanelPlan:
    status: Literal["ready", "blocked"]
    panel_id: str
    subject_sha256: str
    rubric_sha256: str
    reviewer_assignments: tuple[PanelAssignment, ...]
    synthesizer_assignment: PanelAssignment | None
    blockers: tuple[str, ...]
    limitations: tuple[str, ...]
    policy_sha256: str
    accepted_report_sha256: tuple[str, ...] = ()

    @property
    def formal_success(self) -> bool:
        return self.status == "ready"

    @property
    def synthesis_ready(self) -> bool:
        return (
            self.status == "ready"
            and self.synthesizer_assignment is not None
            and len(self.accepted_report_sha256) == len(self.required_roles_for_synthesis)
        )

    @property
    def required_roles_for_synthesis(self) -> tuple[str, ...]:
        return FORMAL_REVIEW_ROLES

    def with_accepted_reports(
        self, reports: Iterable[ReviewerReport]
    ) -> Self:
        if self.status != "ready" or self.synthesizer_assignment is None:
            raise ValueError("blocked panels cannot admit synthesis reports")
        report_values = tuple(reports)
        roles = tuple(report.role_id for report in report_values)
        if set(roles) != set(self.required_roles_for_synthesis) or len(roles) != len(set(roles)):
            raise ValueError("synthesis requires one accepted report for each required role")
        hashes = tuple(report.report_sha256 or "" for report in report_values)
        if len(hashes) != len(set(hashes)):
            raise ValueError("synthesis report hashes must be unique")
        assignment = self.synthesizer_assignment
        envelope = BlindReviewEnvelope(
            panel_id=self.panel_id,
            assignment_id=assignment.assignment_id,
            role_id=SYNTHESIS_ROLE,
            subject_sha256=self.subject_sha256,
            rubric_sha256=self.rubric_sha256,
            policy_sha256=self.policy_sha256,
            synthesizer=True,
            accepted_report_sha256=hashes,
        )
        return replace(
            self,
            synthesizer_assignment=replace(assignment, blind_envelope=envelope),
            accepted_report_sha256=hashes,
        )

    def cross_review_assignment(
        self,
        role_id: str,
        reviewer_identity: ReviewerIdentity,
        *,
        round_number: int = 2,
    ) -> PanelAssignment:
        if self.status != "ready":
            raise ValueError("blocked panels cannot create formal cross-review assignments")
        assignment = next(
            (item for item in self.reviewer_assignments if item.role_id == role_id), None
        )
        if assignment is None:
            raise ValueError(f"unknown formal reviewer role: {role_id}")
        return assignment.for_cross_review(
            reviewer_identity=reviewer_identity, round_number=round_number
        )


def _coerce_identity(value: ReviewerIdentity | Mapping[str, object]) -> ReviewerIdentity:
    if isinstance(value, ReviewerIdentity):
        return value
    try:
        isolated = value.get("isolated", False)
        if not isinstance(isolated, bool):
            raise ValueError("isolated proof must be a boolean")
        return ReviewerIdentity(
            worker_identity_id=str(value["worker_identity_id"]),
            host_agent_id=str(value["host_agent_id"]),
            isolated=isolated,
            role_ids=tuple(str(item) for item in value.get("role_ids", ())),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("identity mapping must prove worker, host, and isolation") from error


def _identity_has_conflict(identity: ReviewerIdentity, role_id: str) -> bool:
    for other_role in identity.role_ids:
        if other_role == role_id:
            continue
        if (
            other_role == "experiment_designer" and role_id == "methodology_reviewer"
        ) or (
            other_role == "methodology_reviewer" and role_id == "experiment_designer"
        ):
            return True
        if other_role in FORMAL_REVIEW_ROLES or role_id in FORMAL_REVIEW_ROLES:
            return True
        if other_role == "research_architect" or role_id == "research_architect":
            return True
        if other_role == SYNTHESIS_ROLE or role_id == SYNTHESIS_ROLE:
            return True
    return False


@dataclass(frozen=True, slots=True)
class FormalPanelPolicy:
    """Frozen D-09 through D-12 policy for a formal independent panel."""

    required_roles: tuple[str, ...] = FORMAL_REVIEW_ROLES
    optional_roles: tuple[str, ...] = ()
    required_dimensions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        required = tuple(self.required_roles)
        optional = tuple(self.optional_roles)
        dimensions = tuple(self.required_dimensions)
        if tuple(sorted(required)) != FORMAL_REVIEW_ROLES:
            raise ValueError(
                "formal policy must require exactly methodology, domain, perspective, and devil's advocate roles"
            )
        if len(set(optional)) != len(optional):
            raise ValueError("optional review roles must be unique")
        if set(optional) & set(required):
            raise ValueError("optional review roles cannot duplicate required roles")
        if len(set(dimensions)) != len(dimensions):
            raise ValueError("required review dimensions must be unique")
        object.__setattr__(self, "required_roles", required)
        object.__setattr__(self, "optional_roles", optional)
        object.__setattr__(self, "required_dimensions", dimensions)

    @property
    def policy_sha256(self) -> str:
        return _digest(
            {
                "optional_roles": self.optional_roles,
                "required_dimensions": self.required_dimensions,
                "required_roles": self.required_roles,
                "synthesizer_role": SYNTHESIS_ROLE,
            }
        )

    def prepare_panel(
        self,
        *,
        panel_id: str,
        subject_sha256: str,
        rubric_sha256: str,
        reviewer_identities: Mapping[str, ReviewerIdentity | Mapping[str, object]],
        synthesizer_identity: ReviewerIdentity | Mapping[str, object] | None,
        execution_mode: str = "native_profile",
        isolated_assignments: bool = True,
    ) -> PanelPlan:
        blockers: list[str] = []
        identities: dict[str, ReviewerIdentity] = {}
        for role, identity in reviewer_identities.items():
            try:
                identities[role] = _coerce_identity(identity)
            except (TypeError, ValueError) as error:
                blockers.append(f"isolation proof is malformed for {role}: {error}")
        missing = [role for role in self.required_roles if role not in identities]
        if missing:
            blockers.append(f"missing required reviewer roles: {', '.join(missing)}")
        if execution_mode not in {"native_profile", "assignment_injected_subagent"}:
            blockers.append("degraded_inline or non-formal execution cannot claim independence")
        if not isolated_assignments:
            blockers.append("isolated assignment delivery was not proven")

        all_roles = self.required_roles + tuple(
            role for role in self.optional_roles if role in identities
        )
        selected = [identities[role] for role in all_roles if role in identities]
        worker_ids = [identity.worker_identity_id for identity in selected]
        host_ids = [identity.host_agent_id for identity in selected]
        if len(worker_ids) != len(set(worker_ids)):
            blockers.append("formal reviewer worker identities are not distinct")
        if len(host_ids) != len(set(host_ids)):
            blockers.append("formal reviewer host identities are not distinct")
        for role in all_roles:
            identity = identities.get(role)
            if identity is None:
                continue
            if not identity.isolated:
                blockers.append(f"isolation proof missing for {role}")
            if _identity_has_conflict(identity, role):
                blockers.append(f"role conflict for {role}")

        synth = _coerce_identity(synthesizer_identity) if synthesizer_identity is not None else None
        if synth is None:
            blockers.append("separate editorial_synthesizer identity is missing")
        else:
            if not synth.isolated:
                blockers.append("synthesis isolation proof is missing")
            if synth.worker_identity_id in worker_ids:
                blockers.append("editorial synthesizer worker identity is reused")
            if synth.host_agent_id in host_ids:
                blockers.append("editorial synthesizer host identity is reused")
            if _identity_has_conflict(synth, SYNTHESIS_ROLE):
                blockers.append("editorial synthesizer role conflict")

        if blockers:
            return PanelPlan(
                status="blocked",
                panel_id=panel_id,
                subject_sha256=subject_sha256,
                rubric_sha256=rubric_sha256,
                reviewer_assignments=(),
                synthesizer_assignment=None,
                blockers=tuple(dict.fromkeys(blockers)),
                limitations=self._initial_limitations(identities),
                policy_sha256=self.policy_sha256,
            )

        reviewer_assignments = tuple(
            self._make_assignment(
                panel_id=panel_id,
                subject_sha256=subject_sha256,
                rubric_sha256=rubric_sha256,
                role_id=role,
                identity=identities[role],
                ordinal=ordinal,
                required=role in self.required_roles,
                execution_mode=execution_mode,
            )
            for ordinal, role in enumerate(all_roles)
        )
        assert synth is not None
        synthesis_id = f"{panel_id}.{SYNTHESIS_ROLE}.assignment"
        synthesis_envelope = BlindReviewEnvelope(
            panel_id=panel_id,
            assignment_id=synthesis_id,
            role_id=SYNTHESIS_ROLE,
            subject_sha256=subject_sha256,
            rubric_sha256=rubric_sha256,
            policy_sha256=self.policy_sha256,
            synthesizer=True,
        )
        synthesis_assignment = PanelAssignment(
            panel_id=panel_id,
            assignment_id=synthesis_id,
            attempt_id=f"{synthesis_id}.attempt-1",
            role_id=SYNTHESIS_ROLE,
            worker_identity_id=synth.worker_identity_id,
            host_agent_id=synth.host_agent_id,
            subject_sha256=subject_sha256,
            rubric_sha256=rubric_sha256,
            acceptance_key=(1, 0, synthesis_id),
            blind_envelope=synthesis_envelope,
            required=True,
            round_number=2,
            execution_mode=execution_mode,  # type: ignore[arg-type]
            execution_provenance=execution_mode,  # type: ignore[arg-type]
        )
        return PanelPlan(
            status="ready",
            panel_id=panel_id,
            subject_sha256=subject_sha256,
            rubric_sha256=rubric_sha256,
            reviewer_assignments=reviewer_assignments,
            synthesizer_assignment=synthesis_assignment,
            blockers=(),
            limitations=self._initial_limitations(identities),
            policy_sha256=self.policy_sha256,
        )

    def create_panel(self, **kwargs: object) -> PanelPlan:
        return self.prepare_panel(**kwargs)  # type: ignore[arg-type]

    def create_assignments(self, **kwargs: object) -> PanelPlan:
        return self.prepare_panel(**kwargs)  # type: ignore[arg-type]

    def _initial_limitations(
        self, identities: Mapping[str, ReviewerIdentity]
    ) -> tuple[str, ...]:
        return tuple(
            f"optional reviewer absent: {role}"
            for role in self.optional_roles
            if role not in identities
        )

    def _make_assignment(
        self,
        *,
        panel_id: str,
        subject_sha256: str,
        rubric_sha256: str,
        role_id: str,
        identity: ReviewerIdentity,
        ordinal: int,
        required: bool,
        execution_mode: str,
    ) -> PanelAssignment:
        assignment_id = f"{panel_id}.{role_id}.assignment"
        envelope = BlindReviewEnvelope(
            panel_id=panel_id,
            assignment_id=assignment_id,
            role_id=role_id,
            subject_sha256=subject_sha256,
            rubric_sha256=rubric_sha256,
            policy_sha256=self.policy_sha256,
        )
        return PanelAssignment(
            panel_id=panel_id,
            assignment_id=assignment_id,
            attempt_id=f"{assignment_id}.attempt-1",
            role_id=role_id,
            worker_identity_id=identity.worker_identity_id,
            host_agent_id=identity.host_agent_id,
            subject_sha256=subject_sha256,
            rubric_sha256=rubric_sha256,
            acceptance_key=(0, ordinal, assignment_id),
            blind_envelope=envelope,
            required=required,
            execution_mode=execution_mode,  # type: ignore[arg-type]
            execution_provenance=execution_mode,  # type: ignore[arg-type]
            isolation_proven=identity.isolated,
        )

    def synthesize(
        self,
        panel: PanelPlan,
        reports: Mapping[str, ReviewerReport] | Iterable[ReviewerReport],
        *,
        covered_dimensions: Iterable[str] = (),
    ) -> SynthesisResult:
        if panel.status != "ready" or panel.synthesizer_assignment is None:
            return SynthesisResult(
                status="blocked",
                synthesis=None,
                synthesis_assignment=None,
                blockers=panel.blockers or ("formal panel independence is unavailable",),
                limitations=panel.limitations,
            )

        report_values = tuple(reports.values()) if isinstance(reports, Mapping) else tuple(reports)
        by_role: dict[str, ReviewerReport] = {}
        blockers: list[str] = []
        for report in report_values:
            if report.role_id in by_role:
                blockers.append(f"duplicate report for required role: {report.role_id}")
            by_role[report.role_id] = report

        missing = [role for role in self.required_roles if role not in by_role]
        if missing:
            blockers.append(f"missing required reports: {', '.join(missing)}")
        assignment_by_role = {item.role_id: item for item in panel.reviewer_assignments}
        reviewer_workers = {item.worker_identity_id for item in panel.reviewer_assignments}
        reviewer_hosts = {item.host_agent_id for item in panel.reviewer_assignments}
        for role, report in by_role.items():
            assignment = assignment_by_role.get(role)
            if assignment is None:
                blockers.append(f"report role is not assigned by this panel: {role}")
                continue
            if (
                report.worker_identity_id != assignment.worker_identity_id
                or report.host_agent_id != assignment.host_agent_id
            ):
                blockers.append(f"report identity does not match assignment: {role}")
            if report.subject_sha256 != panel.subject_sha256 or report.rubric_sha256 != panel.rubric_sha256:
                blockers.append(f"report snapshot mismatch: {role}")
            if report.execution_mode not in {
                "native_profile",
                "assignment_injected_subagent",
            } or not report.isolated:
                blockers.append(f"report independence is unproven: {role}")
        if (
            panel.synthesizer_assignment.worker_identity_id in reviewer_workers
            or panel.synthesizer_assignment.host_agent_id in reviewer_hosts
        ):
            blockers.append("synthesizer identity is not separate from reviewers")

        limitations = list(panel.limitations)
        covered = set(covered_dimensions)
        limitations.extend(
            f"uncovered review dimension: {dimension}"
            for dimension in self.required_dimensions
            if dimension not in covered
        )
        if blockers:
            return SynthesisResult(
                status="blocked",
                synthesis=None,
                synthesis_assignment=None,
                blockers=tuple(dict.fromkeys(blockers)),
                limitations=tuple(dict.fromkeys(limitations)),
            )

        panel = panel.with_accepted_reports(report_values)

        groups: dict[str, list[tuple[ReviewerReport, FindingObservation]]] = defaultdict(list)
        for report in report_values:
            for finding in report.findings:
                groups[finding.finding_id].append((report, finding))

        cells: list[FindingMatrixCell] = []
        critical_blockers: list[str] = []
        for finding_id in sorted(groups):
            observations = tuple(groups[finding_id])
            finding_observations = tuple(item[1] for item in observations)
            source_reports = tuple(item[0] for item in observations)
            stances = Counter(item.stance for item in finding_observations)
            selected_stance, selected_count = sorted(
                stances.items(), key=lambda item: (-item[1], item[0])
            )[0]
            da_observation = next(
                (
                    finding
                    for report, finding in observations
                    if report.role_id == "devils_advocate_reviewer"
                ),
                None,
            )
            if da_observation is not None and (
                da_observation.severity == "critical"
                and (
                    da_observation.stance != selected_stance
                    or not da_observation.resolved
                )
            ):
                classification: FindingClassification = "DA-critical"
            elif len(stances) == 1 and len(finding_observations) == len(report_values):
                classification = "consensus"
            elif selected_count > len(finding_observations) / 2:
                classification = "majority"
            else:
                classification = "split"

            severity = max(
                (finding.severity for finding in finding_observations),
                key=("low", "moderate", "high", "critical").index,
            )
            confidence = round(
                sum(finding.confidence for finding in finding_observations)
                / len(finding_observations),
                12,
            )
            evidence = tuple(
                dict.fromkeys(
                    evidence_hash
                    for finding in finding_observations
                    for evidence_hash in finding.evidence_sha256
                )
            )
            resolution: Literal["resolved", "unresolved"] = (
                "unresolved"
                if any(not finding.resolved for finding in finding_observations)
                else "resolved"
            )
            dissent = tuple(
                finding
                for finding in finding_observations
                if finding.stance != selected_stance or classification in {"split", "DA-critical"}
            )
            cell = FindingMatrixCell(
                finding_id=finding_id,
                source_report_ids=tuple(report.report_id for report in source_reports),
                source_report_sha256=tuple(report.report_sha256 or "" for report in source_reports),
                evidence_sha256=evidence,
                severity=severity,
                confidence=confidence,
                classification=classification,
                resolution=resolution,
                observations=finding_observations,
                dissent=dissent,
            )
            cells.append(cell)
            if resolution == "unresolved" and (
                severity == "critical" or classification == "DA-critical"
            ):
                critical_blockers.append(
                    f"critical dissent remains unresolved for finding {finding_id}"
                )
            if len(source_reports) != len(report_values):
                limitations.append(
                    f"finding {finding_id} was not covered by every required reviewer"
                )

        limitations_tuple = tuple(dict.fromkeys(limitations))
        synth_assignment = panel.synthesizer_assignment
        source_hashes = tuple(report.report_sha256 or "" for report in report_values)
        synth_envelope = BlindReviewEnvelope(
            panel_id=panel.panel_id,
            assignment_id=synth_assignment.assignment_id,
            role_id=SYNTHESIS_ROLE,
            subject_sha256=panel.subject_sha256,
            rubric_sha256=panel.rubric_sha256,
            policy_sha256=panel.policy_sha256,
            synthesizer=True,
            accepted_report_sha256=source_hashes,
        )
        synth_assignment = PanelAssignment(
            panel_id=synth_assignment.panel_id,
            assignment_id=synth_assignment.assignment_id,
            attempt_id=synth_assignment.attempt_id,
            role_id=synth_assignment.role_id,
            worker_identity_id=synth_assignment.worker_identity_id,
            host_agent_id=synth_assignment.host_agent_id,
            subject_sha256=synth_assignment.subject_sha256,
            rubric_sha256=synth_assignment.rubric_sha256,
            acceptance_key=synth_assignment.acceptance_key,
            blind_envelope=synth_envelope,
            required=synth_assignment.required,
            round_number=synth_assignment.round_number,
            execution_mode=synth_assignment.execution_mode,
            execution_provenance=synth_assignment.execution_provenance,
            isolation_proven=synth_assignment.isolation_proven,
        )
        all_blockers = tuple(dict.fromkeys(critical_blockers))
        gate: GateVerdict = "BLOCKED" if all_blockers else "PASS"
        synthesis = SynthesisRecord(
            synthesis_id=f"{panel.panel_id}.synthesis",
            worker_identity_id=synth_assignment.worker_identity_id,
            host_agent_id=synth_assignment.host_agent_id,
            source_reports=tuple(report_values),
            finding_matrix=tuple(cells),
            limitations=limitations_tuple,
            gate_verdict=gate,
        )
        return SynthesisResult(
            status="blocked" if all_blockers else "accepted",
            synthesis=synthesis,
            synthesis_assignment=synth_assignment,
            blockers=all_blockers,
            limitations=limitations_tuple,
        )


def prepare_formal_panel(**kwargs: object) -> PanelPlan:
    """Functional entry point for callers that do not retain a policy object."""

    return FormalPanelPolicy().prepare_panel(**kwargs)  # type: ignore[arg-type]


def synthesize_formal_panel(
    panel: PanelPlan,
    reports: Mapping[str, ReviewerReport] | Iterable[ReviewerReport],
    *,
    policy: FormalPanelPolicy | None = None,
    covered_dimensions: Iterable[str] = (),
) -> SynthesisResult:
    return (policy or FormalPanelPolicy()).synthesize(
        panel, reports, covered_dimensions=covered_dimensions
    )


# Plan 04-01 owns the canonical Pydantic report/finding records.  These aliases
# keep the pure policy's richer observation records separate while making the
# downstream bridge explicit and discoverable to lifecycle plans.
ReviewFinding = OrchestrationReviewFinding
ReviewFindingMatrix = OrchestrationReviewFindingMatrix
ReviewReport = OrchestrationReviewReport
ReviewSynthesis = OrchestrationReviewSynthesis
ReviewFindingContract = OrchestrationReviewFinding
ReviewReportContract = OrchestrationReviewReport
ReviewSynthesisContract = OrchestrationReviewSynthesis
