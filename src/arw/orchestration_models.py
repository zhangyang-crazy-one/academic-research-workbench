"""Strict, immutable Phase 4 orchestration contracts.

These records deliberately describe untrusted worker, hook, host, and human
inputs without granting any of them canonical-write authority.  The parent
runtime is responsible for validating these manifests and appending events.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import (
    BeforeValidator,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from arw.canonical import canonical_json_bytes, sha256_hex, strict_json_loads
from arw.models import ActorId, RunId, Sha256, StableRuntimeId, StrictModel, UtcTimestamp


PHASE4_SCHEMA_NAMES: tuple[str, ...] = (
    "role-catalog.schema.json",
    "assignment.schema.json",
    "worker-proposal.schema.json",
    "review-finding-matrix.schema.json",
    "gate-decision.schema.json",
    "hook-observation.schema.json",
    "host-qualification.schema.json",
    "phase4-evaluation-verdict.schema.json",
)

PHASE4_SCHEMA_MODELS: tuple[type[StrictModel], ...]
PHASE4_SCHEMA_VERSION = "1.0.0"
MAX_OUTPUT_BYTES = 8_388_608

ExecutionMode = Literal[
    "native_profile",
    "assignment_injected_subagent",
    "degraded_inline",
    "blocked",
]
ExecutionProvenance = Literal[
    "native_profile",
    "assignment_injected_subagent",
    "degraded_inline",
    "unavailable",
]
GateVerdict = Literal["PASS", "FAIL", "BLOCKED"]
RoleExecutionCapability = Literal["proposal_only", "no_execution"]
AttemptStatus = Literal[
    "prepared",
    "active",
    "cancel_requested",
    "force_terminated",
    "interrupted",
    "completed",
    "failed",
    "cancelled",
    "rejected_stale",
    "superseded",
    "blocked",
]
RetryReason = Literal[
    "timeout",
    "process_failure",
    "repairable_envelope",
    "permission_denied",
    "stale_inputs",
    "superseded",
    "cancelled",
    "scientific_disagreement",
    "identity_mismatch",
    "policy_violation",
    "digest_mismatch",
]
ReviewClassification = Literal["consensus", "majority", "split", "DA-critical"]

FORMAL_REVIEW_ROLE_IDS = frozenset(
    {
        "methodology_reviewer",
        "domain_reviewer",
        "perspective_reviewer",
        "devils_advocate_reviewer",
    }
)
LOCKED_ROLE_IDS = frozenset(
    {
        "research_architect",
        "methodology_reviewer",
        "domain_reviewer",
        "perspective_reviewer",
        "devils_advocate_reviewer",
        "editorial_synthesizer",
        "experiment_designer",
    }
)
DEFERRED_EXECUTOR_ROLE_IDS = frozenset({"code_runner", "study_manager"})
RETRYABLE_FAILURES = frozenset({"timeout", "process_failure", "repairable_envelope"})
NON_RETRYABLE_FAILURES = frozenset(
    {
        "permission_denied",
        "stale_inputs",
        "superseded",
        "cancelled",
        "scientific_disagreement",
        "identity_mismatch",
        "policy_violation",
        "digest_mismatch",
    }
)


def _require_unique(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")
    return values


def _freeze_json_array(value: object) -> tuple[object, ...]:
    """Accept a JSON array at the wire boundary and retain no mutable list."""

    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    raise ValueError("contract array fields must be JSON arrays")


def _normalized_relative_path(value: str, *, label: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or "\x00" in value
        or "\\" in value
        or path.is_absolute()
        or value != path.as_posix()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"{label} must be a normalized relative POSIX path")
    return value


def _validate_execution_claim(
    *, execution_mode: ExecutionMode, execution_provenance: ExecutionProvenance, independence_eligible: bool
) -> None:
    if execution_mode == "degraded_inline":
        if execution_provenance != "degraded_inline":
            raise ValueError("degraded_inline requires degraded_inline provenance")
        if independence_eligible:
            raise ValueError("degraded_inline cannot carry a formal-independence claim")
    elif execution_mode == "blocked":
        if execution_provenance != "unavailable":
            raise ValueError("blocked execution mode requires unavailable provenance")
        if independence_eligible:
            raise ValueError("blocked execution mode cannot carry a formal-independence claim")
    elif execution_mode == "native_profile":
        if execution_provenance != "native_profile":
            raise ValueError("native_profile requires native_profile provenance")
    elif execution_mode == "assignment_injected_subagent":
        if execution_provenance != "assignment_injected_subagent":
            raise ValueError(
                "assignment_injected_subagent requires assignment_injected_subagent provenance"
            )


class RoleDefinition(StrictModel):
    """One versioned role that can produce only a bounded proposal."""

    role_id: StableRuntimeId
    role_version: Literal["1.0.0"]
    execution_capability: RoleExecutionCapability
    independence_eligible: bool
    capability_ids: Annotated[
        tuple[StableRuntimeId, ...], BeforeValidator(_freeze_json_array), Field(max_length=32)
    ]
    allowed_execution_modes: Annotated[
        tuple[ExecutionMode, ...],
        BeforeValidator(_freeze_json_array),
        Field(min_length=1, max_length=4),
    ]
    developer_instructions_sha256: Sha256

    @field_validator("capability_ids", "allowed_execution_modes")
    @classmethod
    def values_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _require_unique(value, "role values")

    @model_validator(mode="after")
    def deferred_execution_remains_disabled(self) -> Self:
        if self.role_id in DEFERRED_EXECUTOR_ROLE_IDS:
            raise ValueError(f"{self.role_id} is a deferred execution adapter")
        if self.role_id == "experiment_designer":
            if self.execution_capability != "proposal_only":
                raise ValueError("experiment_designer must remain proposal-only")
            if any("execution" in capability for capability in self.capability_ids):
                raise ValueError("experiment_designer cannot receive execution capability")
        if "degraded_inline" in self.allowed_execution_modes and self.independence_eligible:
            raise ValueError("independence-eligible roles cannot use degraded_inline")
        return self


class RoleConflict(StrictModel):
    """An unordered identity-separation rule encoded canonically once."""

    first_role_id: StableRuntimeId
    second_role_id: StableRuntimeId
    reason: Annotated[str, Field(min_length=1, max_length=256)]

    @model_validator(mode="after")
    def pair_is_distinct_and_canonical(self) -> Self:
        if self.first_role_id == self.second_role_id:
            raise ValueError("role conflict pairs must name two distinct roles")
        if self.first_role_id > self.second_role_id:
            raise ValueError("role conflict pairs must be lexicographically ordered")
        return self

    @property
    def key(self) -> tuple[str, str]:
        return (self.first_role_id, self.second_role_id)


def _conflict_key(first: str, second: str) -> tuple[str, str]:
    return tuple(sorted((first, second)))  # type: ignore[return-value]


def _required_conflict_keys() -> frozenset[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for reviewer in FORMAL_REVIEW_ROLE_IDS:
        pairs.add(_conflict_key("research_architect", reviewer))
        pairs.add(_conflict_key("editorial_synthesizer", reviewer))
    reviewers = sorted(FORMAL_REVIEW_ROLE_IDS)
    for index, first in enumerate(reviewers):
        for second in reviewers[index + 1 :]:
            pairs.add(_conflict_key(first, second))
    pairs.add(_conflict_key("experiment_designer", "methodology_reviewer"))
    return frozenset(pairs)


class RoleCatalog(StrictModel):
    """The frozen role and identity-conflict vocabulary for one workflow."""

    schema_version: Literal["arw.role-catalog.v1"]
    catalog_version: Literal["1.0.0"]
    roles: Annotated[
        tuple[RoleDefinition, ...],
        BeforeValidator(_freeze_json_array),
        Field(min_length=len(LOCKED_ROLE_IDS), max_length=64),
    ]
    conflict_pairs: Annotated[
        tuple[RoleConflict, ...], BeforeValidator(_freeze_json_array), Field(min_length=1, max_length=128)
    ]

    @model_validator(mode="after")
    def locked_roles_and_conflicts_are_present(self) -> Self:
        role_ids = tuple(role.role_id for role in self.roles)
        if len(role_ids) != len(set(role_ids)):
            raise ValueError("role catalog role IDs must be unique")
        forbidden = sorted(set(role_ids) & DEFERRED_EXECUTOR_ROLE_IDS)
        if forbidden:
            raise ValueError(f"deferred executor roles are prohibited: {', '.join(forbidden)}")
        missing = sorted(LOCKED_ROLE_IDS - set(role_ids))
        if missing:
            raise ValueError(f"role catalog is missing locked roles: {', '.join(missing)}")
        if role_ids != tuple(sorted(role_ids)):
            raise ValueError("role catalog roles must be sorted by role_id")

        keys = tuple(pair.key for pair in self.conflict_pairs)
        if len(keys) != len(set(keys)):
            raise ValueError("role conflict pairs must be unique")
        if keys != tuple(sorted(keys)):
            raise ValueError("role conflict pairs must be sorted")
        missing_conflicts = sorted(_required_conflict_keys() - set(keys))
        if missing_conflicts:
            raise ValueError("role catalog is missing required identity-conflict pairs")
        return self


def _role_digest(role_id: str) -> str:
    return hashlib.sha256(f"arw.role.v1:{role_id}".encode("utf-8")).hexdigest()


def locked_role_catalog() -> RoleCatalog:
    """Return the deterministic minimum catalog required by D-01 through D-04."""

    roles = (
        RoleDefinition(
            role_id="devils_advocate_reviewer",
            role_version="1.0.0",
            execution_capability="proposal_only",
            independence_eligible=True,
            capability_ids=("files.read",),
            allowed_execution_modes=("native_profile", "assignment_injected_subagent", "blocked"),
            developer_instructions_sha256=_role_digest("devils_advocate_reviewer"),
        ),
        RoleDefinition(
            role_id="domain_reviewer",
            role_version="1.0.0",
            execution_capability="proposal_only",
            independence_eligible=True,
            capability_ids=("files.read",),
            allowed_execution_modes=("native_profile", "assignment_injected_subagent", "blocked"),
            developer_instructions_sha256=_role_digest("domain_reviewer"),
        ),
        RoleDefinition(
            role_id="editorial_synthesizer",
            role_version="1.0.0",
            execution_capability="proposal_only",
            independence_eligible=False,
            capability_ids=("files.read",),
            allowed_execution_modes=(
                "native_profile",
                "assignment_injected_subagent",
                "degraded_inline",
                "blocked",
            ),
            developer_instructions_sha256=_role_digest("editorial_synthesizer"),
        ),
        RoleDefinition(
            role_id="experiment_designer",
            role_version="1.0.0",
            execution_capability="proposal_only",
            independence_eligible=False,
            capability_ids=("files.read",),
            allowed_execution_modes=(
                "native_profile",
                "assignment_injected_subagent",
                "degraded_inline",
                "blocked",
            ),
            developer_instructions_sha256=_role_digest("experiment_designer"),
        ),
        RoleDefinition(
            role_id="methodology_reviewer",
            role_version="1.0.0",
            execution_capability="proposal_only",
            independence_eligible=True,
            capability_ids=("files.read",),
            allowed_execution_modes=("native_profile", "assignment_injected_subagent", "blocked"),
            developer_instructions_sha256=_role_digest("methodology_reviewer"),
        ),
        RoleDefinition(
            role_id="perspective_reviewer",
            role_version="1.0.0",
            execution_capability="proposal_only",
            independence_eligible=True,
            capability_ids=("files.read",),
            allowed_execution_modes=("native_profile", "assignment_injected_subagent", "blocked"),
            developer_instructions_sha256=_role_digest("perspective_reviewer"),
        ),
        RoleDefinition(
            role_id="research_architect",
            role_version="1.0.0",
            execution_capability="proposal_only",
            independence_eligible=False,
            capability_ids=("files.read",),
            allowed_execution_modes=(
                "native_profile",
                "assignment_injected_subagent",
                "degraded_inline",
                "blocked",
            ),
            developer_instructions_sha256=_role_digest("research_architect"),
        ),
    )
    conflicts = tuple(
        RoleConflict(first_role_id=first, second_role_id=second, reason="identity-separation")
        for first, second in sorted(_required_conflict_keys())
    )
    return RoleCatalog(
        schema_version="arw.role-catalog.v1",
        catalog_version="1.0.0",
        roles=roles,
        conflict_pairs=conflicts,
    )


class AssignmentKey(StrictModel):
    """A frozen parent-owned acceptance key, never a completion-order key."""

    topological_layer: Annotated[int, Field(ge=0)]
    task_ordinal: Annotated[int, Field(ge=0)]
    assignment_id: StableRuntimeId

    @property
    def value(self) -> tuple[int, int, str]:
        return (self.topological_layer, self.task_ordinal, self.assignment_id)


class OutputPolicy(StrictModel):
    schema_id: StableRuntimeId
    schema_sha256: Sha256
    max_bytes: Annotated[int, Field(ge=1, le=MAX_OUTPUT_BYTES)]
    max_artifacts: Annotated[int, Field(ge=0, le=32)]


class BlindReviewConstraints(StrictModel):
    required: bool
    subject_sha256: Sha256 | None
    rubric_sha256: Sha256 | None
    forbidden_peer_role_ids: Annotated[
        tuple[StableRuntimeId, ...], BeforeValidator(_freeze_json_array), Field(max_length=32)
    ]

    @field_validator("forbidden_peer_role_ids")
    @classmethod
    def peer_roles_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _require_unique(value, "forbidden peer role IDs")

    @model_validator(mode="after")
    def blind_constraints_are_complete(self) -> Self:
        if self.required and (self.subject_sha256 is None or self.rubric_sha256 is None):
            raise ValueError("blind review requires subject and rubric digests")
        if not self.required and (
            self.subject_sha256 is not None
            or self.rubric_sha256 is not None
            or self.forbidden_peer_role_ids
        ):
            raise ValueError("non-blind assignments cannot carry blind-review bindings")
        return self


class CompletionContract(StrictModel):
    requires_completed_proposal: bool
    required_artifact_kinds: Annotated[
        tuple[StableRuntimeId, ...], BeforeValidator(_freeze_json_array), Field(max_length=32)
    ]
    requires_human_gate: bool

    @field_validator("required_artifact_kinds")
    @classmethod
    def artifact_kinds_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _require_unique(value, "required artifact kinds")


class ImmutableAssignment(StrictModel):
    """The content-addressed worker contract that a retry may not mutate."""

    schema_version: Literal["arw.assignment.v1"]
    protocol_version: Literal["1.0.0"]
    assignment_id: StableRuntimeId
    supersedes_assignment_id: StableRuntimeId | None
    run_id: RunId
    stage_id: StableRuntimeId
    task_id: StableRuntimeId
    role_id: StableRuntimeId
    worker_identity_id: StableRuntimeId
    execution_mode: ExecutionMode
    execution_provenance: ExecutionProvenance
    independence_eligible: bool
    base_revision: Annotated[int, Field(ge=0)]
    input_sha256: Annotated[
        tuple[Sha256, ...], BeforeValidator(_freeze_json_array), Field(min_length=1, max_length=128)
    ]
    capability_ids: Annotated[
        tuple[StableRuntimeId, ...], BeforeValidator(_freeze_json_array), Field(max_length=32)
    ]
    allowed_read_root_ids: Annotated[
        tuple[StableRuntimeId, ...], BeforeValidator(_freeze_json_array), Field(max_length=32)
    ]
    scratch_path_template: str
    result_path_template: str
    output_policy: OutputPolicy
    policy_sha256: Sha256
    context_manifest_sha256: Sha256
    blind_review: BlindReviewConstraints
    deadline_at: UtcTimestamp
    completion_contract: CompletionContract
    acceptance_key: AssignmentKey

    @field_validator("input_sha256", "capability_ids", "allowed_read_root_ids")
    @classmethod
    def bindings_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _require_unique(value, "assignment bindings")

    @field_validator("scratch_path_template", "result_path_template")
    @classmethod
    def attempt_path_template_is_confined(cls, value: str) -> str:
        value = _normalized_relative_path(value, label="attempt path template")
        parts = PurePosixPath(value).parts
        if len(parts) < 3 or parts[0] != "attempts" or parts[1] != "{attempt_id}":
            raise ValueError("attempt path templates must be rooted at attempts/{attempt_id}")
        return value

    @model_validator(mode="after")
    def immutable_bindings_are_coherent(self) -> Self:
        _validate_execution_claim(
            execution_mode=self.execution_mode,
            execution_provenance=self.execution_provenance,
            independence_eligible=self.independence_eligible,
        )
        if self.acceptance_key.assignment_id != self.assignment_id:
            raise ValueError("acceptance key assignment_id must echo assignment_id")
        if self.supersedes_assignment_id == self.assignment_id:
            raise ValueError("an assignment cannot supersede itself")
        if self.blind_review.required and not self.independence_eligible:
            raise ValueError("blind-review assignments must be independence eligible")
        if self.role_id in DEFERRED_EXECUTOR_ROLE_IDS:
            raise ValueError("deferred executor roles are prohibited from assignments")
        if any("execution" in capability for capability in self.capability_ids):
            raise ValueError("controlled execution capabilities are disabled in Phase 4")
        return self

    def canonical_bytes(self) -> bytes:
        return canonical_orchestration_model_bytes(self)

    def canonical_sha256(self) -> str:
        return sha256_hex(self.canonical_bytes())

    def validate_supersedes(self, predecessor: ImmutableAssignment) -> None:
        """Require explicit new identity when an assignment replaces another."""

        if self.assignment_id == predecessor.assignment_id:
            raise ValueError("a superseding assignment requires a new assignment_id")
        if self.supersedes_assignment_id != predecessor.assignment_id:
            raise ValueError("a changed assignment must explicitly supersede its predecessor")
        if self.run_id != predecessor.run_id:
            raise ValueError("a superseding assignment must remain in the same run")


class AttemptDescriptor(StrictModel):
    """Attempt-local lifecycle metadata with a bounded retry and continuation budget."""

    schema_version: Literal["arw.attempt-descriptor.v1"]
    assignment_id: StableRuntimeId
    attempt_id: StableRuntimeId
    attempt_number: Annotated[int, Field(ge=1, le=2)]
    proposal_nonce: StableRuntimeId
    status: AttemptStatus
    retry_reason: RetryReason | None
    retry_eligible: bool
    continuation_count: Annotated[int, Field(ge=0, le=1)]
    host_agent_id: Annotated[str, Field(min_length=1, max_length=256)] | None
    cancellation_deadline_at: UtcTimestamp | None

    @model_validator(mode="after")
    def retry_and_cancellation_bounds_are_coherent(self) -> Self:
        if self.retry_reason is None and self.retry_eligible:
            raise ValueError("retry eligibility requires a retry reason")
        if self.retry_reason in RETRYABLE_FAILURES and not self.retry_eligible:
            raise ValueError("repairable failures must be marked retry eligible")
        if self.retry_reason in NON_RETRYABLE_FAILURES and self.retry_eligible:
            raise ValueError("non-retryable failures cannot receive an automatic retry")
        if self.retry_eligible and self.attempt_number >= 2:
            raise ValueError("retry budget is exhausted after two attempts")
        if self.status == "cancel_requested" and self.cancellation_deadline_at is None:
            raise ValueError("cancellation requests require a grace deadline")
        if self.status == "active" and self.host_agent_id is None:
            raise ValueError("active attempts require an observed host agent ID")
        return self


class ProposedArtifact(StrictModel):
    relative_path: str
    sha256: Sha256
    media_type: Annotated[str, Field(min_length=3, max_length=127)]
    schema_id: StableRuntimeId | None
    byte_count: Annotated[int, Field(ge=0, le=MAX_OUTPUT_BYTES)]

    @field_validator("relative_path")
    @classmethod
    def result_file_is_direct_attempt_child(cls, value: str) -> str:
        value = _normalized_relative_path(value, label="proposal artifact path")
        if len(PurePosixPath(value).parts) != 1:
            raise ValueError("proposal artifact path must be a direct result-file child")
        return value


class WorkerProposal(StrictModel):
    """Untrusted, canonical-byte-bound worker result envelope."""

    schema_version: Literal["arw.worker-proposal.v1"]
    protocol_version: Literal["1.0.0"]
    run_id: RunId
    assignment_id: StableRuntimeId
    attempt_id: StableRuntimeId
    role_id: StableRuntimeId
    worker_identity_id: StableRuntimeId
    host_agent_id: Annotated[str, Field(min_length=1, max_length=256)]
    execution_mode: ExecutionMode
    execution_provenance: ExecutionProvenance
    independence_eligible: bool
    assignment_sha256: Sha256
    context_manifest_sha256: Sha256
    policy_sha256: Sha256
    base_revision: Annotated[int, Field(ge=0)]
    input_sha256: Annotated[
        tuple[Sha256, ...], BeforeValidator(_freeze_json_array), Field(min_length=1, max_length=128)
    ]
    proposal_nonce: StableRuntimeId
    status: Literal["completed", "partial", "blocked", "failed", "cancelled"]
    result_provenance_mode: Literal["executed", "reported", "simulated"]
    requested_next_action: Literal["accept", "retry", "human_decision", "none"]
    artifacts: Annotated[
        tuple[ProposedArtifact, ...], BeforeValidator(_freeze_json_array), Field(max_length=32)
    ]
    evidence_sha256: Annotated[
        tuple[Sha256, ...], BeforeValidator(_freeze_json_array), Field(max_length=128)
    ]
    summary: Annotated[str, Field(min_length=1, max_length=4096)]
    unresolved: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=1024)], ...],
        BeforeValidator(_freeze_json_array),
        Field(max_length=64),
    ]

    @field_validator("input_sha256", "evidence_sha256")
    @classmethod
    def hash_bindings_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _require_unique(value, "proposal hash bindings")

    @model_validator(mode="after")
    def proposal_is_coherent(self) -> Self:
        _validate_execution_claim(
            execution_mode=self.execution_mode,
            execution_provenance=self.execution_provenance,
            independence_eligible=self.independence_eligible,
        )
        if self.status == "completed" and not self.artifacts:
            raise ValueError("completed proposal requires at least one artifact")
        if self.requested_next_action == "accept" and self.status != "completed":
            raise ValueError("only completed proposals may request acceptance")
        artifact_paths = tuple(artifact.relative_path for artifact in self.artifacts)
        if len(artifact_paths) != len(set(artifact_paths)):
            raise ValueError("proposal artifact paths must be unique")
        return self

    def validate_against_assignment(
        self, assignment: ImmutableAssignment, attempt: AttemptDescriptor
    ) -> None:
        expected = {
            "run_id": assignment.run_id,
            "assignment_id": assignment.assignment_id,
            "attempt_id": attempt.attempt_id,
            "role_id": assignment.role_id,
            "worker_identity_id": assignment.worker_identity_id,
            "host_agent_id": attempt.host_agent_id,
            "execution_mode": assignment.execution_mode,
            "execution_provenance": assignment.execution_provenance,
            "independence_eligible": assignment.independence_eligible,
            "assignment_sha256": assignment.canonical_sha256(),
            "context_manifest_sha256": assignment.context_manifest_sha256,
            "policy_sha256": assignment.policy_sha256,
            "base_revision": assignment.base_revision,
            "input_sha256": assignment.input_sha256,
            "proposal_nonce": attempt.proposal_nonce,
        }
        for name, expected_value in expected.items():
            if getattr(self, name) != expected_value:
                raise ProposalValidationError(f"proposal {name} does not echo the immutable assignment")
        if len(self.artifacts) > assignment.output_policy.max_artifacts:
            raise ProposalValidationError("proposal exceeds assignment artifact limit")
        total_bytes = sum(artifact.byte_count for artifact in self.artifacts)
        if total_bytes > assignment.output_policy.max_bytes:
            raise ProposalValidationError("proposal exceeds assignment output byte limit")
        if any(artifact.byte_count > assignment.output_policy.max_bytes for artifact in self.artifacts):
            raise ProposalValidationError("proposal artifact exceeds assignment output byte limit")


class ProposalValidationError(ValueError):
    """Raised before an untrusted proposal can reach a parent acceptance path."""


def validate_worker_proposal_bytes(
    raw: bytes, *, assignment: ImmutableAssignment, attempt: AttemptDescriptor
) -> tuple[WorkerProposal, str]:
    """Require strict fields, exact canonical bytes, and immutable echo bindings."""

    try:
        proposal = WorkerProposal.model_validate(strict_json_loads(raw))
    except (TypeError, ValueError, ValidationError) as error:
        raise ProposalValidationError(str(error)) from error
    canonical = canonical_orchestration_model_bytes(proposal)
    if raw != canonical:
        raise ProposalValidationError("proposal is valid JSON but not canonical ARW bytes")
    proposal.validate_against_assignment(assignment, attempt)
    return proposal, sha256_hex(canonical)


class ReviewFinding(StrictModel):
    finding_id: StableRuntimeId
    source_report_sha256: Annotated[
        tuple[Sha256, ...], BeforeValidator(_freeze_json_array), Field(min_length=1, max_length=16)
    ]
    evidence_sha256: Annotated[
        tuple[Sha256, ...], BeforeValidator(_freeze_json_array), Field(min_length=1, max_length=64)
    ]
    severity: Literal["low", "moderate", "high", "critical"]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    classification: ReviewClassification
    resolution: Literal["resolved", "unresolved"]
    rationale: Annotated[str, Field(min_length=1, max_length=4096)]

    @field_validator("source_report_sha256", "evidence_sha256")
    @classmethod
    def finding_hashes_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _require_unique(value, "finding hash bindings")


class ReviewReport(StrictModel):
    report_id: StableRuntimeId
    role_id: StableRuntimeId
    worker_identity_id: StableRuntimeId
    host_agent_id: Annotated[str, Field(min_length=1, max_length=256)]
    subject_sha256: Sha256
    rubric_sha256: Sha256
    report_sha256: Sha256
    findings: Annotated[
        tuple[ReviewFinding, ...], BeforeValidator(_freeze_json_array), Field(min_length=1, max_length=128)
    ]


class ReviewSynthesis(StrictModel):
    synthesis_id: StableRuntimeId
    worker_identity_id: StableRuntimeId
    host_agent_id: Annotated[str, Field(min_length=1, max_length=256)]
    source_report_sha256: Annotated[
        tuple[Sha256, ...], BeforeValidator(_freeze_json_array), Field(min_length=4, max_length=64)
    ]
    findings: Annotated[
        tuple[ReviewFinding, ...], BeforeValidator(_freeze_json_array), Field(min_length=1, max_length=256)
    ]
    limitations: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=1024)], ...],
        BeforeValidator(_freeze_json_array),
        Field(max_length=64),
    ]

    @field_validator("source_report_sha256")
    @classmethod
    def source_reports_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _require_unique(value, "synthesis source report hashes")


class ReviewFindingMatrix(StrictModel):
    schema_version: Literal["arw.review-finding-matrix.v1"]
    panel_id: StableRuntimeId
    subject_sha256: Sha256
    rubric_sha256: Sha256
    reports: Annotated[
        tuple[ReviewReport, ...], BeforeValidator(_freeze_json_array), Field(min_length=4, max_length=64)
    ]
    synthesis: ReviewSynthesis
    gate_verdict: GateVerdict

    @model_validator(mode="after")
    def panel_is_independent_and_complete(self) -> Self:
        required_roles = FORMAL_REVIEW_ROLE_IDS
        role_ids = tuple(report.role_id for report in self.reports)
        if not required_roles <= set(role_ids):
            raise ValueError("formal panel is missing a required independent review role")
        if len(role_ids) != len(set(role_ids)):
            raise ValueError("formal panel role reports must be unique")
        worker_ids = tuple(report.worker_identity_id for report in self.reports)
        host_ids = tuple(report.host_agent_id for report in self.reports)
        if len(worker_ids) != len(set(worker_ids)) or len(host_ids) != len(set(host_ids)):
            raise ValueError("formal panel requires distinct worker and host identities")
        if self.synthesis.worker_identity_id in set(worker_ids) or self.synthesis.host_agent_id in set(host_ids):
            raise ValueError("editorial synthesis requires a separate identity")
        if any(
            report.subject_sha256 != self.subject_sha256 or report.rubric_sha256 != self.rubric_sha256
            for report in self.reports
        ):
            raise ValueError("all first-round reports must share the frozen subject and rubric")
        report_hashes = {report.report_sha256 for report in self.reports}
        if set(self.synthesis.source_report_sha256) != report_hashes:
            raise ValueError("synthesis must bind every accepted first-round report")
        unresolved_critical = any(
            finding.resolution == "unresolved"
            and (finding.severity == "critical" or finding.classification == "DA-critical")
            for finding in self.synthesis.findings
        )
        if unresolved_critical and self.gate_verdict != "BLOCKED":
            raise ValueError("unresolved critical dissent keeps the review gate BLOCKED")
        return self


class HumanDecisionRecord(StrictModel):
    """An append-only scoped human action; it never rewrites a prior verdict."""

    schema_version: Literal["arw.human-decision.v1"]
    decision_id: StableRuntimeId
    decision_kind: Literal[
        "waiver",
        "correction",
        "access_decision",
        "capability_escalation",
        "root_escalation",
        "replacement",
        "approval",
    ]
    gate_id: StableRuntimeId
    subject_sha256: Sha256
    evidence_sha256: Annotated[
        tuple[Sha256, ...], BeforeValidator(_freeze_json_array), Field(min_length=1, max_length=128)
    ]
    applicable_transition: StableRuntimeId
    accountable_actor_id: ActorId
    accountable_role: Literal["operator", "review_authority", "access_authority", "parent_control_plane"]
    scope: Annotated[str, Field(min_length=1, max_length=256)]
    rationale: Annotated[str, Field(min_length=1, max_length=4096)]
    prior_verdict_sha256: Sha256
    supersedes_decision_id: StableRuntimeId | None
    verdict_rewrite: Literal[False] = False

    @field_validator("evidence_sha256")
    @classmethod
    def evidence_is_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _require_unique(value, "human-decision evidence hashes")

    @field_validator("scope")
    @classmethod
    def scope_is_exact_not_blanket(cls, value: str) -> str:
        if value.strip() in {"*", "all", "future", "any"}:
            raise ValueError("human-decision scope must be exact, not blanket")
        return value

    @model_validator(mode="after")
    def correction_has_explicit_predecessor(self) -> Self:
        if self.decision_kind == "correction" and self.supersedes_decision_id is None:
            raise ValueError("corrections must explicitly supersede a prior decision")
        return self


class GateDecision(StrictModel):
    schema_version: Literal["arw.gate-decision.v1"]
    gate_id: StableRuntimeId
    subject_sha256: Sha256
    evidence_sha256: Annotated[
        tuple[Sha256, ...], BeforeValidator(_freeze_json_array), Field(min_length=1, max_length=128)
    ]
    verdict: GateVerdict
    rationale: Annotated[str, Field(min_length=1, max_length=4096)]
    fresh_until: UtcTimestamp | None
    required: bool
    human_decision: HumanDecisionRecord | None

    @field_validator("evidence_sha256")
    @classmethod
    def gate_evidence_is_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _require_unique(value, "gate evidence hashes")

    @model_validator(mode="after")
    def linked_decision_has_exact_gate_scope(self) -> Self:
        if self.human_decision is not None and self.human_decision.gate_id != self.gate_id:
            raise ValueError("human decision must bind the same gate")
        if self.human_decision is not None and self.human_decision.subject_sha256 != self.subject_sha256:
            raise ValueError("human decision must bind the same subject")
        return self


class HookObservation(StrictModel):
    """A bounded non-authoritative hook outcome suitable only for observation."""

    schema_version: Literal["arw.hook-observation.v1"]
    hook_name: Literal["SessionStart", "SubagentStart", "SubagentStop", "PreToolUse", "PostToolUse", "Stop"]
    hook_definition_sha256: Sha256
    target_id: StableRuntimeId
    status: Literal["trusted_enabled", "disabled", "untrusted", "timeout", "failed"]
    observation_sha256: Sha256
    redacted_error_code: StableRuntimeId | None
    idempotency_key: StableRuntimeId
    continuation_requested: bool
    continuation_count: Annotated[int, Field(ge=0, le=1)]

    @model_validator(mode="after")
    def continuation_is_bounded_and_exact(self) -> Self:
        if self.continuation_requested != (self.continuation_count == 1):
            raise ValueError("hook continuation request and count must agree")
        return self


class HostQualification(StrictModel):
    schema_version: Literal["arw.host-qualification.v1"]
    qualification_id: StableRuntimeId
    codex_version: Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    stage_sha256: Sha256
    adapter_sha256: Sha256
    plugin_sha256: Sha256
    execution_mode: ExecutionMode
    status: GateVerdict
    worker_identity_id: StableRuntimeId | None
    host_agent_id: Annotated[str, Field(min_length=1, max_length=256)] | None
    evidence_sha256: Annotated[
        tuple[Sha256, ...], BeforeValidator(_freeze_json_array), Field(min_length=1, max_length=128)
    ]

    @field_validator("evidence_sha256")
    @classmethod
    def qualification_evidence_is_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _require_unique(value, "host qualification evidence hashes")

    @model_validator(mode="after")
    def qualification_claim_is_honest(self) -> Self:
        if self.status == "PASS":
            if self.execution_mode not in {"native_profile", "assignment_injected_subagent"}:
                raise ValueError(
                    "host qualification PASS requires a formal native execution mode"
                )
            if self.worker_identity_id is None or self.host_agent_id is None:
                raise ValueError("host qualification PASS requires observed distinct identity evidence")
        if self.execution_mode == "blocked" and self.status != "BLOCKED":
            raise ValueError("blocked execution mode must record a BLOCKED host qualification")
        return self


class Phase4EvaluationVerdict(StrictModel):
    schema_version: Literal["arw.phase4-evaluation-verdict.v1"]
    corpus_version: StableRuntimeId
    case_id: Annotated[str, StringConstraints(pattern=r"^P4-(DEV|SEALED)-[0-9]{3}$")]
    manifest_sha256: Sha256
    authority_normalized_replay_sha256: Sha256
    terminal_status: GateVerdict
    execution_mode: ExecutionMode
    evidence_sha256: Annotated[
        tuple[Sha256, ...], BeforeValidator(_freeze_json_array), Field(min_length=1, max_length=128)
    ]
    sealed_parent_only: bool

    @field_validator("evidence_sha256")
    @classmethod
    def evaluation_evidence_is_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _require_unique(value, "evaluation evidence hashes")

    @model_validator(mode="after")
    def terminal_status_matches_execution_mode(self) -> Self:
        if self.execution_mode == "blocked" and self.terminal_status != "BLOCKED":
            raise ValueError("blocked execution mode requires a BLOCKED terminal status")
        if self.sealed_parent_only != self.case_id.startswith("P4-SEALED-"):
            raise ValueError("sealed case identity must match parent-only designation")
        return self


PHASE4_SCHEMA_MODELS = (
    RoleCatalog,
    ImmutableAssignment,
    WorkerProposal,
    ReviewFindingMatrix,
    GateDecision,
    HookObservation,
    HostQualification,
    Phase4EvaluationVerdict,
)


def canonical_orchestration_model_bytes(model: StrictModel) -> bytes:
    """Return canonical JSON bytes for one immutable Phase 4 contract."""

    return canonical_json_bytes(model.model_dump(mode="json", exclude_computed_fields=True))


def generate_phase4_schema_documents() -> dict[str, dict[str, object]]:
    """Generate the checked-in Draft 2020-12 Phase 4 contract documents."""

    documents: dict[str, dict[str, object]] = {}
    for name, model in zip(PHASE4_SCHEMA_NAMES, PHASE4_SCHEMA_MODELS, strict=True):
        document = model.model_json_schema(mode="validation")
        documents[name] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://academic-research-workbench.local/schemas/v1/{name}",
            **document,
        }
    return documents


def write_phase4_schema_documents(destination: Path) -> tuple[tuple[str, str], ...]:
    """Write deterministic Phase 4 schemas for the checked-in registry path."""

    destination.mkdir(parents=True, exist_ok=True)
    written: list[tuple[str, str]] = []
    for name, document in generate_phase4_schema_documents().items():
        rendered = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        (destination / name).write_bytes(rendered)
        written.append((name, hashlib.sha256(rendered).hexdigest()))
    return tuple(written)
