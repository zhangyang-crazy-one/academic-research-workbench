"""Strict, immutable scientific-integrity receipts.

Integrity receipts are observations, not mutable runtime authority.  Their
canonical bytes are content addressed and the evaluator is a pure function of
the stored receipt, a current subject/input inventory, and an injected clock.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal, Mapping, Sequence

from pydantic import BeforeValidator, Field, StringConstraints, field_validator, model_validator

from arw.canonical import canonical_json_bytes, sha256_hex, strict_json_loads
from arw.manifests import ManifestError, _safe_directory, _write_once
from arw.models import ActorId, Sha256, StrictModel


INTEGRITY_SCHEMA_VERSION = "arw.integrity-receipt.v1"
INTEGRITY_SCHEMA_NAME = "integrity-receipt.schema.json"
MAX_CLOCK_SKEW_SECONDS = 300

_NormalizedId = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=128,
        pattern=r"^[a-z][a-z0-9._:-]*$",
    ),
]
_Version = Annotated[
    str,
    StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._+:-]*$"),
]
_ReasonCode = Annotated[
    str,
    StringConstraints(min_length=1, max_length=96, pattern=r"^[a-z][a-z0-9._:-]*$"),
]


def _parse_utc(value: str) -> datetime:
    """Parse the exact UTC timestamp used by canonical runtime records."""

    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except (TypeError, ValueError) as error:
        raise ValueError("timestamps must be exact UTC YYYY-MM-DDTHH:MM:SSZ values") from error


def _ordered_unique(values: Sequence[str], *, label: str) -> tuple[str, ...]:
    result = tuple(values)
    if len(result) != len(set(result)):
        raise ValueError(f"{label} must be unique")
    if result != tuple(sorted(result)):
        raise ValueError(f"{label} must be sorted canonically")
    return result


def _freeze_json_array(value: object) -> tuple[object, ...]:
    """Accept JSON arrays while retaining immutable tuple storage."""

    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    raise ValueError("contract array fields must be JSON arrays")


class IntegrityToolIdentity(StrictModel):
    """Identity of the exact validator implementation that produced a receipt."""

    name: _NormalizedId
    version: _Version
    build_sha256: Sha256


class IntegrityFreshnessPolicy(StrictModel):
    """Explicit receipt freshness and bounded future-clock tolerance."""

    valid_until: str
    clock_skew_seconds: int = Field(ge=0, le=MAX_CLOCK_SKEW_SECONDS)

    @field_validator("valid_until")
    @classmethod
    def valid_until_is_utc(cls, value: str) -> str:
        _parse_utc(value)
        return value


class IntegrityReceipt(StrictModel):
    """Content-addressed scientific integrity observation."""

    schema_version: Literal[INTEGRITY_SCHEMA_VERSION]
    receipt_id: _NormalizedId
    subject_kind: _NormalizedId
    subject_id: _NormalizedId
    subject_sha256: Sha256
    input_sha256: Annotated[tuple[Sha256, ...], BeforeValidator(_freeze_json_array)] = Field(
        min_length=1
    )
    method_id: _NormalizedId
    method_version: _Version
    tool_identity: IntegrityToolIdentity
    observed_at: str
    freshness_policy: IntegrityFreshnessPolicy
    verdict: Literal["PASS", "FAIL", "BLOCKED"]
    reason_codes: Annotated[tuple[_ReasonCode, ...], BeforeValidator(_freeze_json_array)] = Field(
        min_length=1
    )
    reason_text: Annotated[str, StringConstraints(min_length=1, max_length=2048)]
    source_manifest_sha256: Annotated[
        tuple[Sha256, ...], BeforeValidator(_freeze_json_array)
    ] = Field(min_length=1)
    created_by: ActorId
    receipt_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def derive_or_verify_digest(cls, value: Any) -> Any:
        """Derive the hash when absent and reject producer substitution."""

        if isinstance(value, cls) or not isinstance(value, Mapping):
            return value
        body = dict(value)
        supplied = body.pop("receipt_sha256", None)
        try:
            expected = sha256_hex(canonical_json_bytes(body))
        except (TypeError, ValueError):
            # Field validation below reports the useful strict type error.
            return value
        if supplied is not None and supplied != expected:
            raise ValueError("receipt_sha256 does not match canonical receipt bytes")
        body["receipt_sha256"] = expected
        return body

    @field_validator("input_sha256")
    @classmethod
    def inputs_are_canonical(cls, value: tuple[Sha256, ...]) -> tuple[Sha256, ...]:
        return _ordered_unique(value, label="input_sha256")

    @field_validator("source_manifest_sha256")
    @classmethod
    def sources_are_canonical(cls, value: tuple[Sha256, ...]) -> tuple[Sha256, ...]:
        return _ordered_unique(value, label="source_manifest_sha256")

    @field_validator("reason_codes")
    @classmethod
    def reasons_are_canonical(cls, value: tuple[_ReasonCode, ...]) -> tuple[_ReasonCode, ...]:
        return _ordered_unique(value, label="reason_codes")

    @field_validator("observed_at")
    @classmethod
    def observed_at_is_utc(cls, value: str) -> str:
        _parse_utc(value)
        return value

    @model_validator(mode="after")
    def semantic_contract(self) -> "IntegrityReceipt":
        unsigned = self.model_dump(mode="json", exclude={"receipt_sha256"})
        expected = sha256_hex(canonical_json_bytes(unsigned))
        if self.receipt_sha256 != expected:
            raise ValueError("receipt_sha256 does not match canonical receipt bytes")
        invalid_pass_reasons = {
            "subject_digest_mismatch",
            "input_digest_mismatch",
            "freshness_expired",
            "future_timestamp",
            "missing_source",
            "receipt_tampered",
        }
        if self.verdict == "PASS" and invalid_pass_reasons.intersection(self.reason_codes):
            raise ValueError("PASS receipt cannot contain a failure or blocker reason")
        return self

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json"))

    def unsigned_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json", exclude={"receipt_sha256"}))


@dataclass(frozen=True, slots=True)
class IntegrityEvaluation:
    """Pure result of reevaluating one immutable receipt against live inputs."""

    verdict: Literal["PASS", "FAIL", "BLOCKED"]
    reason_codes: tuple[str, ...] = ()
    replacement_evidence: tuple[str, ...] = ()

    @property
    def status(self) -> Literal["PASS", "FAIL", "BLOCKED"]:
        """Alias used by callers that model evaluations as statuses."""

        return self.verdict


class IntegrityReceiptError(ValueError, ManifestError):
    """Receipt bytes or publication location are unsafe or inconsistent."""


def seal_integrity_receipt(value: Mapping[str, Any] | IntegrityReceipt) -> IntegrityReceipt:
    """Validate and deterministically seal one receipt without side effects."""

    if isinstance(value, IntegrityReceipt):
        # Revalidate model_copy()-produced objects so a caller cannot bypass
        # the canonical digest check through Pydantic's non-validating update.
        value = value.model_dump(mode="json")
    try:
        return IntegrityReceipt.model_validate(value)
    except Exception as error:
        raise IntegrityReceiptError(f"invalid integrity receipt: {error}") from error


def _receipt_directory(root: Path, *, create: bool) -> Path:
    try:
        return _safe_directory(root, ("integrity", "receipts", "sha256"), create=create)
    except ManifestError as error:
        raise IntegrityReceiptError(str(error)) from error


def publish_integrity_receipt(root: Path, value: Mapping[str, Any] | IntegrityReceipt) -> Path:
    """Publish one receipt exactly once below a caller-approved run root."""

    receipt = seal_integrity_receipt(value)
    directory = _receipt_directory(root, create=True)
    try:
        return _write_once(directory / f"{receipt.receipt_sha256}.json", receipt.canonical_bytes())
    except ManifestError as error:
        raise IntegrityReceiptError(str(error)) from error


def load_integrity_receipt(root: Path, receipt_sha256: str) -> IntegrityReceipt:
    """Load and revalidate one immutable receipt by its content address."""

    if len(receipt_sha256) != 64 or any(c not in "0123456789abcdef" for c in receipt_sha256):
        raise IntegrityReceiptError("receipt address must be a lowercase SHA-256 digest")
    directory = _receipt_directory(root, create=False)
    path = directory / f"{receipt_sha256}.json"
    if path.is_symlink() or not path.is_file():
        raise IntegrityReceiptError("integrity receipt is missing or unsafe")
    try:
        raw = path.read_bytes()
        receipt = seal_integrity_receipt(strict_json_loads(raw))
    except IntegrityReceiptError:
        raise
    except (OSError, UnicodeError, ValueError) as error:
        raise IntegrityReceiptError(f"integrity receipt is invalid: {error}") from error
    if receipt.receipt_sha256 != receipt_sha256:
        raise IntegrityReceiptError("integrity receipt digest field mismatch")
    return receipt


def _coerce_now(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("evaluation clock must be timezone-aware UTC")
        return value.astimezone(UTC)
    return _parse_utc(value)


def evaluate_integrity_receipt(
    receipt: IntegrityReceipt,
    subject_sha256: str | None,
    input_sha256: Sequence[str] | None,
    now: datetime | str | None = None,
) -> IntegrityEvaluation:
    """Evaluate freshness and live digests without mutating canonical state."""

    try:
        checked = seal_integrity_receipt(receipt)
    except IntegrityReceiptError:
        return IntegrityEvaluation(
            "BLOCKED",
            ("receipt_tampered",),
            ("receipt-replacement-required",),
        )

    current = _coerce_now(now)
    reasons: list[str] = []
    replacements: list[str] = []
    if subject_sha256 is None:
        reasons.append("missing_source")
        replacements.append(f"subject:{checked.subject_sha256}")
    elif subject_sha256 != checked.subject_sha256:
        reasons.append("subject_digest_mismatch")
        replacements.append(f"subject:{subject_sha256}")

    if input_sha256 is None:
        reasons.append("missing_source")
        replacements.append("inputs:missing")
    else:
        try:
            current_inputs = tuple(sorted(set(input_sha256)))
        except TypeError:
            current_inputs = ()
        if current_inputs != checked.input_sha256:
            reasons.append("input_digest_mismatch")
            replacements.append("inputs:" + ",".join(current_inputs))

    observed = _parse_utc(checked.observed_at)
    skew = timedelta(seconds=checked.freshness_policy.clock_skew_seconds)
    if observed > current + skew:
        reasons.append("future_timestamp")
        replacements.append(f"observed_at:{checked.observed_at}")
    if current > _parse_utc(checked.freshness_policy.valid_until):
        reasons.append("freshness_expired")
        replacements.append(f"valid_until:{checked.freshness_policy.valid_until}")

    if not reasons:
        return IntegrityEvaluation(checked.verdict, checked.reason_codes if checked.verdict != "PASS" else ())
    if any(reason in {"missing_source", "future_timestamp", "receipt_tampered"} for reason in reasons):
        verdict: Literal["PASS", "FAIL", "BLOCKED"] = "BLOCKED"
    else:
        verdict = "FAIL"
    return IntegrityEvaluation(verdict, tuple(dict.fromkeys(reasons)), tuple(replacements))


def generate_phase6_schema_documents() -> dict[str, dict[str, object]]:
    """Generate checked-in Draft 2020-12 Phase 6 contract documents."""

    document = IntegrityReceipt.model_json_schema(mode="validation")
    generated = {
        INTEGRITY_SCHEMA_NAME: {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://academic-research-workbench.local/schemas/v1/{INTEGRITY_SCHEMA_NAME}",
            **document,
        }
    }
    # Keep one registry-owned Phase 6 name tuple while allowing each contract
    # module to own its model projection.
    from arw.experiment_provenance import generate_phase6_schema_documents as generate_provenance_schemas

    generated.update(generate_provenance_schemas())
    # Evidence access and claim-capability contracts are kept in their own
    # module to avoid making integrity receipts an authority store.  Import
    # lazily here so the two modules can compose their pure evaluators without
    # creating an import cycle during normal runtime use.
    from arw.evidence_access import generate_phase6_schema_documents as generate_access_schemas

    generated.update(generate_access_schemas())
    from arw.audit_dossier import generate_phase6_audit_schema_documents

    generated.update(generate_phase6_audit_schema_documents())
    return generated


from arw.experiment_provenance import ExperimentProvenance


PHASE6_SCHEMA_MODELS: tuple[type[StrictModel], ...] = (IntegrityReceipt, ExperimentProvenance)
PHASE6_SCHEMA_NAMES: tuple[str, ...] = (
    INTEGRITY_SCHEMA_NAME,
    "experiment-provenance.schema.json",
    "evidence-access-decision.schema.json",
    "lifecycle-evidence.schema.json",
)


def render_integrity_schema_bytes() -> bytes:
    import json

    return (json.dumps(generate_phase6_schema_documents()[INTEGRITY_SCHEMA_NAME], ensure_ascii=False, indent=2) + "\n").encode("utf-8")


__all__ = [
    "INTEGRITY_SCHEMA_NAME",
    "INTEGRITY_SCHEMA_VERSION",
    "IntegrityEvaluation",
    "IntegrityFreshnessPolicy",
    "IntegrityReceipt",
    "IntegrityReceiptError",
    "IntegrityToolIdentity",
    "PHASE6_SCHEMA_MODELS",
    "PHASE6_SCHEMA_NAMES",
    "evaluate_integrity_receipt",
    "generate_phase6_schema_documents",
    "load_integrity_receipt",
    "publish_integrity_receipt",
    "render_integrity_schema_bytes",
    "seal_integrity_receipt",
]
