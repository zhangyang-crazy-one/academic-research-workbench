"""Host-neutral execution observations for Phase 4.

The execution adapter is deliberately smaller than the canonical runtime.  It
can start, cooperatively stop, and force-terminate a host attempt, but it has
no method for accepting proposals, appending events, resolving gates, or
mutating manifests.  Everything returned by an adapter is an observation that
the parent may validate later.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, Self


def _is_finite(value: float) -> bool:
    return value == value and value not in {float("inf"), float("-inf")}


@dataclass(frozen=True, slots=True)
class ExecutionPolicySnapshot:
    """The bounded discretionary values frozen into an assignment policy."""

    max_concurrency: int = 4
    attempt_timeout_s: float = 300.0
    cancel_grace_s: float = 15.0
    max_attempts_per_assignment: int = 2
    proposal_max_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if self.max_concurrency > 64:
            raise ValueError("max_concurrency exceeds the scheduler safety bound")
        if self.attempt_timeout_s <= 0 or not _is_finite(self.attempt_timeout_s):
            raise ValueError("attempt_timeout_s must be a finite positive value")
        if self.cancel_grace_s < 0 or not _is_finite(self.cancel_grace_s):
            raise ValueError("cancel_grace_s must be a finite non-negative value")
        if self.max_attempts_per_assignment not in {1, 2}:
            raise ValueError("max_attempts_per_assignment must be one or two")
        if not 1 <= self.proposal_max_bytes <= 1_048_576:
            raise ValueError("proposal_max_bytes must be between one byte and 1048576")

    @property
    def attempt_timeout_seconds(self) -> float:
        return self.attempt_timeout_s

    @property
    def cancellation_grace_seconds(self) -> float:
        return self.cancel_grace_s

    def canonical_bytes(self) -> bytes:
        return (
            json.dumps(
                {
                    "attempt_timeout_s": self.attempt_timeout_s,
                    "cancel_grace_s": self.cancel_grace_s,
                    "max_attempts_per_assignment": self.max_attempts_per_assignment,
                    "max_concurrency": self.max_concurrency,
                    "proposal_max_bytes": self.proposal_max_bytes,
                },
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")

    @property
    def policy_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


DEFAULT_EXECUTION_POLICY = ExecutionPolicySnapshot()


@dataclass(frozen=True, slots=True)
class DispatchSpec:
    """Immutable input to one host dispatch.

    ``acceptance_key`` accepts the two-integer form used by early Phase 4
    callers and the fully explicit three-part form.  The scheduler always
    expands it to ``(layer, task_ordinal, assignment_id)`` before ordering.
    """

    assignment_id: str
    attempt_id: str
    acceptance_key: tuple[int, int] | tuple[int, int, str]
    assignment_path: Path
    attempt_root: Path
    policy_snapshot: ExecutionPolicySnapshot = DEFAULT_EXECUTION_POLICY
    timeout_seconds: float | None = None
    cancellation_grace_seconds: float | None = None
    proposal_max_bytes: int | None = None
    attempt_number: int = 1
    proposal_nonce: str | None = None

    def __post_init__(self) -> None:
        if not self.assignment_id or not self.attempt_id:
            raise ValueError("assignment_id and attempt_id are required")
        if len(self.acceptance_key) not in {2, 3}:
            raise ValueError("acceptance_key must contain layer and task ordinal")
        if any(not isinstance(value, int) or value < 0 for value in self.acceptance_key[:2]):
            raise ValueError("acceptance_key values must be non-negative integers")
        if len(self.acceptance_key) == 3 and self.acceptance_key[2] != self.assignment_id:
            raise ValueError("acceptance_key assignment ID must echo assignment_id")
        if self.attempt_number < 1:
            raise ValueError("attempt_number must be positive")
        if self.timeout_seconds is not None and (
            self.timeout_seconds <= 0 or not _is_finite(self.timeout_seconds)
        ):
            raise ValueError("timeout_seconds must be finite and positive")
        if self.cancellation_grace_seconds is not None and (
            self.cancellation_grace_seconds < 0
            or not _is_finite(self.cancellation_grace_seconds)
        ):
            raise ValueError("cancellation_grace_seconds must be finite and non-negative")
        if self.proposal_max_bytes is not None and not (
            1 <= self.proposal_max_bytes <= self.policy_snapshot.proposal_max_bytes
        ):
            raise ValueError("proposal_max_bytes exceeds the frozen policy snapshot")

    @property
    def frozen_order_key(self) -> tuple[int, int, str]:
        return (self.acceptance_key[0], self.acceptance_key[1], self.assignment_id)

    @property
    def effective_timeout_seconds(self) -> float:
        return (
            self.timeout_seconds
            if self.timeout_seconds is not None
            else self.policy_snapshot.attempt_timeout_s
        )

    @property
    def effective_cancellation_grace_seconds(self) -> float:
        return (
            self.cancellation_grace_seconds
            if self.cancellation_grace_seconds is not None
            else self.policy_snapshot.cancel_grace_s
        )

    @property
    def effective_proposal_max_bytes(self) -> int:
        return (
            self.proposal_max_bytes
            if self.proposal_max_bytes is not None
            else self.policy_snapshot.proposal_max_bytes
        )

    def for_retry(self, attempt_number: int) -> Self:
        """Return a fresh attempt without changing assignment-bound inputs."""

        if attempt_number <= self.attempt_number:
            raise ValueError("retry attempt number must increase")
        retry_attempt_id = f"{self.attempt_id}.retry-{attempt_number}"
        retry_root = self.attempt_root.parent / retry_attempt_id
        nonce_base = self.proposal_nonce or self.attempt_id
        return type(self)(
            assignment_id=self.assignment_id,
            attempt_id=retry_attempt_id,
            acceptance_key=self.acceptance_key,
            assignment_path=self.assignment_path,
            attempt_root=retry_root,
            policy_snapshot=self.policy_snapshot,
            timeout_seconds=self.timeout_seconds,
            cancellation_grace_seconds=self.cancellation_grace_seconds,
            proposal_max_bytes=self.proposal_max_bytes,
            attempt_number=attempt_number,
            proposal_nonce=f"{nonce_base}.retry-{attempt_number}",
        )


@dataclass(frozen=True, slots=True)
class HostResult:
    """Bounded host metadata; transcript text is never parsed here.

    The optional native fields are observations only.  In particular,
    ``proposal_path`` remains the one direct result path the parent may later
    validate; no field contains a proposal body or a transcript-derived
    proposal.
    """

    attempt_id: str
    host_agent_id: str
    proposal_path: Path
    transcript_reference: str | None = None
    observation_sha256: str | None = None
    output_bytes: int | None = None
    execution_mode: str | None = None
    formal_independence: bool = False
    assignment_mapping_proven: bool = False
    isolation_proven: bool = False
    profile_name: str | None = None
    permission_digest: str | None = None
    hook_config_digest: str | None = None
    process_id: int | None = None
    returncode: int | None = None
    observation_path: Path | None = None
    observation: NativeHostObservation | None = None
    transport: CodexExecTransport | None = None
    worker_identity_id: str | None = None
    qualification_receipt_sha256: str | None = None
    codex_version: str | None = None
    codex_binary_sha256: str | None = None
    profile_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.attempt_id or not self.host_agent_id:
            raise ValueError("host results require attempt and host identities")
        if self.output_bytes is not None and self.output_bytes < 0:
            raise ValueError("output_bytes cannot be negative")


class ExecutionAdapter(Protocol):
    """The only host operations a parent scheduler may request."""

    async def dispatch(self, spec: DispatchSpec) -> HostResult:
        """Dispatch one fresh attempt and return observational metadata."""

    async def request_cancel(self, spec: DispatchSpec) -> None:
        """Request cooperative cancellation of one active attempt."""

    async def force_terminate(self, spec: DispatchSpec) -> None:
        """Request qualified force termination after the grace period."""


class AdapterFailure(RuntimeError):
    """An adapter failure with a scheduler retry taxonomy."""

    reason: str

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.reason)


class ProcessFailure(AdapterFailure):
    reason = "process_failure"


class PermissionDenied(AdapterFailure):
    reason = "permission_denied"


class RepairableEnvelopeFailure(AdapterFailure):
    reason = "repairable_envelope"


class ScientificDisagreement(AdapterFailure):
    reason = "scientific_disagreement"


class StaleAttempt(AdapterFailure):
    reason = "stale_inputs"


NativeExecutionMode = Literal[
    "native_profile",
    "assignment_injected_subagent",
    "degraded_inline",
    "blocked",
]
FormalNativeExecutionMode = Literal[
    "native_profile",
    "assignment_injected_subagent",
]

CodexExecTransport = Literal["isolated_codex_exec"]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_UTC_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z$"
)
_QUALIFICATION_RECEIPT_SCHEMA = "arw.codex-exec-qualification-receipt.v1"
_QUALIFICATION_RECEIPT_MAX_BYTES = 1_048_576
_CREDENTIAL_FILE_MAX_BYTES = 16 * 1024 * 1024
_ALLOWED_CODEX_CREDENTIAL_FILES = frozenset({"auth.json", "config.toml"})
_SAFE_CHILD_ENVIRONMENT_KEYS = frozenset(
    {
        "ALL_PROXY",
        "COMSPEC",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "NO_COLOR",
        "NO_PROXY",
        "PATH",
        "PATHEXT",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "SYSTEMROOT",
        "TERM",
        "TZ",
        "WINDIR",
    }
)


def _non_empty(value: str | None) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_sha256(value: str | None) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


class QualificationReceiptError(ValueError):
    """A retained Codex exec qualification receipt is not canonical or strict."""


def _strict_json_object(raw: bytes) -> dict[str, object]:
    def reject_constant(value: str) -> object:
        raise QualificationReceiptError(f"non-finite JSON number is forbidden: {value}")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise QualificationReceiptError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise QualificationReceiptError("qualification receipt is not strict UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise QualificationReceiptError("qualification receipt must be a JSON object")
    return value


@dataclass(frozen=True, slots=True)
class CodexExecQualificationReceipt:
    """Retained exact-host evidence accepted by the parent before dispatch.

    The adapter verifies these canonical bytes against an independently
    expected digest.  Constructing this object or setting legacy booleans does
    not by itself grant qualification; a regular retained receipt file and its
    expected canonical digest are both mandatory.
    """

    schema_version: Literal["arw.codex-exec-qualification-receipt.v1"]
    qualification_id: str
    transport: CodexExecTransport
    execution_mode: FormalNativeExecutionMode
    codex_version: str
    codex_binary_sha256: str
    profile_name: str | None
    profile_digest: str
    permission_digest: str
    hook_config_digest: str
    credential_bundle_sha256: str
    assignment_id: str
    worker_identity_id: str
    host_agent_id: str
    assignment_mapping_proven: bool
    isolation_proven: bool
    credential_isolation_proven: bool
    observed_at: str
    evidence_sha256: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != _QUALIFICATION_RECEIPT_SCHEMA:
            raise QualificationReceiptError("unsupported qualification receipt schema")
        if self.transport != "isolated_codex_exec":
            raise QualificationReceiptError(
                "qualification receipt transport is not isolated_codex_exec"
            )
        if self.execution_mode not in {"native_profile", "assignment_injected_subagent"}:
            raise QualificationReceiptError("qualification receipt execution mode is not formal")
        for field_name in (
            "qualification_id",
            "assignment_id",
            "worker_identity_id",
            "host_agent_id",
        ):
            value = getattr(self, field_name)
            if not _non_empty(value) or any(token in value for token in ("/", "\\", "\x00")):
                raise QualificationReceiptError(f"invalid {field_name}")
        if _SEMVER_RE.fullmatch(self.codex_version) is None:
            raise QualificationReceiptError("qualification receipt Codex version is invalid")
        for field_name in (
            "codex_binary_sha256",
            "profile_digest",
            "permission_digest",
            "hook_config_digest",
            "credential_bundle_sha256",
        ):
            if not _is_sha256(getattr(self, field_name)):
                raise QualificationReceiptError(f"invalid {field_name}")
        if self.execution_mode == "native_profile" and not _non_empty(self.profile_name):
            raise QualificationReceiptError("native profile receipt requires a profile name")
        if self.execution_mode != "native_profile" and self.profile_name is not None:
            raise QualificationReceiptError("non-profile receipt cannot claim a profile name")
        if not all(
            type(value) is bool
            for value in (
                self.assignment_mapping_proven,
                self.isolation_proven,
                self.credential_isolation_proven,
            )
        ):
            raise QualificationReceiptError("qualification proof flags must be booleans")
        if not (
            self.assignment_mapping_proven
            and self.isolation_proven
            and self.credential_isolation_proven
        ):
            raise QualificationReceiptError(
                "qualification receipt must retain every required proof"
            )
        if _UTC_TIMESTAMP_RE.fullmatch(self.observed_at) is None:
            raise QualificationReceiptError("qualification receipt timestamp is invalid")
        if not self.evidence_sha256 or len(set(self.evidence_sha256)) != len(
            self.evidence_sha256
        ):
            raise QualificationReceiptError(
                "qualification evidence hashes must be non-empty and unique"
            )
        if any(not _is_sha256(value) for value in self.evidence_sha256):
            raise QualificationReceiptError("qualification evidence contains an invalid digest")

    def canonical_bytes(self) -> bytes:
        return (
            json.dumps(
                {
                    "assignment_id": self.assignment_id,
                    "assignment_mapping_proven": self.assignment_mapping_proven,
                    "codex_binary_sha256": self.codex_binary_sha256,
                    "codex_version": self.codex_version,
                    "credential_bundle_sha256": self.credential_bundle_sha256,
                    "credential_isolation_proven": self.credential_isolation_proven,
                    "evidence_sha256": self.evidence_sha256,
                    "execution_mode": self.execution_mode,
                    "hook_config_digest": self.hook_config_digest,
                    "host_agent_id": self.host_agent_id,
                    "isolation_proven": self.isolation_proven,
                    "observed_at": self.observed_at,
                    "permission_digest": self.permission_digest,
                    "profile_digest": self.profile_digest,
                    "profile_name": self.profile_name,
                    "qualification_id": self.qualification_id,
                    "schema_version": self.schema_version,
                    "transport": self.transport,
                    "worker_identity_id": self.worker_identity_id,
                },
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")

    @property
    def receipt_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        if len(raw) > _QUALIFICATION_RECEIPT_MAX_BYTES:
            raise QualificationReceiptError("qualification receipt exceeds the byte bound")
        value = _strict_json_object(raw)
        expected_keys = {
            "assignment_id",
            "assignment_mapping_proven",
            "codex_binary_sha256",
            "codex_version",
            "credential_bundle_sha256",
            "credential_isolation_proven",
            "evidence_sha256",
            "execution_mode",
            "hook_config_digest",
            "host_agent_id",
            "isolation_proven",
            "observed_at",
            "permission_digest",
            "profile_digest",
            "profile_name",
            "qualification_id",
            "schema_version",
            "transport",
            "worker_identity_id",
        }
        if set(value) != expected_keys:
            raise QualificationReceiptError(
                "qualification receipt fields do not match the contract"
            )
        evidence = value.get("evidence_sha256")
        if not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence):
            raise QualificationReceiptError(
                "qualification evidence must be a JSON array of digests"
            )
        scalar_strings = (
            "qualification_id",
            "transport",
            "execution_mode",
            "codex_version",
            "codex_binary_sha256",
            "profile_digest",
            "permission_digest",
            "hook_config_digest",
            "credential_bundle_sha256",
            "assignment_id",
            "worker_identity_id",
            "host_agent_id",
            "observed_at",
            "schema_version",
        )
        if any(not isinstance(value.get(key), str) for key in scalar_strings):
            raise QualificationReceiptError("qualification receipt string field has the wrong type")
        if value.get("profile_name") is not None and not isinstance(
            value.get("profile_name"), str
        ):
            raise QualificationReceiptError("qualification profile name has the wrong type")
        for key in (
            "assignment_mapping_proven",
            "isolation_proven",
            "credential_isolation_proven",
        ):
            if type(value.get(key)) is not bool:
                raise QualificationReceiptError("qualification proof flag has the wrong type")
        receipt = cls(
            schema_version=value["schema_version"],  # type: ignore[arg-type]
            qualification_id=value["qualification_id"],  # type: ignore[arg-type]
            transport=value["transport"],  # type: ignore[arg-type]
            execution_mode=value["execution_mode"],  # type: ignore[arg-type]
            codex_version=value["codex_version"],  # type: ignore[arg-type]
            codex_binary_sha256=value["codex_binary_sha256"],  # type: ignore[arg-type]
            profile_name=value["profile_name"],  # type: ignore[arg-type]
            profile_digest=value["profile_digest"],  # type: ignore[arg-type]
            permission_digest=value["permission_digest"],  # type: ignore[arg-type]
            hook_config_digest=value["hook_config_digest"],  # type: ignore[arg-type]
            credential_bundle_sha256=value["credential_bundle_sha256"],  # type: ignore[arg-type]
            assignment_id=value["assignment_id"],  # type: ignore[arg-type]
            worker_identity_id=value["worker_identity_id"],  # type: ignore[arg-type]
            host_agent_id=value["host_agent_id"],  # type: ignore[arg-type]
            assignment_mapping_proven=value["assignment_mapping_proven"],  # type: ignore[arg-type]
            isolation_proven=value["isolation_proven"],  # type: ignore[arg-type]
            credential_isolation_proven=value[
                "credential_isolation_proven"
            ],  # type: ignore[arg-type]
            observed_at=value["observed_at"],  # type: ignore[arg-type]
            evidence_sha256=tuple(evidence),
        )
        if receipt.canonical_bytes() != raw:
            raise QualificationReceiptError("qualification receipt bytes are not canonical")
        return receipt


@dataclass(frozen=True, slots=True)
class NativeHostConfig:
    """Immutable expected inputs for the isolated ``codex exec`` adapter.

    Legacy identity/proof fields remain accepted for compatibility but never
    grant formal qualification.  Only a canonical retained receipt whose hash
    equals ``expected_qualification_receipt_sha256`` may do so.
    """

    execution_mode: NativeExecutionMode | None = None
    profile_name: str | None = None
    profile_available: bool | None = None
    permission_digest: str | None = None
    hook_config_digest: str | None = None
    stable_host_identity: bool = False
    host_agent_id: str | None = None
    assignment_mapping_proven: bool = False
    mapped_assignment_id: str | None = None
    isolation_proven: bool = False
    max_depth: int = 1
    max_threads: int = 4
    sandbox: str = "workspace-write"
    codex_command: tuple[str, ...] = ("codex",)
    executable: str | None = None
    command: tuple[str, ...] | None = None
    codex_version: str | None = None
    codex_binary_sha256: str | None = None
    profile_digest: str | None = None
    qualification_receipt_path: Path | None = None
    expected_qualification_receipt_sha256: str | None = None
    codex_home: Path | None = None
    credential_source_codex_home: Path | None = None
    credential_files: tuple[str, ...] = ("auth.json", "config.toml")
    environment: tuple[tuple[str, str], ...] = ()
    observation_max_bytes: int = 8 * 1024 * 1024
    force_termination_qualified: bool = False
    force_termination_proven: bool | None = None

    def __post_init__(self) -> None:
        raw_command: object = self.command or self.codex_command
        if isinstance(raw_command, str):
            command = (raw_command,)
        else:
            command = tuple(str(part) for part in raw_command)  # type: ignore[union-attr]
        if self.executable is not None:
            command = (str(self.executable),)
        if self.command is not None:
            object.__setattr__(self, "command", command)
        else:
            object.__setattr__(self, "codex_command", command)
        for field_name in (
            "codex_home",
            "credential_source_codex_home",
            "qualification_receipt_path",
        ):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, Path):
                object.__setattr__(self, field_name, Path(value))
        if (
            self.codex_home is not None
            and self.credential_source_codex_home is not None
            and self.codex_home.resolve() != self.credential_source_codex_home.resolve()
        ):
            raise ValueError("codex_home and credential_source_codex_home disagree")
        raw_environment: object = self.environment
        if isinstance(raw_environment, Mapping):
            environment = tuple(
                (str(key), str(value)) for key, value in raw_environment.items()
            )
        else:
            environment = tuple(
                (str(key), str(value)) for key, value in raw_environment  # type: ignore[union-attr]
            )
        object.__setattr__(self, "environment", environment)
        credential_files = tuple(str(item) for item in self.credential_files)
        object.__setattr__(self, "credential_files", credential_files)
        if self.max_depth != 1:
            raise ValueError("native Codex execution requires agents.max_depth=1")
        if self.max_threads != 4:
            raise ValueError("native Codex execution requires agents.max_threads=4")
        if self.sandbox not in {"read-only", "workspace-write"}:
            raise ValueError("native Codex sandbox must be read-only or workspace-write")
        if not 1 <= self.observation_max_bytes <= 64 * 1024 * 1024:
            raise ValueError("observation_max_bytes is outside the safety bound")
        if self.execution_mode not in {
            None,
            "native_profile",
            "assignment_injected_subagent",
            "degraded_inline",
            "blocked",
        }:
            raise ValueError("unknown native execution mode")
        if not command or any(not _non_empty(str(part)) for part in command):
            raise ValueError("native Codex command must not be empty")
        if len({key for key, _ in environment}) != len(environment):
            raise ValueError("native environment keys must be unique")
        if any(key not in _SAFE_CHILD_ENVIRONMENT_KEYS for key, _ in environment):
            raise ValueError("Codex exec environment key is not in the positive allowlist")
        if any("\x00" in value for _, value in environment):
            raise ValueError("Codex exec environment values cannot contain NUL")
        if not credential_files or len(set(credential_files)) != len(credential_files):
            raise ValueError("credential_files must be non-empty and unique")
        if any(item not in _ALLOWED_CODEX_CREDENTIAL_FILES for item in credential_files):
            raise ValueError("credential_files contains an unapproved Codex input")
        if self.codex_version is not None and _SEMVER_RE.fullmatch(self.codex_version) is None:
            raise ValueError("expected Codex version is invalid")
        for field_name in (
            "codex_binary_sha256",
            "profile_digest",
            "permission_digest",
            "hook_config_digest",
            "expected_qualification_receipt_sha256",
        ):
            value = getattr(self, field_name)
            if value is not None and not _is_sha256(value):
                raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")

    @property
    def configured_mode(self) -> NativeExecutionMode:
        if self.execution_mode is not None:
            return self.execution_mode
        return "native_profile" if _non_empty(self.profile_name) else "assignment_injected_subagent"

    @property
    def command_argv(self) -> tuple[str, ...]:
        if self.executable is not None:
            return (self.executable,)
        return self.command or self.codex_command

    @property
    def termination_is_qualified(self) -> bool:
        if self.force_termination_proven is not None:
            return self.force_termination_proven
        return self.force_termination_qualified

    @property
    def credential_source_root(self) -> Path | None:
        """Return the preconfigured source; children never receive this path."""

        return self.credential_source_codex_home or self.codex_home


@dataclass(frozen=True, slots=True)
class _CredentialSourceFile:
    name: str
    path: Path
    sha256: str


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _credential_source_bundle(
    config: NativeHostConfig,
) -> tuple[tuple[_CredentialSourceFile, ...], str | None, tuple[str, ...]]:
    source_root = config.credential_source_root
    if source_root is None:
        return (), None, ("missing_preconfigured_codex_home",)
    if source_root.is_symlink() or not source_root.is_dir():
        return (), None, ("unsafe_preconfigured_codex_home",)
    files: list[_CredentialSourceFile] = []
    reasons: list[str] = []
    for name in config.credential_files:
        path = source_root / name
        if path.is_symlink() or not path.is_file():
            reasons.append(f"missing_safe_credential_input:{name}")
            continue
        try:
            size = path.stat().st_size
        except OSError:
            reasons.append(f"unreadable_credential_input:{name}")
            continue
        if size > _CREDENTIAL_FILE_MAX_BYTES:
            reasons.append(f"credential_input_too_large:{name}")
            continue
        try:
            file_digest = _hash_file(path)
        except OSError:
            reasons.append(f"unreadable_credential_input:{name}")
            continue
        files.append(_CredentialSourceFile(name=name, path=path, sha256=file_digest))
    if reasons:
        return tuple(files), None, tuple(reasons)
    bundle_bytes = (
        json.dumps(
            {
                "files": [
                    {"path": item.name, "sha256": item.sha256}
                    for item in sorted(files, key=lambda item: item.name)
                ]
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    return tuple(files), hashlib.sha256(bundle_bytes).hexdigest(), ()


def _resolved_executable_digest(config: NativeHostConfig) -> tuple[str | None, str | None]:
    executable = config.command_argv[0]
    candidate: Path | None
    if os.path.isabs(executable) or os.sep in executable or (
        os.altsep is not None and os.altsep in executable
    ):
        candidate = Path(executable)
    else:
        resolved = shutil.which(executable)
        candidate = Path(resolved) if resolved is not None else None
    if candidate is None:
        return None, None
    try:
        resolved_candidate = candidate.resolve(strict=True)
        if not resolved_candidate.is_file():
            return None, None
        return str(resolved_candidate), _hash_file(resolved_candidate)
    except OSError:
        return None, None


def _load_retained_qualification_receipt(
    config: NativeHostConfig,
) -> tuple[CodexExecQualificationReceipt | None, str | None, tuple[str, ...]]:
    path = config.qualification_receipt_path
    expected_digest = config.expected_qualification_receipt_sha256
    reasons: list[str] = []
    if path is None:
        reasons.append("missing_qualification_receipt")
    if expected_digest is None:
        reasons.append("missing_expected_qualification_receipt_digest")
    if path is None:
        return None, None, tuple(reasons)
    if path.is_symlink() or not path.is_file():
        reasons.append("qualification_receipt_not_regular")
        return None, None, tuple(reasons)
    try:
        raw = path.read_bytes()
    except OSError:
        reasons.append("qualification_receipt_unreadable")
        return None, None, tuple(reasons)
    actual_digest = hashlib.sha256(raw).hexdigest()
    if expected_digest is not None and actual_digest != expected_digest:
        reasons.append("qualification_receipt_digest_mismatch")
    try:
        receipt = CodexExecQualificationReceipt.from_canonical_bytes(raw)
    except QualificationReceiptError:
        reasons.append("qualification_receipt_not_canonical")
        return None, actual_digest, tuple(reasons)
    if receipt.receipt_sha256 != actual_digest:
        reasons.append("qualification_receipt_digest_invalid")
    return receipt, actual_digest, tuple(reasons)


@dataclass(frozen=True, slots=True)
class NativeHostQualification:
    """A qualification result with explicit non-formal outcomes."""

    requested_mode: NativeExecutionMode
    execution_mode: NativeExecutionMode
    formal_independence: bool
    stable_host_identity: bool
    assignment_mapping_proven: bool
    isolation_proven: bool
    profile_configured: bool
    permission_configured: bool
    hook_configured: bool
    host_agent_id: str | None = None
    worker_identity_id: str | None = None
    transport: CodexExecTransport = "isolated_codex_exec"
    qualification_receipt_sha256: str | None = None
    codex_version: str | None = None
    codex_binary_sha256: str | None = None
    profile_digest: str | None = None
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.execution_mode in {"native_profile", "assignment_injected_subagent"}:
            if not self.formal_independence:
                raise ValueError("formal Codex exec modes require formal independence")
            if (
                self.transport != "isolated_codex_exec"
                or not _is_sha256(self.qualification_receipt_sha256)
                or not _is_sha256(self.codex_binary_sha256)
                or not _is_sha256(self.profile_digest)
                or self.codex_version is None
                or _SEMVER_RE.fullmatch(self.codex_version) is None
                or not _non_empty(self.worker_identity_id)
                or not _non_empty(self.host_agent_id)
            ):
                raise ValueError("formal Codex exec qualification lacks exact retained evidence")
        elif self.formal_independence:
            raise ValueError("non-formal native modes cannot claim independence")
        if self.execution_mode == "degraded_inline" and not self.reason_codes:
            raise ValueError("degraded inline qualification needs an explicit reason")

    @property
    def classification(self) -> NativeExecutionMode:
        return self.execution_mode

    @property
    def independence_eligible(self) -> bool:
        return self.formal_independence

    @property
    def status(self) -> Literal["PASS", "BLOCKED"]:
        return "PASS" if self.formal_independence else "BLOCKED"

    @property
    def assignment_mapped(self) -> bool:
        return self.assignment_mapping_proven

    def canonical_bytes(self) -> bytes:
        return (
            json.dumps(
                {
                    "assignment_mapping_proven": self.assignment_mapping_proven,
                    "codex_binary_sha256": self.codex_binary_sha256,
                    "codex_version": self.codex_version,
                    "execution_mode": self.execution_mode,
                    "formal_independence": self.formal_independence,
                    "host_agent_id": self.host_agent_id,
                    "hook_configured": self.hook_configured,
                    "isolation_proven": self.isolation_proven,
                    "permission_configured": self.permission_configured,
                    "profile_configured": self.profile_configured,
                    "profile_digest": self.profile_digest,
                    "qualification_receipt_sha256": self.qualification_receipt_sha256,
                    "reason_codes": self.reason_codes,
                    "requested_mode": self.requested_mode,
                    "stable_host_identity": self.stable_host_identity,
                    "status": self.status,
                    "transport": self.transport,
                    "worker_identity_id": self.worker_identity_id,
                },
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")

    @property
    def observation_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class NativeHostObservation:
    """Redaction-safe metadata for one isolated ``codex exec`` attempt.

    ``stdout_reference`` and ``stderr_reference`` point to retained raw
    observations.  Their contents are deliberately opaque to this module and
    are never parsed as a proposal or as an identity binding.
    """

    attempt_id: str
    assignment_id: str
    process_id: int
    returncode: int | None
    execution_mode: NativeExecutionMode
    formal_independence: bool
    host_agent_id: str | None
    assignment_mapping_proven: bool
    isolation_proven: bool
    profile_name: str | None
    permission_digest: str | None
    hook_config_digest: str | None
    sandbox: str
    max_depth: int
    max_threads: int
    command_reference: tuple[str, ...]
    stdout_reference: str
    stderr_reference: str
    observation_reference: str
    proposal_reference: str
    stdout_sha256: str
    stderr_sha256: str
    stdout_bytes: int
    stderr_bytes: int
    stdout_truncated: bool
    stderr_truncated: bool
    transport: CodexExecTransport = "isolated_codex_exec"
    worker_identity_id: str | None = None
    qualification_receipt_sha256: str | None = None
    codex_version: str | None = None
    codex_binary_sha256: str | None = None
    profile_digest: str | None = None
    cancellation_requested: bool = False
    force_termination_requested: bool = False
    termination_signal: str | None = None

    def canonical_bytes(self) -> bytes:
        return (
            json.dumps(
                {
                    "assignment_id": self.assignment_id,
                    "assignment_mapping_proven": self.assignment_mapping_proven,
                    "attempt_id": self.attempt_id,
                    "cancellation_requested": self.cancellation_requested,
                    "codex_binary_sha256": self.codex_binary_sha256,
                    "codex_version": self.codex_version,
                    "execution_mode": self.execution_mode,
                    "formal_independence": self.formal_independence,
                    "force_termination_requested": self.force_termination_requested,
                    "host_agent_id": self.host_agent_id,
                    "hook_config_digest": self.hook_config_digest,
                    "hook_configured": _non_empty(self.hook_config_digest),
                    "isolation_proven": self.isolation_proven,
                    "max_depth": self.max_depth,
                    "max_threads": self.max_threads,
                    "permission_digest": self.permission_digest,
                    "permission_configured": _non_empty(self.permission_digest),
                    "profile_name": self.profile_name,
                    "profile_digest": self.profile_digest,
                    "qualification_receipt_sha256": self.qualification_receipt_sha256,
                    "returncode": self.returncode,
                    "sandbox": self.sandbox,
                    "stdout_bytes": self.stdout_bytes,
                    "stdout_reference": self.stdout_reference,
                    "stdout_sha256": self.stdout_sha256,
                    "stdout_truncated": self.stdout_truncated,
                    "stderr_bytes": self.stderr_bytes,
                    "stderr_reference": self.stderr_reference,
                    "stderr_sha256": self.stderr_sha256,
                    "stderr_truncated": self.stderr_truncated,
                    "termination_signal": self.termination_signal,
                    "observation_reference": self.observation_reference,
                    "proposal_reference": self.proposal_reference,
                    "process_id": self.process_id,
                    "command_reference": self.command_reference,
                    "transport": self.transport,
                    "worker_identity_id": self.worker_identity_id,
                },
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")

    @property
    def observation_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


class HostQualificationBlocked(AdapterFailure):
    """The host cannot honestly claim a formal native execution mode."""

    reason = "host_qualification_blocked"

    def __init__(self, qualification: NativeHostQualification) -> None:
        self.qualification = qualification
        super().__init__("; ".join(qualification.reason_codes) or "host qualification blocked")

    @property
    def classification(self) -> NativeExecutionMode:
        return self.qualification.execution_mode

    @property
    def formal_independence(self) -> bool:
        return self.qualification.formal_independence


class NativeProcessFailure(ProcessFailure):
    """A process failure with retained host observations."""

    def __init__(
        self,
        message: str,
        *,
        result: HostResult | None = None,
    ) -> None:
        self.result = result
        super().__init__(message)


class NativeCancelledExecution(AdapterFailure):
    """A process that exited after the parent requested cancellation."""

    reason = "cancelled"

    def __init__(self, message: str, *, result: HostResult | None = None) -> None:
        self.result = result
        super().__init__(message)


class ForceTerminationNotQualified(AdapterFailure):
    """Force termination was requested outside the qualified boundary."""

    reason = "force_termination_unqualified"


@dataclass(frozen=True, slots=True)
class _StreamCapture:
    total_bytes: int
    digest: str
    truncated: bool


@dataclass(slots=True)
class _CredentialProvision:
    environment: dict[str, str]
    isolated_home: Path
    isolated_codex_home: Path
    cleaned: bool = False

    def cleanup(self) -> None:
        if self.cleaned:
            return
        for path in (self.isolated_codex_home, self.isolated_home):
            try:
                if path.is_symlink():
                    path.unlink(missing_ok=True)
                elif path.exists():
                    shutil.rmtree(path)
            except OSError:
                # Cleanup is best-effort and never turns host output into
                # authority. A later run-root audit can flag a retained path.
                pass
        self.cleaned = True


@dataclass(slots=True)
class _ActiveNativeProcess:
    spec: DispatchSpec
    process: asyncio.subprocess.Process
    qualification: NativeHostQualification
    stdout_task: asyncio.Task[_StreamCapture]
    stderr_task: asyncio.Task[_StreamCapture]
    stdout_path: Path
    stderr_path: Path
    observation_path: Path
    credential_provision: _CredentialProvision
    started_at: float
    cancel_requested_at: float | None = None
    force_termination_requested: bool = False
    termination_signal: str | None = None


def qualify_native_host(
    config: NativeHostConfig,
    *,
    assignment_id: str | None = None,
    host_agent_id: str | None = None,
) -> NativeHostQualification:
    """Verify retained exact-host evidence without trusting caller assertions."""

    requested = config.configured_mode

    if requested == "degraded_inline":
        return NativeHostQualification(
            requested_mode=requested,
            execution_mode="degraded_inline",
            formal_independence=False,
            stable_host_identity=False,
            assignment_mapping_proven=False,
            isolation_proven=False,
            profile_configured=False,
            permission_configured=False,
            hook_configured=False,
            reason_codes=("inline_execution_is_not_independent",),
        )
    if requested == "blocked":
        return NativeHostQualification(
            requested_mode=requested,
            execution_mode="blocked",
            formal_independence=False,
            stable_host_identity=False,
            assignment_mapping_proven=False,
            isolation_proven=False,
            profile_configured=False,
            permission_configured=False,
            hook_configured=False,
            reason_codes=("host_route_explicitly_blocked",),
        )

    receipt, receipt_digest, receipt_reasons = _load_retained_qualification_receipt(config)
    credential_files, credential_bundle_sha256, credential_reasons = (
        _credential_source_bundle(config)
    )
    _executable_path, actual_binary_sha256 = _resolved_executable_digest(config)
    reasons = [*receipt_reasons, *credential_reasons]
    if actual_binary_sha256 is None:
        reasons.append("codex_executable_unavailable")
    if config.codex_version is None:
        reasons.append("missing_expected_codex_version")
    if config.codex_binary_sha256 is None:
        reasons.append("missing_expected_codex_binary_digest")
    if config.profile_digest is None:
        reasons.append("missing_expected_profile_digest")
    if config.permission_digest is None:
        reasons.append("missing_expected_permission_digest")
    if config.hook_config_digest is None:
        reasons.append("missing_expected_hook_digest")

    profile_file_sha256 = next(
        (item.sha256 for item in credential_files if item.name == "config.toml"),
        None,
    )
    if profile_file_sha256 is None:
        reasons.append("missing_profile_configuration_input")
    elif config.profile_digest is not None and profile_file_sha256 != config.profile_digest:
        reasons.append("profile_configuration_digest_drift")

    if receipt is not None:
        if receipt.transport != "isolated_codex_exec":
            reasons.append("qualification_transport_mismatch")
        if receipt.execution_mode != requested:
            reasons.append("qualification_execution_mode_mismatch")
        if assignment_id is not None and receipt.assignment_id != assignment_id:
            reasons.append("qualification_assignment_mismatch")
        if config.mapped_assignment_id is not None and (
            config.mapped_assignment_id != receipt.assignment_id
        ):
            reasons.append("configured_assignment_mapping_mismatch")
        if host_agent_id is not None and host_agent_id != receipt.host_agent_id:
            reasons.append("caller_host_identity_mismatch")
        if config.host_agent_id is not None and config.host_agent_id != receipt.host_agent_id:
            reasons.append("configured_host_identity_mismatch")
        if config.codex_version != receipt.codex_version:
            reasons.append("codex_version_drift")
        if config.codex_binary_sha256 != receipt.codex_binary_sha256:
            reasons.append("expected_binary_digest_drift")
        if actual_binary_sha256 != receipt.codex_binary_sha256:
            reasons.append("codex_binary_digest_drift")
        if config.profile_name != receipt.profile_name:
            reasons.append("profile_name_drift")
        if config.profile_digest != receipt.profile_digest:
            reasons.append("profile_digest_drift")
        if config.permission_digest != receipt.permission_digest:
            reasons.append("permission_digest_drift")
        if config.hook_config_digest != receipt.hook_config_digest:
            reasons.append("hook_config_digest_drift")
        if credential_bundle_sha256 != receipt.credential_bundle_sha256:
            reasons.append("credential_bundle_digest_drift")

    reasons = list(dict.fromkeys(reasons))
    formal = not reasons
    stable_identity = formal and receipt is not None and _non_empty(receipt.host_agent_id)
    assignment_mapped = formal and receipt is not None and receipt.assignment_mapping_proven
    isolation = formal and receipt is not None and (
        receipt.isolation_proven and receipt.credential_isolation_proven
    )
    return NativeHostQualification(
        requested_mode=requested,
        execution_mode=requested if formal else "blocked",
        formal_independence=formal,
        stable_host_identity=stable_identity,
        assignment_mapping_proven=assignment_mapped,
        isolation_proven=isolation,
        profile_configured=formal and profile_file_sha256 == config.profile_digest,
        permission_configured=formal and _is_sha256(config.permission_digest),
        hook_configured=formal and _is_sha256(config.hook_config_digest),
        host_agent_id=receipt.host_agent_id if receipt is not None else None,
        worker_identity_id=receipt.worker_identity_id if receipt is not None else None,
        transport="isolated_codex_exec",
        qualification_receipt_sha256=receipt_digest if receipt is not None else None,
        codex_version=receipt.codex_version if receipt is not None else None,
        codex_binary_sha256=(
            receipt.codex_binary_sha256 if receipt is not None else actual_binary_sha256
        ),
        profile_digest=receipt.profile_digest if receipt is not None else config.profile_digest,
        reason_codes=tuple(reasons),
    )


def _redacted_command_reference(command: Sequence[str]) -> tuple[str, ...]:
    """Keep flags for audit while removing host-specific absolute paths."""

    return tuple(
        "<host-path>" if Path(part).is_absolute() else part
        for part in command
    )


class CodexExecExecutionAdapter:
    """Thin, qualified transport for one isolated ``codex exec`` child.

    The adapter intentionally does not import the runtime or manifest layer.
    It creates only attempt-local scratch/result/observation directories and
    returns a direct proposal path for the parent to validate.  ``--json``
    output is copied byte-for-byte to an observation file and never decoded.
    """

    def __init__(
        self,
        config: NativeHostConfig | None = None,
        **config_overrides: object,
    ) -> None:
        if config is not None and config_overrides:
            raise TypeError("pass either config or native host configuration fields")
        self.config = config or NativeHostConfig(**config_overrides)
        self._active: dict[str, _ActiveNativeProcess] = {}
        self._observations: dict[str, NativeHostObservation] = {}

    @property
    def configuration(self) -> NativeHostConfig:
        return self.config

    @property
    def qualification(self) -> NativeHostQualification:
        return qualify_native_host(self.config)

    @property
    def execution_mode(self) -> NativeExecutionMode:
        return self.qualification.execution_mode

    @property
    def formal_independence(self) -> bool:
        return self.qualification.formal_independence

    def classify(
        self,
        *,
        assignment_id: str | None = None,
        host_agent_id: str | None = None,
    ) -> NativeHostQualification:
        return qualify_native_host(
            self.config,
            assignment_id=assignment_id,
            host_agent_id=host_agent_id,
        )

    def qualify(
        self,
        *,
        assignment_id: str | None = None,
        host_agent_id: str | None = None,
    ) -> NativeHostQualification:
        return self.classify(
            assignment_id=assignment_id,
            host_agent_id=host_agent_id,
        )

    @property
    def classification(self) -> NativeExecutionMode:
        return self.execution_mode

    def qualification_for(self, spec: DispatchSpec) -> NativeHostQualification:
        return self.classify(assignment_id=spec.assignment_id)

    def observation_for(self, attempt_id: str) -> NativeHostObservation | None:
        return self._observations.get(attempt_id)

    async def dispatch(self, spec: DispatchSpec) -> HostResult:
        qualification = self.qualification_for(spec)
        if qualification.execution_mode not in {
            "native_profile",
            "assignment_injected_subagent",
        }:
            raise HostQualificationBlocked(qualification)
        host_agent_id = qualification.host_agent_id
        if not _non_empty(host_agent_id):
            raise HostQualificationBlocked(qualification)

        attempt_root, scratch_root, result_root, observation_root = self._prepare_roots(spec)
        assignment_path = self._assignment_snapshot(spec, attempt_root)
        proposal_path = result_root / "proposal.json"
        command = self._command(spec, scratch_root, result_root, qualification)
        provision = self._provision_environment(scratch_root)
        rechecked_qualification = self.qualification_for(spec)
        if (
            not rechecked_qualification.formal_independence
            or rechecked_qualification.observation_sha256
            != qualification.observation_sha256
        ):
            provision.cleanup()
            raise HostQualificationBlocked(rechecked_qualification)
        qualification = rechecked_qualification
        prompt = self._assignment_prompt(assignment_path, proposal_path)
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=scratch_root,
                env=provision.environment,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=(os.name == "posix"),
            )
        except FileNotFoundError as error:
            provision.cleanup()
            raise NativeProcessFailure("codex executable is unavailable") from error
        except PermissionError as error:
            provision.cleanup()
            raise PermissionDenied("codex executable is not runnable") from error
        except OSError as error:
            provision.cleanup()
            raise NativeProcessFailure(f"codex process could not start: {error}") from error

        if process.stdin is not None:
            try:
                process.stdin.write(prompt.encode("utf-8"))
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                # The child may have failed before consuming its prompt; its
                # exit code and retained streams remain the observation.
                pass
            finally:
                process.stdin.close()

        stdout_path = observation_root / "stdout.jsonl"
        stderr_path = observation_root / "stderr.log"
        observation_path = observation_root / "host-observation.json"
        stdout_task = asyncio.create_task(
            self._capture_stream(
                process.stdout,
                stdout_path,
                self.config.observation_max_bytes,
            )
        )
        stderr_task = asyncio.create_task(
            self._capture_stream(
                process.stderr,
                stderr_path,
                self.config.observation_max_bytes,
            )
        )
        active = _ActiveNativeProcess(
            spec=spec,
            process=process,
            qualification=qualification,
            stdout_task=stdout_task,
            stderr_task=stderr_task,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            observation_path=observation_path,
            credential_provision=provision,
            started_at=time.monotonic(),
        )
        self._active[spec.attempt_id] = active
        returncode: int | None = None
        task_cancelled = False
        try:
            try:
                returncode = await process.wait()
            except asyncio.CancelledError:
                task_cancelled = True
                if process.returncode is None:
                    if active.cancel_requested_at is None:
                        active.cancel_requested_at = time.monotonic()
                    if not active.force_termination_requested:
                        try:
                            self._signal_process(active, force=False)
                        except OSError:
                            pass
                    # Do not turn a caller cancellation into an unbounded wait.
                    # The group is cooperatively signaled and a background reaper
                    # prevents the leader from becoming an orphaned zombie.
                    asyncio.create_task(self._reap_process(process, provision))
                    stdout_task.cancel()
                    stderr_task.cancel()
                returncode = process.returncode
                raise
        finally:
            captures = await asyncio.gather(
                stdout_task,
                stderr_task,
                return_exceptions=True,
            )
            stdout_capture = (
                captures[0]
                if isinstance(captures[0], _StreamCapture)
                else _StreamCapture(0, hashlib.sha256(b"").hexdigest(), False)
            )
            stderr_capture = (
                captures[1]
                if isinstance(captures[1], _StreamCapture)
                else _StreamCapture(0, hashlib.sha256(b"").hexdigest(), False)
            )
            if returncode is None:
                returncode = process.returncode
            observation = NativeHostObservation(
                attempt_id=spec.attempt_id,
                assignment_id=spec.assignment_id,
                process_id=process.pid,
                returncode=returncode,
                execution_mode=qualification.execution_mode,
                formal_independence=qualification.formal_independence,
                host_agent_id=qualification.host_agent_id,
                assignment_mapping_proven=qualification.assignment_mapping_proven,
                isolation_proven=qualification.isolation_proven,
                profile_name=self.config.profile_name,
                permission_digest=self.config.permission_digest,
                hook_config_digest=self.config.hook_config_digest,
                sandbox=self.config.sandbox,
                max_depth=self.config.max_depth,
                max_threads=self.config.max_threads,
                command_reference=_redacted_command_reference(command),
                stdout_reference=self._reference(spec, "observations/stdout.jsonl"),
                stderr_reference=self._reference(spec, "observations/stderr.log"),
                observation_reference=self._reference(spec, "observations/host-observation.json"),
                proposal_reference=self._reference(spec, "result/proposal.json"),
                stdout_sha256=stdout_capture.digest,
                stderr_sha256=stderr_capture.digest,
                stdout_bytes=stdout_capture.total_bytes,
                stderr_bytes=stderr_capture.total_bytes,
                stdout_truncated=stdout_capture.truncated,
                stderr_truncated=stderr_capture.truncated,
                transport="isolated_codex_exec",
                worker_identity_id=qualification.worker_identity_id,
                qualification_receipt_sha256=qualification.qualification_receipt_sha256,
                codex_version=qualification.codex_version,
                codex_binary_sha256=qualification.codex_binary_sha256,
                profile_digest=qualification.profile_digest,
                cancellation_requested=active.cancel_requested_at is not None,
                force_termination_requested=active.force_termination_requested,
                termination_signal=active.termination_signal,
            )
            observation_path.write_bytes(observation.canonical_bytes())
            self._observations[spec.attempt_id] = observation
            self._active.pop(spec.attempt_id, None)
            if process.returncode is not None:
                provision.cleanup()

        if task_cancelled:
            raise asyncio.CancelledError
        result = HostResult(
            attempt_id=spec.attempt_id,
            host_agent_id=host_agent_id,
            proposal_path=proposal_path,
            transcript_reference=observation.stdout_reference,
            observation_sha256=observation.observation_sha256,
            output_bytes=observation.stdout_bytes + observation.stderr_bytes,
            execution_mode=qualification.execution_mode,
            formal_independence=qualification.formal_independence,
            assignment_mapping_proven=qualification.assignment_mapping_proven,
            isolation_proven=qualification.isolation_proven,
            profile_name=self.config.profile_name,
            permission_digest=self.config.permission_digest,
            hook_config_digest=self.config.hook_config_digest,
            process_id=process.pid,
            returncode=returncode,
            observation_path=observation_path,
            observation=observation,
            transport="isolated_codex_exec",
            worker_identity_id=qualification.worker_identity_id,
            qualification_receipt_sha256=qualification.qualification_receipt_sha256,
            codex_version=qualification.codex_version,
            codex_binary_sha256=qualification.codex_binary_sha256,
            profile_digest=qualification.profile_digest,
        )
        if active.cancel_requested_at is not None:
            raise NativeCancelledExecution(
                f"attempt {spec.attempt_id} exited after cooperative cancellation",
                result=result,
            )
        if returncode != 0:
            raise NativeProcessFailure(
                f"codex exited with return code {returncode}",
                result=result,
            )
        return result

    async def request_cancel(self, spec: DispatchSpec) -> None:
        active = self._active.get(spec.attempt_id)
        if active is None or active.process.returncode is not None:
            return
        if active.cancel_requested_at is not None:
            return
        active.cancel_requested_at = time.monotonic()
        self._signal_process(active, force=False)

    async def force_terminate(self, spec: DispatchSpec) -> None:
        active = self._active.get(spec.attempt_id)
        if active is None or active.process.returncode is not None:
            return
        if active.force_termination_requested:
            return
        if active.cancel_requested_at is None:
            raise ForceTerminationNotQualified(
                "force termination requires a prior cooperative cancellation request"
            )
        elapsed = time.monotonic() - active.cancel_requested_at
        if elapsed < spec.effective_cancellation_grace_seconds:
            raise ForceTerminationNotQualified(
                "force termination was requested before the frozen cancellation grace elapsed"
            )
        if not self.config.termination_is_qualified:
            raise ForceTerminationNotQualified(
                "the host has no qualified process-group force-termination mapping"
            )
        try:
            signaled = self._signal_process(active, force=True)
        except OSError as error:
            raise ForceTerminationNotQualified(
                f"qualified force termination could not signal the process: {error}"
            ) from error
        if not signaled:
            if active.process.returncode is not None:
                await active.process.wait()
                return
            raise ForceTerminationNotQualified(
                "qualified force termination produced no process-group signal"
            )
        active.force_termination_requested = True
        await active.process.wait()

    def _prepare_roots(self, spec: DispatchSpec) -> tuple[Path, Path, Path, Path]:
        if any(
            token in spec.attempt_id
            for token in ("/", "\\", "\x00")
        ) or spec.attempt_id in {".", ".."}:
            raise HostQualificationBlocked(
                NativeHostQualification(
                    requested_mode=self.config.configured_mode,
                    execution_mode="blocked",
                    formal_independence=False,
                    stable_host_identity=False,
                    assignment_mapping_proven=False,
                    isolation_proven=False,
                    profile_configured=_non_empty(self.config.profile_name),
                    permission_configured=_non_empty(self.config.permission_digest),
                    hook_configured=_non_empty(self.config.hook_config_digest),
                    reason_codes=("unsafe_attempt_id",),
                )
            )
        attempt_root = spec.attempt_root
        if attempt_root.is_symlink():
            raise ProcessFailure("attempt root must not be a symlink")
        attempt_root.mkdir(parents=True, exist_ok=True)
        scratch_root = attempt_root / "scratch"
        result_root = attempt_root / "result"
        observation_root = attempt_root / "observations"
        for path in (scratch_root, result_root, observation_root):
            if path.exists() and path.is_symlink():
                raise ProcessFailure("native attempt directories must not be symlinks")
            path.mkdir(parents=True, exist_ok=True)
        fixed_files = (
            result_root / "proposal.json",
            observation_root / "stdout.jsonl",
            observation_root / "stderr.log",
            observation_root / "host-observation.json",
        )
        if any(path.exists() or path.is_symlink() for path in fixed_files):
            raise StaleAttempt("native attempt result or observations already exist")
        return attempt_root, scratch_root, result_root, observation_root

    def _assignment_snapshot(self, spec: DispatchSpec, attempt_root: Path) -> Path:
        """Use the parent-installed attempt snapshot, with a test fallback."""

        snapshot = attempt_root / "assignment.json"
        if snapshot.is_symlink() or (snapshot.exists() and not snapshot.is_file()):
            raise StaleAttempt("attempt assignment snapshot is not a regular file")
        if snapshot.is_file():
            return snapshot

        source = spec.assignment_path
        if source.is_symlink() or not source.is_file():
            raise StaleAttempt("immutable assignment snapshot is unavailable")
        try:
            with snapshot.open("xb") as handle:
                handle.write(source.read_bytes())
        except FileExistsError:
            if snapshot.is_symlink() or not snapshot.is_file():
                raise StaleAttempt("attempt assignment snapshot changed during dispatch")
        return snapshot

    def _command(
        self,
        spec: DispatchSpec,
        scratch_root: Path,
        result_root: Path,
        qualification: NativeHostQualification,
    ) -> tuple[str, ...]:
        command: list[str] = [
            *self.config.command_argv,
            "exec",
            "--ephemeral",
            "--json",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--cd",
            str(scratch_root),
            "--add-dir",
            str(result_root),
            "--sandbox",
            self.config.sandbox,
        ]
        if qualification.execution_mode == "native_profile":
            command.extend(("--profile", self.config.profile_name or ""))
        command.extend(
            (
                "-c",
                "agents.max_depth=1",
                "-c",
                f"agents.max_threads={self.config.max_threads}",
                "-",
            )
        )
        return tuple(command)

    def _provision_environment(self, scratch_root: Path) -> _CredentialProvision:
        """Create a fresh child home and copy only approved Codex inputs."""

        environment = {
            key: value
            for key in _SAFE_CHILD_ENVIRONMENT_KEYS
            if (value := os.environ.get(key)) is not None
        }
        for key, value in self.config.environment:
            environment[key] = value
        isolated_home = scratch_root / "home"
        codex_home = scratch_root / "codex-home"
        for path in (isolated_home, codex_home):
            if path.exists() or path.is_symlink():
                raise StaleAttempt("isolated Codex home already exists")
            path.mkdir(mode=0o700)
            path.chmod(0o700)
        source_files, bundle_sha256, reasons = _credential_source_bundle(self.config)
        if reasons or bundle_sha256 is None:
            provision = _CredentialProvision(environment, isolated_home, codex_home)
            provision.cleanup()
            raise PermissionDenied("safe Codex credential provision is unavailable")
        receipt, _receipt_digest, receipt_reasons = _load_retained_qualification_receipt(
            self.config
        )
        if (
            receipt_reasons
            or receipt is None
            or receipt.credential_bundle_sha256 != bundle_sha256
        ):
            provision = _CredentialProvision(environment, isolated_home, codex_home)
            provision.cleanup()
            raise PermissionDenied("Codex credential bundle is not receipt-bound")
        for source in source_files:
            destination = codex_home / source.name
            try:
                descriptor = os.open(
                    destination,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
                with source.path.open("rb") as input_handle, os.fdopen(
                    descriptor, "wb"
                ) as output_handle:
                    shutil.copyfileobj(input_handle, output_handle, length=1024 * 1024)
                destination.chmod(0o600)
            except OSError as error:
                provision = _CredentialProvision(environment, isolated_home, codex_home)
                provision.cleanup()
                raise PermissionDenied("safe Codex credential provision failed") from error
            if _hash_file(destination) != source.sha256:
                provision = _CredentialProvision(environment, isolated_home, codex_home)
                provision.cleanup()
                raise PermissionDenied("provisioned Codex input digest drifted")
        environment["HOME"] = str(isolated_home)
        environment["CODEX_HOME"] = str(codex_home)
        return _CredentialProvision(environment, isolated_home, codex_home)

    @staticmethod
    def _assignment_prompt(assignment_path: Path, proposal_path: Path) -> str:
        assignment = str(assignment_path.resolve())
        proposal = str(proposal_path.resolve())
        return (
            "Follow only the immutable ARW assignment protocol. "
            f"Read the assignment at {assignment}. "
            f"Write the schema-valid proposal only to {proposal}. "
            "Do not return proposal bytes in the final response; the parent "
            "will validate the direct result file and retain host output only as observation."
        )

    @staticmethod
    def _reference(spec: DispatchSpec, suffix: str) -> str:
        return f"attempts/{spec.attempt_id}/{suffix}"

    async def _capture_stream(
        self,
        reader: asyncio.StreamReader | None,
        path: Path,
        max_bytes: int,
    ) -> _StreamCapture:
        digest = hashlib.sha256()
        total = 0
        stored = 0
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            if reader is not None:
                while True:
                    chunk = await reader.read(64 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    total += len(chunk)
                    if stored < max_bytes:
                        keep = chunk[: max_bytes - stored]
                        handle.write(keep)
                        stored += len(keep)
        return _StreamCapture(total, digest.hexdigest(), total > stored)

    @staticmethod
    async def _reap_process(
        process: asyncio.subprocess.Process,
        provision: _CredentialProvision | None = None,
    ) -> None:
        try:
            await process.wait()
        except (OSError, asyncio.CancelledError):
            return
        finally:
            if provision is not None:
                provision.cleanup()

    @staticmethod
    def _signal_process(active: _ActiveNativeProcess, *, force: bool) -> bool:
        process = active.process
        if process.returncode is not None:
            return False
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
            except ProcessLookupError:
                return False
            active.termination_signal = "SIGKILL" if force else "SIGTERM"
            return True
        if force:
            process.kill()
            active.termination_signal = "terminate"
        else:
            process.terminate()
            active.termination_signal = "terminate"
        return True


# Backward names retain imports but no longer describe the transport as native.
CodexNativeExecutionAdapter = CodexExecExecutionAdapter
CodexExecExecutionConfig = NativeHostConfig
CodexExecHostConfig = NativeHostConfig
CodexExecHostQualification = NativeHostQualification
CodexExecHostObservation = NativeHostObservation
qualify_codex_exec_host = qualify_native_host
CodexNativeExecutionConfig = NativeHostConfig
CodexNativeHostConfig = NativeHostConfig
NativeHostConfiguration = NativeHostConfig
HostQualification = NativeHostQualification
HostQualificationEvidence = NativeHostQualification


@dataclass(frozen=True, slots=True)
class FakeDispatchPlan:
    """A deterministic fake behavior used by unit tests only."""

    delay_seconds: float = 0.0
    result: HostResult | None = None
    error: BaseException | None = None
    wait_for_cancel: bool = False
    cooperative_cancel: bool = True

    def __post_init__(self) -> None:
        if self.delay_seconds < 0 or not _is_finite(self.delay_seconds):
            raise ValueError("fake delay must be finite and non-negative")


class DeterministicFakeAdapter:
    """In-memory adapter with explicit, inspectable lifecycle observations.

    This fake intentionally has no canonical writer surface.  It records
    dispatch/cancel/force calls solely so tests can verify bounded behavior.
    """

    def __init__(
        self,
        plans: Mapping[str, FakeDispatchPlan | Sequence[FakeDispatchPlan]],
    ) -> None:
        self._plans = {
            assignment_id: (
                tuple(plan) if not isinstance(plan, FakeDispatchPlan) else (plan,)
            )
            for assignment_id, plan in plans.items()
        }
        self._calls: dict[str, int] = {}
        self._dispatch_specs: dict[str, list[DispatchSpec]] = {}
        self._lifecycle: dict[str, list[str]] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._active = 0
        self._max_active = 0
        self._completion_order: list[str] = []

    @property
    def max_active(self) -> int:
        return self._max_active

    @property
    def completion_order(self) -> tuple[str, ...]:
        return tuple(self._completion_order)

    def dispatches_for(self, assignment_id: str) -> tuple[DispatchSpec, ...]:
        return tuple(self._dispatch_specs.get(assignment_id, ()))

    def lifecycle_for(self, assignment_id: str) -> tuple[str, ...]:
        return tuple(self._lifecycle.get(assignment_id, ()))

    def _plan_for(self, spec: DispatchSpec) -> FakeDispatchPlan:
        plans = self._plans.get(spec.assignment_id)
        if not plans:
            return FakeDispatchPlan()
        index = self._calls.get(spec.assignment_id, 0)
        self._calls[spec.assignment_id] = index + 1
        return plans[min(index, len(plans) - 1)]

    async def dispatch(self, spec: DispatchSpec) -> HostResult:
        self._lifecycle.setdefault(spec.assignment_id, []).append("dispatch")
        self._dispatch_specs.setdefault(spec.assignment_id, []).append(spec)
        plan = self._plan_for(spec)
        self._active += 1
        self._max_active = max(self._max_active, self._active)
        try:
            if plan.delay_seconds:
                await asyncio.sleep(plan.delay_seconds)
            if plan.wait_for_cancel:
                event = self._cancel_events.setdefault(spec.assignment_id, asyncio.Event())
                await event.wait()
            if plan.error is not None:
                raise plan.error
            result = plan.result or HostResult(
                attempt_id=spec.attempt_id,
                host_agent_id=f"fake-host-{spec.assignment_id}",
                proposal_path=spec.attempt_root / "result" / "proposal.json",
            )
            self._completion_order.append(spec.assignment_id)
            return result
        finally:
            self._active -= 1

    async def request_cancel(self, spec: DispatchSpec) -> None:
        self._lifecycle.setdefault(spec.assignment_id, []).append("request_cancel")
        plan = self._plans.get(spec.assignment_id, (FakeDispatchPlan(),))[min(
            self._calls.get(spec.assignment_id, 1) - 1,
            len(self._plans.get(spec.assignment_id, (FakeDispatchPlan(),))) - 1,
        )]
        if plan.cooperative_cancel:
            self._cancel_events.setdefault(spec.assignment_id, asyncio.Event()).set()

    async def force_terminate(self, spec: DispatchSpec) -> None:
        self._lifecycle.setdefault(spec.assignment_id, []).append("force_terminate")


FakeExecutionAdapter = DeterministicFakeAdapter
