"""Offline acceptance of numeric experiment claims against a versioned contract.

The evaluator reads only the external experiment provenance already accepted by
ARW (:mod:`arw.kernel.artifacts.experiment_provenance`) and the raw output files
that provenance names under one authorized root. It never starts a process,
evaluates an expression, calls a model, or opens a network connection. A pass
means only that the supplied artifacts conform to one contract version; it is
not a statistical, scientific, or causal endorsement and grants no claim
capability.
"""

from __future__ import annotations

import csv
import io
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Context, Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, Field, StringConstraints, field_validator, model_validator

from arw.kernel.artifacts.experiment_provenance import (
    ExperimentProvenance,
    seal_experiment_provenance,
)
from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex, strict_json_loads
from arw.kernel.ledger.manifests import ManifestError, _safe_directory, _write_once
from arw.kernel.state.models import Sha256, StableRuntimeId, StrictModel

EXPERIMENT_CONTRACT_SCHEMA_VERSION = "arw.experiment-contract.v1"
EXPERIMENT_ACCEPTANCE_SCHEMA_VERSION = "arw.experiment-acceptance.v1"
EXPERIMENT_CONTRACT_SCHEMA_NAME = "experiment-contract.schema.json"
EXPERIMENT_ACCEPTANCE_SCHEMA_NAME = "experiment-acceptance.schema.json"
ACCEPTANCE_EVALUATOR_VERSION = "1.0.0"
MAX_CONTRACT_BYTES = 262_144
MAX_DATA_BYTES = 8_388_608
MAX_DATA_ROWS = 200_000
MAX_CHECKS = 64

OPERATORS = ("count@1", "max@1", "mean@1", "median@1", "min@1", "sum@1")
UNSUPPORTED_KINDS = (
    "causal_effect",
    "conditional_effect",
    "interaction_effect",
    "leaderboard_rank",
    "statistical_significance",
)
CheckStatus = Literal[
    "passed",
    "failed",
    "evidence_missing",
    "invalid_contract",
    "invalid_artifact",
    "unsupported",
]
# Overall status is the most severe check status; ``passed`` requires every
# check to pass. Blocking states outrank a substantive failure because a failed
# comparison is only meaningful when its contract and evidence are valid.
STATUS_SEVERITY: tuple[str, ...] = (
    "invalid_contract",
    "invalid_artifact",
    "evidence_missing",
    "failed",
    "unsupported",
    "passed",
)

_DECIMAL = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$")
_NON_FINITE = re.compile(r"^[+-]?(?:nan|inf|infinity)$", re.IGNORECASE)
_CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)
_Array = BeforeValidator(lambda value: tuple(value) if isinstance(value, list) else value)

DecimalText = Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=_DECIMAL.pattern)]
Label = Annotated[str, StringConstraints(min_length=1, max_length=256)]
ShortLabel = Annotated[str, StringConstraints(min_length=1, max_length=128)]
Unit = Annotated[str, StringConstraints(min_length=1, max_length=64)]


def _decimal(text: str) -> Decimal:
    with localcontext(_CONTEXT):
        return Decimal(text)


def _text(value: Decimal) -> str:
    """Render a decimal deterministically without exponent drift."""

    with localcontext(_CONTEXT):
        normalized = (+value).normalize()
    if normalized == 0:
        return "0"
    rendered = format(normalized, "f")
    return rendered


def _non_negative(value: str, *, label: str) -> str:
    if _decimal(value) < 0:
        raise ValueError(f"{label} must be non-negative")
    return value


class Tolerance(StrictModel):
    absolute: DecimalText = "0"
    relative: DecimalText = "0"

    @field_validator("absolute", "relative")
    @classmethod
    def tolerance_is_non_negative(cls, value: str) -> str:
        return _non_negative(value, label="tolerance")


class ValueRange(StrictModel):
    minimum: DecimalText | None = None
    maximum: DecimalText | None = None

    @model_validator(mode="after")
    def range_is_ordered(self) -> "ValueRange":
        if self.minimum is None and self.maximum is None:
            raise ValueError("a value range must declare minimum or maximum")
        if (
            self.minimum is not None
            and self.maximum is not None
            and _decimal(self.minimum) > _decimal(self.maximum)
        ):
            raise ValueError("value range minimum exceeds maximum")
        return self


class DataSelector(StrictModel):
    """One numeric column of a provenance-named CSV artifact."""

    artifact_id: StableRuntimeId
    format: Literal["csv"]
    column: ShortLabel
    row_id_column: ShortLabel | None = None
    missing_values: Literal["reject", "exclude"] = "reject"


class ComparisonContext(StrictModel):
    """Everything that must agree before two values may be compared."""

    metric_definition: Label
    unit: Unit
    dataset: Label
    split: ShortLabel
    evaluation_condition: Label


class NumericReproductionCheck(StrictModel):
    check_id: StableRuntimeId
    kind: Literal["numeric_reproduction"]
    reported_metric: ShortLabel
    unit: Unit
    operator: Literal["count@1", "max@1", "mean@1", "median@1", "min@1", "sum@1"]
    data: DataSelector
    tolerance: Tolerance
    valid_range: ValueRange | None = None


class ComparisonSide(StrictModel):
    label: ShortLabel
    reported_metric: ShortLabel
    context: ComparisonContext


class Threshold(StrictModel):
    mode: Literal["absolute", "relative"]
    value: DecimalText

    @field_validator("value")
    @classmethod
    def threshold_is_non_negative(cls, value: str) -> str:
        return _non_negative(value, label="threshold")


class BaselineComparisonCheck(StrictModel):
    check_id: StableRuntimeId
    kind: Literal["baseline_comparison"]
    candidate: ComparisonSide
    baseline: ComparisonSide
    direction: Literal["higher_is_better", "lower_is_better"]
    threshold: Threshold
    valid_range: ValueRange | None = None

    @model_validator(mode="after")
    def sides_differ(self) -> "BaselineComparisonCheck":
        if self.candidate.reported_metric == self.baseline.reported_metric:
            raise ValueError("candidate and baseline must name different reported metrics")
        return self


class UnsupportedClaimCheck(StrictModel):
    """A declared claim type the MVP refuses rather than weakening into a pass."""

    check_id: StableRuntimeId
    kind: Literal[
        "causal_effect",
        "conditional_effect",
        "interaction_effect",
        "leaderboard_rank",
        "statistical_significance",
    ]
    description: Label


ContractCheck = Annotated[
    NumericReproductionCheck | BaselineComparisonCheck | UnsupportedClaimCheck,
    Field(discriminator="kind"),
]


class BudgetDeclaration(StrictModel):
    usage_metric: ShortLabel
    unit: Unit
    limit: DecimalText

    @field_validator("limit")
    @classmethod
    def limit_is_non_negative(cls, value: str) -> str:
        return _non_negative(value, label="budget limit")


class ExperimentContract(StrictModel):
    """Immutable, versioned acceptance contract for one claim.

    A changed threshold, tolerance, or analysis is a new contract version with a
    new digest; the earlier contract and its results stay replayable. The
    ``declared_timing`` field is the author's declaration only: whether it was
    really fixed in advance is decided from parent-ledger ordering at
    evaluation time, never from a self-reported timestamp.
    """

    schema_version: Literal["arw.experiment-contract.v1"]
    contract_id: StableRuntimeId
    contract_version: Annotated[int, Field(ge=1, le=10_000)]
    supersedes_contract_sha256: Sha256 | None = None
    claim_id: StableRuntimeId
    claim_sha256: Sha256
    declared_timing: Literal["predeclared", "exploratory"]
    checks: Annotated[tuple[ContractCheck, ...], _Array] = Field(min_length=1, max_length=MAX_CHECKS)
    budget: BudgetDeclaration | None = None

    @model_validator(mode="after")
    def check_ids_are_unique(self) -> "ExperimentContract":
        identifiers = [check.check_id for check in self.checks]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("contract check identifiers must be unique")
        if self.contract_version == 1 and self.supersedes_contract_sha256 is not None:
            raise ValueError("contract version 1 cannot supersede another contract")
        if self.contract_version > 1 and self.supersedes_contract_sha256 is None:
            raise ValueError("a later contract version must name the contract it supersedes")
        return self

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json", exclude_none=True))

    @property
    def contract_sha256(self) -> str:
        return sha256_hex(self.canonical_bytes())


class TimingEvidence(StrictModel):
    """Parent-ledger acceptance order of the contract and the provenance.

    Both values must come from the parent's canonical journal; they are the only
    accepted evidence that a contract existed before the results did.
    """

    contract_sequence: Annotated[int, Field(ge=1)]
    provenance_sequence: Annotated[int, Field(ge=1)]


class CheckResult(StrictModel):
    check_id: StableRuntimeId
    kind: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    status: CheckStatus
    reasons: Annotated[
        tuple[Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,63}$")], ...], _Array
    ] = ()
    observed: DecimalText | None = None
    expected: DecimalText | None = None
    sample_count: Annotated[int, Field(ge=0)] | None = None
    excluded_missing: Annotated[int, Field(ge=0)] | None = None
    artifact_sha256: Sha256 | None = None


class ExperimentAcceptanceResult(StrictModel):
    """Deterministic, timestamp-free outcome; identical inputs replay byte-for-byte."""

    schema_version: Literal["arw.experiment-acceptance.v1"]
    evaluator_version: Literal["1.0.0"]
    scope: Literal["contract_conformance_only"]
    contract_id: StableRuntimeId
    contract_version: Annotated[int, Field(ge=1)]
    contract_sha256: Sha256
    provenance_sha256: Sha256
    claim_id: StableRuntimeId
    claim_sha256: Sha256
    predeclaration: Literal[
        "verified_predeclared",
        "predeclaration_unverified",
        "predeclaration_contradicted",
        "exploratory",
    ]
    checks: Annotated[tuple[CheckResult, ...], _Array] = Field(min_length=1, max_length=MAX_CHECKS)
    overall_status: CheckStatus
    budget_status: Literal[
        "not_declared",
        "within_budget",
        "exceeded",
        "unverifiable",
        "invalid_contract",
    ]

    @model_validator(mode="after")
    def overall_is_most_severe(self) -> "ExperimentAcceptanceResult":
        if self.overall_status != _overall(tuple(check.status for check in self.checks)):
            raise ValueError("overall_status must be the most severe check status")
        return self

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json", exclude_none=True))

    @property
    def result_sha256(self) -> str:
        return sha256_hex(self.canonical_bytes())


class ExperimentAcceptanceError(ValueError, ManifestError):
    """Contract, result, or storage bytes are unsafe or inconsistent."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _overall(statuses: Sequence[str]) -> str:
    for status in STATUS_SEVERITY:
        if status in statuses:
            return status
    raise ValueError("acceptance results need at least one check")


@dataclass(frozen=True, slots=True)
class _Outcome:
    status: str
    reasons: tuple[str, ...] = ()
    observed: Decimal | None = None
    expected: Decimal | None = None
    sample_count: int | None = None
    excluded_missing: int | None = None
    artifact_sha256: str | None = None


class _Blocked(Exception):
    def __init__(self, status: str, *reasons: str, artifact_sha256: str | None = None) -> None:
        super().__init__(status)
        self.status = status
        self.reasons = reasons
        self.artifact_sha256 = artifact_sha256


def seal_experiment_contract(value: Mapping[str, Any] | ExperimentContract) -> ExperimentContract:
    if isinstance(value, ExperimentContract):
        value = value.model_dump(mode="json", exclude_none=True)
    try:
        contract = ExperimentContract.model_validate(value)
    except Exception as error:
        raise ExperimentAcceptanceError("invalid_contract", f"invalid experiment contract: {error}") from error
    if len(contract.canonical_bytes()) > MAX_CONTRACT_BYTES:
        raise ExperimentAcceptanceError("invalid_contract", "experiment contract exceeds the bounded byte limit")
    return contract


def _metric_value(provenance: ExperimentProvenance, name: str, unit: str) -> Decimal:
    for metric in provenance.metrics:
        if metric.name != name:
            continue
        if metric.unit != unit:
            raise _Blocked("invalid_contract", "unit_mismatch")
        value = metric.value
        if isinstance(value, float) and not math.isfinite(value):
            raise _Blocked("invalid_artifact", "non_finite_value")
        # repr() is the shortest round-tripping text, so the decimal is exact
        # for the reported value rather than its binary expansion.
        return _decimal(repr(value) if isinstance(value, float) else str(value))
    raise _Blocked("evidence_missing", "reported_metric_missing")


def _check_range(value: Decimal, valid_range: ValueRange | None) -> None:
    if valid_range is None:
        return
    if valid_range.minimum is not None and value < _decimal(valid_range.minimum):
        raise _Blocked("invalid_artifact", "value_out_of_range")
    if valid_range.maximum is not None and value > _decimal(valid_range.maximum):
        raise _Blocked("invalid_artifact", "value_out_of_range")


def _read_artifact(provenance: ExperimentProvenance, artifact_id: str, root: Path) -> tuple[bytes, str]:
    artifact = next((item for item in provenance.artifacts if item.artifact_id == artifact_id), None)
    if artifact is None:
        raise _Blocked("invalid_contract", "unknown_artifact")
    if artifact.content_path is None:
        raise _Blocked("evidence_missing", "raw_output_not_supplied")
    relative = PurePosixPath(artifact.content_path)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise _Blocked("invalid_artifact", "artifact_path_unsafe")
    candidate = root
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise _Blocked("invalid_artifact", "artifact_path_unsafe")
    if not candidate.exists():
        raise _Blocked("evidence_missing", "raw_output_missing")
    if not candidate.is_file() or not candidate.resolve().is_relative_to(root):
        raise _Blocked("invalid_artifact", "artifact_path_unsafe")
    if candidate.stat().st_size > MAX_DATA_BYTES:
        raise _Blocked("invalid_artifact", "artifact_too_large")
    data = candidate.read_bytes()
    if len(data) > MAX_DATA_BYTES:
        raise _Blocked("invalid_artifact", "artifact_too_large")
    if sha256_hex(data) != artifact.content_sha256:
        raise _Blocked("invalid_artifact", "artifact_digest_mismatch")
    return data, artifact.content_sha256


def _column(data: bytes, selector: DataSelector, artifact_sha256: str) -> tuple[list[Decimal], int]:
    def blocked(*reasons: str) -> _Blocked:
        return _Blocked("invalid_artifact", *reasons, artifact_sha256=artifact_sha256)

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise blocked("csv_malformed") from error
    if text.startswith("﻿"):
        text = text[1:]
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as error:
        raise blocked("csv_malformed") from error
    if not rows:
        raise blocked("csv_malformed")
    header = rows[0]
    if len(header) != len(set(header)):
        raise blocked("csv_malformed")
    if selector.column not in header:
        raise blocked("column_missing")
    if selector.row_id_column is not None and selector.row_id_column not in header:
        raise blocked("column_missing")
    body = [row for row in rows[1:] if row != []]
    if len(body) > MAX_DATA_ROWS:
        raise blocked("artifact_too_large")
    index = header.index(selector.column)
    id_index = None if selector.row_id_column is None else header.index(selector.row_id_column)
    seen: set[str] = set()
    values: list[Decimal] = []
    excluded = 0
    for row in body:
        if len(row) != len(header):
            raise blocked("csv_malformed")
        if id_index is not None:
            identifier = row[id_index].strip()
            if not identifier:
                raise blocked("missing_sample_id")
            if identifier in seen:
                raise blocked("duplicate_sample_id")
            seen.add(identifier)
        cell = row[index].strip()
        if cell == "":
            if selector.missing_values == "reject":
                raise blocked("missing_value")
            excluded += 1
            continue
        if _NON_FINITE.match(cell):
            raise blocked("non_finite_value")
        if not _DECIMAL.match(cell):
            raise blocked("non_numeric_value")
        try:
            values.append(_decimal(cell))
        except InvalidOperation as error:
            raise blocked("non_numeric_value") from error
    if not values:
        raise blocked("no_samples")
    return values, excluded


def _apply(operator: str, values: Sequence[Decimal]) -> Decimal:
    with localcontext(_CONTEXT):
        if operator == "count@1":
            return Decimal(len(values))
        if operator == "sum@1":
            return sum(values, Decimal(0))
        if operator == "mean@1":
            return sum(values, Decimal(0)) / Decimal(len(values))
        if operator == "min@1":
            return min(values)
        if operator == "max@1":
            return max(values)
        if operator == "median@1":
            ordered = sorted(values)
            middle = len(ordered) // 2
            if len(ordered) % 2:
                return ordered[middle]
            return (ordered[middle - 1] + ordered[middle]) / Decimal(2)
    raise _Blocked("invalid_contract", "unknown_operator")


def _reproduce(check: NumericReproductionCheck, provenance: ExperimentProvenance, root: Path) -> _Outcome:
    reported = _metric_value(provenance, check.reported_metric, check.unit)
    data, digest = _read_artifact(provenance, check.data.artifact_id, root)
    values, excluded = _column(data, check.data, digest)
    for value in values:
        try:
            _check_range(value, check.valid_range)
        except _Blocked as blocked:
            raise _Blocked(blocked.status, *blocked.reasons, artifact_sha256=digest) from None
    computed = _apply(check.operator, values)
    with localcontext(_CONTEXT):
        allowed = _decimal(check.tolerance.absolute) + _decimal(check.tolerance.relative) * abs(reported)
        within = abs(computed - reported) <= allowed
    return _Outcome(
        status="passed" if within else "failed",
        reasons=() if within else ("reproduction_outside_tolerance",),
        observed=computed,
        expected=reported,
        sample_count=len(values),
        excluded_missing=excluded,
        artifact_sha256=digest,
    )


_CONTEXT_FIELDS = ("metric_definition", "unit", "dataset", "split", "evaluation_condition")


def _compare(check: BaselineComparisonCheck, provenance: ExperimentProvenance) -> _Outcome:
    mismatched = tuple(
        f"context_{field}_mismatch"
        for field in _CONTEXT_FIELDS
        if getattr(check.candidate.context, field) != getattr(check.baseline.context, field)
    )
    if mismatched:
        raise _Blocked("invalid_contract", "incomparable_context", *mismatched)
    candidate = _metric_value(provenance, check.candidate.reported_metric, check.candidate.context.unit)
    baseline = _metric_value(provenance, check.baseline.reported_metric, check.baseline.context.unit)
    _check_range(candidate, check.valid_range)
    _check_range(baseline, check.valid_range)
    threshold = _decimal(check.threshold.value)
    with localcontext(_CONTEXT):
        improvement = candidate - baseline if check.direction == "higher_is_better" else baseline - candidate
        if check.threshold.mode == "relative":
            if baseline == 0:
                raise _Blocked("invalid_contract", "relative_threshold_zero_baseline")
            observed = improvement / abs(baseline)
        else:
            observed = improvement
        # The threshold is inclusive: an improvement exactly equal to it passes.
        passed = observed >= threshold
    return _Outcome(
        status="passed" if passed else "failed",
        reasons=() if passed else ("improvement_below_threshold",),
        observed=observed,
        expected=threshold,
    )


def _evaluate_check(check: ContractCheck, provenance: ExperimentProvenance, root: Path) -> CheckResult:
    try:
        if isinstance(check, UnsupportedClaimCheck):
            outcome = _Outcome(status="unsupported", reasons=(f"{check.kind}_not_supported",))
        elif isinstance(check, NumericReproductionCheck):
            outcome = _reproduce(check, provenance, root)
        else:
            outcome = _compare(check, provenance)
    except _Blocked as blocked:
        outcome = _Outcome(
            status=blocked.status,
            reasons=tuple(dict.fromkeys(blocked.reasons)),
            artifact_sha256=blocked.artifact_sha256,
        )
    return CheckResult(
        check_id=check.check_id,
        kind=check.kind,
        status=outcome.status,  # type: ignore[arg-type]
        reasons=outcome.reasons,
        observed=None if outcome.observed is None else _text(outcome.observed),
        expected=None if outcome.expected is None else _text(outcome.expected),
        sample_count=outcome.sample_count,
        excluded_missing=outcome.excluded_missing,
        artifact_sha256=outcome.artifact_sha256,
    )


def _budget_status(budget: BudgetDeclaration | None, provenance: ExperimentProvenance) -> str:
    if budget is None:
        return "not_declared"
    try:
        usage = _metric_value(provenance, budget.usage_metric, budget.unit)
    except _Blocked as blocked:
        if blocked.status == "invalid_contract":
            return "invalid_contract"
        return "unverifiable"
    return "within_budget" if usage <= _decimal(budget.limit) else "exceeded"


def _predeclaration(contract: ExperimentContract, timing: TimingEvidence | None) -> str:
    if contract.declared_timing == "exploratory":
        return "exploratory"
    if timing is None:
        return "predeclaration_unverified"
    if timing.contract_sequence < timing.provenance_sequence:
        return "verified_predeclared"
    return "predeclaration_contradicted"


def evaluate_experiment_acceptance(
    contract: Mapping[str, Any] | ExperimentContract,
    provenance: Mapping[str, Any] | ExperimentProvenance,
    artifact_root: Path,
    *,
    timing: Mapping[str, Any] | TimingEvidence | None = None,
) -> ExperimentAcceptanceResult:
    """Evaluate one contract version against sealed provenance and raw files."""

    checked_contract = seal_experiment_contract(contract)
    checked_provenance = seal_experiment_provenance(provenance)
    checked_timing = None
    if timing is not None:
        try:
            checked_timing = (
                timing if isinstance(timing, TimingEvidence) else TimingEvidence.model_validate(timing)
            )
        except Exception as error:
            raise ExperimentAcceptanceError("invalid_timing_evidence", f"invalid timing evidence: {error}") from error
    root = Path(artifact_root)
    if root.is_symlink() or not root.is_dir():
        raise ExperimentAcceptanceError("unsafe_artifact_root", "artifact root must be an existing real directory")
    root = root.resolve()
    checks = tuple(_evaluate_check(check, checked_provenance, root) for check in checked_contract.checks)
    return ExperimentAcceptanceResult(
        schema_version="arw.experiment-acceptance.v1",
        evaluator_version="1.0.0",
        scope="contract_conformance_only",
        contract_id=checked_contract.contract_id,
        contract_version=checked_contract.contract_version,
        contract_sha256=checked_contract.contract_sha256,
        provenance_sha256=checked_provenance.provenance_sha256,
        claim_id=checked_contract.claim_id,
        claim_sha256=checked_contract.claim_sha256,
        predeclaration=_predeclaration(checked_contract, checked_timing),  # type: ignore[arg-type]
        checks=checks,
        overall_status=_overall(tuple(item.status for item in checks)),  # type: ignore[arg-type]
        budget_status=_budget_status(checked_contract.budget, checked_provenance),  # type: ignore[arg-type]
    )


def seal_experiment_acceptance(value: Mapping[str, Any] | ExperimentAcceptanceResult) -> ExperimentAcceptanceResult:
    if isinstance(value, ExperimentAcceptanceResult):
        value = value.model_dump(mode="json", exclude_none=True)
    try:
        return ExperimentAcceptanceResult.model_validate(value)
    except Exception as error:
        raise ExperimentAcceptanceError("invalid_result", f"invalid experiment acceptance result: {error}") from error


def replay_experiment_acceptance(
    result: Mapping[str, Any] | ExperimentAcceptanceResult,
    contract: Mapping[str, Any] | ExperimentContract,
    provenance: Mapping[str, Any] | ExperimentProvenance,
    artifact_root: Path,
    *,
    timing: Mapping[str, Any] | TimingEvidence | None = None,
) -> ExperimentAcceptanceResult:
    """Re-run the evaluator and require byte-identical canonical output."""

    recorded = seal_experiment_acceptance(result)
    replayed = evaluate_experiment_acceptance(contract, provenance, artifact_root, timing=timing)
    if replayed.canonical_bytes() != recorded.canonical_bytes():
        raise ExperimentAcceptanceError("replay_mismatch", "experiment acceptance result does not replay")
    return recorded


def _directory(root: Path, leaf: str, *, create: bool) -> Path:
    try:
        return _safe_directory(root, ("experiment", leaf, "sha256"), create=create)
    except ManifestError as error:
        raise ExperimentAcceptanceError("unsafe_store", str(error)) from error


def publish_experiment_contract(root: Path, contract: Mapping[str, Any] | ExperimentContract) -> Path:
    checked = seal_experiment_contract(contract)
    try:
        return _write_once(
            _directory(root, "contracts", create=True) / f"{checked.contract_sha256}.json",
            checked.canonical_bytes(),
        )
    except ManifestError as error:
        raise ExperimentAcceptanceError("unsafe_store", str(error)) from error


def publish_experiment_acceptance(root: Path, result: Mapping[str, Any] | ExperimentAcceptanceResult) -> Path:
    checked = seal_experiment_acceptance(result)
    try:
        return _write_once(
            _directory(root, "acceptance", create=True) / f"{checked.result_sha256}.json",
            checked.canonical_bytes(),
        )
    except ManifestError as error:
        raise ExperimentAcceptanceError("unsafe_store", str(error)) from error


def _load(root: Path, leaf: str, digest: str) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ExperimentAcceptanceError("invalid_address", "address must be a lowercase SHA-256 digest")
    path = _directory(root, leaf, create=False) / f"{digest}.json"
    if path.is_symlink() or not path.is_file():
        raise ExperimentAcceptanceError("missing", f"experiment {leaf} record is missing or unsafe")
    data = path.read_bytes()
    if sha256_hex(data) != digest:
        raise ExperimentAcceptanceError("digest_mismatch", f"experiment {leaf} record digest mismatch")
    return data


def load_experiment_contract(root: Path, contract_sha256: str) -> ExperimentContract:
    return seal_experiment_contract(strict_json_loads(_load(root, "contracts", contract_sha256)))


def load_experiment_acceptance(root: Path, result_sha256: str) -> ExperimentAcceptanceResult:
    return seal_experiment_acceptance(strict_json_loads(_load(root, "acceptance", result_sha256)))


def experiment_acceptance_schema_documents() -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for name, model in (
        (EXPERIMENT_CONTRACT_SCHEMA_NAME, ExperimentContract),
        (EXPERIMENT_ACCEPTANCE_SCHEMA_NAME, ExperimentAcceptanceResult),
    ):
        document = model.model_json_schema(mode="validation")
        document["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        document["$id"] = f"https://academic-research-workbench.local/schemas/v1/{name}"
        result[name] = document
    return result


__all__ = [
    "ACCEPTANCE_EVALUATOR_VERSION",
    "EXPERIMENT_ACCEPTANCE_SCHEMA_NAME",
    "EXPERIMENT_ACCEPTANCE_SCHEMA_VERSION",
    "EXPERIMENT_CONTRACT_SCHEMA_NAME",
    "EXPERIMENT_CONTRACT_SCHEMA_VERSION",
    "OPERATORS",
    "STATUS_SEVERITY",
    "UNSUPPORTED_KINDS",
    "BaselineComparisonCheck",
    "BudgetDeclaration",
    "CheckResult",
    "ComparisonContext",
    "ComparisonSide",
    "DataSelector",
    "ExperimentAcceptanceError",
    "ExperimentAcceptanceResult",
    "ExperimentContract",
    "NumericReproductionCheck",
    "Threshold",
    "TimingEvidence",
    "Tolerance",
    "UnsupportedClaimCheck",
    "ValueRange",
    "evaluate_experiment_acceptance",
    "experiment_acceptance_schema_documents",
    "load_experiment_acceptance",
    "load_experiment_contract",
    "publish_experiment_acceptance",
    "publish_experiment_contract",
    "replay_experiment_acceptance",
    "seal_experiment_acceptance",
    "seal_experiment_contract",
]
