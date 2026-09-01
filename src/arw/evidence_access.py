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

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex, strict_json_loads
from arw.kernel.ledger.manifests import ManifestError, _safe_directory, _write_once
from arw.kernel.state.models import ActorId, Sha256, StableRuntimeId, StrictModel, UtcTimestamp


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
LIFECYCLE_SCHEMA_NAME = "lifecycle-evidence.schema.json"

LicenseStatus = Literal["clear", "ambiguous", "restricted", "unavailable", "unknown"]
DecisionKind = Literal["initial", "verification", "correction", "waiver", "replacement"]
_ID = Annotated[str, StringConstraints(min_length=3, max_length=128, pattern=r"^[a-z][a-z0-9._:-]*$")]
_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|(?:^|[?&])token(?:=|[&_])|password|passwd|secret|authorization|bearer|private[_-]?key|begin [^-\n]*private key|sk-[a-z0-9]|ghp_[a-z0-9]|://[^/\s:@]+:[^/@\s]+@)"
)
_PRIVATE_PATH_PATTERN = re.compile(r"(?:^|[/\\])(?:home|users|private|secrets?)(?:[/\\]|$)", re.I)


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
    evidence_sha256: Annotated[tuple[Sha256, ...], BeforeValidator(_freeze_array)] = Field(
        min_length=1, max_length=64
    )
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

    @field_validator("evidence_sha256")
    @classmethod
    def evidence_digests_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _ordered_unique(value, label="evidence_sha256")

    @field_validator("created_at", "superseded_at")
    @classmethod
    def timestamps_are_utc(cls, value: str | None) -> str | None:
        if value is not None:
            _parse_utc(value)
        return value

    @field_validator("source_uri")
    @classmethod
    def source_uri_is_bounded(cls, value: str | None) -> str | None:
        if value is not None and (
            "\x00" in value
            or "\\" in value
            or value.lower().startswith("file://")
            or _SECRET_PATTERN.search(value)
            or _PRIVATE_PATH_PATTERN.search(value)
        ):
            raise ValueError("source_uri contains unsafe or private content")
        return value

    @field_validator("rationale", "scope")
    @classmethod
    def decision_text_is_redacted(cls, value: str) -> str:
        if _SECRET_PATTERN.search(value) or _PRIVATE_PATH_PATTERN.search(value):
            raise ValueError("access decision text contains secret or private content")
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
    root: Path | None = None,
    allowed_root: Path | None = None,
    evidence_root: Path | None = None,
    parent_authority: Any = None,
    authority: Any = None,
    now: datetime | str | None = None,
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
        receipt = current.public_verification_receipt_sha256
        if (
            receipt is None
            or public_verification_receipt_sha256 is not None
            and public_verification_receipt_sha256 != receipt
        ):
            raise EvidenceAccessError("public promotion requires the exact fresh verification receipt")
        receipt_root = allowed_root or root or evidence_root
        if receipt_root is None:
            raise EvidenceAccessError("public promotion requires a run-root verification receipt")
        try:
            from arw.integrity import evaluate_integrity_receipt, load_integrity_receipt

            checked_receipt = load_integrity_receipt(receipt_root, receipt)
            evaluation = evaluate_integrity_receipt(
                checked_receipt,
                current.subject_sha256,
                current.evidence_sha256,
                now,
            )
        except Exception as error:
            raise EvidenceAccessError("public verification receipt is missing or invalid") from error
        if evaluation.verdict != "PASS":
            raise EvidenceAccessError(
                "public verification receipt is stale or digest-mismatched: "
                + ",".join(evaluation.reason_codes)
            )
        parent = authority if authority is not None else parent_authority
        if parent is None:
            raise EvidenceAccessError("public promotion requires parent-authorized transition")
        try:
            from arw.kernel.state.orchestration_models import HumanAuthority

            if not isinstance(parent, HumanAuthority):
                raise TypeError("authority must be a validated HumanAuthority")
            clock = _coerce_utc(now)
            if not (_parse_utc(parent.authenticated_at) <= clock <= _parse_utc(parent.expires_at)):
                raise ValueError("authority is outside its authentication window")
            if current.authority_sha256 != parent.authority_sha256:
                raise ValueError("transition authority does not match parent authority")
            if current.accountable_actor_id != parent.authenticated_actor_id:
                raise ValueError("transition actor does not match authenticated authority")
            if current.accountable_role != parent.accountable_role:
                raise ValueError("transition role does not match authenticated authority")
            if current.scope not in parent.allowed_scopes:
                raise ValueError("transition scope is not authorized")
            if current.decision_kind not in parent.allowed_decision_kinds:
                raise ValueError("transition kind is not authorized")
        except EvidenceAccessError:
            raise
        except Exception as error:
            raise EvidenceAccessError("transition lacks a valid parent authority envelope") from error
    if current.license_status in {"ambiguous", "unknown", "unavailable"} and current.access_state == EvidenceAccessState.PUBLICLY_VERIFIED:
        raise EvidenceAccessError("unresolved license cannot be promoted to public verification")
    return AccessTransition(previous.decision_sha256, current.decision_sha256, f"{previous.access_state.value}->{current.access_state.value}")


def supersede_evidence_access_decision(
    predecessor: EvidenceAccessDecision,
    successor: Mapping[str, Any] | EvidenceAccessDecision,
    *,
    public_verification_receipt_sha256: str | None = None,
    root: Path | None = None,
    allowed_root: Path | None = None,
    evidence_root: Path | None = None,
    parent_authority: Any = None,
    authority: Any = None,
    now: datetime | str | None = None,
) -> EvidenceAccessDecision:
    current = seal_evidence_access_decision(successor)
    validate_access_transition(
        predecessor,
        current,
        public_verification_receipt_sha256=public_verification_receipt_sha256,
        root=root,
        allowed_root=allowed_root,
        evidence_root=evidence_root,
        parent_authority=parent_authority,
        authority=authority,
        now=now,
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
    return seal_evidence_access_decision(value)


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


def _fresh_until(
    value: str | None, now: datetime | str | None, *, observed_at: str | None = None
) -> bool:
    if value is None:
        return False
    try:
        current = _coerce_utc(now)
        if observed_at is not None and _parse_utc(observed_at) > current:
            return False
        return current <= _parse_utc(value)
    except (TypeError, ValueError):
        return False


def _coerce_utc(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("evaluation clock must be timezone-aware")
        return value.astimezone(UTC)
    return _parse_utc(value)


class LifecycleEvidenceRecord(StrictModel):
    """Typed, digest-bound lifecycle evidence used by claim capabilities."""

    schema_version: Literal["arw.lifecycle-evidence.v1"]
    record_kind: Annotated[str, StringConstraints(min_length=3, max_length=64, pattern=r"^[a-z][a-z0-9._:-]*$")]
    receipt_id: StableRuntimeId
    subject_sha256: Sha256
    input_sha256: Annotated[tuple[Sha256, ...], BeforeValidator(_freeze_array)] = Field(min_length=1)
    observed_at: UtcTimestamp
    fresh_until: UtcTimestamp
    verdict: Literal["PASS", "FAIL", "BLOCKED"]
    receipt_sha256: Sha256

    @field_validator("input_sha256")
    @classmethod
    def inputs_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _ordered_unique(value, label="input_sha256")

    @model_validator(mode="before")
    @classmethod
    def derive_digest(cls, value: Any) -> Any:
        if isinstance(value, cls) or not isinstance(value, Mapping):
            return value
        body = dict(value)
        supplied = body.pop("receipt_sha256", None)
        expected = sha256_hex(canonical_json_bytes(body))
        if supplied is not None and supplied != expected:
            raise ValueError("lifecycle receipt digest does not match canonical bytes")
        body["receipt_sha256"] = expected
        return body

    @model_validator(mode="after")
    def digest_is_canonical(self) -> "LifecycleEvidenceRecord":
        if self.receipt_sha256 != sha256_hex(canonical_json_bytes(self.model_dump(mode="json", exclude={"receipt_sha256"}))):
            raise ValueError("lifecycle receipt digest does not match canonical bytes")
        if _parse_utc(self.fresh_until) <= _parse_utc(self.observed_at):
            raise ValueError("lifecycle receipt freshness window must be positive")
        return self


def _lifecycle_record(
    value: Any,
    *,
    record_kind: str,
    subject_sha256: str,
    input_sha256: Sequence[str],
    now: datetime | str | None,
) -> LifecycleEvidenceRecord | None:
    try:
        raw = value.model_dump(mode="json") if isinstance(value, LifecycleEvidenceRecord) else value
        record = LifecycleEvidenceRecord.model_validate(raw)
        if record.record_kind != record_kind or record.subject_sha256 != subject_sha256:
            return None
        if record.input_sha256 != tuple(sorted(set(input_sha256))):
            return None
        if record.verdict != "PASS" or not _fresh_until(
            record.fresh_until, now, observed_at=record.observed_at
        ):
            return None
        return record
    except Exception:
        return None


def _lifecycle_block_reason(
    value: Any,
    *,
    record_kind: str,
    subject_sha256: str,
    input_sha256: Sequence[str],
    now: datetime | str | None,
) -> str:
    """Return a stable reason without treating malformed rows as evidence."""

    if value is None:
        return "missing_citation_lifecycle_receipt" if record_kind == "citation" else "missing_lifecycle_receipt"

    try:
        raw = value.model_dump(mode="json") if isinstance(value, LifecycleEvidenceRecord) else value
        record = LifecycleEvidenceRecord.model_validate(raw)
        if record.record_kind != record_kind or record.subject_sha256 != subject_sha256:
            return "lifecycle_receipt_subject_mismatch"
        if record.input_sha256 != tuple(sorted(set(input_sha256))):
            return "lifecycle_receipt_input_mismatch"
        if record.verdict != "PASS":
            return "lifecycle_receipt_not_pass"
        if _parse_utc(record.observed_at) > _coerce_utc(now):
            return "lifecycle_receipt_not_yet_observed"
        if not _fresh_until(record.fresh_until, now):
            return "lifecycle_receipt_stale"
    except Exception:
        return "lifecycle_receipt_invalid"
    return "lifecycle_receipt_invalid"


def evaluate_claim_capability(
    capability: ClaimCapability,
    access_decision: EvidenceAccessDecision | Mapping[str, Any] | None = None,
    *,
    integrity_receipt: Any = None,
    provenance: Any = None,
    qualification_receipts: Mapping[str, Any] | Sequence[Any] | None = None,
    citation_lifecycle_receipt: Any = None,
    citation_receipt: Any = None,
    reproduction_decision: Any = None,
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
    try:
        decision = _decision(access_decision)
    except EvidenceAccessError:
        return ClaimCapabilityDecision(
            capability, "BLOCKED", ("access_decision_invalid",), ("evidence-access-decision",)
        )
    reasons, replacements = _access_blocker(decision)
    scope = decision.scope if decision else ""
    if caller_claims:
        reasons.append("caller_supplied_capability_flag")
        replacements.append("canonical-lifecycle-evidence")
    if reasons:
        return ClaimCapabilityDecision(capability, "BLOCKED", tuple(dict.fromkeys(reasons)), tuple(dict.fromkeys(replacements)), scope)

    assert decision is not None
    if capability == "citation_verified":
        lifecycle = citation_lifecycle_receipt if citation_lifecycle_receipt is not None else citation_receipt
        lifecycle_record = _lifecycle_record(
            lifecycle,
            record_kind="citation",
            subject_sha256=decision.subject_sha256,
            input_sha256=decision.evidence_sha256,
            now=now,
        )
        if lifecycle_record is None:
            lifecycle_reason = _lifecycle_block_reason(
                lifecycle,
                record_kind="citation",
                subject_sha256=decision.subject_sha256,
                input_sha256=decision.evidence_sha256,
                now=now,
            )
            lifecycle_reasons = (
                (lifecycle_reason, "freshness_expired")
                if lifecycle_reason == "lifecycle_receipt_stale"
                else (lifecycle_reason,)
            )
            return ClaimCapabilityDecision(
                capability,
                "BLOCKED",
                lifecycle_reasons,
                ("citation-lifecycle-receipt",),
                scope,
            )
        more_reasons, more_replacements = _fresh_integrity(
            integrity_receipt,
            subject_sha256=decision.subject_sha256,
            input_sha256=decision.evidence_sha256,
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
            policy_reasons = list(policy.reason_codes)
            policy_replacements = list(policy.replacement_evidence)
            if reproduction_decision is None:
                policy_reasons.append("missing_reproduction_decision")
                policy_replacements.append("reproduction-decision")
            if any(
                item.access_state != "publicly_verified"
                for item in checked.source_datasets
            ):
                policy_reasons.append("provenance_source_access_not_publicly_verified")
                policy_replacements.append("public-dataset-access-receipt")
            return ClaimCapabilityDecision(
                capability,
                "BLOCKED",
                tuple(dict.fromkeys(policy_reasons)),
                tuple(dict.fromkeys(policy_replacements)),
                scope,
            )
        except Exception:
            return ClaimCapabilityDecision(capability, "BLOCKED", ("external_provenance_invalid",), ("experiment-provenance-replacement",), scope)

    if capability == "independent_review_complete":
        reasons = []
        replacements = []
        try:
            from arw.kernel.state.orchestration_models import GateDecision, PanelManifest, ReviewFindingMatrix

            panel = PanelManifest.model_validate(panel_manifest.model_dump(mode="json") if hasattr(panel_manifest, "model_dump") else panel_manifest)
            matrix = ReviewFindingMatrix.model_validate(review_matrix.model_dump(mode="json") if hasattr(review_matrix, "model_dump") else review_matrix)
            gate = GateDecision.model_validate(gate_decision.model_dump(mode="json") if hasattr(gate_decision, "model_dump") else gate_decision)
            if panel.status != "ready" or panel.manifest_sha256 != matrix.panel_manifest_sha256:
                reasons.append("panel_manifest_not_ready_or_mismatch")
            if matrix.subject_sha256 != decision.subject_sha256:
                reasons.append("review_subject_mismatch")
            if gate.subject_sha256 != decision.subject_sha256 or not set(decision.evidence_sha256).issubset(set(gate.evidence_sha256)):
                reasons.append("review_evidence_unbound")
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
        ("run_replay_receipt", run_replay_receipt),
        ("passport_receipts", passport_receipts),
        ("graph_projection_receipt", graph_projection_receipt),
        ("test_receipts", test_receipts),
        ("build_receipt", build_receipt),
        ("benchmark_receipts", benchmark_receipts),
    )
    reasons: list[str] = []
    record_kinds = {
        "run_replay_receipt": "run_replay",
        "passport_receipts": "passport",
        "graph_projection_receipt": "graph_projection",
        "test_receipts": "test",
        "build_receipt": "build",
        "benchmark_receipts": "benchmark",
    }
    for name, value in required:
        values = value if isinstance(value, (tuple, list)) else (value,)
        if not values or any(
            _lifecycle_record(
                item,
                record_kind=record_kinds[name],
                subject_sha256=decision.subject_sha256,
                input_sha256=decision.evidence_sha256,
                now=now,
            )
            is None
            for item in values
        ):
            reasons.append(f"missing_{name}")
    if technical_blockers:
        reasons.append("unresolved_technical_blockers")
    if reasons:
        return ClaimCapabilityDecision(capability, "BLOCKED", tuple(dict.fromkeys(reasons)), ("complete-audit-dossier-evidence",), scope)
    return ClaimCapabilityDecision(capability, "PASS", scope=scope)


def generate_phase6_schema_documents() -> dict[str, dict[str, object]]:
    document = EvidenceAccessDecision.model_json_schema(mode="validation")
    generated = {
        EVIDENCE_ACCESS_SCHEMA_NAME: {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://academic-research-workbench.local/schemas/v1/{EVIDENCE_ACCESS_SCHEMA_NAME}",
            **document,
        }
    }
    lifecycle = LifecycleEvidenceRecord.model_json_schema(mode="validation")
    generated[LIFECYCLE_SCHEMA_NAME] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://academic-research-workbench.local/schemas/v1/{LIFECYCLE_SCHEMA_NAME}",
        **lifecycle,
    }
    return generated


PHASE6_SCHEMA_NAMES: tuple[str, ...] = (EVIDENCE_ACCESS_SCHEMA_NAME, LIFECYCLE_SCHEMA_NAME)


__all__ = [
    "AccessTransition",
    "CLAIM_CAPABILITIES",
    "ClaimCapabilityDecision",
    "EVIDENCE_ACCESS_SCHEMA_NAME",
    "EVIDENCE_ACCESS_SCHEMA_VERSION",
    "LIFECYCLE_SCHEMA_NAME",
    "EVIDENCE_ACCESS_STATES",
    "EvidenceAccessDecision",
    "EvidenceAccessError",
    "EvidenceAccessState",
    "LifecycleEvidenceRecord",
    "evaluate_claim_capability",
    "generate_phase6_schema_documents",
    "load_evidence_access_decision",
    "publish_evidence_access_decision",
    "seal_evidence_access_decision",
    "supersede_evidence_access_decision",
    "validate_access_transition",
]
