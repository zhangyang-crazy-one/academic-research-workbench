"""Evidence access decisions and fail-closed scientific claim gates.

Access decisions are observations attached to canonical evidence.  They are
immutable and append-only: a correction or waiver is a new decision which
names the exact predecessor.  Claim evaluation is deliberately pure and
never promotes an inaccessible record merely because a caller supplied a
boolean, a Markdown statement, or a row from the disposable graph.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, Field, StringConstraints, field_validator, model_validator

from arw.canonical import canonical_json_bytes, sha256_hex, strict_json_loads
from arw.manifests import ManifestError, _safe_directory, _write_once
from arw.models import ActorId, Sha256, StableRuntimeId, StrictModel, UtcTimestamp


EVIDENCE_ACCESS_SCHEMA_VERSION = "arw.evidence-access-decision.v1"
EVIDENCE_ACCESS_SCHEMA_NAME = "evidence-access-decision.schema.json"


class EvidenceAccessState(str, Enum):
    """The only access states accepted at a canonical boundary."""

    PUBLICLY_VERIFIED = "publicly_verified"
    LOCALLY_SUPPLIED = "locally_supplied"
    RESTRICTED = "restricted"
    UNAVAILABLE = "unavailable"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


EVIDENCE_ACCESS_STATES: tuple[str, ...] = tuple(item.value for item in EvidenceAccessState)
ClaimCapability = Literal[
    "citation_verified",
    "experiment_reproduced",
    "independent_review_complete",
    "audit_complete",
]
CLAIM_CAPABILITIES: tuple[str, ...] = (
    "citation_verified",
    "experiment_reproduced",
    "independent_review_complete",
    "audit_complete",
)

LicenseStatus = Literal["clear", "ambiguous", "restricted", "unavailable", "unknown"]
DecisionKind = Literal["initial", "verification", "correction", "waiver", "replacement"]
_ID = Annotated[str, StringConstraints(min_length=3, max_length=128, pattern=r"^[a-z][a-z0-9._:-]*$")]


def _parse_utc(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except (TypeError, ValueError) as error:
        raise ValueError("timestamps must be exact UTC YYYY-MM-DDTHH:MM:SSZ values") from error


def _freeze_array(value: object) -> tuple[object, ...]:
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    raise ValueError("contract array fields must be JSON arrays")


def _ordered_unique(values: Sequence[str], *, label: str) -> tuple[str, ...]:
    result = tuple(values)
    if len(result) != len(set(result)):
        raise ValueError(f"{label} must be unique")
    if result != tuple(sorted(result)):
        raise ValueError(f"{label} must be sorted canonically")
    return result


def _coerce_access_state(value: object) -> EvidenceAccessState:
    try:
        return value if isinstance(value, EvidenceAccessState) else EvidenceAccessState(value)
    except (TypeError, ValueError) as error:
        raise ValueError("access_state must be one of the five canonical states") from error


class EvidenceAccessError(ValueError, ManifestError):
    """Unsafe, invalid, or non-append-only evidence access operation."""


class EvidenceAccessDecision(StrictModel):
    """One immutable, digest-bound access decision."""

    schema_version: Literal[EVIDENCE_ACCESS_SCHEMA_VERSION]
    decision_id: StableRuntimeId
    evidence_id: _ID
    subject_sha256: Sha256
    evidence_sha256: Sha256
    source_manifest_sha256: Annotated[tuple[Sha256, ...], BeforeValidator(_freeze_array)] = Field(
        min_length=1, max_length=64
    )
    access_state: Annotated[EvidenceAccessState, BeforeValidator(_coerce_access_state)]
    source_kind: _ID = "evidence"
    source_uri: Annotated[str, StringConstraints(min_length=1, max_length=512)] | None = None
    license_status: LicenseStatus
    license_name: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None = None
    accountable_actor_id: ActorId
    accountable_role: Literal["operator", "review_authority", "access_authority", "parent_control_plane"]
    authority_sha256: Sha256
    rationale: Annotated[str, Field(min_length=1, max_length=4096)]
    scope: Annotated[str, Field(min_length=1, max_length=256)]
    created_at: UtcTimestamp
    decision_kind: DecisionKind = "initial"
    predecessor_sha256: Sha256 | None = None
    supersedes_decision_id: StableRuntimeId | None = None
    superseded_at: UtcTimestamp | None = None
    public_verification_receipt_sha256: Sha256 | None = None
    decision_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def derive_or_verify_digest(cls, value: Any) -> Any:
        if isinstance(value, cls) or not isinstance(value, Mapping):
            return value
        body = dict(value)
        supplied = body.pop("decision_sha256", None)
        # Include every defaulted optional field in the bytes that are signed.
        defaults: dict[str, object] = {
            "source_kind": "evidence",
            "source_uri": None,
            "license_name": None,
            "decision_kind": "initial",
            "predecessor_sha256": None,
            "supersedes_decision_id": None,
            "superseded_at": None,
            "public_verification_receipt_sha256": None,
        }
        for key, default in defaults.items():
            body.setdefault(key, default)
        expected = sha256_hex(canonical_json_bytes(body))
        if supplied is not None and supplied != expected:
            raise ValueError("decision_sha256 does not match canonical decision bytes")
        body["decision_sha256"] = expected
        return body

    @field_validator("source_manifest_sha256")
    @classmethod
    def source_manifests_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _ordered_unique(value, label="source_manifest_sha256")

    @field_validator("created_at", "superseded_at")
    @classmethod
    def timestamps_are_utc(cls, value: str | None) -> str | None:
        if value is not None:
            _parse_utc(value)
        return value

    @field_validator("source_uri")
    @classmethod
    def source_uri_is_bounded(cls, value: str | None) -> str | None:
        if value is not None and ("\x00" in value or "\\" in value):
            raise ValueError("source_uri contains unsafe path characters")
        return value

    @model_validator(mode="after")
    def semantic_contract(self) -> "EvidenceAccessDecision":
        unsigned = self.model_dump(mode="json", exclude={"decision_sha256"})
        if self.decision_sha256 != sha256_hex(canonical_json_bytes(unsigned)):
            raise ValueError("decision_sha256 does not match canonical decision bytes")
        if self.supersedes_decision_id is None and self.predecessor_sha256 is not None:
            raise ValueError("predecessor_sha256 requires supersedes_decision_id")
        if self.supersedes_decision_id is not None and self.predecessor_sha256 is None:
            raise ValueError("superseding decision requires predecessor_sha256")
        if self.access_state == EvidenceAccessState.PUBLICLY_VERIFIED:
            if self.license_status != "clear":
                raise ValueError("public verification requires a clear license status")
            if self.public_verification_receipt_sha256 is None:
                raise ValueError("public verification requires a fresh verification receipt")
        if self.license_status in {"ambiguous", "unknown", "unavailable"} and self.access_state not in {
            EvidenceAccessState.HUMAN_REVIEW_REQUIRED,
            EvidenceAccessState.UNAVAILABLE,
            EvidenceAccessState.RESTRICTED,
        }:
            raise ValueError("ambiguous or unresolved license requires human review or unavailable state")
        if self.access_state == EvidenceAccessState.HUMAN_REVIEW_REQUIRED and self.decision_kind == "initial":
            # Initial human-review decisions are valid, but must say what the
            # reviewer must resolve; this prevents a vacuous blocker record.
            if not self.rationale.strip():
                raise ValueError("human-review decision requires a rationale")
        return self

    def unsigned_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json", exclude={"decision_sha256"}))

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json"))


@dataclass(frozen=True, slots=True)
class AccessTransition:
    """Validated append-only successor relation."""

    predecessor_sha256: str
    successor_sha256: str
    transition: str


def seal_evidence_access_decision(value: Mapping[str, Any] | EvidenceAccessDecision) -> EvidenceAccessDecision:
    if isinstance(value, EvidenceAccessDecision):
        value = value.model_dump(mode="json")
    try:
        return EvidenceAccessDecision.model_validate(value)
    except Exception as error:
        raise EvidenceAccessError(f"invalid evidence access decision: {error}") from error


def _access_directory(root: Path, *, create: bool) -> Path:
    try:
        return _safe_directory(root, ("evidence", "access", "sha256"), create=create)
    except ManifestError as error:
        raise EvidenceAccessError(str(error)) from error


def publish_evidence_access_decision(root: Path, value: Mapping[str, Any] | EvidenceAccessDecision) -> Path:
    decision = seal_evidence_access_decision(value)
    try:
        return _write_once(
            _access_directory(root, create=True) / f"{decision.decision_sha256}.json",
            decision.canonical_bytes(),
        )
    except ManifestError as error:
        raise EvidenceAccessError(str(error)) from error


def load_evidence_access_decision(root: Path, decision_sha256: str) -> EvidenceAccessDecision:
    if not re.fullmatch(r"[0-9a-f]{64}", decision_sha256):
        raise EvidenceAccessError("decision address must be a lowercase SHA-256 digest")
    try:
        path = _access_directory(root, create=False) / f"{decision_sha256}.json"
        if path.is_symlink() or not path.is_file():
            raise EvidenceAccessError("evidence access decision is missing or unsafe")
        decision = seal_evidence_access_decision(strict_json_loads(path.read_bytes()))
    except EvidenceAccessError:
        raise
    except (OSError, UnicodeError, ValueError) as error:
        raise EvidenceAccessError(f"evidence access decision is invalid: {error}") from error
    if decision.decision_sha256 != decision_sha256:
        raise EvidenceAccessError("evidence access decision digest field mismatch")
    if path.read_bytes() != decision.canonical_bytes():
        raise EvidenceAccessError("evidence access decision is not canonical")
    return decision


_ALLOWED_TRANSITIONS: dict[EvidenceAccessState, frozenset[EvidenceAccessState]] = {
    EvidenceAccessState.PUBLICLY_VERIFIED: frozenset(
        {EvidenceAccessState.PUBLICLY_VERIFIED, EvidenceAccessState.RESTRICTED, EvidenceAccessState.UNAVAILABLE, EvidenceAccessState.HUMAN_REVIEW_REQUIRED, EvidenceAccessState.LOCALLY_SUPPLIED}
    ),
    EvidenceAccessState.LOCALLY_SUPPLIED: frozenset(
        {EvidenceAccessState.LOCALLY_SUPPLIED, EvidenceAccessState.RESTRICTED, EvidenceAccessState.UNAVAILABLE, EvidenceAccessState.HUMAN_REVIEW_REQUIRED}
    ),
    EvidenceAccessState.RESTRICTED: frozenset(
        {EvidenceAccessState.RESTRICTED, EvidenceAccessState.UNAVAILABLE, EvidenceAccessState.HUMAN_REVIEW_REQUIRED}
    ),
    EvidenceAccessState.UNAVAILABLE: frozenset(
        {EvidenceAccessState.UNAVAILABLE, EvidenceAccessState.HUMAN_REVIEW_REQUIRED}
    ),
    EvidenceAccessState.HUMAN_REVIEW_REQUIRED: frozenset(
        {EvidenceAccessState.HUMAN_REVIEW_REQUIRED, EvidenceAccessState.RESTRICTED, EvidenceAccessState.UNAVAILABLE, EvidenceAccessState.LOCALLY_SUPPLIED, EvidenceAccessState.PUBLICLY_VERIFIED}
    ),
}


def validate_access_transition(
    predecessor: EvidenceAccessDecision,
    successor: EvidenceAccessDecision,
    *,
    public_verification_receipt_sha256: str | None = None,
) -> AccessTransition:
    """Validate a successor without mutating or rewriting its predecessor."""

    previous = seal_evidence_access_decision(predecessor)
    current = seal_evidence_access_decision(successor)
    if current.evidence_id != previous.evidence_id or current.subject_sha256 != previous.subject_sha256:
        raise EvidenceAccessError("access successor must bind the same evidence and subject")
    if current.predecessor_sha256 != previous.decision_sha256:
        raise EvidenceAccessError("access successor predecessor hash does not match")
    if current.supersedes_decision_id != previous.decision_id:
        raise EvidenceAccessError("access successor must name the exact predecessor decision")
    if current.access_state not in _ALLOWED_TRANSITIONS[previous.access_state]:
        raise EvidenceAccessError("access transition is not allowed")
    if current.access_state == EvidenceAccessState.PUBLICLY_VERIFIED:
        receipt = public_verification_receipt_sha256 or current.public_verification_receipt_sha256
        if receipt is None or receipt != current.public_verification_receipt_sha256:
            raise EvidenceAccessError("public promotion requires the exact fresh verification receipt")
    if current.license_status in {"ambiguous", "unknown", "unavailable"} and current.access_state == EvidenceAccessState.PUBLICLY_VERIFIED:
        raise EvidenceAccessError("unresolved license cannot be promoted to public verification")
    return AccessTransition(previous.decision_sha256, current.decision_sha256, f"{previous.access_state.value}->{current.access_state.value}")


def supersede_evidence_access_decision(
    predecessor: EvidenceAccessDecision,
    successor: Mapping[str, Any] | EvidenceAccessDecision,
    *,
    public_verification_receipt_sha256: str | None = None,
) -> EvidenceAccessDecision:
    current = seal_evidence_access_decision(successor)
    validate_access_transition(
        predecessor,
        current,
        public_verification_receipt_sha256=public_verification_receipt_sha256,
    )
    return current


@dataclass(frozen=True, slots=True)
class ClaimCapabilityDecision:
    capability: ClaimCapability
    status: Literal["PASS", "FAIL", "BLOCKED"]
    reason_codes: tuple[str, ...] = ()
    replacement_evidence: tuple[str, ...] = ()
    scope: str = ""

    @property
    def verdict(self) -> Literal["PASS", "FAIL", "BLOCKED"]:
        return self.status

    @property
    def human_review_required(self) -> bool:
        return "evidence_access_requires_human_review" in self.reason_codes


def _decision(value: EvidenceAccessDecision | Mapping[str, Any] | None) -> EvidenceAccessDecision | None:
    if value is None:
        return None
    try:
        return seal_evidence_access_decision(value)
    except EvidenceAccessError:
        return None


def _access_blocker(decision: EvidenceAccessDecision | None) -> tuple[list[str], list[str]]:
    if decision is None:
        return ["missing_access_decision"], ["evidence-access-decision"]
    if decision.access_state != EvidenceAccessState.PUBLICLY_VERIFIED:
        return ["evidence_access_requires_human_review"], [
            f"access:{decision.evidence_id}:human_review_required",
        ]
    return [], []


def _fresh_integrity(
    receipt: Any,
    *,
    subject_sha256: str,
    input_sha256: Sequence[str] | None,
    now: datetime | str | None,
) -> tuple[list[str], list[str]]:
    if receipt is None:
        return ["missing_fresh_integrity_receipt"], ["integrity-receipt"]
    try:
        from arw.integrity import IntegrityReceipt, evaluate_integrity_receipt, seal_integrity_receipt

        checked = seal_integrity_receipt(receipt if isinstance(receipt, Mapping) else receipt.model_dump(mode="json"))
        if not isinstance(checked, IntegrityReceipt):
            raise ValueError
        evaluation = evaluate_integrity_receipt(checked, subject_sha256, input_sha256, now)
    except Exception:
        return ["integrity_receipt_invalid"], ["integrity-receipt-replacement"]
    if evaluation.verdict != "PASS":
        return list(evaluation.reason_codes or ("integrity_receipt_not_fresh",)), list(
            evaluation.replacement_evidence or ("integrity-receipt-replacement",)
        )
    return [], []


def _fresh_until(value: str | None, now: datetime | str | None) -> bool:
    if value is None:
        return False
    current = _parse_utc(now) if isinstance(now, str) else (now or datetime.now(UTC)).astimezone(UTC)
    try:
        return current <= _parse_utc(value)
    except ValueError:
        return False


def evaluate_claim_capability(
    capability: ClaimCapability,
    access_decision: EvidenceAccessDecision | Mapping[str, Any] | None = None,
    *,
    integrity_receipt: Any = None,
    provenance: Any = None,
    qualification_receipts: Mapping[str, Any] | Sequence[Any] | None = None,
    panel_manifest: Any = None,
    review_matrix: Any = None,
    gate_decision: Any = None,
    run_replay_receipt: Any = None,
    passport_receipts: Sequence[Any] | None = None,
    graph_projection_receipt: Any = None,
    test_receipts: Sequence[Any] | None = None,
    benchmark_receipts: Sequence[Any] | None = None,
    build_receipt: Any = None,
    technical_blockers: Sequence[str] | None = None,
    now: datetime | str | None = None,
    **caller_claims: object,
) -> ClaimCapabilityDecision:
    """Evaluate one scientific claim solely from typed lifecycle evidence."""

    if capability not in CLAIM_CAPABILITIES:
        raise ValueError(f"unknown claim capability: {capability}")
    decision = _decision(access_decision)
    reasons, replacements = _access_blocker(decision)
    scope = decision.scope if decision else ""
    if caller_claims:
        reasons.append("caller_supplied_capability_flag")
        replacements.append("canonical-lifecycle-evidence")
    if reasons:
        return ClaimCapabilityDecision(capability, "BLOCKED", tuple(dict.fromkeys(reasons)), tuple(dict.fromkeys(replacements)), scope)

    assert decision is not None
    if capability == "citation_verified":
        more_reasons, more_replacements = _fresh_integrity(
            integrity_receipt,
            subject_sha256=decision.subject_sha256,
            input_sha256=(decision.evidence_sha256,),
            now=now,
        )
        if more_reasons:
            return ClaimCapabilityDecision(capability, "BLOCKED", tuple(more_reasons), tuple(more_replacements), scope)
        return ClaimCapabilityDecision(capability, "PASS", scope=scope)

    if capability == "experiment_reproduced":
        if provenance is None:
            return ClaimCapabilityDecision(capability, "BLOCKED", ("missing_external_provenance",), ("experiment-provenance",), scope)
        try:
            from arw.experiment_provenance import evaluate_controlled_execution_policy, seal_experiment_provenance

            checked = seal_experiment_provenance(provenance)
            policy = evaluate_controlled_execution_policy(checked, qualification_receipts, now=now)
            return ClaimCapabilityDecision(
                capability,
                "BLOCKED",
                tuple(dict.fromkeys(policy.reason_codes)),
                tuple(dict.fromkeys(policy.replacement_evidence)),
                scope,
            )
        except Exception:
            return ClaimCapabilityDecision(capability, "BLOCKED", ("external_provenance_invalid",), ("experiment-provenance-replacement",), scope)

    if capability == "independent_review_complete":
        reasons = []
        replacements = []
        try:
            from arw.orchestration_models import GateDecision, PanelManifest, ReviewFindingMatrix

            panel = PanelManifest.model_validate(panel_manifest.model_dump(mode="json") if hasattr(panel_manifest, "model_dump") else panel_manifest)
            matrix = ReviewFindingMatrix.model_validate(review_matrix.model_dump(mode="json") if hasattr(review_matrix, "model_dump") else review_matrix)
            gate = GateDecision.model_validate(gate_decision.model_dump(mode="json") if hasattr(gate_decision, "model_dump") else gate_decision)
            if panel.status != "ready" or panel.manifest_sha256 != matrix.panel_manifest_sha256:
                reasons.append("panel_manifest_not_ready_or_mismatch")
            if matrix.gate_verdict != "PASS" or gate.verdict != "PASS":
                reasons.append("review_gate_not_pass")
            if not _fresh_until(gate.fresh_until, now):
                reasons.append("review_gate_stale")
            if tuple(sorted(matrix.synthesis.source_report_sha256)) != tuple(sorted(report.report_sha256 for report in matrix.reports)):
                reasons.append("review_report_hash_set_incomplete")
        except Exception:
            reasons.append("missing_review_lifecycle_evidence")
            replacements.append("panel-manifest-review-matrix-gate")
        if reasons:
            return ClaimCapabilityDecision(capability, "BLOCKED", tuple(dict.fromkeys(reasons)), tuple(dict.fromkeys(replacements or ("fresh-independent-review-evidence",))), scope)
        return ClaimCapabilityDecision(capability, "PASS", scope=scope)

    # audit_complete: every input is an explicit lifecycle receipt.  Truthy
    # caller booleans are not accepted as substitutes for these records.
    required = (
        ("missing_run_replay_receipt", run_replay_receipt),
        ("missing_passport_receipts", passport_receipts),
        ("missing_graph_projection_receipt", graph_projection_receipt),
        ("missing_test_receipts", test_receipts),
        ("missing_build_receipt", build_receipt),
    )
    reasons = [code for code, value in required if not value]
    if benchmark_receipts is None:
        reasons.append("missing_benchmark_receipts")
    if technical_blockers:
        reasons.append("unresolved_technical_blockers")
    if reasons:
        return ClaimCapabilityDecision(capability, "BLOCKED", tuple(dict.fromkeys(reasons)), ("complete-audit-dossier-evidence",), scope)
    return ClaimCapabilityDecision(capability, "PASS", scope=scope)


def generate_phase6_schema_documents() -> dict[str, dict[str, object]]:
    document = EvidenceAccessDecision.model_json_schema(mode="validation")
    return {
        EVIDENCE_ACCESS_SCHEMA_NAME: {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://academic-research-workbench.local/schemas/v1/{EVIDENCE_ACCESS_SCHEMA_NAME}",
            **document,
        }
    }


PHASE6_SCHEMA_NAMES: tuple[str, ...] = (EVIDENCE_ACCESS_SCHEMA_NAME,)


__all__ = [
    "AccessTransition",
    "CLAIM_CAPABILITIES",
    "ClaimCapabilityDecision",
    "EVIDENCE_ACCESS_SCHEMA_NAME",
    "EVIDENCE_ACCESS_SCHEMA_VERSION",
    "EVIDENCE_ACCESS_STATES",
    "EvidenceAccessDecision",
    "EvidenceAccessError",
    "EvidenceAccessState",
    "evaluate_claim_capability",
    "generate_phase6_schema_documents",
    "load_evidence_access_decision",
    "publish_evidence_access_decision",
    "seal_evidence_access_decision",
    "supersede_evidence_access_decision",
    "validate_access_transition",
]
