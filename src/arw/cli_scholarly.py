"""Explicit parent-side commands for citation and PDF evidence proposals."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from uuid import uuid4

from arw.kernel.core.canonical import canonical_json_bytes, strict_json_loads
from arw.kernel.execution.host_dispatch import _blocked_execution_adapter
from arw.kernel.execution.orchestration import OrchestrationService
from arw.kernel.ledger.journal import replay_run
from arw.kernel.ledger.manifests import _safe_directory, _write_once
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.policy.citations import (
    ReferenceRecord,
    ReferenceUse,
    accepted_citation_evidence,
    check_response,
    check_unavailable,
    evaluate_use,
    fetch_response,
    load_check_history,
    publish_check,
)
from arw.kernel.state.models import RuntimeCommandRequest
from arw.kernel.state.orchestration_models import GateDecision
from arw.pdf_extraction import (
    MAX_PDF_BYTES,
    extract_docling_local,
    extract_grobid,
    extract_pdf_from_root,
    pdf_human_review_item,
    register_pdf_extraction,
)


def _read_model(path: Path, model, *, max_bytes: int = 65_536):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
        raise ValueError("unsafe or oversized scholarly input")
    raw = path.read_bytes()
    strict_json_loads(raw)
    return model.model_validate_json(raw)


def _canonical_citation_gate(
    args, reference: ReferenceRecord, use: ReferenceUse
) -> dict[str, object]:
    if args.run_root is None or args.request is None:
        raise ValueError("canonical citation gate requires both run root and request")
    if args.store.resolve(strict=True) != args.run_root.resolve(strict=True):
        raise ValueError("canonical citation store must be the run root")
    request = _read_model(args.request, RuntimeCommandRequest)
    if request.actor_role != "parent_control_plane":
        raise ValueError("canonical citation gate requires parent_control_plane")
    events = replay_run(args.run_root).events
    ref_manifest, use_manifest, accepted = accepted_citation_evidence(
        args.run_root, reference, use, events
    )
    selected = {receipt.receipt_sha256 for _, receipt in accepted}
    if args.receipt and not set(args.receipt).issubset(selected):
        raise ValueError("requested citation receipt is not parent-accepted")
    receipts = tuple(receipt for _, receipt in accepted)
    proposal = evaluate_use(use, reference, receipts, applicable=args.provider)
    disposition = proposal["verdict"]
    verdict = (
        "PASS"
        if disposition == "PASS"
        else "FAIL"
        if disposition == "BLOCK"
        else "BLOCKED"
    )
    evidence = (ref_manifest, use_manifest, *(digest for digest, _ in accepted))
    raw_blockers = proposal.get("open_blocker_receipts", ())
    blocker_list: list[str] = [str(item) for item in raw_blockers] if isinstance(raw_blockers, (list, tuple)) else []
    history = ",".join(blocker_list)
    selected_list: list[str] = sorted(str(s) for s in selected)
    selected_str = ",".join(selected_list)
    rationale = (
        f"citation use={use.use_id} role={use.role} status={proposal['status']} "
        f"disposition={disposition}; accepted_receipts={selected_str}; "
        f"historical_blockers={history}"
    )
    if disposition == "HUMAN_REVIEW":
        rationale += "; human_review_required"
    if len(rationale) > 4096:
        raise ValueError("citation gate rationale exceeds contract limit")
    decision = GateDecision(
        schema_version="arw.gate-decision.v1",
        gate_id="citation." + use_manifest[:24] + "." + request.command_id[-12:],
        subject_sha256=use_manifest,
        evidence_sha256=evidence,
        verdict=verdict,
        rationale=rationale,
        fresh_until=None,
        required=True,
        human_decision=None,
    )

    def prevalidate(_state, replayed):
        try:
            current = accepted_citation_evidence(
                args.run_root, reference, use, replayed.events
            )
            if current != (ref_manifest, use_manifest, accepted):
                return (
                    "citation-evidence-changed",
                    "accepted citation evidence changed before gate append",
                )
        except (ValueError, RuntimeError, OSError) as error:
            return "citation-evidence-invalid", str(error)
        return None

    outcome = OrchestrationService(
        args.run_root, adapter=_blocked_execution_adapter()
    ).evaluate_gate(request, decision, prevalidate=prevalidate)
    return outcome.model_dump(mode="json")


def handle(args) -> dict[str, object]:
    if args.command == "citation":
        reference = _read_model(args.reference, ReferenceRecord)
        if args.citation_action == "check":
            now = args.observed_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            check_id = "check." + uuid4().hex
            if args.response is not None:
                if (
                    args.response.is_symlink()
                    or args.response.stat().st_size > 1_048_576
                ):
                    raise ValueError("unsafe or oversized provider response")
                raw = args.response.read_bytes()
                receipt = check_response(
                    reference,
                    args.provider,
                    raw,
                    observed_at=now,
                    check_id=check_id,
                    batch_id=args.batch_id,
                )
            else:
                try:
                    raw = fetch_response(
                        reference, args.provider, allow_network=args.allow_network
                    )
                except HTTPError as error:
                    raw = error.read(1_048_577)
                    if len(raw) > 1_048_576:
                        raise ValueError(
                            "provider error response exceeds byte limit"
                        ) from error
                    receipt = check_response(
                        reference,
                        args.provider,
                        raw,
                        observed_at=now,
                        http_status=error.code,
                        check_id=check_id,
                        batch_id=args.batch_id,
                    )
                except (OSError, TimeoutError):
                    raw = b""
                    receipt = check_unavailable(
                        reference,
                        args.provider,
                        observed_at=now,
                        error_code="transport_error",
                        check_id=check_id,
                        batch_id=args.batch_id,
                    )
                else:
                    receipt = check_response(
                        reference,
                        args.provider,
                        raw,
                        observed_at=now,
                        check_id=check_id,
                        batch_id=args.batch_id,
                    )
            publish_check(args.store, receipt, raw)
            return {
                "receipt": receipt.model_dump(mode="json"),
                "parent_admission": "required",
            }
        use = _read_model(args.use, ReferenceUse)
        if args.run_root is not None or args.request is not None:
            return _canonical_citation_gate(args, reference, use)
        receipts = load_check_history(args.store, reference)
        if args.receipt and not set(args.receipt).issubset(
            {item.receipt_sha256 for item in receipts}
        ):
            raise ValueError(
                "requested citation receipt is absent from verified history"
            )
        return {
            "gate_proposal": evaluate_use(
                use, reference, receipts, applicable=args.provider
            ),
            "parent_admission": "required",
        }
    if args.provider == "grobid":
        if not args.grobid_endpoint:
            raise ValueError("GROBID requires an explicit loopback endpoint")
        raw = read_retained_bytes(args.root, args.path, max_bytes=MAX_PDF_BYTES)
        extraction, text = extract_grobid(
            raw,
            endpoint=args.grobid_endpoint,
            allow_local_service=args.allow_local_service,
        )
    elif args.provider == "docling":
        if (
            args.docling_artifacts_path is None
            or args.grobid_endpoint
            or args.allow_local_service
        ):
            raise ValueError("Docling requires only an explicit local artifacts path")
        raw = read_retained_bytes(args.root, args.path, max_bytes=MAX_PDF_BYTES)
        extraction, text = extract_docling_local(
            raw, artifacts_path=args.docling_artifacts_path
        )
    else:
        if (
            args.grobid_endpoint
            or args.allow_local_service
            or args.docling_artifacts_path is not None
        ):
            raise ValueError("GROBID options require the grobid provider")
        extraction, text = extract_pdf_from_root(args.root, args.path)
    if args.control_root is not None:
        from arw.composition import files_admin_service

        registered_root = files_admin_service(args.control_root).load_root(args.root_id)
        if args.root.resolve(strict=True) != Path(registered_root.canonical_path):
            raise ValueError("PDF source root differs from registered file root")
    output = _safe_directory(
        args.output_root, ("pdf", extraction.source_sha256), create=True
    )
    text_path = _write_once(output / f"{extraction.extracted_text_sha256}.txt", text)
    document = canonical_json_bytes(extraction.model_dump(mode="json"))
    manifest_path = _write_once(
        output / f"{extraction.extracted_text_sha256}.json", document
    )
    result: dict[str, object] = {
        "extraction": extraction.model_dump(mode="json"),
        "text_path": str(text_path),
        "manifest_path": str(manifest_path),
        "parent_admission": "required",
    }
    review = pdf_human_review_item(extraction)
    if review is not None:
        review_path = _write_once(
            output / f"{extraction.extracted_text_sha256}.review.json",
            canonical_json_bytes(review.model_dump(mode="json")),
        )
        result["human_review"] = review.model_dump(mode="json")
        result["human_review_path"] = str(review_path)
    if args.control_root is not None:
        from arw.composition import files_admin_service

        service = files_admin_service(args.control_root)
        registration = register_pdf_extraction(
            service,
            args.root_id,
            args.file_id,
            args.path,
            extraction,
            text,
            registration_id=args.registration_id,
            extracted_at=args.extracted_at
            or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        result["registration"] = registration.model_dump(
            mode="json", exclude_computed_fields=True
        )
    return result
