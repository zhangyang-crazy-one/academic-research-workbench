"""Canonical, replay-first scientific audit dossier.

The dossier is deliberately a *view* over the parent-owned journal and
content-addressed evidence.  It contains references and verdicts, never raw
research text, and neither the JSON/Markdown renderers nor a graph projection
can append canonical runtime state.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import BeforeValidator, Field, StringConstraints, field_validator, model_validator

from arw.canonical import canonical_json_bytes, sha256_hex, strict_json_loads
from arw.manifests import ManifestError, _safe_directory, _write_once
from arw.models import RunId, Sha256, StableRuntimeId, StrictModel, UtcTimestamp


AUDIT_DOSSIER_SCHEMA_VERSION = "arw.audit-dossier.v1"
AUDIT_DOSSIER_SCHEMA_NAME = "audit-dossier.schema.json"
MAX_DOSSIER_BYTES = 2 * 1024 * 1024
MAX_DOSSIER_REFS = 512
MAX_DOSSIER_BLOCKERS = 128
MAX_DOSSIER_TEST_LOGS = 256
def _as_digest_tuple(value: object) -> object:
    if isinstance(value, list):
        return tuple(value)
    if isinstance(value, str):
        return (value,)
    return value


_SHA_ARRAY = Annotated[tuple[Sha256, ...], BeforeValidator(_as_digest_tuple)]
_AS_TUPLE = lambda v: tuple(v) if isinstance(v, list) else v
_ID = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9._:-]*$")]
_CODE = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$")]
_TEXT = Annotated[str, StringConstraints(min_length=1, max_length=4096)]
_SECRET = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|password|passwd|secret|authorization|bearer|private[_-]?key|begin [^-\n]*private key|sk-[a-z0-9]|ghp_[a-z0-9])"
)
_PRIVATE = re.compile(r"(?:^|[/\\])(?:home|users|private|secrets?)(?:[/\\]|$)", re.I)


def _ordered_unique(value: Sequence[str], *, label: str, max_length: int = MAX_DOSSIER_REFS) -> tuple[str, ...]:
    result = tuple(value)
    if len(result) > max_length:
        raise ValueError(f"{label} exceeds the bounded reference limit")
    if len(result) != len(set(result)):
        raise ValueError(f"{label} must be unique")
    if result != tuple(sorted(result)):
        raise ValueError(f"{label} must be sorted canonically")
    return result


def _safe_text(value: str, *, label: str) -> str:
    if "\x00" in value or "\r" in value or len(value.encode("utf-8")) > 16_384:
        raise ValueError(f"{label} contains unsafe or oversized text")
    if _SECRET.search(value) or _PRIVATE.search(value) or "private full text" in value.lower():
        raise ValueError(f"{label} contains a secret or private path")
    return value


def _digest(value: object) -> str:
    return sha256_hex(canonical_json_bytes(value))


class DossierRunHistory(StrictModel):
    sequence: int = Field(ge=1)
    event_sha256: Sha256
    event_type: _ID
    resulting_revision: int = Field(ge=0)


class DossierClaimCapability(StrictModel):
    capability: Literal[
        "citation_verified",
        "experiment_reproduced",
        "independent_review_complete",
        "audit_complete",
    ]
    verdict: Literal["PASS", "FAIL", "BLOCKED"]
    reason_codes: Annotated[tuple[_CODE, ...], BeforeValidator(_AS_TUPLE)] = ()
    replacement_evidence: Annotated[tuple[_CODE, ...], BeforeValidator(_AS_TUPLE)] = ()
    scope: str = ""

    @field_validator("reason_codes", "replacement_evidence")
    @classmethod
    def canonical_arrays(cls, value: tuple[str, ...], info) -> tuple[str, ...]:
        return _ordered_unique(value, label=info.field_name)

    @field_validator("scope")
    @classmethod
    def scope_safe(cls, value: str) -> str:
        return _safe_text(value, label="claim scope") if value else value


class DossierReviewReference(StrictModel):
    panel_manifest_sha256: Sha256 | None = None
    review_matrix_sha256: Sha256 | None = None
    review_report_sha256: _SHA_ARRAY = ()
    synthesis_sha256: Sha256 | None = None
    dissent_refs: _SHA_ARRAY = ()

    @field_validator("review_report_sha256", "dissent_refs")
    @classmethod
    def references_are_canonical(cls, value: tuple[str, ...], info) -> tuple[str, ...]:
        return _ordered_unique(value, label=info.field_name)


class DossierTestLog(StrictModel):
    name: _ID
    command_digest: Sha256
    result: Literal["PASS", "FAIL", "BLOCKED"]
    stdout_sha256: Sha256
    stderr_sha256: Sha256
    duration_ms: int | None = Field(default=None, ge=0, le=86_400_000)


class DossierBenchmarkVersion(StrictModel):
    name: _ID
    version: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    source_sha256: Sha256 | None = None

    @field_validator("version")
    @classmethod
    def version_is_safe(cls, value: str) -> str:
        return _safe_text(value, label="benchmark version")


class DossierQualification(StrictModel):
    verdict: Literal["PASS", "FAIL", "BLOCKED"]
    reason_codes: Annotated[tuple[_CODE, ...], BeforeValidator(_AS_TUPLE)] = ()
    evidence_sha256: _SHA_ARRAY = ()
    rationale: _TEXT = "qualification evidence is retained by exact digest"

    @field_validator("reason_codes", "evidence_sha256")
    @classmethod
    def qualification_arrays(cls, value: tuple[str, ...], info) -> tuple[str, ...]:
        return _ordered_unique(value, label=info.field_name)

    @field_validator("rationale")
    @classmethod
    def rationale_safe(cls, value: str) -> str:
        return _safe_text(value, label="qualification rationale")


class DossierBlocker(StrictModel):
    code: _CODE
    severity: Literal["low", "moderate", "high", "critical"] = "high"
    message: _TEXT
    evidence_sha256: _SHA_ARRAY = ()
    replacement_evidence: Annotated[tuple[_CODE, ...], BeforeValidator(_AS_TUPLE)] = ()
    legal: bool = False

    @field_validator("evidence_sha256", "replacement_evidence")
    @classmethod
    def blocker_arrays(cls, value: tuple[str, ...], info) -> tuple[str, ...]:
        return _ordered_unique(value, label=info.field_name)

    @field_validator("message")
    @classmethod
    def blocker_message_safe(cls, value: str) -> str:
        return _safe_text(value, label="blocker message")


class AuditDossierManifest(StrictModel):
    """The sole canonical source for both dossier renderings."""

    schema_version: Literal[AUDIT_DOSSIER_SCHEMA_VERSION]
    dossier_id: StableRuntimeId
    run_id: RunId
    generated_at: UtcTimestamp
    ledger_head_sha256: Sha256
    ledger_history_sha256: _SHA_ARRAY = ()
    run_history: Annotated[tuple[DossierRunHistory, ...], BeforeValidator(_AS_TUPLE)] = ()
    run_manifest_sha256: Sha256
    passport_sha256: _SHA_ARRAY = ()
    artifact_manifest_sha256: _SHA_ARRAY = ()
    integrity_receipt_sha256: _SHA_ARRAY = ()
    experiment_provenance_sha256: _SHA_ARRAY = ()
    access_decisions: _SHA_ARRAY = ()
    claim_capabilities: Annotated[tuple[DossierClaimCapability, ...], BeforeValidator(_AS_TUPLE)] = ()
    panel_manifest_sha256: Sha256 | None = None
    review_matrix_sha256: Sha256 | None = None
    review_report_sha256: _SHA_ARRAY = ()
    synthesis_sha256: Sha256 | None = None
    dissent_refs: _SHA_ARRAY = ()
    human_decision_sha256: _SHA_ARRAY = ()
    graph_projection_receipt_sha256: _SHA_ARRAY = ()
    graph_watermark: int | None = Field(default=None, ge=0)
    test_logs: Annotated[tuple[DossierTestLog, ...], BeforeValidator(_AS_TUPLE)] = ()
    benchmark_versions: Annotated[tuple[DossierBenchmarkVersion, ...], BeforeValidator(_AS_TUPLE)] = ()
    build_identity_sha256: Sha256 | None = None
    source_identity_sha256: _SHA_ARRAY = ()
    integration_lock_sha256: Sha256 | None = None
    technical_qualification: DossierQualification
    release_qualification: DossierQualification
    blockers: Annotated[tuple[DossierBlocker, ...], BeforeValidator(_AS_TUPLE)] = ()
    dossier_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def derive_or_verify_digest(cls, value: Any) -> Any:
        if isinstance(value, cls) or not isinstance(value, Mapping):
            return value
        body = dict(value)
        supplied = body.pop("dossier_sha256", None)
        defaults: dict[str, object] = {
            "ledger_history_sha256": [], "run_history": [], "passport_sha256": [],
            "artifact_manifest_sha256": [], "integrity_receipt_sha256": [],
            "experiment_provenance_sha256": [], "access_decisions": [],
            "claim_capabilities": [], "panel_manifest_sha256": None,
            "review_matrix_sha256": None, "review_report_sha256": [],
            "synthesis_sha256": None, "dissent_refs": [], "human_decision_sha256": [],
            "graph_projection_receipt_sha256": [], "graph_watermark": None,
            "test_logs": [], "benchmark_versions": [], "build_identity_sha256": None,
            "source_identity_sha256": [], "integration_lock_sha256": None, "blockers": [],
        }
        # Older Phase 6 handoff notes used singular/verbose names.  Consume
        # those spellings at the boundary, then emit one canonical vocabulary.
        aliases = {
            "blocker": "blockers",
            "access_decision_sha256": "access_decisions",
            "source_manifest_sha256": "source_identity_sha256",
            "build_sha256": "build_identity_sha256",
            "integration_lock": "integration_lock_sha256",
        }
        for source, target in aliases.items():
            if source in body and target not in body:
                body[target] = body.pop(source)
        for key in ("technical_qualification", "release_qualification"):
            if isinstance(body.get(key), str):
                body[key] = {"verdict": body[key]}
        if isinstance(body.get("claim_capabilities"), Mapping):
            body["claim_capabilities"] = [
                ({**value, "capability": key} if isinstance(value, Mapping) else {"capability": key, "verdict": value})
                for key, value in body["claim_capabilities"].items()
            ]
        if isinstance(body.get("claim_capabilities"), (list, tuple)):
            body["claim_capabilities"] = [
                {**item, "reason_codes": item.get("reason_codes", []), "replacement_evidence": item.get("replacement_evidence", []), "scope": item.get("scope", "")}
                if isinstance(item, Mapping) else item
                for item in body["claim_capabilities"]
            ]
        for key in ("technical_qualification", "release_qualification"):
            if isinstance(body.get(key), Mapping):
                body[key] = {"reason_codes": [], "evidence_sha256": [], "rationale": "qualification evidence is retained by exact digest", **body[key]}
        if isinstance(body.get("blockers"), (list, tuple)):
            body["blockers"] = [
                {"severity": "high", "evidence_sha256": [], "replacement_evidence": [], "legal": False, **item}
                if isinstance(item, Mapping) else item
                for item in body["blockers"]
            ]
        for key, default in defaults.items():
            body.setdefault(key, default)
        try:
            expected = _digest(body)
        except (TypeError, ValueError):
            return value
        if supplied is not None and supplied != expected:
            raise ValueError("dossier_sha256 does not match canonical dossier bytes")
        body["dossier_sha256"] = expected
        return body

    @field_validator(
        "ledger_history_sha256", "passport_sha256", "artifact_manifest_sha256",
        "integrity_receipt_sha256", "experiment_provenance_sha256", "access_decisions",
        "review_report_sha256", "dissent_refs", "human_decision_sha256",
        "graph_projection_receipt_sha256", "source_identity_sha256",
    )
    @classmethod
    def digest_arrays_are_canonical(cls, value: tuple[str, ...], info) -> tuple[str, ...]:
        return _ordered_unique(value, label=info.field_name)

    @field_validator("run_history")
    @classmethod
    def history_is_canonical(cls, value: tuple[DossierRunHistory, ...]) -> tuple[DossierRunHistory, ...]:
        sequences = tuple(item.sequence for item in value)
        if len(sequences) > MAX_DOSSIER_REFS or len(sequences) != len(set(sequences)):
            raise ValueError("run history sequence identities must be unique and bounded")
        if sequences != tuple(sorted(sequences)):
            raise ValueError("run history must be sorted by sequence")
        return value

    @field_validator("claim_capabilities")
    @classmethod
    def claims_are_canonical(cls, value: tuple[DossierClaimCapability, ...]) -> tuple[DossierClaimCapability, ...]:
        ids = tuple(item.capability for item in value)
        if len(ids) != len(set(ids)) or ids != tuple(sorted(ids)):
            raise ValueError("claim capabilities must be unique and sorted")
        return value

    @field_validator("test_logs")
    @classmethod
    def logs_are_canonical(cls, value: tuple[DossierTestLog, ...]) -> tuple[DossierTestLog, ...]:
        if len(value) > MAX_DOSSIER_TEST_LOGS:
            raise ValueError("test logs exceed bounded output limit")
        names = tuple(item.name for item in value)
        if len(names) != len(set(names)) or names != tuple(sorted(names)):
            raise ValueError("test logs must be unique and sorted")
        return value

    @field_validator("blockers")
    @classmethod
    def blockers_are_bounded(cls, value: tuple[DossierBlocker, ...]) -> tuple[DossierBlocker, ...]:
        if len(value) > MAX_DOSSIER_BLOCKERS:
            raise ValueError("blockers exceed bounded output limit")
        codes = tuple(item.code for item in value)
        if len(codes) != len(set(codes)) or codes != tuple(sorted(codes)):
            raise ValueError("blockers must be unique and sorted")
        return value

    @model_validator(mode="after")
    def canonical_digest_and_verdicts(self) -> Self:
        unsigned = self.model_dump(mode="json", exclude={"dossier_sha256"})
        if self.dossier_sha256 != _digest(unsigned):
            raise ValueError("dossier_sha256 does not match canonical dossier bytes")
        if self.release_qualification.verdict == "PASS":
            legal = {"SUP-04", "P04-09", "CC_BY_NC_PERMISSION_UNRESOLVED"}
            if any(blocker.code in legal for blocker in self.blockers):
                raise ValueError("release qualification cannot pass with unresolved legal blockers")
        if len(self.model_dump_json().encode("utf-8")) > MAX_DOSSIER_BYTES:
            raise ValueError("dossier exceeds bounded canonical byte limit")
        return self

    def unsigned_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json", exclude={"dossier_sha256"}))

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json"))


def seal_audit_dossier(value: Mapping[str, Any] | AuditDossierManifest) -> AuditDossierManifest:
    if isinstance(value, AuditDossierManifest):
        value = value.model_dump(mode="json")
    try:
        return AuditDossierManifest.model_validate(value)
    except Exception as error:
        raise AuditDossierError(f"invalid audit dossier: {error}") from error


class AuditDossierError(ValueError, ManifestError):
    """Unsafe, malformed, or non-canonical dossier bytes."""


def _dossier_directory(root: Path, *, create: bool) -> Path:
    try:
        return _safe_directory(root, ("evidence", "audit-dossiers", "sha256"), create=create)
    except ManifestError as error:
        raise AuditDossierError(str(error)) from error


def publish_audit_dossier(root: Path, value: Mapping[str, Any] | AuditDossierManifest) -> Path:
    dossier = seal_audit_dossier(value)
    try:
        return _write_once(_dossier_directory(root, create=True) / f"{dossier.dossier_sha256}.json", dossier.canonical_bytes())
    except ManifestError as error:
        raise AuditDossierError(str(error)) from error


def load_audit_dossier(root: Path, dossier_sha256: str) -> AuditDossierManifest:
    if not re.fullmatch(r"[0-9a-f]{64}", dossier_sha256):
        raise AuditDossierError("dossier address must be a lowercase SHA-256 digest")
    directory = _dossier_directory(root, create=False)
    path = directory / f"{dossier_sha256}.json"
    if path.is_symlink() or not path.is_file():
        raise AuditDossierError("audit dossier is missing or unsafe")
    try:
        dossier = seal_audit_dossier(strict_json_loads(path.read_bytes()))
    except (OSError, UnicodeError, ValueError) as error:
        raise AuditDossierError(f"audit dossier is invalid: {error}") from error
    if dossier.dossier_sha256 != dossier_sha256 or path.read_bytes() != dossier.canonical_bytes():
        raise AuditDossierError("audit dossier is not canonically addressed")
    return dossier


def render_audit_dossier_json(value: Mapping[str, Any] | AuditDossierManifest) -> bytes:
    """Return the canonical JSON view; it is not a writable authority store."""

    return seal_audit_dossier(value).canonical_bytes()


def render_audit_dossier_markdown(value: Mapping[str, Any] | AuditDossierManifest) -> bytes:
    """Render a deterministic, explicitly non-authoritative presentation."""

    dossier = seal_audit_dossier(value)
    lines = [
        "# Scientific Audit Dossier",
        "",
        "> This Markdown is a deterministic, non-authoritative rendering of the canonical JSON manifest.",
        "> Canonical authority remains the replayed ledger and immutable content-addressed records.",
        "",
        f"- Dossier: `{dossier.dossier_id}`",
        f"- Run: `{dossier.run_id}`",
        f"- Generated at: `{dossier.generated_at}`",
        f"- Ledger head: `{dossier.ledger_head_sha256}`",
        f"- Dossier SHA-256: `{dossier.dossier_sha256}`",
        "",
        "## Qualification",
        "",
        f"- Technical: **{dossier.technical_qualification.verdict}**",
        f"- Release: **{dossier.release_qualification.verdict}**",
        f"- Technical reasons: `{', '.join(dossier.technical_qualification.reason_codes) or 'none'}`",
        f"- Release reasons: `{', '.join(dossier.release_qualification.reason_codes) or 'none'}`",
        "",
        "## Evidence references (non-authoritative)",
        "",
        f"- Run manifest: `{dossier.run_manifest_sha256}`",
        f"- Passports: {', '.join(f'`{v}`' for v in dossier.passport_sha256) or 'none'}",
        f"- Artifacts: {', '.join(f'`{v}`' for v in dossier.artifact_manifest_sha256) or 'none'}",
        f"- Integrity receipts: {', '.join(f'`{v}`' for v in dossier.integrity_receipt_sha256) or 'none'}",
        f"- External provenance: {', '.join(f'`{v}`' for v in dossier.experiment_provenance_sha256) or 'none'}",
        f"- Access decisions: {', '.join(f'`{v}`' for v in dossier.access_decisions) or 'none'}",
        f"- Graph receipts: {', '.join(f'`{v}`' for v in dossier.graph_projection_receipt_sha256) or 'none'}",
        "",
        "## Claim capabilities",
        "",
    ]
    for claim in dossier.claim_capabilities:
        reasons = ", ".join(claim.reason_codes) or "none"
        lines.append(f"- `{claim.capability}`: **{claim.verdict}** (reasons: `{reasons}`)")
    lines.extend(["", "## Review and human evidence", ""])
    lines.extend([
        f"- Panel manifest: `{dossier.panel_manifest_sha256 or 'none'}`",
        f"- Review matrix: `{dossier.review_matrix_sha256 or 'none'}`",
        f"- Reports: {', '.join(f'`{v}`' for v in dossier.review_report_sha256) or 'none'}",
        f"- Dissent: {', '.join(f'`{v}`' for v in dossier.dissent_refs) or 'none'}",
        f"- Human decisions: {', '.join(f'`{v}`' for v in dossier.human_decision_sha256) or 'none'}",
        "",
        "## Blockers",
        "",
    ])
    if dossier.blockers:
        lines.extend(f"- `{b.code}` ({b.severity}): {b.message}" for b in dossier.blockers)
    else:
        lines.append("- none")
    lines.extend(["", "## Authority boundary", "", "SQLite/graph projections, test logs, reports, and this Markdown are evidence references only; they cannot change ledger state, claim verdicts, or release permission.", ""])
    return "\n".join(lines).encode("utf-8")


def _coerce_sha_refs(values: Sequence[Any] | None) -> tuple[str, ...]:
    result: list[str] = []
    if isinstance(values, str) or isinstance(values, Mapping) or hasattr(values, "model_dump"):
        values = (values,)
    for value in values or ():
        if isinstance(value, str):
            result.append(value)
        elif isinstance(value, Mapping):
            for key in ("sha256", "digest", "receipt_sha256", "provenance_sha256", "decision_sha256", "manifest_sha256", "identity_sha256", "build_identity_sha256", "source_identity_sha256", "integration_lock_sha256"):
                if isinstance(value.get(key), str):
                    result.append(value[key])
                    break
            else:
                raise AuditDossierError("evidence reference lacks an exact digest")
        else:
            for key in ("sha256", "receipt_sha256", "provenance_sha256", "decision_sha256", "manifest_sha256", "identity_sha256", "build_identity_sha256", "source_identity_sha256", "integration_lock_sha256"):
                candidate = getattr(value, key, None)
                if isinstance(candidate, str):
                    result.append(candidate)
                    break
            else:
                raise AuditDossierError("evidence reference lacks an exact digest")
    return tuple(sorted(set(result)))


def _validated_refs(kind: str, values: Sequence[Any] | None) -> tuple[str, ...]:
    """Validate typed evidence before reducing it to exact digest references."""

    if not values:
        return ()
    if isinstance(values, Mapping) or hasattr(values, "model_dump"):
        values = (values,)
    checked: list[Any] = []
    for value in values:
        raw = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        if isinstance(raw, Mapping) and raw.get("schema_version"):
            try:
                if kind == "integrity":
                    from arw.integrity import seal_integrity_receipt

                    checked.append(seal_integrity_receipt(raw))
                    continue
                if kind == "provenance":
                    from arw.experiment_provenance import seal_experiment_provenance

                    checked.append(seal_experiment_provenance(raw))
                    continue
                if kind == "access":
                    from arw.evidence_access import seal_evidence_access_decision

                    checked.append(seal_evidence_access_decision(raw))
                    continue
                if kind == "graph":
                    from arw.graph_models import GraphProjectionReceipt

                    receipt = GraphProjectionReceipt.model_validate(raw, strict=True)
                    checked.append(sha256_hex(canonical_json_bytes(receipt.model_dump(mode="json"))))
                    continue
            except Exception as error:
                raise AuditDossierError(f"{kind} evidence is malformed or tampered") from error
        checked.append(value)
    return _coerce_sha_refs(checked)


def assemble_audit_dossier(
    run_root: Path | None = None,
    *,
    replay_state: Any = None,
    run_manifest_sha256: str | None = None,
    generated_at: str | None = None,
    dossier_id: str = "audit-dossier.current",
    ledger_history_sha256: Sequence[str] | None = None,
    run_history: Sequence[Mapping[str, Any] | DossierRunHistory] | None = None,
    evidence: Mapping[str, Sequence[Any]] | None = None,
    claim_capabilities: Sequence[Mapping[str, Any] | DossierClaimCapability] | None = None,
    review: Mapping[str, Any] | None = None,
    graph: Mapping[str, Any] | None = None,
    test_logs: Sequence[Mapping[str, Any] | DossierTestLog] | None = None,
    benchmark_versions: Sequence[Mapping[str, Any] | DossierBenchmarkVersion] | None = None,
    build_identity_sha256: str | None = None,
    source_identity_sha256: Sequence[str] | None = None,
    integration_lock_sha256: str | None = None,
    technical_qualification: Mapping[str, Any] | DossierQualification | None = None,
    release_qualification: Mapping[str, Any] | DossierQualification | None = None,
    blockers: Sequence[Mapping[str, Any] | DossierBlocker] | None = None,
    projection_available: bool | None = None,
) -> AuditDossierManifest:
    """Assemble references after replay; no event, graph, or SQLite writes occur."""

    if replay_state is None and run_root is not None:
        from arw.journal import replay_run

        replay_state = replay_run(run_root)
    if replay_state is None:
        raise AuditDossierError("replay_state or run_root is required")
    run_id = getattr(replay_state, "run_id", None)
    if not isinstance(run_id, str):
        raise AuditDossierError("replay state lacks run_id")
    head = getattr(replay_state, "last_event_sha256", None)
    if not isinstance(head, str):
        raise AuditDossierError("replay state lacks ledger head")
    events = tuple(getattr(replay_state, "events", ()) or ())
    if run_manifest_sha256 is None:
        run_manifest_sha256 = run_manifest_sha256_from_root(run_root) if run_root is not None else None
    if run_manifest_sha256 is None:
        raise AuditDossierError("run_manifest_sha256 is required")
    if generated_at is None:
        generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    history = tuple(run_history or (
        DossierRunHistory(
            sequence=int(getattr(event, "sequence")),
            event_sha256=str(getattr(event, "event_sha256")),
            event_type=str(getattr(event, "event_type")),
            resulting_revision=int(getattr(event, "resulting_revision")),
        ) for event in events
    ))
    ev = evidence or {}
    rev = review or {}
    graph = graph or {}
    local_blockers = list(blockers or ())
    if getattr(replay_state, "recovery_health", "healthy") != "healthy":
        local_blockers.append({
            "code": "canonical_replay_not_healthy",
            "severity": "critical",
            "message": "canonical journal replay is not healthy; dossier is evidence-only until recovery",
            "replacement_evidence": ("canonical-replay-recovery",),
        })
    sequences = tuple(item.sequence for item in history)
    if sequences and sequences != tuple(range(1, len(sequences) + 1)):
        local_blockers.append({
            "code": "canonical_replay_noncontiguous",
            "severity": "critical",
            "message": "canonical replay history is not contiguous",
            "replacement_evidence": ("canonical-replay-recovery",),
        })
    graph_items = graph.get("receipts") or graph.get("receipt")
    if graph_items is not None and not isinstance(graph_items, (tuple, list)):
        graph_items = (graph_items,)
    if graph_items:
        # Validate a graph receipt before retaining its digest.  A graph row or
        # SQLite database without this receipt is never enough for authority.
        _validated_refs("graph", graph_items)
    if projection_available is False or graph.get("status") in {"BLOCKED", "projection_unavailable", "projection_corrupt"}:
        local_blockers.append({"code": "projection_unavailable", "severity": "high", "message": "disposable graph projection is unavailable; canonical replay remains authoritative", "replacement_evidence": ("graph-projection-rebuild",)})
    technical_codes = sorted({item.get("code") for item in local_blockers if isinstance(item, Mapping) and item.get("code") not in {"SUP-04", "P04-09", "CC_BY_NC_PERMISSION_UNRESOLVED"}})
    technical = technical_qualification or ({"verdict": "BLOCKED", "reason_codes": technical_codes, "evidence_sha256": (), "rationale": "one or more replay or projection technical blockers remain"} if technical_codes else {"verdict": "PASS", "reason_codes": (), "evidence_sha256": (), "rationale": "canonical replay and typed evidence were assembled"})
    release = release_qualification or {"verdict": "BLOCKED", "reason_codes": ("CC_BY_NC_PERMISSION_UNRESOLVED", "P04-09", "SUP-04"), "evidence_sha256": (), "rationale": "intended use, distribution, accountable approval, and permission evidence remain unresolved"}
    manifest = {
        "schema_version": AUDIT_DOSSIER_SCHEMA_VERSION,
        "dossier_id": dossier_id,
        "run_id": run_id,
        "generated_at": generated_at,
        "ledger_head_sha256": head,
        "ledger_history_sha256": _coerce_sha_refs(ledger_history_sha256 or tuple(getattr(event, "event_sha256") for event in events)),
        "run_history": history,
        "run_manifest_sha256": run_manifest_sha256,
        "passport_sha256": _coerce_sha_refs(ev.get("passports", ev.get("passport_sha256"))),
        "artifact_manifest_sha256": _coerce_sha_refs(ev.get("artifacts", ev.get("artifact_manifest_sha256"))),
        "integrity_receipt_sha256": _validated_refs("integrity", ev.get("integrity", ev.get("integrity_receipt_sha256"))),
        "experiment_provenance_sha256": _validated_refs("provenance", ev.get("provenance", ev.get("experiment_provenance_sha256"))),
        "access_decisions": _validated_refs("access", ev.get("access", ev.get("access_decisions"))),
        "claim_capabilities": tuple(claim_capabilities or (
            {"capability": capability, "verdict": "BLOCKED", "reason_codes": ("missing_claim_lifecycle_evidence",), "replacement_evidence": ("claim-lifecycle-evidence",)}
            for capability in ("audit_complete", "citation_verified", "experiment_reproduced", "independent_review_complete")
        )),
        "panel_manifest_sha256": rev.get("panel_manifest_sha256"),
        "review_matrix_sha256": rev.get("review_matrix_sha256"),
        "review_report_sha256": _coerce_sha_refs(rev.get("review_report_sha256", rev.get("reports"))),
        "synthesis_sha256": rev.get("synthesis_sha256"),
        "dissent_refs": _coerce_sha_refs(rev.get("dissent_refs", rev.get("dissent"))),
        "human_decision_sha256": _coerce_sha_refs(rev.get("human_decision_sha256", rev.get("human_decisions"))),
        "graph_projection_receipt_sha256": _validated_refs("graph", graph_items) if graph_items else _coerce_sha_refs(graph.get("receipt_sha256")),
        "graph_watermark": graph.get("watermark"),
        "test_logs": tuple(test_logs or ()),
        "benchmark_versions": tuple(benchmark_versions or ()),
        "build_identity_sha256": build_identity_sha256,
        "source_identity_sha256": _coerce_sha_refs(source_identity_sha256),
        "integration_lock_sha256": integration_lock_sha256,
        "technical_qualification": technical,
        "release_qualification": release,
        "blockers": tuple(local_blockers),
    }
    return seal_audit_dossier(manifest)


def run_manifest_sha256_from_root(root: Path) -> str:
    if root is None:
        raise AuditDossierError("run root is required")
    path = root / "run-manifest.json"
    if path.is_symlink() or not path.is_file():
        raise AuditDossierError("run manifest is missing or unsafe")
    return sha256_hex(path.read_bytes())


def replay_audit_dossier(value: Mapping[str, Any] | AuditDossierManifest, *, projection_available: bool = True) -> AuditDossierManifest:
    """Cold-validate a dossier; projection loss adds only an in-memory blocker."""

    dossier = seal_audit_dossier(value)
    if projection_available:
        return dossier
    blockers = list(dossier.blockers)
    if not any(item.code == "projection_unavailable" for item in blockers):
        blockers.append(DossierBlocker(code="projection_unavailable", severity="high", message="disposable graph projection is unavailable; canonical replay remains authoritative", replacement_evidence=("graph-projection-rebuild",)))
    body = dossier.model_dump(mode="json", exclude={"dossier_sha256"})
    body["blockers"] = [item.model_dump(mode="json") if isinstance(item, DossierBlocker) else item for item in blockers]
    return seal_audit_dossier(body)


def generate_audit_dossier_schema_document() -> dict[str, Any]:
    document = AuditDossierManifest.model_json_schema(mode="validation")
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": f"https://academic-research-workbench.local/schemas/v1/{AUDIT_DOSSIER_SCHEMA_NAME}", **document}


def generate_phase6_audit_schema_documents() -> dict[str, dict[str, Any]]:
    return {AUDIT_DOSSIER_SCHEMA_NAME: generate_audit_dossier_schema_document()}


__all__ = [
    "AUDIT_DOSSIER_SCHEMA_NAME", "AUDIT_DOSSIER_SCHEMA_VERSION", "AuditDossierError",
    "AuditDossierManifest", "DossierBenchmarkVersion", "DossierBlocker", "DossierClaimCapability",
    "DossierQualification", "DossierReviewReference", "DossierRunHistory", "DossierTestLog",
    "assemble_audit_dossier", "generate_audit_dossier_schema_document", "generate_phase6_audit_schema_documents",
    "load_audit_dossier", "publish_audit_dossier", "render_audit_dossier_json", "render_audit_dossier_markdown",
    "replay_audit_dossier", "run_manifest_sha256_from_root", "seal_audit_dossier",
]
