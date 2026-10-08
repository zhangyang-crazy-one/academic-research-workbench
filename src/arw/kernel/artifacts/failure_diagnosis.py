"""Read-only diagnosis of accepted, frozen failure evidence."""

from __future__ import annotations

import re
from decimal import Decimal, DecimalException
from fractions import Fraction
from pathlib import Path
from typing import Any

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.ledger.journal import JournalError, replay_run
from arw.kernel.ledger.manifests import (
    ManifestError,
    load_artifact_manifest,
    validate_accepted_event_manifests,
)
from arw.kernel.ledger.source_locations import SourceLocatorError, read_retained_bytes
from arw.kernel.state.failure_diagnosis import (
    CanonicalSource,
    FailedAttemptReceipt,
    FailureDiagnosis,
    FailureDiagnosisRequest,
    FailureEditRecord,
    FrozenFailureAcceptance,
    MechanismHypothesis,
    PatternJudgment,
)
from arw.kernel.state.models import StrictModel
from arw.kernel.state.research_memory import MemoryQuery, ResearchMemory

MAX_SOURCE_BYTES = 65_536
_NUMBER = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$")
_MECHANISMS = ("sign_inversion", "unit_mismatch", "sample_mapping")
_STATEMENTS = {
    "sign_inversion": ("A sign is inverted while preserving sample and unit", "A same-unit nonzero sample does not equal the negated expected value"),
    "unit_mismatch": ("A reported unit label differs from the frozen unit", "Every reported unit matches its frozen unit"),
    "sample_mapping": ("A reported case reads a different source sample ID", "Every traced source sample ID equals its reported sample ID"),
}
_PROBES = {
    "sign_inversion": "Trace one nonzero case through the sign operation with its sample ID and unit fixed",
    "unit_mismatch": "Compare one retained raw value in the declared source and target units",
    "sample_mapping": "Trace stable sample IDs through the raw-to-reported join",
}
_OUTCOMES = {
    "sign_inversion": "same sample and unit; numeric value is negated",
    "unit_mismatch": "same sample; numeric scale or unit label changes",
    "sample_mapping": "reported value follows another source sample ID",
}


class FailureDiagnosisError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _number(text: str) -> Fraction:
    if len(text) > 64 or not _NUMBER.fullmatch(text):
        raise FailureDiagnosisError("numeric_out_of_domain", "numeric evidence is outside the bounded domain")
    mantissa, separator, exponent_text = text.lower().partition("e")
    if len(mantissa.lstrip("+-").replace(".", "")) > 64 or (separator and (
        len(exponent_text.lstrip("+-")) > 4 or abs(int(exponent_text)) > 1000
    )):
        raise FailureDiagnosisError("numeric_out_of_domain", "numeric evidence is outside the bounded domain")
    try:
        return Fraction(Decimal(text))
    except (DecimalException, ValueError, OverflowError) as error:
        raise FailureDiagnosisError("numeric_out_of_domain", "numeric evidence cannot be parsed exactly") from error


def _accepted(root: Path, events: tuple[Any, ...], artifact_id: str, *, kind: type[StrictModel]):
    matching = [event for event in events if event.event_type in {"artifact.accepted", "research_artifact_accepted"}
                and event.payload.artifact_id == artifact_id]
    if len(matching) != 1:
        raise FailureDiagnosisError("source_missing_or_ambiguous", "source artifact must have one accepted event")
    event = matching[0]
    try:
        manifest = load_artifact_manifest(root, event.payload.manifest_sha256)
    except (ManifestError, OSError) as error:
        raise FailureDiagnosisError("source_manifest_invalid", "accepted artifact manifest is missing or invalid") from error
    if manifest.artifact_kind != "learning-evidence" or manifest.artifact_id != artifact_id:
        raise FailureDiagnosisError("source_kind_invalid", "diagnosis requires accepted learning-evidence artifacts")
    try:
        raw = read_retained_bytes(root, manifest.content_path, max_bytes=MAX_SOURCE_BYTES)
    except (SourceLocatorError, OSError) as error:
        raise FailureDiagnosisError("source_bytes_invalid", "accepted source bytes are missing or unsafe") from error
    if sha256_hex(raw) != manifest.content_sha256 or manifest.content_sha256 != event.payload.artifact_sha256:
        raise FailureDiagnosisError("source_digest_mismatch", "accepted source bytes differ from event and manifest")
    reference = CanonicalSource(
        event_id=event.event_id, event_sha256=event.event_sha256,
        artifact_id=artifact_id, artifact_sha256=manifest.content_sha256,
    )
    try:
        model = kind.model_validate_json(raw)
    except (ValueError, TypeError) as error:
        raise FailureDiagnosisError("source_contract_invalid", "accepted source does not match its diagnosis contract") from error
    return event, reference, model, raw


def _signature(receipt: FailedAttemptReceipt, acceptance: FrozenFailureAcceptance) -> tuple[tuple[str, str], ...]:
    expected = {case.sample_id: case for case in acceptance.cases}
    observed = {case.sample_id: case for case in receipt.cases}
    if set(expected) != set(observed):
        raise FailureDiagnosisError("sample_set_mismatch", "receipt sample IDs differ from frozen acceptance")
    mismatches = []
    for sample_id in sorted(expected):
        target, actual = expected[sample_id], observed[sample_id]
        if target.unit != actual.unit:
            mismatches.append((sample_id, "unit"))
        if _number(target.expected_value) != _number(actual.value):
            mismatches.append((sample_id, "value"))
        if actual.source_sample_id is not None and actual.source_sample_id != sample_id:
            mismatches.append((sample_id, "source_sample"))
    if not mismatches:
        raise FailureDiagnosisError("false_failed_receipt", "failed receipt does not conflict with frozen acceptance")
    return tuple(mismatches)


def _source_chain(acceptance: CanonicalSource, failures, changes, prior=None) -> str:
    return sha256_hex(canonical_json_bytes({
        "acceptance": acceptance.model_dump(mode="json"),
        "failures": [source.model_dump(mode="json") for source in failures],
        "changes": [source.model_dump(mode="json") for source in changes],
        "prior": None if prior is None else prior.model_dump(mode="json"),
    }))


def _validate_handoff(provider, request: FailureDiagnosisRequest, prior: CanonicalSource, run_id: str) -> None:
    query = MemoryQuery(scope="project", run_id=run_id)
    def read_checked(memory_id: str):
        try:
            response = provider.read(memory_id, query=query)
            document = ResearchMemory.model_validate_json(canonical_json_bytes(response["memory"]))
        except Exception as error:
            raise FailureDiagnosisError("handoff_invalid", "handoff is missing or failed memory integrity verification") from error
        if not document.verify_digest():
            raise FailureDiagnosisError("handoff_invalid", "handoff body digest is invalid")
        return response, document

    _, document = read_checked(request.handoff_memory_id)
    if document.kind != "handoff" or document.run_id != run_id:
        raise FailureDiagnosisError("handoff_invalid", "handoff identity or body is invalid")
    if prior.artifact_id not in document.source_artifact_ids or prior.event_id not in document.source_ledger_event_ids:
        raise FailureDiagnosisError("handoff_source_mismatch", "handoff does not cite the prior diagnosis")
    if not any(link.kind == "artifact" and link.target_id == prior.artifact_id
               and link.sha256 == prior.artifact_sha256 and link.event_id == prior.event_id
               for link in document.links):
        raise FailureDiagnosisError("handoff_source_mismatch", "handoff lacks the exact prior diagnosis link")
    if request.previous_handoff_memory_id is not None:
        previous, earlier = read_checked(request.previous_handoff_memory_id)
        if (
            request.previous_handoff_memory_id not in document.supersedes
            or previous["lifecycle"]["status"] != "superseded"
            or earlier.project_id != document.project_id
            or earlier.run_id != document.run_id
        ):
            raise FailureDiagnosisError("handoff_successor_mismatch", "handoff does not follow its accepted predecessor")


def diagnose_failure(run_root: Path, request: FailureDiagnosisRequest, *, memory_provider=None) -> FailureDiagnosis:
    """Read accepted evidence; return advice without writing a file or running a probe."""

    request = FailureDiagnosisRequest.model_validate_json(request.model_dump_json())
    root = Path(run_root)
    try:
        replayed = replay_run(root)
        validate_accepted_event_manifests(root, replayed.events)
    except (JournalError, ManifestError, OSError) as error:
        raise FailureDiagnosisError("canonical_evidence_invalid", "canonical journal or accepted manifests failed verification") from error
    if replayed.recovery_health != "healthy":
        raise FailureDiagnosisError("journal_unhealthy", "diagnosis requires a healthy canonical journal")
    acceptance_event, acceptance_ref, acceptance, _ = _accepted(
        root, replayed.events, request.acceptance_artifact_id, kind=FrozenFailureAcceptance
    )
    receipts = [_accepted(root, replayed.events, artifact_id, kind=FailedAttemptReceipt)
                for artifact_id in request.failure_artifact_ids]
    edits = [_accepted(root, replayed.events, artifact_id, kind=FailureEditRecord)
             for artifact_id in request.change_artifact_ids]
    failure_refs = tuple(item[1] for item in receipts)
    change_refs = tuple(item[1] for item in edits)
    if [item[0].sequence for item in receipts] != sorted(item[0].sequence for item in receipts):
        raise FailureDiagnosisError("failure_order_invalid", "failed receipts must follow accepted journal order")
    if [item[0].sequence for item in edits] != sorted(item[0].sequence for item in edits):
        raise FailureDiagnosisError("edit_order_invalid", "edit records must follow accepted journal order")
    attempt_ids = [item[2].attempt_id for item in receipts]
    if len(attempt_ids) != len(set(attempt_ids)):
        raise FailureDiagnosisError("duplicate_attempt", "failed receipt attempt IDs must be unique")
    signatures = []
    for event, _, receipt, _ in receipts:
        if event.sequence <= acceptance_event.sequence or receipt.acceptance_sha256 != acceptance_ref.artifact_sha256:
            raise FailureDiagnosisError("stale_acceptance", "acceptance must precede and bind each failed receipt")
        signatures.append(_signature(receipt, acceptance))
    for event, _, edit, _ in edits:
        if event.sequence <= acceptance_event.sequence or edit.attempt_id not in attempt_ids:
            raise FailureDiagnosisError("stale_edit", "edit must belong to an observed attempt after acceptance")
        if edit.predecessor_attempt_id is not None and edit.predecessor_attempt_id not in attempt_ids:
            raise FailureDiagnosisError("stale_edit", "edit predecessor attempt is missing")
    prior_ref = None
    prior_report = None
    chain_id = "failure." + sha256_hex(canonical_json_bytes({
        "run_id": replayed.run_id, "acceptance_sha256": acceptance_ref.artifact_sha256,
    }))[:32]
    if request.prior_diagnosis_artifact_id is not None:
        prior_event, prior_ref, prior_report, prior_raw = _accepted(
            root, replayed.events, request.prior_diagnosis_artifact_id, kind=FailureDiagnosis
        )
        if prior_report.canonical_bytes() != prior_raw:
            raise FailureDiagnosisError("prior_diagnosis_invalid", "prior diagnosis bytes are not canonical")
        if (
            prior_report.run_id != replayed.run_id
            or prior_report.diagnosis_chain_id != chain_id
            or prior_report.acceptance != acceptance_ref
            or prior_report.source_chain_sha256 != _source_chain(
                prior_report.acceptance, prior_report.failed_receipts,
                prior_report.change_records, prior_report.prior_diagnosis,
            )
            or prior_report.failed_receipts != failure_refs[:len(prior_report.failed_receipts)]
            or prior_report.change_records != change_refs[:len(prior_report.change_records)]
            or prior_event.sequence <= receipts[len(prior_report.failed_receipts) - 1][0].sequence
        ):
            raise FailureDiagnosisError("prior_diagnosis_stale", "prior diagnosis does not bind the current accepted chain")
        if request.handoff_memory_id is not None:
            if memory_provider is None:
                raise FailureDiagnosisError("handoff_unavailable", "memory provider is unavailable")
            _validate_handoff(memory_provider, request, prior_ref, replayed.run_id)
    latest = receipts[-1][2]
    target = {case.sample_id: case for case in acceptance.cases}
    observed = {case.sample_id: case for case in latest.cases}
    sign_cases = [
        (_number(target[sample].expected_value), _number(observed[sample].value))
        for sample in sorted(target)
        if target[sample].unit == observed[sample].unit
        and observed[sample].source_sample_id in (None, sample)
        and _number(target[sample].expected_value) != 0
    ]
    sign_status = (
        "ruled_out" if any(actual != -expected for expected, actual in sign_cases)
        else "kept" if len(sign_cases) == len(target)
        else "unresolved"
    )
    unit_status = "kept" if any(target[s].unit != observed[s].unit for s in target) else "ruled_out"
    source_ids = [observed[s].source_sample_id for s in sorted(target)]
    mapping_status = (
        "kept" if any(source is not None and source != sample for sample, source in zip(sorted(target), source_ids))
        else "ruled_out" if all(source == sample for sample, source in zip(sorted(target), source_ids))
        else "unresolved"
    )
    statuses = {"sign_inversion": sign_status, "unit_mismatch": unit_status, "sample_mapping": mapping_status}
    if prior_report is not None:
        for prior_hypothesis in prior_report.hypotheses:
            if prior_hypothesis.status != "ruled_out":
                continue
            current = statuses[prior_hypothesis.mechanism_id]
            if current == "kept":
                raise FailureDiagnosisError("conflicting_successor_evidence", "new evidence conflicts with a prior ruling")
            statuses[prior_hypothesis.mechanism_id] = "ruled_out"
    recurrence = "yes" if len(signatures) > len(set(signatures)) else "unknown"
    reversed_edit = any(
        left.field == right.field and left.before == right.after and left.after == right.before
        for i, (_, _, first, _) in enumerate(edits)
        for _, _, second, _ in edits[i + 1:]
        for left in first.edits for right in second.edits
    )
    patterns = (
        PatternJudgment(kind="recurrence", finding=recurrence,
                        rationale="matching accepted failure signatures" if recurrence == "yes" else "available receipts do not establish recurrence",
                        sources=failure_refs),
        PatternJudgment(kind="opposing_edits", finding="yes" if reversed_edit else "unknown",
                        rationale="reversed before/after edit pair" if reversed_edit else "available edits do not establish opposing changes",
                        sources=change_refs or failure_refs),
        PatternJudgment(kind="expectation_mismatch", finding="yes",
                        rationale="reported cases conflict with the earlier frozen acceptance",
                        sources=(acceptance_ref, *failure_refs)),
    )
    hypotheses = []
    for mechanism in _MECHANISMS:
        status = statuses[mechanism]
        statement, falsifier = _STATEMENTS[mechanism]
        hypotheses.append(MechanismHypothesis.model_validate({
            "mechanism_id": mechanism,
            "statement": statement,
            "falsifier": falsifier,
            "status": status,
            "rationale": (
                "accepted observations are compatible; mechanism remains unproven" if status == "kept"
                else "accepted observations contradict a necessary pattern" if status == "ruled_out"
                else "accepted observations do not expose the needed distinction"
            ),
            "sources": (acceptance_ref, *failure_refs),
            "probe": {"question": _PROBES[mechanism], "expected_outcomes": tuple(
                {"mechanism_id": candidate, "expected_result": _OUTCOMES[candidate]}
                for candidate in _MECHANISMS
            ), "actual_evidence": None},
            "recommend_probe": status != "ruled_out",
        }))
    return FailureDiagnosis(
        schema_version="arw.failure-diagnosis.v1",
        run_id=replayed.run_id,
        diagnosis_chain_id=chain_id,
        acceptance=acceptance_ref,
        failed_receipts=failure_refs,
        change_records=change_refs,
        prior_diagnosis=prior_ref,
        resumed_from_memory_id=request.handoff_memory_id,
        source_chain_sha256=_source_chain(acceptance_ref, failure_refs, change_refs, prior_ref),
        symptom="Accepted failed observations conflict with frozen acceptance",
        patterns=patterns,
        hypotheses=tuple(hypotheses),
        causal_status="unknown",
        execution_effect="read_only_advice",
    )
