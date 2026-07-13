"""Strict contracts for the files-first control and query planes."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StringConstraints,
    computed_field,
    field_validator,
    model_validator,
)


SCHEMA_VERSION = "1.0.0"
RANKING_VERSION = "files-rank-v1"
TOKENIZER_ID = "unicode61-cjk-v1"
CONTRACT_LIMITS: dict[str, int] = {
    "list_files": 200,
    "read_bytes": 65_536,
    "read_lines": 1_000,
    "search_hits": 100,
    "snippet_bytes": 2_048,
    "outline_nodes": 200,
    "context_lines": 200,
    "query_bytes": 4_096,
    "cursor_bytes": 4_096,
    "timeout_ms": 5_000,
}

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
StableId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9._-]{2,127}$")]
UtcTimestamp = Annotated[
    str,
    StringConstraints(
        pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
    ),
]
FileType = Literal["text", "markdown", "latex", "bibtex", "source", "pdf", "binary"]
Freshness = Literal["live", "current", "stale_metadata", "stale_conflict"]


class FileContractError(ValueError):
    """A stable contract error suitable for CLI and MCP error mapping."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class StrictFileModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


def normalize_relative_path(value: str) -> str:
    if not value or value in {".", ".."} or "\x00" in value or "\\" in value:
        raise FileContractError("invalid_relative_path", "path must be normalized POSIX relative")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise FileContractError("invalid_relative_path", "path must remain below its root")
    normalized = PurePosixPath(*(part for part in path.parts if part != ".")).as_posix()
    if normalized in {"", "."}:
        raise FileContractError("invalid_relative_path", "path must name a file")
    return normalized


class RelativePathMixin:
    @field_validator("relative_path", check_fields=False)
    @classmethod
    def validate_relative_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return normalize_relative_path(value)
        except FileContractError as error:
            raise ValueError(str(error)) from error


class FileRoot(StrictFileModel):
    schema_version: Literal["1.0.0"]
    root_id: StableId
    root_instance_id: StableId
    policy_id: StableId
    canonical_path: Annotated[str, Field(min_length=1, max_length=4096)]
    created_at: UtcTimestamp


class FileObservation(RelativePathMixin, StrictFileModel):
    relative_path: str
    file_type: FileType
    size_bytes: Annotated[int, Field(ge=0)]
    digest: Sha256
    descriptor_fingerprint: Annotated[str, Field(min_length=1, max_length=256)] | None


class FileIdentityRecord(RelativePathMixin, StrictFileModel):
    file_id: StableId
    relative_path: str
    file_type: FileType
    size_bytes: Annotated[int, Field(ge=0)]
    digest: Sha256
    descriptor_fingerprint: Annotated[str, Field(min_length=1, max_length=256)] | None
    identity_evidence: Literal["created", "same_path", "os_identity", "unique_digest"]
    previous_relative_path: str | None

    @field_validator("previous_relative_path")
    @classmethod
    def normalize_previous_path(cls, value: str | None) -> str | None:
        return None if value is None else normalize_relative_path(value)


class IdentityReconciliation(StrictFileModel):
    records: list[FileIdentityRecord]
    deleted_file_ids: list[StableId]
    ambiguous_digests: list[Sha256]


class FileIdentityManifest(StrictFileModel):
    schema_version: Literal["1.0.0"]
    root_id: StableId
    root_instance_id: StableId
    generation_id: StableId
    previous_generation_id: StableId | None
    created_at: UtcTimestamp
    records: list[FileIdentityRecord]
    deleted_file_ids: list[StableId]
    ambiguous_digests: list[Sha256]

    @model_validator(mode="after")
    def canonical_order(self) -> Self:
        object.__setattr__(self, "records", sorted(self.records, key=lambda item: item.relative_path))
        object.__setattr__(self, "deleted_file_ids", sorted(self.deleted_file_ids))
        object.__setattr__(self, "ambiguous_digests", sorted(self.ambiguous_digests))
        if len(self.records) != len({item.file_id for item in self.records}):
            raise ValueError("file IDs must be unique within an identity manifest")
        if len(self.records) != len({item.relative_path for item in self.records}):
            raise ValueError("relative paths must be unique within an identity manifest")
        return self


def reconcile_file_identities(
    previous: Sequence[FileIdentityRecord],
    current: Sequence[FileObservation],
    *,
    id_factory: Callable[[], str],
) -> IdentityReconciliation:
    previous_by_path = {item.relative_path: item for item in previous}
    unmatched_previous = {item.file_id: item for item in previous}
    unmatched_current: dict[str, FileObservation] = {}
    resolved: list[FileIdentityRecord] = []

    def record(observation: FileObservation, file_id: str, evidence: str, old: str | None) -> None:
        resolved.append(
            FileIdentityRecord(
                file_id=file_id,
                relative_path=observation.relative_path,
                file_type=observation.file_type,
                size_bytes=observation.size_bytes,
                digest=observation.digest,
                descriptor_fingerprint=observation.descriptor_fingerprint,
                identity_evidence=evidence,
                previous_relative_path=old,
            )
        )

    for observation in current:
        prior = previous_by_path.get(observation.relative_path)
        if prior is None:
            unmatched_current[observation.relative_path] = observation
            continue
        unmatched_previous.pop(prior.file_id, None)
        record(observation, prior.file_id, "same_path", None)

    prior_by_fingerprint: dict[str, list[FileIdentityRecord]] = defaultdict(list)
    current_by_fingerprint: dict[str, list[FileObservation]] = defaultdict(list)
    for item in unmatched_previous.values():
        if item.descriptor_fingerprint:
            prior_by_fingerprint[item.descriptor_fingerprint].append(item)
    for item in unmatched_current.values():
        if item.descriptor_fingerprint:
            current_by_fingerprint[item.descriptor_fingerprint].append(item)
    for fingerprint in sorted(set(prior_by_fingerprint) & set(current_by_fingerprint)):
        old_group = prior_by_fingerprint[fingerprint]
        new_group = current_by_fingerprint[fingerprint]
        if len(old_group) != 1 or len(new_group) != 1:
            continue
        prior, observation = old_group[0], new_group[0]
        unmatched_previous.pop(prior.file_id, None)
        unmatched_current.pop(observation.relative_path, None)
        record(observation, prior.file_id, "os_identity", prior.relative_path)

    prior_digest_count = Counter(item.digest for item in unmatched_previous.values())
    current_digest_count = Counter(item.digest for item in unmatched_current.values())
    ambiguous = sorted(
        digest
        for digest in set(prior_digest_count) & set(current_digest_count)
        if prior_digest_count[digest] != 1 or current_digest_count[digest] != 1
    )
    prior_by_digest = {item.digest: item for item in unmatched_previous.values() if prior_digest_count[item.digest] == 1}
    for path in sorted(tuple(unmatched_current)):
        observation = unmatched_current[path]
        prior = prior_by_digest.get(observation.digest)
        if prior is None or current_digest_count[observation.digest] != 1:
            continue
        unmatched_previous.pop(prior.file_id, None)
        unmatched_current.pop(path, None)
        record(observation, prior.file_id, "unique_digest", prior.relative_path)

    for path in sorted(unmatched_current):
        record(unmatched_current[path], id_factory(), "created", None)

    return IdentityReconciliation(
        records=sorted(resolved, key=lambda item: item.relative_path),
        deleted_file_ids=sorted(unmatched_previous),
        ambiguous_digests=ambiguous,
    )


class ExtractionRegistration(StrictFileModel):
    schema_version: Literal["1.0.0"]
    registration_id: StableId
    source_file_id: StableId
    source_digest: Sha256
    extracted_text_digest: Sha256
    extractor_name: StableId
    extractor_version: Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][a-z0-9.-]+)?$")]
    extracted_at: UtcTimestamp
    quality_state: Literal["complete", "failed", "malformed"]
    access_state: Literal["accessible", "missing", "denied"]

    @computed_field
    @property
    def search_eligible(self) -> bool:
        return self.quality_state == "complete" and self.access_state == "accessible"


class GenerationFile(RelativePathMixin, StrictFileModel):
    file_id: StableId
    relative_path: str
    file_type: FileType
    size_bytes: Annotated[int, Field(ge=0)]
    source_digest: Sha256
    index_state: Literal["indexed", "degraded", "metadata_only"]
    degraded_reason: StableId | None
    extraction_registration_sha256: Sha256 | None

    @model_validator(mode="after")
    def state_is_coherent(self) -> Self:
        if (self.index_state == "degraded") != (self.degraded_reason is not None):
            raise ValueError("only degraded files carry a degraded reason")
        return self


class GenerationIntegrityFailure(RelativePathMixin, StrictFileModel):
    code: StableId
    message: Annotated[str, Field(min_length=1, max_length=1024)]
    file_id: StableId | None
    relative_path: str | None


class FileGenerationManifest(StrictFileModel):
    schema_version: Literal["1.0.0"]
    generation_id: StableId
    root_id: StableId
    root_instance_id: StableId
    identity_manifest_sha256: Sha256
    database_sha256: Sha256
    contract_sha256: Sha256
    created_at: UtcTimestamp
    closed_at: UtcTimestamp
    source_count: Annotated[int, Field(ge=0)]
    indexed_count: Annotated[int, Field(ge=0)]
    degraded_count: Annotated[int, Field(ge=0)]
    verdict: Literal["complete", "degraded", "blocked"]
    files: list[GenerationFile]
    integrity_failures: list[GenerationIntegrityFailure]
    extraction_registration_sha256: list[Sha256]
    tokenizer_id: StableId
    ranking_version: StableId
    parser_versions: dict[StableId, Annotated[str, Field(min_length=1, max_length=128)]]

    @model_validator(mode="after")
    def close_is_consistent(self) -> Self:
        files = sorted(self.files, key=lambda item: item.relative_path)
        object.__setattr__(self, "files", files)
        object.__setattr__(
            self,
            "integrity_failures",
            sorted(self.integrity_failures, key=lambda item: (item.code, item.file_id or "", item.relative_path or "")),
        )
        object.__setattr__(self, "extraction_registration_sha256", sorted(self.extraction_registration_sha256))
        object.__setattr__(self, "parser_versions", dict(sorted(self.parser_versions.items())))
        if self.source_count != len(files):
            raise ValueError("source_count does not match files")
        if self.indexed_count != sum(item.index_state == "indexed" for item in files):
            raise ValueError("indexed_count does not match files")
        if self.degraded_count != sum(item.index_state == "degraded" for item in files):
            raise ValueError("degraded_count does not match files")
        expected = "blocked" if self.integrity_failures else ("degraded" if self.degraded_count else "complete")
        if self.verdict != expected:
            raise ValueError("generation verdict does not match degradation/integrity state")
        return self


class FileAdminReceipt(StrictFileModel):
    schema_version: Literal["1.0.0"]
    receipt_id: StableId
    operation: Literal["sync", "rebuild", "repair"]
    status: Literal["complete", "degraded", "blocked"]
    root_id: StableId
    attempt_id: StableId
    previous_generation_id: StableId | None
    candidate_generation_id: StableId
    selected_generation_id: StableId | None
    generation_manifest_sha256: Sha256 | None
    identity_manifest_sha256: Sha256 | None
    degraded_file_ids: list[StableId]
    blocking_reasons: list[StableId]
    started_at: UtcTimestamp
    completed_at: UtcTimestamp

    @model_validator(mode="after")
    def result_is_consistent(self) -> Self:
        object.__setattr__(self, "degraded_file_ids", sorted(self.degraded_file_ids))
        object.__setattr__(self, "blocking_reasons", sorted(self.blocking_reasons))
        if self.status == "blocked":
            if not self.blocking_reasons or self.generation_manifest_sha256 is not None:
                raise ValueError("blocked receipts require reasons and cannot attest a generation")
            if self.selected_generation_id != self.previous_generation_id:
                raise ValueError("blocked work must retain the previous generation")
        else:
            if self.blocking_reasons or self.generation_manifest_sha256 is None:
                raise ValueError("promotable receipts require a manifest and no blocking reasons")
            if self.selected_generation_id != self.candidate_generation_id:
                raise ValueError("successful work must select its candidate generation")
        return self


class ByteRange(StrictFileModel):
    start: Annotated[int, Field(ge=0)]
    max_bytes: Annotated[int, Field(ge=1, le=CONTRACT_LIMITS["read_bytes"])]


class LineRange(StrictFileModel):
    start_line: Annotated[int, Field(ge=1)]
    max_lines: Annotated[int, Field(ge=1, le=CONTRACT_LIMITS["read_lines"])]


class FilesListRequest(StrictFileModel):
    schema_version: Literal["1.0.0"]
    root_id: StableId
    max_files: Annotated[int, Field(ge=1, le=CONTRACT_LIMITS["list_files"])] = CONTRACT_LIMITS["list_files"]
    cursor: Annotated[str, Field(min_length=1, max_length=CONTRACT_LIMITS["cursor_bytes"])] | None = None


class FileListEntry(RelativePathMixin, StrictFileModel):
    file_id: StableId
    relative_path: str
    file_type: FileType
    size_bytes: Annotated[int, Field(ge=0)]
    current_digest: Sha256 | None
    indexed_digest: Sha256 | None
    extraction_state: Literal["direct_text", "registered", "degraded", "not_applicable"]
    freshness: Freshness


class FilesListResult(StrictFileModel):
    schema_version: Literal["1.0.0"]
    root_id: StableId
    selected_generation_id: StableId
    files: list[FileListEntry]
    next_cursor: str | None
    complete_page: Literal[True]


class FilesReadRequest(RelativePathMixin, StrictFileModel):
    schema_version: Literal["1.0.0"]
    root_id: StableId
    file_id: StableId
    relative_path: str
    expected_digest: Sha256 | None
    byte_range: ByteRange | None
    line_range: LineRange | None
    cursor: Annotated[str, Field(min_length=1, max_length=CONTRACT_LIMITS["cursor_bytes"])] | None

    @model_validator(mode="after")
    def exactly_one_range(self) -> Self:
        if (self.byte_range is None) == (self.line_range is None):
            raise ValueError("exactly one byte_range or line_range is required")
        return self


class FilesReadSuccess(RelativePathMixin, StrictFileModel):
    schema_version: Literal["1.0.0"]
    status: Literal["ok"]
    root_id: StableId
    file_id: StableId
    relative_path: str
    current_digest: Sha256
    encoding: Literal["bytes", "utf-8"]
    content: str
    truncated: bool
    next_cursor: str | None


class FilesReadStale(RelativePathMixin, StrictFileModel):
    schema_version: Literal["1.0.0"]
    status: Literal["stale_conflict"]
    root_id: StableId
    file_id: StableId
    relative_path: str
    expected_digest: Sha256
    current_digest: Sha256 | None
    error_code: Literal["digest_mismatch", "descriptor_changed", "deleted"]
    message: Annotated[str, Field(min_length=1, max_length=1024)]


class FilesReadDenied(RelativePathMixin, StrictFileModel):
    schema_version: Literal["1.0.0"]
    status: Literal["denied", "encoding_error", "budget_exceeded", "timeout"]
    root_id: StableId
    file_id: StableId | None
    relative_path: str | None
    error_code: StableId
    message: Annotated[str, Field(min_length=1, max_length=1024)]


class FilesReadResult(
    RootModel[Annotated[FilesReadSuccess | FilesReadStale | FilesReadDenied, Field(discriminator="status")]]
):
    pass


class FilesSearchRequest(StrictFileModel):
    schema_version: Literal["1.0.0"]
    root_id: StableId
    mode: Literal["exact", "full_text"]
    query: Annotated[str, Field(min_length=1, max_length=CONTRACT_LIMITS["query_bytes"])]
    max_hits: Annotated[int, Field(ge=1, le=CONTRACT_LIMITS["search_hits"])]
    max_snippet_bytes: Annotated[int, Field(ge=0, le=CONTRACT_LIMITS["snippet_bytes"])]
    cursor: Annotated[str, Field(min_length=1, max_length=CONTRACT_LIMITS["cursor_bytes"])] | None

    @model_validator(mode="after")
    def no_raw_fts_language(self) -> Self:
        if self.mode == "full_text":
            raw_operator = re.compile(r"(?:[:*\"()]|\b(?:AND|OR|NOT|NEAR)\b)", re.IGNORECASE)
            if raw_operator.search(self.query):
                raise ValueError("full_text accepts plain terms, not raw FTS syntax")
        return self


class SourceLocation(StrictFileModel):
    start_byte: Annotated[int, Field(ge=0)]
    end_byte: Annotated[int, Field(ge=0)]
    start_line: Annotated[int, Field(ge=1)] | None = None
    end_line: Annotated[int, Field(ge=1)] | None = None


class FileSearchHit(RelativePathMixin, StrictFileModel):
    file_id: StableId
    relative_path: str
    indexed_digest: Sha256
    current_digest: Sha256 | None
    freshness: Literal["current", "stale_metadata"]
    sync_required: bool
    score: float | None
    location: SourceLocation | None
    snippet: str | None

    @model_validator(mode="after")
    def stale_has_no_body_fields(self) -> Self:
        if self.freshness == "stale_metadata" and (
            self.score is not None or self.location is not None or self.snippet is not None
        ):
            raise ValueError("stale search metadata cannot carry body-derived fields")
        if self.freshness == "current" and self.sync_required:
            raise ValueError("current hits cannot require synchronization")
        return self


class FilesSearchResult(StrictFileModel):
    schema_version: Literal["1.0.0"]
    root_id: StableId
    generation_id: StableId
    mode: Literal["exact", "full_text"]
    normalized_query: str
    tokenizer_id: StableId
    ranking_version: StableId
    hits: list[FileSearchHit]
    next_cursor: str | None
    complete_page: Literal[True]


class FilesOutlineRequest(StrictFileModel):
    schema_version: Literal["1.0.0"]
    root_id: StableId
    generation_id: StableId
    file_id: StableId
    expected_digest: Sha256
    max_nodes: Annotated[int, Field(ge=1, le=CONTRACT_LIMITS["outline_nodes"])]
    cursor: str | None


class OutlineNode(StrictFileModel):
    level: Annotated[int, Field(ge=1, le=16)]
    kind: StableId
    title: Annotated[str, Field(min_length=1, max_length=1024)]
    location: SourceLocation


class FilesOutlineResult(StrictFileModel):
    schema_version: Literal["1.0.0"]
    status: Literal["ok", "no_structure", "stale_conflict", "degraded"]
    root_id: StableId
    generation_id: StableId
    file_id: StableId
    current_digest: Sha256 | None
    parser_version: str | None
    nodes: list[OutlineNode]
    next_cursor: str | None

    @model_validator(mode="after")
    def non_ok_has_no_nodes(self) -> Self:
        if self.status != "ok" and self.nodes:
            raise ValueError("non-ok outlines cannot carry nodes")
        return self


class FilesContextRequest(StrictFileModel):
    schema_version: Literal["1.0.0"]
    root_id: StableId
    generation_id: StableId
    file_id: StableId
    expected_digest: Sha256
    hit_id: StableId | None
    location: SourceLocation | None
    before_lines: Annotated[int, Field(ge=0, le=CONTRACT_LIMITS["context_lines"])]
    after_lines: Annotated[int, Field(ge=0, le=CONTRACT_LIMITS["context_lines"])]

    @model_validator(mode="after")
    def exactly_one_anchor(self) -> Self:
        if (self.hit_id is None) == (self.location is None):
            raise ValueError("exactly one same-file hit or location anchor is required")
        return self


class FilesContextResult(StrictFileModel):
    schema_version: Literal["1.0.0"]
    status: Literal["ok", "stale_conflict", "degraded"]
    root_id: StableId
    generation_id: StableId
    file_id: StableId
    current_digest: Sha256 | None
    location: SourceLocation | None
    context: str | None
    truncated: bool

    @model_validator(mode="after")
    def stale_has_no_context(self) -> Self:
        if self.status != "ok" and (self.location is not None or self.context is not None):
            raise ValueError("non-ok context results cannot carry body-derived fields")
        return self
