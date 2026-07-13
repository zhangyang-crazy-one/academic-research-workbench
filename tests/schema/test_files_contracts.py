from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
from pathlib import Path
from types import ModuleType

import jsonschema
import pytest
from pydantic import ValidationError


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests/fixtures/files-first"
EXPECTED_FILE_SCHEMAS = (
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


def _production_module(name: str) -> ModuleType:
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as error:
        if error.name != name:
            raise
        pytest.fail(
            f"expected RED: production contract module {name!r} is not implemented"
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _root_instance() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "root_id": "research-root",
        "root_instance_id": "rootinst_fixture_001",
        "policy_id": "research-files-v1",
        "canonical_path": "/workspace/research",
        "created_at": "2026-07-14T00:00:00Z",
    }


def _read_request() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "root_id": "research-root",
        "file_id": "file_fixture_001",
        "relative_path": "documents/paper.md",
        "expected_digest": "a" * 64,
        "byte_range": {"start": 0, "max_bytes": 128},
        "line_range": None,
        "cursor": None,
    }


def _stale_read_result() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "status": "stale_conflict",
        "root_id": "research-root",
        "file_id": "file_fixture_001",
        "relative_path": "documents/paper.md",
        "expected_digest": "a" * 64,
        "current_digest": "b" * 64,
        "error_code": "digest_mismatch",
        "message": "the live file no longer matches the expected digest",
    }


def test_files_first_fixture_tree_is_synthetic_complete_and_digest_bound() -> None:
    manifest = json.loads((FIXTURE_ROOT / "fixture-manifest.json").read_text("utf-8"))
    assert manifest["synthetic_only"] is True
    required = {
        "root/multilingual/chinese.txt",
        "root/multilingual/mixed-cjk.txt",
        "root/documents/paper.md",
        "root/documents/paper.tex",
        "root/references/library.bib",
        "root/source/example.py",
        "root/plain/notes.txt",
        "root/duplicates/copy-a.txt",
        "root/duplicates/copy-b.txt",
        "root/rename/unambiguous-old.txt",
        "root/rename/ambiguous-old-a.txt",
        "root/rename/ambiguous-old-b.txt",
        "root/ignored/ignored.txt",
        "root/private/credentials.txt",
        "root/malformed/malformed-utf8.hex",
        "root/pdf/registered-paper.pdf",
        "registrations/registered-paper.txt",
        "registrations/registered-paper.json",
        "canaries.json",
    }
    assert all((FIXTURE_ROOT / relative).is_file() for relative in required)

    duplicate = manifest["duplicate_group"]
    duplicate_digests = {_sha256(FIXTURE_ROOT / path) for path in duplicate["paths"]}
    assert duplicate_digests == {duplicate["sha256"]}
    assert duplicate["expected_identity"] == "distinct-file-ids"

    registration = manifest["registered_extraction"]
    assert _sha256(FIXTURE_ROOT / registration["source_path"]) == registration["source_sha256"]
    assert _sha256(FIXTURE_ROOT / registration["text_path"]) == registration["text_sha256"]
    registered = json.loads(
        (FIXTURE_ROOT / registration["registration_path"]).read_text(encoding="utf-8")
    )
    assert registered["source_digest"] == registration["source_sha256"]
    assert registered["extracted_text_digest"] == registration["text_sha256"]


def test_fixture_malformed_utf8_and_canaries_are_explicit_and_non_private() -> None:
    manifest = json.loads((FIXTURE_ROOT / "fixture-manifest.json").read_text("utf-8"))
    malformed = manifest["malformed_utf8"]
    malformed_bytes = bytes.fromhex((FIXTURE_ROOT / malformed["path"]).read_text().strip())
    assert len(malformed_bytes) == malformed["decoded_size"]
    assert hashlib.sha256(malformed_bytes).hexdigest() == malformed["decoded_sha256"]
    with pytest.raises(UnicodeDecodeError):
        malformed_bytes.decode("utf-8")

    canaries = json.loads((FIXTURE_ROOT / "canaries.json").read_text("utf-8"))["canaries"]
    assert len({item["token"] for item in canaries}) == len(canaries)
    assert all(item["token"].startswith("ARW-TEST-") for item in canaries)
    extracted = (FIXTURE_ROOT / "registrations/registered-paper.txt").read_text("utf-8")
    assert all(item["token"] not in extracted for item in canaries)
    for item in canaries:
        assert item["token"] in (FIXTURE_ROOT / item["path"]).read_text(
            encoding="utf-8", errors="ignore"
        )


def test_later_phase_modules_collect_under_explicit_plan_ownership() -> None:
    ownership = {
        "tests/integration/test_files_admin.py": "Plan 03-02",
        "tests/integration/test_file_generations.py": "Plan 03-02",
        "tests/integration/test_files_mcp.py": "Plan 03-03",
        "tests/integration/test_files_formats.py": "Plan 03-04",
        "tests/integration/test_files_security.py": "Plan 03-05",
    }
    for relative, owner in ownership.items():
        source = (REPOSITORY_ROOT / relative).read_text(encoding="utf-8")
        assert "pytest.mark.skip" in source
        assert owner in source


def test_checked_file_schema_documents_are_generated_strict_and_registered() -> None:
    contracts = _production_module("arw.file_contracts")
    from arw.schema_registry import SCHEMA_NAMES

    assert contracts.FILE_SCHEMA_NAMES == EXPECTED_FILE_SCHEMAS
    generated = contracts.generate_file_schema_documents()
    assert tuple(generated) == EXPECTED_FILE_SCHEMAS
    assert set(EXPECTED_FILE_SCHEMAS) <= set(SCHEMA_NAMES)
    for name, expected in generated.items():
        path = REPOSITORY_ROOT / "schemas/v1" / name
        assert path.is_file(), f"missing checked contract {name}"
        actual = json.loads(path.read_text(encoding="utf-8"))
        assert actual == expected
        assert actual["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert actual["$id"] == f"https://arw.local/schemas/v1/{name}"
        jsonschema.Draft202012Validator.check_schema(actual)


def test_root_model_and_schema_reject_additional_properties_independently() -> None:
    models = _production_module("arw.file_models")
    root = models.FileRoot.model_validate(_root_instance())
    schema = json.loads(
        (REPOSITORY_ROOT / "schemas/v1/file-root.schema.json").read_text(encoding="utf-8")
    )
    validator = jsonschema.Draft202012Validator(schema)
    validator.validate(root.model_dump(mode="json"))
    invalid = {**_root_instance(), "unexpected": True}
    with pytest.raises(ValidationError):
        models.FileRoot.model_validate(invalid)
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(invalid)


def test_read_request_and_no_body_stale_result_match_checked_schemas() -> None:
    models = _production_module("arw.file_models")
    request = models.FilesReadRequest.model_validate(_read_request())
    stale = models.FilesReadResult.model_validate(_stale_read_result())
    request_validator = jsonschema.Draft202012Validator(
        json.loads(
            (REPOSITORY_ROOT / "schemas/v1/files-read-request.schema.json").read_text(
                encoding="utf-8"
            )
        )
    )
    result_validator = jsonschema.Draft202012Validator(
        json.loads(
            (REPOSITORY_ROOT / "schemas/v1/files-read-result.schema.json").read_text(
                encoding="utf-8"
            )
        )
    )
    request_validator.validate(request.model_dump(mode="json"))
    result_validator.validate(stale.model_dump(mode="json"))
    forbidden = {**_stale_read_result(), "content": "stale body"}
    with pytest.raises(ValidationError):
        models.FilesReadResult.model_validate(forbidden)
    with pytest.raises(jsonschema.ValidationError):
        result_validator.validate(forbidden)


def test_file_schema_regeneration_is_byte_stable(tmp_path: Path) -> None:
    contracts = _production_module("arw.file_contracts")
    first = contracts.write_file_schema_documents(tmp_path / "first")
    second = contracts.write_file_schema_documents(tmp_path / "second")
    assert first == second
    for name in EXPECTED_FILE_SCHEMAS:
        assert (tmp_path / "first" / name).read_bytes() == (
            tmp_path / "second" / name
        ).read_bytes()


def test_native_contract_header_is_deterministic_and_checked(tmp_path: Path) -> None:
    script = REPOSITORY_ROOT / "scripts/generate-file-contract-header"
    first = tmp_path / "first.h"
    second = tmp_path / "second.h"
    environment = {**os.environ, "UV_OFFLINE": "1"}
    for destination in (first, second):
        completed = subprocess.run(
            [str(script), "--output", str(destination)],
            cwd=REPOSITORY_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
    assert first.read_bytes() == second.read_bytes()

    check = subprocess.run(
        [str(script), "--check", "--output", str(first)],
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert check.returncode == 0, check.stderr
    first.write_text(first.read_text(encoding="utf-8") + "/* drift */\n", encoding="utf-8")
    drift = subprocess.run(
        [str(script), "--check", "--output", str(first)],
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert drift.returncode != 0
    assert "drift" in drift.stderr.lower()


def test_native_header_binds_tools_limits_modes_and_schema_digests() -> None:
    from arw.file_contracts import FILE_SCHEMA_NAMES
    from arw.file_models import CONTRACT_LIMITS, RANKING_VERSION, TOKENIZER_ID

    header = (REPOSITORY_ROOT / "generated/file-contracts.h").read_text(encoding="utf-8")
    for index, tool in enumerate(
        ("list_files", "read_file", "search_files", "get_outline", "get_context"),
        start=1,
    ):
        assert f'#define ARW_FILES_TOOL_{index} "{tool}"' in header
    assert '#define ARW_FILES_SEARCH_MODE_EXACT "exact"' in header
    assert '#define ARW_FILES_SEARCH_MODE_FULL_TEXT "full_text"' in header
    assert f'#define ARW_FILES_RANKING_VERSION "{RANKING_VERSION}"' in header
    assert f'#define ARW_FILES_TOKENIZER_ID "{TOKENIZER_ID}"' in header
    for key, value in CONTRACT_LIMITS.items():
        macro = key.upper()
        assert f"#define ARW_FILES_LIMIT_{macro} {value}" in header
    for name in FILE_SCHEMA_NAMES:
        digest = _sha256(REPOSITORY_ROOT / "schemas/v1" / name)
        macro = name.removesuffix(".schema.json").replace("-", "_").upper()
        assert f'#define ARW_FILES_SCHEMA_{macro}_SHA256 "{digest}"' in header


def test_native_header_generation_rejects_checked_schema_drift(tmp_path: Path) -> None:
    contracts = _production_module("arw.file_contracts")
    schema_root = tmp_path / "schemas"
    contracts.write_file_schema_documents(schema_root)
    changed = schema_root / "files-list-request.schema.json"
    document = json.loads(changed.read_text(encoding="utf-8"))
    document["title"] = "tampered contract"
    changed.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(contracts.FileContractError) as captured:
        contracts.render_native_contract_header(schema_root)
    assert captured.value.code == "file_schema_drift"
