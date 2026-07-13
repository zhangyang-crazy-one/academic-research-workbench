from __future__ import annotations

import importlib
from collections.abc import Iterator
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


def _record(
    models: ModuleType,
    *,
    file_id: str,
    path: str,
    digest: str,
    fingerprint: str | None,
) -> object:
    return models.FileIdentityRecord.model_validate(
        {
            "file_id": file_id,
            "relative_path": path,
            "file_type": "text",
            "size_bytes": 64,
            "digest": digest,
            "descriptor_fingerprint": fingerprint,
            "identity_evidence": "created",
            "previous_relative_path": None,
        }
    )


def _observation(
    models: ModuleType,
    *,
    path: str,
    digest: str,
    fingerprint: str | None,
) -> object:
    return models.FileObservation.model_validate(
        {
            "relative_path": path,
            "file_type": "text",
            "size_bytes": 64,
            "digest": digest,
            "descriptor_fingerprint": fingerprint,
        }
    )


def _id_factory(values: list[str]) -> object:
    iterator: Iterator[str] = iter(values)
    return lambda: next(iterator)


def test_file_root_and_relative_paths_are_strict_and_normalized() -> None:
    models = _production_module("arw.file_models")
    root = models.FileRoot.model_validate(
        {
            "schema_version": "1.0.0",
            "root_id": "research-root",
            "root_instance_id": "rootinst_fixture_001",
            "policy_id": "research-files-v1",
            "canonical_path": "/workspace/research",
            "created_at": "2026-07-14T00:00:00Z",
        }
    )
    assert root.root_id == "research-root"
    with pytest.raises(ValidationError):
        models.FileRoot.model_validate({**root.model_dump(mode="json"), "extra": True})

    assert models.normalize_relative_path("notes/./paper.md") == "notes/paper.md"
    for unsafe in ("", ".", "../secret", "notes/../secret", "/tmp/secret", "a\\b"):
        with pytest.raises(models.FileContractError):
            models.normalize_relative_path(unsafe)


def test_same_path_and_unambiguous_rename_preserve_logical_identity() -> None:
    models = _production_module("arw.file_models")
    previous = [
        _record(
            models,
            file_id="file_original_001",
            path="papers/original.md",
            digest=_digest("a"),
            fingerprint="dev1:ino1",
        ),
        _record(
            models,
            file_id="file_rename_001",
            path="papers/old-name.md",
            digest=_digest("b"),
            fingerprint="dev1:ino2",
        ),
    ]
    current = [
        _observation(
            models,
            path="papers/original.md",
            digest=_digest("c"),
            fingerprint="dev1:ino1",
        ),
        _observation(
            models,
            path="papers/new-name.md",
            digest=_digest("b"),
            fingerprint="dev1:ino2",
        ),
    ]
    result = models.reconcile_file_identities(
        previous, current, id_factory=_id_factory(["file_unused_001"])
    )
    by_path = {record.relative_path: record for record in result.records}
    assert by_path["papers/original.md"].file_id == "file_original_001"
    assert by_path["papers/original.md"].identity_evidence == "same_path"
    assert by_path["papers/new-name.md"].file_id == "file_rename_001"
    assert by_path["papers/new-name.md"].identity_evidence == "os_identity"
    assert by_path["papers/new-name.md"].previous_relative_path == "papers/old-name.md"
    assert result.deleted_file_ids == []


def test_duplicate_and_ambiguous_rename_candidates_never_merge_identity() -> None:
    models = _production_module("arw.file_models")
    duplicate_digest = _digest("d")
    previous = [
        _record(
            models,
            file_id="file_old_a_001",
            path="old/a.txt",
            digest=duplicate_digest,
            fingerprint=None,
        ),
        _record(
            models,
            file_id="file_old_b_001",
            path="old/b.txt",
            digest=duplicate_digest,
            fingerprint=None,
        ),
    ]
    current = [
        _observation(
            models,
            path="new/a.txt",
            digest=duplicate_digest,
            fingerprint=None,
        ),
        _observation(
            models,
            path="new/b.txt",
            digest=duplicate_digest,
            fingerprint=None,
        ),
    ]
    result = models.reconcile_file_identities(
        previous,
        current,
        id_factory=_id_factory(["file_new_a_001", "file_new_b_001"]),
    )
    assert {record.file_id for record in result.records} == {
        "file_new_a_001",
        "file_new_b_001",
    }
    assert all(record.identity_evidence == "created" for record in result.records)
    assert result.deleted_file_ids == ["file_old_a_001", "file_old_b_001"]
    assert result.ambiguous_digests == [duplicate_digest]


def test_one_to_one_digest_rename_is_allowed_only_when_unique() -> None:
    models = _production_module("arw.file_models")
    previous = [
        _record(
            models,
            file_id="file_unique_001",
            path="old/unique.txt",
            digest=_digest("e"),
            fingerprint=None,
        )
    ]
    current = [
        _observation(
            models,
            path="new/unique.txt",
            digest=_digest("e"),
            fingerprint=None,
        )
    ]
    result = models.reconcile_file_identities(
        previous, current, id_factory=_id_factory(["file_unused_001"])
    )
    assert result.records[0].file_id == "file_unique_001"
    assert result.records[0].identity_evidence == "unique_digest"


def test_read_request_selects_exactly_one_bounded_range() -> None:
    models = _production_module("arw.file_models")
    common = {
        "schema_version": "1.0.0",
        "root_id": "research-root",
        "file_id": "file_fixture_001",
        "relative_path": "documents/paper.md",
        "expected_digest": _digest("a"),
        "cursor": None,
    }
    byte_request = models.FilesReadRequest.model_validate(
        {
            **common,
            "byte_range": {"start": 0, "max_bytes": 1024},
            "line_range": None,
        }
    )
    assert byte_request.byte_range.max_bytes == 1024
    line_request = models.FilesReadRequest.model_validate(
        {
            **common,
            "byte_range": None,
            "line_range": {"start_line": 1, "max_lines": 20},
        }
    )
    assert line_request.line_range.start_line == 1
    with pytest.raises(ValidationError):
        models.FilesReadRequest.model_validate(
            {
                **common,
                "byte_range": {"start": 0, "max_bytes": 1024},
                "line_range": {"start_line": 1, "max_lines": 20},
            }
        )
    with pytest.raises(ValidationError):
        models.FilesReadRequest.model_validate(
            {**common, "byte_range": None, "line_range": None}
        )
    with pytest.raises(ValidationError):
        models.FilesReadRequest.model_validate(
            {
                **common,
                "byte_range": {
                    "start": 0,
                    "max_bytes": models.CONTRACT_LIMITS["read_bytes"] + 1,
                },
                "line_range": None,
            }
        )


def test_search_mode_is_explicit_disjoint_and_rejects_raw_fts_syntax() -> None:
    models = _production_module("arw.file_models")
    common = {
        "schema_version": "1.0.0",
        "root_id": "research-root",
        "max_hits": 10,
        "max_snippet_bytes": 128,
        "cursor": None,
    }
    exact = models.FilesSearchRequest.model_validate(
        {**common, "mode": "exact", "query": "title:literal OR *"}
    )
    assert exact.mode == "exact"
    full_text = models.FilesSearchRequest.model_validate(
        {**common, "mode": "full_text", "query": "证据 chain"}
    )
    assert full_text.mode == "full_text"
    with pytest.raises(ValidationError):
        models.FilesSearchRequest.model_validate(
            {**common, "mode": "full_text", "query": 'title:secret OR "phrase"*'}
        )
    with pytest.raises(ValidationError):
        models.FilesSearchRequest.model_validate(
            {**common, "mode": "combined", "query": "evidence"}
        )


def test_stale_conflict_and_stale_search_metadata_cannot_carry_body_text() -> None:
    models = _production_module("arw.file_models")
    stale_read = {
        "schema_version": "1.0.0",
        "status": "stale_conflict",
        "root_id": "research-root",
        "file_id": "file_fixture_001",
        "relative_path": "documents/paper.md",
        "expected_digest": _digest("a"),
        "current_digest": _digest("b"),
        "error_code": "digest_mismatch",
        "message": "live bytes changed",
    }
    models.FilesReadResult.model_validate(stale_read)
    with pytest.raises(ValidationError):
        models.FilesReadResult.model_validate({**stale_read, "content": "old body"})

    stale_hit = {
        "hit_id": None,
        "file_id": "file_fixture_001",
        "relative_path": "documents/paper.md",
        "file_type": "markdown",
        "indexed_digest": _digest("a"),
        "current_digest": _digest("b"),
        "extraction_registration_sha256": None,
        "freshness": "stale_metadata",
        "sync_required": True,
        "score": None,
        "location": None,
        "snippet": None,
    }
    models.FileSearchHit.model_validate(stale_hit)
    with pytest.raises(ValidationError):
        models.FileSearchHit.model_validate({**stale_hit, "snippet": "old body"})


def test_cursor_is_mac_bound_to_operation_query_generation_and_expiry() -> None:
    contracts = _production_module("arw.file_contracts")
    now = [1_000]
    codec = contracts.CursorCodec(secret=b"s" * 32, clock=lambda: now[0])
    parameters = {"mode": "full_text", "query": "证据", "max_hits": 10}
    token = codec.issue(
        operation="search_files",
        root_id="research-root",
        parameters=parameters,
        generation_id="generation_fixture_001",
        position={"rank": "0.25", "file_id": "file_fixture_001", "offset": 12},
        ttl_seconds=60,
    )
    decoded = codec.decode(
        token,
        operation="search_files",
        root_id="research-root",
        parameters=parameters,
        generation_id="generation_fixture_001",
    )
    assert decoded.position["file_id"] == "file_fixture_001"

    mismatch_cases = [
        ({"operation": "list_files"}, "cursor_operation_mismatch"),
        ({"parameters": {**parameters, "query": "other"}}, "cursor_query_mismatch"),
        ({"generation_id": "generation_fixture_002"}, "cursor_generation_mismatch"),
    ]
    for overrides, code in mismatch_cases:
        expected = {
            "operation": "search_files",
            "root_id": "research-root",
            "parameters": parameters,
            "generation_id": "generation_fixture_001",
            **overrides,
        }
        with pytest.raises(contracts.CursorError) as captured:
            codec.decode(token, **expected)
        assert captured.value.code == code

    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(contracts.CursorError) as captured:
        codec.decode(
            tampered,
            operation="search_files",
            root_id="research-root",
            parameters=parameters,
            generation_id="generation_fixture_001",
        )
    assert captured.value.code == "cursor_tampered"

    now[0] = 1_061
    with pytest.raises(contracts.CursorError) as captured:
        codec.decode(
            token,
            operation="search_files",
            root_id="research-root",
            parameters=parameters,
            generation_id="generation_fixture_001",
        )
    assert captured.value.code == "cursor_expired"


def test_read_cursor_binds_file_digest_and_range_mode() -> None:
    contracts = _production_module("arw.file_contracts")
    codec = contracts.CursorCodec(secret=b"r" * 32, clock=lambda: 2_000)
    token = codec.issue(
        operation="read_file",
        root_id="research-root",
        parameters={"relative_path": "documents/paper.md"},
        file_id="file_fixture_001",
        expected_digest=_digest("a"),
        range_mode="bytes",
        position={"next_byte": 128},
        ttl_seconds=60,
    )
    for field, value, code in (
        ("file_id", "file_fixture_002", "cursor_file_mismatch"),
        ("expected_digest", _digest("b"), "cursor_digest_mismatch"),
        ("range_mode", "lines", "cursor_range_mismatch"),
    ):
        arguments = {
            "operation": "read_file",
            "root_id": "research-root",
            "parameters": {"relative_path": "documents/paper.md"},
            "file_id": "file_fixture_001",
            "expected_digest": _digest("a"),
            "range_mode": "bytes",
            field: value,
        }
        with pytest.raises(contracts.CursorError) as captured:
            codec.decode(token, **arguments)
        assert captured.value.code == code
