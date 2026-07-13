from __future__ import annotations

import hashlib
import itertools
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from arw.file_models import ExtractionRegistration, FilesSearchRequest
from arw.files import FilesAdminService, load_query_generation
from arw.files_mcp import FilesMcpServer


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests/fixtures/files-first"


def _service(control: Path) -> FilesAdminService:
    sequence = itertools.count(1)
    return FilesAdminService(
        control,
        id_factory=lambda kind: f"{kind}_format_{next(sequence):03d}",
        clock=lambda: "2026-07-14T00:00:00Z",
    )


def _prepare(
    tmp_path: Path,
    *,
    register_pdf: bool = True,
    extractor_version: str = "1.0.0",
) -> tuple[Path, Path, FilesAdminService, FilesMcpServer, dict[str, dict[str, Any]]]:
    root = tmp_path / "root"
    shutil.copytree(FIXTURE_ROOT / "root", root)
    control = tmp_path / "control"
    service = _service(control)
    service.register_root(
        root_id="research-root",
        root_path=root,
        policy_id="research-files-v1",
    )
    first = service.sync("research-root", extractor_version=extractor_version)
    first_identity = json.loads(
        (
            service.generation_path("research-root", first.selected_generation_id)
            / "identity-manifest.json"
        ).read_text(encoding="utf-8")
    )
    records = {item["relative_path"]: item for item in first_identity["records"]}
    if register_pdf:
        source = records["pdf/registered-paper.pdf"]
        extracted = FIXTURE_ROOT / "registrations/registered-paper.txt"
        registration = ExtractionRegistration(
            schema_version="1.0.0",
            registration_id="extraction_format_001",
            source_file_id=source["file_id"],
            source_digest=source["digest"],
            extracted_text_digest=hashlib.sha256(extracted.read_bytes()).hexdigest(),
            extractor_name="fixture-extractor",
            extractor_version="1.0.0",
            extracted_at="2026-07-14T00:00:00Z",
            quality_state="complete",
            access_state="accessible",
        )
        service.register_extraction("research-root", registration, extracted)
        receipt = service.sync("research-root", extractor_version=extractor_version)
        identity = json.loads(
            (
                service.generation_path("research-root", receipt.selected_generation_id)
                / "identity-manifest.json"
            ).read_text(encoding="utf-8")
        )
        records = {item["relative_path"]: item for item in identity["records"]}
    generation = load_query_generation(control, "research-root")
    return root, control, service, FilesMcpServer(generation), records


def _request(server: FilesMcpServer, name: str, arguments: dict[str, object]) -> tuple[dict[str, Any], bool]:
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )
    assert response is not None
    result = response["result"]
    payload = json.loads(result["content"][0]["text"])
    assert isinstance(payload, dict)
    return payload, bool(result["isError"])


def _search(
    server: FilesMcpServer,
    query: str,
    *,
    mode: str = "exact",
    max_hits: int = 100,
    cursor: str | None = None,
) -> dict[str, Any]:
    payload, error = _request(
        server,
        "search_files",
        {
            "schema_version": "1.0.0",
            "root_id": "research-root",
            "mode": mode,
            "query": query,
            "max_hits": max_hits,
            "max_snippet_bytes": 256,
            "cursor": cursor,
        },
    )
    assert error is False, payload
    return payload


def _outline(server: FilesMcpServer, record: dict[str, Any]) -> dict[str, Any]:
    payload, error = _request(
        server,
        "get_outline",
        {
            "schema_version": "1.0.0",
            "root_id": "research-root",
            "generation_id": server.generation.selected.generation_id,
            "file_id": record["file_id"],
            "expected_digest": record["digest"],
            "max_nodes": 200,
            "cursor": None,
        },
    )
    assert error is False, payload
    return payload


def test_exact_and_full_text_search_cover_cjk_with_stable_pagination(tmp_path: Path) -> None:
    _, _, _, server, _ = _prepare(tmp_path)

    literal = _search(server, "ARW_MIXED_CJK_V1")
    assert literal["normalized_query"] == "ARW_MIXED_CJK_V1"
    assert [hit["relative_path"] for hit in literal["hits"]] == [
        "multilingual/mixed-cjk.txt"
    ]
    assert literal["hits"][0]["hit_id"]
    assert literal["hits"][0]["snippet"].count("ARW_MIXED_CJK_V1") == 1
    assert _search(server, "arw_mixed_cjk_v1")["hits"] == []

    cjk = _search(server, "证据", mode="full_text")
    assert cjk["normalized_query"] == "证据"
    assert cjk["tokenizer_id"] == "unicode61-cjk-v1"
    assert cjk["ranking_version"] == "files-rank-v1"
    assert "multilingual/chinese.txt" in {
        hit["relative_path"] for hit in cjk["hits"]
    }

    first = _search(server, "evidence", mode="full_text", max_hits=1)
    assert len(first["hits"]) == 1
    assert first["next_cursor"]
    second = _search(
        server,
        "evidence",
        mode="full_text",
        max_hits=1,
        cursor=first["next_cursor"],
    )
    combined = first["hits"] + second["hits"]
    unpaged = _search(server, "evidence", mode="full_text", max_hits=100)["hits"]
    assert combined == unpaged[:2]
    assert all(hit["indexed_digest"] and hit["location"] for hit in combined)

    common = {
        "schema_version": "1.0.0",
        "root_id": "research-root",
        "mode": "full_text",
        "max_hits": 10,
        "max_snippet_bytes": 64,
        "cursor": None,
    }
    with pytest.raises(ValidationError):
        FilesSearchRequest.model_validate(
            {**common, "query": 'title:secret OR "phrase"*'}
        )


def test_stale_search_outline_and_context_never_return_indexed_body(tmp_path: Path) -> None:
    root, _, _, server, records = _prepare(tmp_path)
    indexed = _search(server, "证据", mode="full_text")
    chinese_hit = next(
        hit for hit in indexed["hits"] if hit["relative_path"] == "multilingual/chinese.txt"
    )
    assert chinese_hit["freshness"] == "current"

    (root / "multilingual/chinese.txt").write_text(
        "ARW-TEST-REPLACEMENT-BODY must not leak\n", encoding="utf-8"
    )
    stale = _search(server, "证据", mode="full_text")
    stale_hit = next(
        hit for hit in stale["hits"] if hit["relative_path"] == "multilingual/chinese.txt"
    )
    assert stale_hit["freshness"] == "stale_metadata"
    assert stale_hit["sync_required"] is True
    for field in ("score", "location", "snippet", "hit_id"):
        assert stale_hit[field] is None
    assert "证据" not in json.dumps(stale_hit, ensure_ascii=False)
    assert "REPLACEMENT" not in json.dumps(stale_hit)

    outline = _outline(server, records["multilingual/chinese.txt"])
    assert outline["status"] == "stale_conflict"
    assert outline["nodes"] == []

    context, error = _request(
        server,
        "get_context",
        {
            "schema_version": "1.0.0",
            "root_id": "research-root",
            "generation_id": server.generation.selected.generation_id,
            "file_id": records["multilingual/chinese.txt"]["file_id"],
            "expected_digest": records["multilingual/chinese.txt"]["digest"],
            "hit_id": chinese_hit["hit_id"],
            "location": None,
            "before_lines": 1,
            "after_lines": 1,
        },
    )
    assert error is False
    assert context["status"] == "stale_conflict"
    assert context["context"] is None
    assert "证据" not in json.dumps(context, ensure_ascii=False)


def test_research_formats_have_deterministic_outlines_and_anchored_context(tmp_path: Path) -> None:
    _, _, _, server, records = _prepare(tmp_path)
    expected = {
        "documents/paper.md": [
            (1, "markdown_heading", "Reproducible Evidence"),
            (2, "markdown_heading", "Method"),
            (3, "markdown_heading", "Limits"),
        ],
        "documents/paper.tex": [
            (1, "latex_section", "Files-First Evidence"),
            (2, "latex_subsection", "Freshness"),
        ],
        "source/example.py": [
            (1, "source_function", "bind_claim_to_source"),
            (1, "source_class", "EvidenceIndex"),
        ],
        "references/library.bib": [
            (1, "bibtex_entry", "fixture2026"),
        ],
    }
    for relative_path, golden in expected.items():
        result = _outline(server, records[relative_path])
        assert result["status"] == "ok"
        assert [
            (node["level"], node["kind"], node["title"])
            for node in result["nodes"]
        ] == golden
        starts = [node["location"]["start_byte"] for node in result["nodes"]]
        assert starts == sorted(starts)
        assert result["parser_version"].endswith("-v1")

    for relative_path in ("plain/notes.txt", "pdf/registered-paper.pdf"):
        result = _outline(server, records[relative_path])
        assert result["status"] == "no_structure"
        assert result["nodes"] == []

    hit = _search(server, "stable logical file identity")["hits"][0]
    context, error = _request(
        server,
        "get_context",
        {
            "schema_version": "1.0.0",
            "root_id": "research-root",
            "generation_id": server.generation.selected.generation_id,
            "file_id": hit["file_id"],
            "expected_digest": hit["indexed_digest"],
            "hit_id": hit["hit_id"],
            "location": None,
            "before_lines": 1,
            "after_lines": 1,
        },
    )
    assert error is False, context
    assert context["status"] == "ok"
    assert "stable logical file identity" in context["context"]

    other = records["documents/paper.tex"]
    rebound, rebound_error = _request(
        server,
        "get_context",
        {
            "schema_version": "1.0.0",
            "root_id": "research-root",
            "generation_id": server.generation.selected.generation_id,
            "file_id": other["file_id"],
            "expected_digest": other["digest"],
            "hit_id": hit["hit_id"],
            "location": None,
            "before_lines": 1,
            "after_lines": 1,
        },
    )
    assert rebound_error is True
    assert rebound["error_code"] == "cursor_file_mismatch"


def test_only_complete_version_matched_registered_pdf_text_is_searchable(tmp_path: Path) -> None:
    _, _, service, server, _ = _prepare(tmp_path)
    valid = _search(server, "reproducible PDF evidence")
    pdf_hits = [hit for hit in valid["hits"] if hit["file_type"] == "pdf"]
    assert len(pdf_hits) == 1
    assert pdf_hits[0]["relative_path"] == "pdf/registered-paper.pdf"
    assert pdf_hits[0]["extraction_registration_sha256"]
    serialized = json.dumps(pdf_hits[0])
    assert "ARW-TEST-RAW-PDF" not in serialized

    service.sync("research-root", extractor_version="2.0.0")
    invalidated = FilesMcpServer(load_query_generation(service.control_root, "research-root"))
    assert not [
        hit
        for hit in _search(invalidated, "reproducible PDF evidence")["hits"]
        if hit["file_type"] == "pdf"
    ]
    pdf_file = next(
        item
        for item in invalidated.generation.manifest.files
        if item.relative_path == "pdf/registered-paper.pdf"
    )
    assert pdf_file.index_state == "degraded"
    assert pdf_file.degraded_reason == "extractor_version_mismatch"

    _, _, _, missing, _ = _prepare(tmp_path / "missing", register_pdf=False)
    assert _search(missing, "reproducible PDF evidence")["hits"] == []
