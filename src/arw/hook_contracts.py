"""Strict, observational hook contracts for Phase 4.

Hooks can hydrate context and report bounded warnings, but they are not an
authorization, provenance, gate, or canonical-write channel.  These models
therefore contain no event, acceptance, transition, retry, or state-mutation
field and reject such fields at the wire boundary.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BeforeValidator, Field, ValidationError, model_validator

from arw.kernel.core.canonical import canonical_json_bytes, strict_json_loads
from arw.models import Sha256, StableRuntimeId, StrictModel
from arw.orchestration_models import HookObservation as CanonicalHookObservation


HookName = Literal[
    "SessionStart",
    "SubagentStart",
    "SubagentStop",
    "PreToolUse",
    "PostToolUse",
    "Stop",
]
HookStatus = Literal["trusted_enabled", "disabled", "untrusted", "timeout", "failed"]
ContinuationOwner = Literal["SubagentStop", "Stop"]
ParitySurface = Literal["runtime", "mcp", "integrity", "gate", "provenance"]
ObservationKind = Literal[
    "hydration",
    "assignment_context",
    "proposal_incomplete",
    "proposal_malformed",
    "policy_warning",
    "deliverable_open",
    "gate_open",
]

HOOK_STATUSES: tuple[HookStatus, ...] = (
    "trusted_enabled",
    "disabled",
    "untrusted",
    "timeout",
    "failed",
)
CONFIGURED_HOOK_NAMES: tuple[HookName, ...] = ("SessionStart", "SubagentStop", "Stop")
MAX_HOOK_INPUT_BYTES = 16 * 1024
MAX_HOOK_OUTPUT_BYTES = 32 * 1024
PARITY_SURFACES: tuple[ParitySurface, ...] = (
    "runtime",
    "mcp",
    "integrity",
    "gate",
    "provenance",
)
PRIVILEGED_FIELDS = frozenset(
    {
        "accept_evidence",
        "acceptance_decision",
        "append_event",
        "canonical_event",
        "gate_verdict",
        "retry_assignment",
        "state_mutation_request",
        "transition",
        "transition_id",
        "write_manifest",
    }
)


class HookContractError(ValueError):
    """Raised when untrusted hook bytes cannot satisfy the observation contract."""


class ContinuationContractError(HookContractError):
    """Raised when a hook attempts an unowned or repeated continuation."""


def _freeze_array(value: object) -> tuple[object, ...]:
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    raise ValueError("contract arrays must be JSON arrays")


class CodexReceiptControl(StrictModel):
    """One parent-owned control echoed by the observational host adapter."""

    surface: ParitySurface
    parent_enforced: Literal[True]
    hook_bypass_safe: Literal[True]


class CodexHookReceipt(StrictModel):
    """Redacted receipt emitted by the installed official-wire hook adapter."""

    schema_version: Literal["arw.codex-hook-observation.v1"]
    authority: Literal["observational"]
    hook_event_name: Literal["SessionStart", "SubagentStop", "Stop"]
    input_sha256: Sha256
    hook_definition_sha256: Sha256
    plugin_root_sha256: Sha256
    session_id_sha256: Sha256
    turn_id_sha256: Sha256 | None
    subject_id_sha256: Sha256 | None
    agent_type_sha256: Sha256 | None
    model_sha256: Sha256
    cwd_sha256: Sha256
    permission_mode: Literal[
        "default", "acceptEdits", "plan", "dontAsk", "bypassPermissions"
    ]
    source: Literal["startup", "resume", "clear", "compact"] | None
    stop_hook_active: bool | None
    status: Literal["observed"]
    redacted_error_code: None
    parent_controls: Annotated[
        tuple[CodexReceiptControl, ...],
        BeforeValidator(_freeze_array),
        Field(min_length=5, max_length=5),
    ]
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def receipt_is_derived_and_non_authoritative(self) -> Self:
        if tuple(control.surface for control in self.parent_controls) != PARITY_SURFACES:
            raise HookContractError("Codex hook receipt controls are incomplete or reordered")
        unsigned = self.model_dump(mode="json", exclude={"receipt_sha256"})
        expected = hashlib.sha256(canonical_json_bytes(unsigned)).hexdigest()
        if self.receipt_sha256 != expected:
            raise HookContractError("Codex hook receipt hash is not derived from canonical bytes")
        return self

    def to_orchestration_observation(self) -> CanonicalHookObservation:
        """Project a verified receipt; trust remains bound by the integration lock."""

        subject = self.subject_id_sha256 or self.turn_id_sha256 or self.session_id_sha256
        return CanonicalHookObservation(
            schema_version="arw.hook-observation.v1",
            hook_name=self.hook_event_name,
            hook_definition_sha256=self.hook_definition_sha256,
            target_id=f"hook-target.{subject[:32]}",
            status="trusted_enabled",
            observation_sha256=self.receipt_sha256,
            redacted_error_code=None,
            idempotency_key=f"hook-receipt.{self.receipt_sha256[:32]}",
            continuation_requested=False,
            continuation_count=0,
        )


def load_codex_hook_receipt(
    path: Path,
    *,
    receipt_root: Path,
    expected_hook_definition_sha256: str,
) -> CodexHookReceipt:
    """Load one retained official-host receipt through a bounded exact boundary."""

    try:
        root = receipt_root.resolve(strict=True)
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as error:
        raise HookContractError("Codex hook receipt is outside its retained root") from error
    if receipt_root.is_symlink() or not root.is_dir() or path.is_symlink() or not resolved.is_file():
        raise HookContractError("Codex hook receipt path is unsafe")
    try:
        raw = resolved.read_bytes()
    except OSError as error:
        raise HookContractError("Codex hook receipt is unreadable") from error
    if not raw or len(raw) > MAX_HOOK_OUTPUT_BYTES:
        raise HookContractError("Codex hook receipt exceeds the bounded size")
    try:
        receipt = CodexHookReceipt.model_validate_json(raw, strict=True)
    except (ValueError, ValidationError) as error:
        raise HookContractError(f"invalid Codex hook receipt: {error}") from error
    if raw != canonical_json_bytes(receipt.model_dump(mode="json")):
        raise HookContractError("Codex hook receipt bytes are not canonical")
    if resolved.name != f"{receipt.receipt_sha256}.json":
        raise HookContractError("Codex hook receipt filename is not content addressed")
    if receipt.hook_definition_sha256 != expected_hook_definition_sha256:
        raise HookContractError("Codex hook receipt binds another hook definition")
    return receipt


def _contains_privileged_field(value: object) -> str | None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in PRIVILEGED_FIELDS:
                return key
            found = _contains_privileged_field(child)
            if found is not None:
                return found
    elif isinstance(value, (tuple, list)):
        for child in value:
            found = _contains_privileged_field(child)
            if found is not None:
                return found
    return None


def _wire_size(raw: bytes | str) -> int:
    if isinstance(raw, bytes):
        return len(raw)
    if isinstance(raw, str):
        return len(raw.encode("utf-8"))
    raise TypeError("hook wire value must be bytes or str")


def _load_wire_mapping(raw: bytes | str, *, limit: int, label: str) -> Mapping[str, object]:
    if _wire_size(raw) > limit:
        raise HookContractError(f"{label} exceeds the bounded wire size")
    try:
        payload = strict_json_loads(raw)
    except (TypeError, ValueError) as error:
        raise HookContractError(f"malformed {label} JSON: {error}") from error
    if not isinstance(payload, Mapping):
        raise HookContractError(f"{label} must be a JSON object")
    forbidden = _contains_privileged_field(payload)
    if forbidden is not None:
        raise HookContractError(f"privileged hook field rejected: {forbidden}")
    return payload


class HookInvocation(StrictModel):
    """Parent-provided identity and bounded input metadata for one hook call."""

    schema_version: Literal["arw.hook-invocation.v1"]
    hook_name: HookName
    command_id: StableRuntimeId
    target_id: StableRuntimeId
    hook_definition_sha256: Sha256
    input_sha256: Sha256
    timeout_seconds: Annotated[float, Field(gt=0, le=30)]

    @classmethod
    def from_wire(cls, raw: bytes | str) -> Self:
        """Parse one bounded parent invocation without accepting authority fields."""

        payload = _load_wire_mapping(raw, limit=MAX_HOOK_INPUT_BYTES, label="hook invocation")
        try:
            return cls.model_validate(payload)
        except (TypeError, ValueError, ValidationError) as error:
            raise HookContractError(f"invalid hook invocation: {error}") from error

    def to_wire(self) -> bytes:
        wire = canonical_json_bytes(self.model_dump(mode="json"))
        if len(wire) > MAX_HOOK_OUTPUT_BYTES:
            raise HookContractError("hook invocation exceeds the bounded wire size")
        return wire


class ParentParityControl(StrictModel):
    """One authority control that remains parent-enforced when hooks are absent."""

    surface: ParitySurface
    parent_enforced: Literal[True] = True
    authority_digest: Sha256
    hook_bypass_safe: Literal[True] = True


class HookParityMatrix(StrictModel):
    """Five-mode hook parity evidence for the parent authority boundary."""

    schema_version: Literal["arw.hook-parity.v1"]
    hook_status: HookStatus
    authority_digest: Sha256
    controls: Annotated[
        tuple[ParentParityControl, ...], BeforeValidator(_freeze_array), Field(min_length=5, max_length=5)
    ]

    @model_validator(mode="after")
    def is_complete_and_parent_owned(self) -> Self:
        surfaces = tuple(control.surface for control in self.controls)
        if surfaces != PARITY_SURFACES:
            raise HookContractError(
                "parity matrix must contain runtime, mcp, integrity, gate, and provenance exactly once"
            )
        if any(control.authority_digest != self.authority_digest for control in self.controls):
            raise HookContractError("every parity control must bind the parent authority digest")
        return self

    @classmethod
    def for_status(
        cls, status: HookStatus, *, authority_digest: str
    ) -> Self:
        return cls(
            schema_version="arw.hook-parity.v1",
            hook_status=status,
            authority_digest=authority_digest,
            controls=tuple(
                ParentParityControl(
                    surface=surface,
                    authority_digest=authority_digest,
                )
                for surface in PARITY_SURFACES
            ),
        )

    @property
    def authority_normalized_digest(self) -> str:
        """The digest used to compare authority after hook-only fields are removed."""

        return self.authority_digest

    def assert_parity(self, other: "HookParityMatrix") -> None:
        if self.authority_normalized_digest != other.authority_normalized_digest:
            raise HookContractError("hook status changed the parent authority digest")
        if tuple(control.model_dump(mode="json") for control in self.controls) != tuple(
            control.model_dump(mode="json") for control in other.controls
        ):
            raise HookContractError("hook status changed a parent-enforced control")


class ContinuationRequest(StrictModel):
    """A bounded convenience request; it cannot select a transition or retry."""

    schema_version: Literal["arw.hook-continuation.v1"]
    owner: ContinuationOwner
    target_id: StableRuntimeId
    idempotency_key: StableRuntimeId
    reason_code: Literal[
        "proposal_incomplete",
        "proposal_malformed",
        "deliverable_open",
        "gate_open",
    ]


class HookObservation(StrictModel):
    """Strict stdout observation with no canonical authority representation."""

    schema_version: Literal["arw.hook-observation-contract.v1"]
    hook_name: HookName
    command_id: StableRuntimeId
    target_id: StableRuntimeId
    hook_definition_sha256: Sha256
    status: HookStatus
    observation_kind: ObservationKind
    observation_sha256: Sha256
    redacted_error_code: StableRuntimeId | None
    failure_reason: Annotated[str, Field(min_length=1, max_length=256)] | None
    continuation_request: ContinuationRequest | None
    continuation_count: Annotated[int, Field(ge=0, le=1)]
    parity: HookParityMatrix

    @model_validator(mode="after")
    def observation_is_bounded_and_parent_owned(self) -> Self:
        if self.parity.hook_status != self.status:
            raise HookContractError("observation and parity statuses must match")
        if self.status in {"timeout", "failed"} and self.failure_reason is None:
            raise HookContractError("timeout and failed hooks require a redacted failure reason")
        if self.continuation_request is None:
            if self.continuation_count != 0:
                raise HookContractError("continuation count requires a continuation request")
            return self
        request = self.continuation_request
        if self.status != "trusted_enabled":
            raise HookContractError("only a trusted enabled hook may request convenience continuation")
        if self.continuation_count != 1:
            raise HookContractError("a hook continuation request has an exact count of one")
        if request.target_id != self.target_id:
            raise HookContractError("continuation target must match the observation target")
        if request.owner != self.hook_name:
            raise HookContractError("continuation owner must match the hook event")
        return self

    @classmethod
    def from_wire(cls, raw: bytes | str) -> Self:
        payload = _load_wire_mapping(raw, limit=MAX_HOOK_OUTPUT_BYTES, label="hook observation")
        try:
            return cls.model_validate(payload)
        except (TypeError, ValueError, ValidationError) as error:
            raise HookContractError(f"invalid hook observation: {error}") from error

    def to_wire(self) -> bytes:
        wire = canonical_json_bytes(self.model_dump(mode="json"))
        if len(wire) > MAX_HOOK_OUTPUT_BYTES:
            raise HookContractError("hook observation exceeds the bounded wire size")
        return wire

    def to_orchestration_observation(self) -> CanonicalHookObservation:
        """Project only the allowed observation fields into the Phase 4 record."""

        request = self.continuation_request
        idempotency_key = (
            request.idempotency_key
            if request is not None
            else f"{self.command_id}.{self.target_id}.observation"
        )
        return CanonicalHookObservation(
            schema_version="arw.hook-observation.v1",
            hook_name=self.hook_name,
            hook_definition_sha256=self.hook_definition_sha256,
            target_id=self.target_id,
            status=self.status,
            observation_sha256=self.observation_sha256,
            redacted_error_code=self.redacted_error_code,
            idempotency_key=idempotency_key,
            continuation_requested=request is not None,
            continuation_count=self.continuation_count,
        )

    @classmethod
    def create(
        cls,
        *,
        hook_name: HookName,
        command_id: str,
        target_id: str,
        hook_definition_sha256: str,
        status: HookStatus,
        observation_kind: ObservationKind,
        observation_sha256: str,
        authority_digest: str,
        redacted_error_code: str | None = None,
        failure_reason: str | None = None,
        continuation_request: ContinuationRequest | None = None,
    ) -> Self:
        return cls(
            schema_version="arw.hook-observation-contract.v1",
            hook_name=hook_name,
            command_id=command_id,
            target_id=target_id,
            hook_definition_sha256=hook_definition_sha256,
            status=status,
            observation_kind=observation_kind,
            observation_sha256=observation_sha256,
            redacted_error_code=redacted_error_code,
            failure_reason=failure_reason,
            continuation_request=continuation_request,
            continuation_count=1 if continuation_request is not None else 0,
            parity=HookParityMatrix.for_status(status, authority_digest=authority_digest),
        )


class ContinuationBudget(StrictModel):
    """Parent-side one-shot budget keyed by owner, target, and idempotency key."""

    schema_version: Literal["arw.hook-continuation-budget.v1"]
    owner: ContinuationOwner
    target_id: StableRuntimeId
    idempotency_key: StableRuntimeId
    used_count: Annotated[int, Field(ge=0, le=1)] = 0

    @classmethod
    def initial(
        cls,
        *,
        owner: ContinuationOwner,
        target_id: str,
        idempotency_key: str,
    ) -> Self:
        return cls(
            schema_version="arw.hook-continuation-budget.v1",
            owner=owner,
            target_id=target_id,
            idempotency_key=idempotency_key,
            used_count=0,
        )

    def admit(self, observation: HookObservation) -> Self:
        request = observation.continuation_request
        if request is None:
            return self
        if request.owner != self.owner or request.target_id != self.target_id:
            raise ContinuationContractError("continuation owner or target does not match budget")
        if request.idempotency_key != self.idempotency_key:
            raise ContinuationContractError("continuation idempotency key does not match budget")
        if self.used_count >= 1:
            raise ContinuationContractError("continuation budget is exhausted; at most one is allowed")
        return self.model_validate(
            {
                **self.model_dump(mode="json"),
                "used_count": 1,
            }
        )


ObservationContract = HookObservation
HookParity = HookParityMatrix
ContinuationCounter = ContinuationBudget
