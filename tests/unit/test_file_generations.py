from __future__ import annotations

import importlib
from types import ModuleType

import pytest
from pydantic import ValidationError


def _production_module(name: str) -> ModuleType:
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as error:
        if error.name != name:
            raise
        pytest.fail(
            f"expected RED: production contract module {name!r} is not implemented"
        )


def _digest(character: str) -> str:
    return character * 64


def _generation_file(models: ModuleType, *, degraded: bool = False) -> object:
    return models.GenerationFile.model_validate(
        {
            "file_id": "file_degraded_001" if degraded else "file_indexed_001",
            "relative_path": "plain/degraded.txt" if degraded else "documents/paper.md",
            "file_type": "text",
            "size_bytes": 64,
            "source_digest": _digest("b" if degraded else "a"),
            "index_state": "degraded" if degraded else "indexed",
            "degraded_reason": "invalid_utf8" if degraded else None,
            "extraction_registration_sha256": None,
        }
    )


def _manifest(models: ModuleType, *, verdict: str = "degraded") -> object:
    files = [_generation_file(models)]
    issues: list[dict[str, object]] = []
    if verdict == "degraded":
        files.append(_generation_file(models, degraded=True))
    elif verdict == "blocked":
        issues.append(
            {
                "code": "database_digest_mismatch",
                "message": "closed database digest differs from the manifest",
                "file_id": None,
                "relative_path": None,
            }
        )
    return models.FileGenerationManifest.model_validate(
        {
            "schema_version": "1.0.0",
            "generation_id": "generation_fixture_001",
            "root_id": "research-root",
            "root_instance_id": "rootinst_fixture_001",
            "identity_manifest_sha256": _digest("1"),
            "database_sha256": _digest("2"),
            "contract_sha256": _digest("3"),
            "created_at": "2026-07-14T00:00:00Z",
            "closed_at": "2026-07-14T00:00:01Z",
            "source_count": len(files),
            "indexed_count": sum(item.index_state == "indexed" for item in files),
            "degraded_count": sum(item.index_state == "degraded" for item in files),
            "verdict": verdict,
            "files": [item.model_dump(mode="json") for item in reversed(files)],
            "integrity_failures": issues,
            "extraction_registration_sha256": [],
            "tokenizer_id": "unicode61-cjk-v1",
            "ranking_version": "files-rank-v1",
            "parser_versions": {"markdown": "tree-sitter-v1", "plain": "none-v1"},
        }
    )


def _receipt(
    models: ModuleType,
    contracts: ModuleType,
    manifest: object,
    *,
    status: str = "degraded",
) -> object:
    blocked = status == "blocked"
    return models.FileAdminReceipt.model_validate(
        {
            "schema_version": "1.0.0",
            "receipt_id": "receipt_fixture_001",
            "operation": "sync",
            "status": status,
            "root_id": "research-root",
            "attempt_id": "attempt_fixture_001",
            "previous_generation_id": "generation_previous_001",
            "candidate_generation_id": manifest.generation_id,
            "selected_generation_id": (
                "generation_previous_001" if blocked else manifest.generation_id
            ),
            "generation_manifest_sha256": (
                None if blocked else contracts.canonical_file_model_sha256(manifest)
            ),
            "identity_manifest_sha256": _digest("1"),
            "degraded_file_ids": (
                [] if blocked else ["file_degraded_001"]
            ),
            "blocking_reasons": (
                ["database_digest_mismatch"] if blocked else []
            ),
            "started_at": "2026-07-14T00:00:00Z",
            "completed_at": "2026-07-14T00:00:02Z",
        }
    )


def test_extraction_registration_binds_source_text_version_quality_and_access() -> None:
    models = _production_module("arw.file_models")
    contracts = _production_module("arw.file_contracts")
    registration = models.ExtractionRegistration.model_validate(
        {
            "schema_version": "1.0.0",
            "registration_id": "extraction_fixture_pdf_001",
            "source_file_id": "file_fixture_pdf_001",
            "source_digest": _digest("a"),
            "extracted_text_digest": _digest("b"),
            "extractor_name": "fixture-extractor",
            "extractor_version": "1.0.0",
            "extracted_at": "2026-07-14T00:00:00Z",
            "quality_state": "complete",
            "access_state": "accessible",
        }
    )
    assert registration.search_eligible is True
    contracts.validate_extraction_registration(
        registration,
        source_digest=_digest("a"),
        expected_extractor_version="1.0.0",
    )
    with pytest.raises(contracts.FileContractError) as captured:
        contracts.validate_extraction_registration(
            registration,
            source_digest=_digest("a"),
            expected_extractor_version="2.0.0",
        )
    assert captured.value.code == "extractor_version_mismatch"


def test_generation_manifest_counts_and_verdict_are_internally_consistent() -> None:
    models = _production_module("arw.file_models")
    manifest = _manifest(models)
    assert [item.relative_path for item in manifest.files] == sorted(
        item.relative_path for item in manifest.files
    )
    invalid = manifest.model_dump(mode="json")
    invalid["indexed_count"] += 1
    with pytest.raises(ValidationError):
        models.FileGenerationManifest.model_validate(invalid)


def test_generation_failure_taxonomy_keeps_degradation_and_integrity_distinct() -> None:
    contracts = _production_module("arw.file_contracts")
    assert contracts.classify_generation_issue("invalid_utf8") == "degraded"
    assert contracts.classify_generation_issue("extraction_failed") == "degraded"
    assert contracts.classify_generation_issue("descriptor_changed") == "blocking"
    assert contracts.classify_generation_issue("database_digest_mismatch") == "blocking"
    with pytest.raises(contracts.FileContractError) as captured:
        contracts.classify_generation_issue("unknown-failure")
    assert captured.value.code == "unknown_generation_issue"


def test_canonical_generation_and_receipt_bytes_are_order_independent() -> None:
    models = _production_module("arw.file_models")
    contracts = _production_module("arw.file_contracts")
    manifest = _manifest(models)
    reordered = manifest.model_copy(
        update={"files": list(reversed(manifest.files)), "parser_versions": dict(reversed(list(manifest.parser_versions.items())))}
    )
    assert contracts.canonical_file_model_bytes(manifest) == contracts.canonical_file_model_bytes(
        reordered
    )
    receipt = _receipt(models, contracts, manifest)
    assert contracts.canonical_file_model_bytes(receipt).endswith(b"\n")
    assert len(contracts.canonical_file_model_sha256(receipt)) == 64


def test_only_complete_or_degraded_verified_generation_can_be_promoted() -> None:
    models = _production_module("arw.file_models")
    contracts = _production_module("arw.file_contracts")
    manifest = _manifest(models)
    receipt = _receipt(models, contracts, manifest)
    contracts.validate_generation_for_promotion(manifest, receipt)

    blocked_manifest = _manifest(models, verdict="blocked")
    blocked_receipt = _receipt(
        models, contracts, blocked_manifest, status="blocked"
    )
    assert blocked_receipt.selected_generation_id == "generation_previous_001"
    with pytest.raises(contracts.FileContractError) as captured:
        contracts.validate_generation_for_promotion(blocked_manifest, blocked_receipt)
    assert captured.value.code == "generation_integrity_blocked"

