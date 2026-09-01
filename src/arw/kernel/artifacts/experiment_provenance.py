"""Strict, external-only experiment provenance and qualification policy.

This module intentionally records observations from experiments executed outside
ARW.  It never starts a process.  Provenance is immutable, content addressed,
and accepted into the parent ledger only through :func:`ingest_experiment_provenance`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal, TYPE_CHECKING

from pydantic import BeforeValidator, Field, StrictFloat, StrictInt, StringConstraints, field_validator, model_validator

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex, strict_json_loads
from arw.kernel.ledger.manifests import ManifestError, _safe_directory, _safe_root, _write_once
from arw.kernel.state.models import ActorId, RunId, Sha256, StableRuntimeId, StrictModel, UtcTimestamp

if TYPE_CHECKING:  # pragma: no cover - imported only for static tooling
    from arw.runtime import CommandOutcome, RuntimeCommandService
    from arw.kernel.state.models import RuntimeCommandRequest


EXPERIMENT_PROVENANCE_SCHEMA_VERSION = "arw.experiment-provenance.v1"
EXPERIMENT_PROVENANCE_SCHEMA_NAME = "experiment-provenance.schema.json"
MAX_PROVENANCE_BYTES = 1_048_576
MAX_ENVIRONMENT_FIELDS = 32
MAX_QUALIFICATION_RECEIPTS = 4
QUALIFICATION_KINDS = (
    "sandbox_approval",
    "accountable_approval",
    "environment_capture",
    "provenance_equivalence_probe",
)
EVIDENCE_ACCESS_STATES = (
    "publicly_verified",
    "locally_supplied",
    "restricted",
    "unavailable",
    "human_review_required",
)

_Array = BeforeValidator(lambda value: tuple(value) if isinstance(value, list) else value)
_SecretPattern = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|password|passwd|secret|authorization|bearer|private[_-]?key|begin [^-\n]*private key|sk-[a-z0-9]|ghp_[a-z0-9])"
)
_PrivatePathPattern = re.compile(r"(?:^|[/\\])(?:home|users|private|secrets?)(?:[/\\]|$)", re.IGNORECASE)
_ENV_KEY_PATTERN = re.compile(
    r"^(?:os|python|cuda|framework|compiler|runtime|package|driver|arch|kernel|codex|git)(?:[._-][a-z0-9]+)*$"
)


def _parse_utc(value: str) -> datetime:
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


def _safe_reference(value: str, *, label: str, allow_uri: bool = True) -> str:
    if not value or "\x00" in value or "\\" in value:
        raise ValueError(f"{label} must be a non-empty normalized reference")
    if _SecretPattern.search(value) or _PrivatePathPattern.search(value):
        raise ValueError(f"{label} contains a secret or private-path marker")
    if allow_uri and "://" in value:
        if value.startswith(("http://", "https://", "doi:")):
            return value
        raise ValueError(f"{label} uses an unsupported URI scheme")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} must be a normalized relative POSIX path")
    return value


def _secret_safe(value: str, *, label: str) -> str:
    if not value or "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError(f"{label} is empty or contains control characters")
    if len(value) > 256 or _SecretPattern.search(value):
        raise ValueError(f"{label} contains a secret-looking value")
    if _PrivatePathPattern.search(value):
        raise ValueError(f"{label} contains a private path")
    return value


def _freeze_array(value: object) -> tuple[object, ...]:
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    raise ValueError("contract array fields must be JSON arrays")


class DatasetSource(StrictModel):
    uri_or_path: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    content_sha256: Sha256
    access_state: Literal[
        "publicly_verified",
        "locally_supplied",
        "restricted",
        "unavailable",
        "human_review_required",
    ]
    manifest_sha256: Sha256 | None = None

    @field_validator("uri_or_path")
    @classmethod
    def reference_is_safe(cls, value: str) -> str:
        return _safe_reference(value, label="dataset uri_or_path")

    @model_validator(mode="after")
    def content_digest_is_canonical(self) -> "DatasetSource":
        # A bounded local path may carry the digest of its actual bytes; the
        # parent intake verifies that digest under ``allowed_root``.  External
        # URI records have no local bytes and therefore bind to canonical
        # source identity/manifest bytes here.
        if "://" not in self.uri_or_path:
            return self
        expected = sha256_hex(
            canonical_json_bytes(
                {
                    "uri_or_path": self.uri_or_path,
                    "access_state": self.access_state,
                    "manifest_sha256": self.manifest_sha256,
                }
            )
        )
        if self.content_sha256 != expected:
            raise ValueError("dataset content_sha256 is not derived from canonical source identity")
        return self


class ModelIdentity(StrictModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    revision: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    source_sha256: Sha256

    @field_validator("name", "revision")
    @classmethod
    def identity_is_safe(cls, value: str) -> str:
        return _secret_safe(value, label="model identity")

    @model_validator(mode="after")
    def source_digest_is_canonical(self) -> "ModelIdentity":
        expected = sha256_hex(canonical_json_bytes({"name": self.name, "revision": self.revision}))
        if self.source_sha256 != expected:
            raise ValueError("model source_sha256 is not derived from canonical identity")
        return self


class ConfigurationIdentity(StrictModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    canonical_sha256: Sha256
    content_type: Annotated[str, StringConstraints(min_length=3, max_length=127)]

    @field_validator("name", "content_type")
    @classmethod
    def configuration_value_is_safe(cls, value: str) -> str:
        return _secret_safe(value, label="configuration identity")

    @model_validator(mode="after")
    def configuration_digest_is_canonical(self) -> "ConfigurationIdentity":
        expected = sha256_hex(
            canonical_json_bytes({"name": self.name, "content_type": self.content_type})
        )
        if self.canonical_sha256 != expected:
            raise ValueError("configuration canonical_sha256 is not derived from canonical identity")
        return self


class ExperimentMetric(StrictModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    value: StrictInt | StrictFloat
    unit: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    metric_sha256: Sha256

    @field_validator("name", "unit")
    @classmethod
    def metric_value_is_safe(cls, value: str) -> str:
        return _secret_safe(value, label="metric")

    @model_validator(mode="after")
    def metric_digest_is_canonical(self) -> "ExperimentMetric":
        expected = sha256_hex(
            canonical_json_bytes({"name": self.name, "unit": self.unit, "value": self.value})
        )
        if self.metric_sha256 != expected:
            raise ValueError("metric_sha256 is not derived from canonical metric bytes")
        return self


class ExperimentArtifact(StrictModel):
    artifact_id: StableRuntimeId
    media_type: Annotated[str, StringConstraints(min_length=3, max_length=127)]
    content_sha256: Sha256
    manifest_sha256: Sha256
    content_path: Annotated[str, StringConstraints(min_length=1, max_length=512)] | None = None

    @field_validator("media_type")
    @classmethod
    def media_type_is_safe(cls, value: str) -> str:
        return _secret_safe(value, label="artifact media_type")

    @field_validator("content_path")
    @classmethod
    def path_is_safe(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _safe_reference(value, label="artifact content_path", allow_uri=False)

    @model_validator(mode="after")
    def content_digest_is_canonical(self) -> "ExperimentArtifact":
        if self.content_path is not None:
            return self
        expected = sha256_hex(
            canonical_json_bytes(
                {
                    "artifact_id": self.artifact_id,
                    "media_type": self.media_type,
                    "manifest_sha256": self.manifest_sha256,
                    "content_path": self.content_path,
                }
            )
        )
        if self.content_sha256 != expected:
            raise ValueError("artifact content_sha256 is not derived from canonical artifact identity")
        return self


class EnvironmentIdentity(StrictModel):
    key: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    redacted_value_or_digest: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    tool_version: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    redacted: Literal[True]

    @field_validator("key")
    @classmethod
    def key_is_allowlisted(cls, value: str) -> str:
        if not _ENV_KEY_PATTERN.fullmatch(value):
            raise ValueError("environment key is outside the redacted allowlist")
        return value

    @field_validator("redacted_value_or_digest", "tool_version")
    @classmethod
    def value_is_redacted_and_safe(cls, value: str) -> str:
        return _secret_safe(value, label="environment identity")


class RunnerIdentity(StrictModel):
    identity: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    command_digest: Sha256
    host_digest: Sha256
    started_at: UtcTimestamp
    finished_at: UtcTimestamp

    @field_validator("identity")
    @classmethod
    def runner_is_safe(cls, value: str) -> str:
        return _secret_safe(value, label="runner identity")

    @field_validator("started_at", "finished_at")
    @classmethod
    def timestamp_is_utc(cls, value: str) -> str:
        _parse_utc(value)
        return value

    @model_validator(mode="after")
    def interval_is_valid(self) -> "RunnerIdentity":
        if _parse_utc(self.finished_at) < _parse_utc(self.started_at):
            raise ValueError("runner finished_at precedes started_at")
        return self


class ExecutionClaim(StrictModel):
    mode: Literal["external_only"]
    status: Literal["imported", "blocked"]


class QualificationReceiptRef(StrictModel):
    kind: Literal[
        "sandbox_approval",
        "accountable_approval",
        "environment_capture",
        "provenance_equivalence_probe",
    ]
    receipt_sha256: Sha256


class QualificationReceipt(StrictModel):
    """A candidate qualification receipt supplied to the pure policy check."""

    kind: Literal[
        "sandbox_approval",
        "accountable_approval",
        "environment_capture",
        "provenance_equivalence_probe",
    ]
    subject_sha256: Sha256
    configuration_sha256: Sha256
    artifacts_sha256: Sha256
    observed_at: UtcTimestamp
    valid_until: UtcTimestamp
    verdict: Literal["PASS", "FAIL", "BLOCKED"]
    receipt_sha256: Sha256
    authority_sha256: Sha256 | None = None
    accountable_actor_id: ActorId | None = None
    probe_result: Literal["equivalent", "not_equivalent"] | None = None

    @model_validator(mode="before")
    @classmethod
    def derive_or_verify_digest(cls, value: Any) -> Any:
        if isinstance(value, cls) or not isinstance(value, Mapping):
            return value
        body = dict(value)
        supplied = body.pop("receipt_sha256", None)
        # Pydantic's canonical JSON includes optional fields as explicit nulls;
        # include them before deriving the digest so model_validate and cold
        # replay cover identical bytes.
        body.setdefault("authority_sha256", None)
        body.setdefault("accountable_actor_id", None)
        body.setdefault("probe_result", None)
        expected = sha256_hex(canonical_json_bytes(body))
        if supplied is not None and supplied != expected:
            raise ValueError("qualification receipt digest does not match canonical bytes")
        body["receipt_sha256"] = expected
        return body

    @field_validator("observed_at", "valid_until")
    @classmethod
    def timestamps_are_utc(cls, value: str) -> str:
        _parse_utc(value)
        return value

    @model_validator(mode="after")
    def semantic_contract(self) -> "QualificationReceipt":
        unsigned = self.model_dump(mode="json", exclude={"receipt_sha256"})
        if self.receipt_sha256 != sha256_hex(canonical_json_bytes(unsigned)):
            raise ValueError("qualification receipt digest does not match canonical bytes")
        if _parse_utc(self.valid_until) <= _parse_utc(self.observed_at):
            raise ValueError("qualification receipt must have a positive freshness window")
        if self.kind == "provenance_equivalence_probe" and self.verdict == "PASS" and self.probe_result != "equivalent":
            raise ValueError("passing equivalence probe must record equivalent")
        if self.kind == "accountable_approval" and self.verdict == "PASS":
            if self.authority_sha256 is None or self.accountable_actor_id is None:
                raise ValueError("accountable approval requires authority identity evidence")
        return self


class ExperimentProvenance(StrictModel):
    schema_version: Literal[EXPERIMENT_PROVENANCE_SCHEMA_VERSION]
    provenance_id: StableRuntimeId
    run_id: RunId
    experiment_id: StableRuntimeId
    source_datasets: Annotated[tuple[DatasetSource, ...], _Array] = Field(min_length=1)
    model_identity: Annotated[tuple[ModelIdentity, ...], _Array] = Field(min_length=1)
    configuration: Annotated[tuple[ConfigurationIdentity, ...], _Array] = Field(min_length=1)
    metrics: Annotated[tuple[ExperimentMetric, ...], _Array] = Field(min_length=1)
    artifacts: Annotated[tuple[ExperimentArtifact, ...], _Array] = Field(min_length=1)
    environment: Annotated[tuple[EnvironmentIdentity, ...], _Array] = Field(
        min_length=1, max_length=MAX_ENVIRONMENT_FIELDS
    )
    runner: RunnerIdentity
    execution_claim: ExecutionClaim
    qualification_receipts: Annotated[tuple[QualificationReceiptRef, ...], _Array] = Field(
        max_length=MAX_QUALIFICATION_RECEIPTS
    )
    source_manifest_sha256: Annotated[tuple[Sha256, ...], _Array] = Field(min_length=1)
    created_at: UtcTimestamp
    provenance_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def derive_or_verify_digest(cls, value: Any) -> Any:
        if isinstance(value, cls) or not isinstance(value, Mapping):
            return value
        body = dict(value)
        supplied = body.pop("provenance_sha256", None)
        expected = sha256_hex(canonical_json_bytes(body))
        if supplied is not None and supplied != expected:
            raise ValueError("provenance_sha256 does not match canonical provenance bytes")
        body["provenance_sha256"] = expected
        return body

    @field_validator("created_at")
    @classmethod
    def created_at_is_utc(cls, value: str) -> str:
        _parse_utc(value)
        return value

    @field_validator("source_manifest_sha256")
    @classmethod
    def source_manifests_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _ordered_unique(value, label="source_manifest_sha256")

    @model_validator(mode="after")
    def identities_are_unique_and_digest_is_bound(self) -> "ExperimentProvenance":
        _ordered_unique(tuple(item.uri_or_path for item in self.source_datasets), label="source_datasets")
        _ordered_unique(tuple(item.name for item in self.model_identity), label="model_identity")
        _ordered_unique(tuple(item.name for item in self.configuration), label="configuration")
        _ordered_unique(tuple(item.name for item in self.metrics), label="metrics")
        _ordered_unique(tuple(item.artifact_id for item in self.artifacts), label="artifacts")
        _ordered_unique(tuple(item.key for item in self.environment), label="environment")
        _ordered_unique(tuple(item.kind for item in self.qualification_receipts), label="qualification_receipts")
        if self.execution_claim.mode != "external_only":
            raise ValueError("Phase 6 accepts only external_only provenance")
        unsigned = self.model_dump(mode="json", exclude={"provenance_sha256"})
        if self.provenance_sha256 != sha256_hex(canonical_json_bytes(unsigned)):
            raise ValueError("provenance_sha256 does not match canonical provenance bytes")
        return self

    @property
    def configuration_sha256(self) -> str:
        return sha256_hex(canonical_json_bytes([item.model_dump(mode="json") for item in self.configuration]))

    @property
    def artifacts_sha256(self) -> str:
        return sha256_hex(canonical_json_bytes([item.model_dump(mode="json") for item in self.artifacts]))

    def unsigned_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json", exclude={"provenance_sha256"}))

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json"))


class ProvenanceError(ValueError, ManifestError):
    """Provenance bytes or authority envelope are unsafe or invalid."""


@dataclass(frozen=True, slots=True)
class ControlledExecutionDecision:
    status: Literal["BLOCKED"]
    reason_codes: tuple[str, ...]
    replacement_evidence: tuple[str, ...]
    subprocess_allowed: Literal[False] = False


@dataclass(frozen=True, slots=True)
class ProvenanceAuthorityEnvelope:
    runtime: "RuntimeCommandService"
    request: "RuntimeCommandRequest"


@dataclass(frozen=True, slots=True)
class ProvenanceIngestResult:
    provenance: ExperimentProvenance
    path: Path
    outcome: "CommandOutcome"


def seal_experiment_provenance(value: Mapping[str, Any] | ExperimentProvenance) -> ExperimentProvenance:
    if isinstance(value, ExperimentProvenance):
        return value
    try:
        return ExperimentProvenance.model_validate(value)
    except Exception as error:
        raise ProvenanceError(f"invalid experiment provenance: {error}") from error


def _provenance_directory(root: Path, *, create: bool) -> Path:
    try:
        return _safe_directory(root, ("experiment", "provenance", "sha256"), create=create)
    except ManifestError as error:
        raise ProvenanceError(str(error)) from error


def publish_experiment_provenance(root: Path, value: Mapping[str, Any] | ExperimentProvenance) -> Path:
    provenance = seal_experiment_provenance(value)
    if len(provenance.canonical_bytes()) > MAX_PROVENANCE_BYTES:
        raise ProvenanceError("provenance envelope exceeds the bounded byte limit")
    try:
        return _write_once(
            _provenance_directory(root, create=True) / f"{provenance.provenance_sha256}.json",
            provenance.canonical_bytes(),
        )
    except ManifestError as error:
        raise ProvenanceError(str(error)) from error


def load_experiment_provenance(root: Path, provenance_sha256: str) -> ExperimentProvenance:
    if not re.fullmatch(r"[0-9a-f]{64}", provenance_sha256):
        raise ProvenanceError("provenance address must be a lowercase SHA-256 digest")
    path = _provenance_directory(root, create=False) / f"{provenance_sha256}.json"
    if path.is_symlink() or not path.is_file():
        raise ProvenanceError("experiment provenance is missing or unsafe")
    try:
        provenance = seal_experiment_provenance(strict_json_loads(path.read_bytes()))
    except (OSError, UnicodeError, ValueError) as error:
        raise ProvenanceError(f"experiment provenance is invalid: {error}") from error
    if provenance.provenance_sha256 != provenance_sha256:
        raise ProvenanceError("experiment provenance digest field mismatch")
    return provenance


def _verify_local_references(root: Path, provenance: ExperimentProvenance) -> None:
    """Verify local files when an external record intentionally names one."""

    root = _safe_root(root)
    for reference, expected in (
        *(
            (item.uri_or_path, item.content_sha256)
            for item in provenance.source_datasets
            if "://" not in item.uri_or_path
        ),
        *(
            (item.content_path, item.content_sha256)
            for item in provenance.artifacts
            if item.content_path is not None
        ),
    ):
        assert reference is not None
        candidate = root / PurePosixPath(reference)
        if candidate.is_symlink():
            raise ProvenanceError("local provenance reference must not be a symlink")
        if not candidate.exists():
            raise ProvenanceError(f"local provenance reference is missing: {reference}")
        if not candidate.is_file() or not candidate.resolve().is_relative_to(root):
            raise ProvenanceError("local provenance reference escapes the allowed root")
        if sha256_hex(candidate.read_bytes()) != expected:
            raise ProvenanceError("local provenance content digest mismatch")


def _authority_parts(
    allowed_root: Path, authority_envelope: ProvenanceAuthorityEnvelope
) -> ProvenanceAuthorityEnvelope:
    from arw.kernel.state.models import RuntimeCommandRequest
    from arw.runtime import RuntimeCommandService

    if not isinstance(authority_envelope, ProvenanceAuthorityEnvelope):
        raise ProvenanceError("authority envelope must be an existing ProvenanceAuthorityEnvelope")
    if not isinstance(authority_envelope.runtime, RuntimeCommandService) or not isinstance(
        authority_envelope.request, RuntimeCommandRequest
    ):
        raise ProvenanceError("authority envelope must contain typed parent runtime objects")
    request = authority_envelope.request
    if request.actor_role != "parent_control_plane":
        raise ProvenanceError("only parent_control_plane may publish provenance")
    if authority_envelope.runtime.run_root.resolve() != allowed_root.resolve():
        raise ProvenanceError("authority runtime root differs from allowed_root")
    return authority_envelope


def ingest_experiment_provenance(
    provenance: Mapping[str, Any] | ExperimentProvenance,
    allowed_root: Path,
    authority_envelope: ProvenanceAuthorityEnvelope,
) -> ProvenanceIngestResult:
    """Parent-owned immutable publication followed by one canonical event."""

    checked = seal_experiment_provenance(provenance)
    _verify_local_references(allowed_root, checked)
    authority = _authority_parts(allowed_root, authority_envelope)
    path = publish_experiment_provenance(allowed_root, checked)
    outcome = authority.runtime.append_experiment_provenance(
        authority.request,
        provenance_id=checked.provenance_id,
        experiment_id=checked.experiment_id,
        provenance_sha256=checked.provenance_sha256,
    )
    if not outcome.accepted:
        raise ProvenanceError(
            f"parent runtime rejected provenance acceptance: {outcome.rejection.code if outcome.rejection else 'unknown'}"
        )
    return ProvenanceIngestResult(provenance=checked, path=path, outcome=outcome)


def evaluate_controlled_execution_policy(
    provenance: ExperimentProvenance,
    qualification_receipts: Mapping[str, QualificationReceipt] | Sequence[QualificationReceipt] | None = None,
    *,
    now: datetime | str | None = None,
    **caller_flags: object,
) -> ControlledExecutionDecision:
    """Pure fail-closed gate evaluation; this function never executes a process."""

    checked = seal_experiment_provenance(provenance)
    # The configuration/artifacts digests are derived properties; compute them
    # once instead of re-hashing canonical bytes on every receipt kind check.
    checked_configuration_sha256 = checked.configuration_sha256
    checked_artifacts_sha256 = checked.artifacts_sha256
    current = datetime.now(UTC) if now is None else (_parse_utc(now) if isinstance(now, str) else now.astimezone(UTC))
    reasons: list[str] = []
    replacements: list[str] = []
    if caller_flags:
        reasons.append("caller_supplied_gate_flag")
        replacements.append("parent-qualified-receipts")
    receipts: dict[str, QualificationReceipt] = {}
    if qualification_receipts is not None:
        values = qualification_receipts.values() if isinstance(qualification_receipts, Mapping) else qualification_receipts
        for item in values:
            try:
                # Revalidate even already-typed objects: ``model_copy(update=…)``
                # intentionally skips Pydantic validators and must not create
                # an authority bypass for a forged receipt.
                raw_item = item.model_dump(mode="json") if isinstance(item, QualificationReceipt) else item
                item = QualificationReceipt.model_validate(raw_item)
            except Exception:
                reasons.append("qualification_receipt_invalid")
                continue
            receipts[item.kind] = item
    for kind in QUALIFICATION_KINDS:
        receipt = receipts.get(kind)
        if receipt is None:
            reasons.append(f"missing_{kind}")
            replacements.append(kind)
            continue
        if receipt.verdict != "PASS":
            reasons.append(f"{kind}_not_pass")
        if receipt.subject_sha256 != checked.provenance_sha256:
            reasons.append(f"{kind}_subject_mismatch")
        if receipt.configuration_sha256 != checked_configuration_sha256:
            reasons.append(f"{kind}_configuration_mismatch")
        if receipt.artifacts_sha256 != checked_artifacts_sha256:
            reasons.append(f"{kind}_artifacts_mismatch")
        if _parse_utc(receipt.valid_until) <= current:
            reasons.append(f"{kind}_stale")
        if _parse_utc(receipt.observed_at) > current:
            reasons.append(f"{kind}_future_timestamp")
        if kind == "provenance_equivalence_probe" and receipt.probe_result != "equivalent":
            reasons.append("provenance_equivalence_failed")
        if kind == "accountable_approval" and (
            receipt.authority_sha256 is None or receipt.accountable_actor_id is None
        ):
            reasons.append("accountable_approval_unauthorized")
    # Even a complete, fresh four-receipt set cannot enable a subprocess in v1.
    reasons.append("controlled_execution_adapter_disabled")
    replacements.append("future-qualified-execution-adapter")
    return ControlledExecutionDecision(
        status="BLOCKED",
        reason_codes=tuple(dict.fromkeys(reasons)),
        replacement_evidence=tuple(dict.fromkeys(replacements)),
    )


def generate_phase6_schema_documents() -> dict[str, dict[str, object]]:
    document = ExperimentProvenance.model_json_schema(mode="validation")
    return {
        EXPERIMENT_PROVENANCE_SCHEMA_NAME: {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://academic-research-workbench.local/schemas/v1/{EXPERIMENT_PROVENANCE_SCHEMA_NAME}",
            **document,
        }
    }


PHASE6_SCHEMA_MODELS: tuple[type[StrictModel], ...] = (ExperimentProvenance,)
PHASE6_SCHEMA_NAMES: tuple[str, ...] = (EXPERIMENT_PROVENANCE_SCHEMA_NAME,)


__all__ = [
    "EVIDENCE_ACCESS_STATES",
    "EXPERIMENT_PROVENANCE_SCHEMA_NAME",
    "EXPERIMENT_PROVENANCE_SCHEMA_VERSION",
    "QUALIFICATION_KINDS",
    "ConfigurationIdentity",
    "ControlledExecutionDecision",
    "DatasetSource",
    "EnvironmentIdentity",
    "ExecutionClaim",
    "ExperimentArtifact",
    "ExperimentMetric",
    "ExperimentProvenance",
    "ModelIdentity",
    "ProvenanceAuthorityEnvelope",
    "ProvenanceError",
    "ProvenanceIngestResult",
    "QualificationReceipt",
    "QualificationReceiptRef",
    "RunnerIdentity",
    "PHASE6_SCHEMA_MODELS",
    "PHASE6_SCHEMA_NAMES",
    "evaluate_controlled_execution_policy",
    "generate_phase6_schema_documents",
    "ingest_experiment_provenance",
    "load_experiment_provenance",
    "publish_experiment_provenance",
    "seal_experiment_provenance",
]
