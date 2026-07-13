"""Deterministic helpers shared by files administration and native contracts."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from arw.canonical import canonical_json_bytes
from arw.file_models import (
    CONTRACT_LIMITS,
    RANKING_VERSION,
    TOKENIZER_ID,
    ExtractionRegistration,
    FileAdminReceipt,
    FileContractError,
    FileGenerationManifest,
    FileIdentityManifest,
    FileRoot,
    FilesContextRequest,
    FilesContextResult,
    FilesListRequest,
    FilesListResult,
    FilesOutlineRequest,
    FilesOutlineResult,
    FilesReadRequest,
    FilesReadResult,
    FilesSearchRequest,
    FilesSearchResult,
    StrictFileModel,
)


FILE_SCHEMA_NAMES: tuple[str, ...] = (
    "file-root.schema.json",
    "file-identity-manifest.schema.json",
    "file-generation-manifest.schema.json",
    "extraction-registration.schema.json",
    "file-admin-receipt.schema.json",
    "files-list-request.schema.json",
    "files-list-result.schema.json",
    "files-read-request.schema.json",
    "files-read-result.schema.json",
    "files-search-request.schema.json",
    "files-search-result.schema.json",
    "files-outline-request.schema.json",
    "files-outline-result.schema.json",
    "files-context-request.schema.json",
    "files-context-result.schema.json",
)

_SCHEMA_MODELS: tuple[type[BaseModel], ...] = (
    FileRoot,
    FileIdentityManifest,
    FileGenerationManifest,
    ExtractionRegistration,
    FileAdminReceipt,
    FilesListRequest,
    FilesListResult,
    FilesReadRequest,
    FilesReadResult,
    FilesSearchRequest,
    FilesSearchResult,
    FilesOutlineRequest,
    FilesOutlineResult,
    FilesContextRequest,
    FilesContextResult,
)


class CursorError(FileContractError):
    pass


class CursorEnvelope(StrictFileModel):
    version: int
    operation: str
    root_id: str
    parameters_sha256: str
    generation_id: str | None = None
    file_id: str | None = None
    expected_digest: str | None = None
    range_mode: str | None = None
    position: dict[str, Any]
    issued_at: int
    expires_at: int


def _urlsafe_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _urlsafe_decode(value: str) -> bytes:
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, UnicodeEncodeError) as error:
        raise CursorError("cursor_malformed", "cursor is not canonical base64url") from error
    if _urlsafe_encode(raw) != value:
        raise CursorError("cursor_tampered", "cursor has a non-canonical encoding")
    return raw


class CursorCodec:
    def __init__(self, *, secret: bytes, clock: Callable[[], int | float] = time.time) -> None:
        if len(secret) < 32:
            raise ValueError("cursor secret must contain at least 32 bytes")
        self._secret = bytes(secret)
        self._clock = clock

    def issue(
        self,
        *,
        operation: str,
        root_id: str,
        parameters: Mapping[str, object],
        position: Mapping[str, object],
        ttl_seconds: int,
        generation_id: str | None = None,
        file_id: str | None = None,
        expected_digest: str | None = None,
        range_mode: str | None = None,
    ) -> str:
        if not 1 <= ttl_seconds <= 3_600:
            raise CursorError("cursor_ttl_invalid", "cursor TTL is outside the server ceiling")
        now = int(self._clock())
        envelope = CursorEnvelope(
            version=1,
            operation=operation,
            root_id=root_id,
            parameters_sha256=hashlib.sha256(canonical_json_bytes(dict(parameters))).hexdigest(),
            generation_id=generation_id,
            file_id=file_id,
            expected_digest=expected_digest,
            range_mode=range_mode,
            position=dict(position),
            issued_at=now,
            expires_at=now + ttl_seconds,
        )
        payload = canonical_json_bytes(envelope.model_dump(mode="json"))
        payload_token = _urlsafe_encode(payload)
        signature = _urlsafe_encode(hmac.digest(self._secret, payload, "sha256"))
        token = f"{payload_token}.{signature}"
        if len(token.encode("ascii")) > CONTRACT_LIMITS["cursor_bytes"]:
            raise CursorError("cursor_too_large", "cursor exceeds the server ceiling")
        return token

    def decode(
        self,
        token: str,
        *,
        operation: str,
        root_id: str,
        parameters: Mapping[str, object],
        generation_id: str | None = None,
        file_id: str | None = None,
        expected_digest: str | None = None,
        range_mode: str | None = None,
    ) -> CursorEnvelope:
        if len(token.encode("utf-8")) > CONTRACT_LIMITS["cursor_bytes"]:
            raise CursorError("cursor_too_large", "cursor exceeds the server ceiling")
        try:
            payload_token, signature_token = token.split(".")
        except ValueError as error:
            raise CursorError("cursor_malformed", "cursor must contain payload and signature") from error
        payload = _urlsafe_decode(payload_token)
        signature = _urlsafe_decode(signature_token)
        if not hmac.compare_digest(signature, hmac.digest(self._secret, payload, "sha256")):
            raise CursorError("cursor_tampered", "cursor signature does not match")
        try:
            envelope = CursorEnvelope.model_validate(json.loads(payload))
        except (ValueError, TypeError) as error:
            raise CursorError("cursor_malformed", "cursor payload is invalid") from error

        expected_parameters = hashlib.sha256(canonical_json_bytes(dict(parameters))).hexdigest()
        checks = (
            (envelope.operation == operation, "cursor_operation_mismatch"),
            (envelope.root_id == root_id, "cursor_root_mismatch"),
            (envelope.parameters_sha256 == expected_parameters, "cursor_query_mismatch"),
            (envelope.generation_id == generation_id, "cursor_generation_mismatch"),
            (envelope.file_id == file_id, "cursor_file_mismatch"),
            (envelope.expected_digest == expected_digest, "cursor_digest_mismatch"),
            (envelope.range_mode == range_mode, "cursor_range_mismatch"),
        )
        for valid, code in checks:
            if not valid:
                raise CursorError(code, "cursor is bound to a different request")
        if int(self._clock()) > envelope.expires_at:
            raise CursorError("cursor_expired", "cursor has expired")
        return envelope


def _canonical_model_value(model: BaseModel) -> object:
    value = model.model_dump(mode="json")
    if isinstance(model, FileGenerationManifest):
        value["files"] = sorted(value["files"], key=lambda item: item["relative_path"])
        value["integrity_failures"] = sorted(
            value["integrity_failures"],
            key=lambda item: (item["code"], item.get("file_id") or "", item.get("relative_path") or ""),
        )
        value["extraction_registration_sha256"] = sorted(value["extraction_registration_sha256"])
        value["parser_versions"] = dict(sorted(value["parser_versions"].items()))
    if isinstance(model, FileIdentityManifest):
        value["records"] = sorted(value["records"], key=lambda item: item["relative_path"])
        value["deleted_file_ids"] = sorted(value["deleted_file_ids"])
        value["ambiguous_digests"] = sorted(value["ambiguous_digests"])
    return value


def canonical_file_model_bytes(model: BaseModel) -> bytes:
    return canonical_json_bytes(_canonical_model_value(model))


def canonical_file_model_sha256(model: BaseModel) -> str:
    return hashlib.sha256(canonical_file_model_bytes(model)).hexdigest()


def classify_generation_issue(code: str) -> str:
    degraded = {"invalid_utf8", "unsupported_format", "extraction_failed", "extraction_missing"}
    blocking = {
        "descriptor_changed",
        "root_escape",
        "database_digest_mismatch",
        "database_integrity_failed",
        "manifest_digest_mismatch",
        "schema_invalid",
    }
    if code in degraded:
        return "degraded"
    if code in blocking:
        return "blocking"
    raise FileContractError("unknown_generation_issue", f"unknown generation issue: {code}")


def validate_extraction_registration(
    registration: ExtractionRegistration,
    *,
    source_digest: str,
    expected_extractor_version: str,
) -> None:
    if registration.source_digest != source_digest:
        raise FileContractError("source_digest_mismatch", "registered extraction names different source bytes")
    if registration.extractor_version != expected_extractor_version:
        raise FileContractError("extractor_version_mismatch", "registered extraction uses an obsolete extractor")
    if not registration.search_eligible:
        raise FileContractError("extraction_ineligible", "registered extraction is incomplete or inaccessible")


def validate_generation_for_promotion(
    manifest: FileGenerationManifest,
    receipt: FileAdminReceipt,
) -> None:
    if manifest.verdict == "blocked" or receipt.status == "blocked":
        raise FileContractError("generation_integrity_blocked", "integrity failure prevents promotion")
    if receipt.candidate_generation_id != manifest.generation_id:
        raise FileContractError("generation_id_mismatch", "receipt and manifest name different generations")
    if receipt.generation_manifest_sha256 != canonical_file_model_sha256(manifest):
        raise FileContractError("generation_manifest_digest_mismatch", "receipt does not bind the manifest")
    if receipt.selected_generation_id != manifest.generation_id:
        raise FileContractError("generation_not_selected", "receipt did not select the candidate")


def generate_file_schema_documents() -> dict[str, dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    for name, model in zip(FILE_SCHEMA_NAMES, _SCHEMA_MODELS, strict=True):
        document = model.model_json_schema(mode="validation")
        document = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://arw.local/schemas/v1/{name}",
            **document,
        }
        documents[name] = document
    return documents


def write_file_schema_documents(destination: Path) -> tuple[tuple[str, str], ...]:
    destination.mkdir(parents=True, exist_ok=True)
    written: list[tuple[str, str]] = []
    for name, document in generate_file_schema_documents().items():
        rendered = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        (destination / name).write_bytes(rendered)
        written.append((name, hashlib.sha256(rendered).hexdigest()))
    return tuple(written)
