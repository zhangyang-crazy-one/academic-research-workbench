"""Bounded, read-only contracts for source-bound failure diagnosis."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.state.models import EventId, RunId, Sha256, StableRuntimeId, StrictModel

_DECIMAL = r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$"
DecimalText = Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=_DECIMAL)]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=256)]
MechanismId = Literal["sign_inversion", "unit_mismatch", "sample_mapping"]
Finding = Literal["yes", "no", "unknown"]
HypothesisStatus = Literal["kept", "ruled_out", "unresolved"]


class AcceptanceCase(StrictModel):
    sample_id: StableRuntimeId
    expected_value: DecimalText
    unit: ShortText


class FrozenFailureAcceptance(StrictModel):
    schema_version: Literal["arw.failure-acceptance.v1"]
    acceptance_id: StableRuntimeId
    metric: ShortText
    cases: tuple[AcceptanceCase, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def unique_samples(self):
        ids = [case.sample_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("acceptance sample IDs must be unique")
        return self


class ObservedCase(StrictModel):
    sample_id: StableRuntimeId
    value: DecimalText
    unit: ShortText
    source_sample_id: StableRuntimeId | None = None


class FailedAttemptReceipt(StrictModel):
    schema_version: Literal["arw.failed-attempt.v1"]
    attempt_id: StableRuntimeId
    acceptance_sha256: Sha256
    status: Literal["failed"]
    cases: tuple[ObservedCase, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def unique_samples(self):
        ids = [case.sample_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("observed sample IDs must be unique")
        return self


class RecordedEdit(StrictModel):
    field: ShortText
    before: ShortText
    after: ShortText

    @model_validator(mode="after")
    def changes_value(self):
        if self.before == self.after:
            raise ValueError("an edit must change its field")
        return self


class FailureEditRecord(StrictModel):
    schema_version: Literal["arw.failure-edit.v1"]
    attempt_id: StableRuntimeId
    predecessor_attempt_id: StableRuntimeId | None = None
    edits: tuple[RecordedEdit, ...] = Field(min_length=1, max_length=32)


class FailureDiagnosisRequest(StrictModel):
    schema_version: Literal["arw.failure-diagnosis-request.v1"]
    acceptance_artifact_id: StableRuntimeId
    failure_artifact_ids: tuple[StableRuntimeId, ...] = Field(min_length=1, max_length=8)
    change_artifact_ids: tuple[StableRuntimeId, ...] = Field(default=(), max_length=8)
    prior_diagnosis_artifact_id: StableRuntimeId | None = None
    handoff_memory_id: StableRuntimeId | None = None
    previous_handoff_memory_id: StableRuntimeId | None = None

    @model_validator(mode="after")
    def coherent_continuation(self):
        ids = (self.acceptance_artifact_id, *self.failure_artifact_ids, *self.change_artifact_ids)
        if len(ids) != len(set(ids)):
            raise ValueError("diagnosis source artifact IDs must be unique")
        if self.handoff_memory_id is not None and self.prior_diagnosis_artifact_id is None:
            raise ValueError("handoff requires a prior accepted diagnosis")
        if self.previous_handoff_memory_id is not None and self.handoff_memory_id is None:
            raise ValueError("previous handoff requires a current handoff")
        return self


class CanonicalSource(StrictModel):
    event_id: EventId
    event_sha256: Sha256
    artifact_id: StableRuntimeId
    artifact_sha256: Sha256


class PatternJudgment(StrictModel):
    kind: Literal["recurrence", "opposing_edits", "expectation_mismatch"]
    finding: Finding
    rationale: ShortText
    sources: tuple[CanonicalSource, ...] = Field(min_length=1, max_length=16)


class ProbeOutcome(StrictModel):
    mechanism_id: MechanismId
    expected_result: ShortText


class DiscriminatingProbe(StrictModel):
    question: ShortText
    expected_outcomes: tuple[ProbeOutcome, ...] = Field(min_length=2, max_length=3)
    actual_evidence: CanonicalSource | None = None

    @model_validator(mode="after")
    def distinguishes(self):
        ids = [outcome.mechanism_id for outcome in self.expected_outcomes]
        if len(ids) != len(set(ids)) or len({outcome.expected_result for outcome in self.expected_outcomes}) < 2:
            raise ValueError("probe outcomes must distinguish distinct mechanisms")
        return self


class MechanismHypothesis(StrictModel):
    mechanism_id: MechanismId
    statement: ShortText
    falsifier: ShortText
    status: HypothesisStatus
    rationale: ShortText
    sources: tuple[CanonicalSource, ...] = Field(min_length=1, max_length=16)
    probe: DiscriminatingProbe
    recommend_probe: bool

    @model_validator(mode="after")
    def no_ruled_out_recommendation(self):
        if self.status == "ruled_out" and self.recommend_probe:
            raise ValueError("a ruled-out mechanism cannot recommend its probe")
        return self


class FailureDiagnosis(StrictModel):
    schema_version: Literal["arw.failure-diagnosis.v1"]
    run_id: RunId
    diagnosis_chain_id: StableRuntimeId
    acceptance: CanonicalSource
    failed_receipts: tuple[CanonicalSource, ...] = Field(min_length=1, max_length=8)
    change_records: tuple[CanonicalSource, ...] = Field(default=(), max_length=8)
    prior_diagnosis: CanonicalSource | None = None
    resumed_from_memory_id: StableRuntimeId | None = None
    source_chain_sha256: Sha256
    symptom: ShortText
    patterns: tuple[PatternJudgment, PatternJudgment, PatternJudgment]
    hypotheses: tuple[MechanismHypothesis, ...] = Field(min_length=2, max_length=3)
    causal_status: Literal["unknown"] = "unknown"
    execution_effect: Literal["read_only_advice"] = "read_only_advice"

    @model_validator(mode="after")
    def unique_mechanisms(self):
        ids = [item.mechanism_id for item in self.hypotheses]
        if len(ids) != len(set(ids)):
            raise ValueError("diagnosis mechanisms must be unique")
        return self

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json", exclude_none=True))

    @property
    def diagnosis_sha256(self) -> str:
        return sha256_hex(self.canonical_bytes())


def failure_diagnosis_schema_documents() -> dict[str, dict[str, object]]:
    models = (
        ("failure-acceptance.schema.json", FrozenFailureAcceptance),
        ("failed-attempt.schema.json", FailedAttemptReceipt),
        ("failure-edit.schema.json", FailureEditRecord),
        ("failure-diagnosis-request.schema.json", FailureDiagnosisRequest),
        ("failure-diagnosis.schema.json", FailureDiagnosis),
    )
    result = {}
    for name, model in models:
        document = model.model_json_schema(mode="validation")
        document["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        document["$id"] = f"https://academic-research-workbench.local/schemas/v1/{name}"
        result[name] = document
    return result
