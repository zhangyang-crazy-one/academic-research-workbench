"""LocalStoreFilesAdapter vs the pinned v1 golden wire behavior (PR4 task 2.3).

The same seeded corpus + golden envelopes used by
``tests/compat/test_port_adapters.py`` are replayed through the local-store
adapter.  The oracle-required tightening is applied for search: the FULL
envelope is compared byte-for-byte (hit_id scrubbed), not just the
relative_path list.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any

import pytest
from arw_ext.local_store import (  # pyright: ignore[reportMissingImports]
    LocalProjectionStore,
    LocalStoreFilesAdapter,
    ingest_files_generation,
)

from arw.file_models import (
    FilesContextRequest,
    FilesListRequest,
    FilesOutlineRequest,
    FilesReadRequest,
    FilesSearchRequest,
    LineRange,
    SourceLocation,
)
from arw.files import FilesAdminService, load_query_generation

from .normalize import read_golden_json

pytestmark = pytest.mark.v2_compat

GOLDEN_MCP = Path(__file__).parent / "golden" / "mcp"


def _scrub(value: Any) -> Any:
    """Recursively scrub HMAC-signed tokens (hit_id / next_cursor)."""

    if isinstance(value, dict):
        return {k: ("<SCRUBBED>" if k in {"hit_id", "next_cursor"} else _scrub(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value


def _scrub_golden(payload: Any) -> Any:
    """Golden files already scrub hit_id; next_cursor is null in goldens."""

    return _scrub(payload)


def _adapter_on_seeded_corpus(
    tmp_path: Path,
) -> tuple[LocalStoreFilesAdapter, str, dict[str, Any], LocalProjectionStore]:
    root = tmp_path / "root"
    (root / "notes").mkdir(parents=True)
    (root / "notes" / "a.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    (root / "notes" / "中文.md").write_text("# 标题\n\n中文证据行\n", encoding="utf-8")
    (root / "notes" / "binary.txt").write_bytes(b"valid\xffinvalid")
    control = tmp_path / "control"
    sequence = itertools.count(1)
    service = FilesAdminService(
        control,
        id_factory=lambda kind: f"{kind}_test_{next(sequence):03d}",
        clock=lambda: "2026-07-14T00:00:00Z",
    )
    service.register_root(root_id="research-root", root_path=root, policy_id="research-files-v1")
    receipt = service.sync("research-root", extractor_version="1.0.0")
    generation_id = receipt.selected_generation_id
    assert generation_id is not None
    generation = load_query_generation(control, "research-root")

    store = LocalProjectionStore(tmp_path / "arw.db")
    store.open()
    ingested = ingest_files_generation(store.connection, generation)
    assert ingested == 3
    adapter = LocalStoreFilesAdapter(store)

    manifest = json.loads(
        (service.generation_path("research-root", generation_id) / "identity-manifest.json")
        .read_text(encoding="utf-8")
    )
    records = {item["relative_path"]: item for item in manifest["records"]}
    return adapter, generation_id, records, store


def test_list_files_matches_golden(tmp_path: Path) -> None:
    adapter, _generation_id, _records, store = _adapter_on_seeded_corpus(tmp_path)
    try:
        result = adapter.list_files(
            FilesListRequest(
                schema_version="1.0.0", root_id="research-root", max_files=50, cursor=None
            )
        )
        golden = read_golden_json(GOLDEN_MCP / "tool_happy_paths.json")
        assert _scrub(result.model_dump(mode="json")) == _scrub_golden(golden["2"]["payload"])
    finally:
        store.close()


def test_read_file_matches_golden(tmp_path: Path) -> None:
    adapter, _generation_id, records, store = _adapter_on_seeded_corpus(tmp_path)
    try:
        a_txt = records["notes/a.txt"]
        result = adapter.read_file(
            FilesReadRequest(
                schema_version="1.0.0",
                root_id="research-root",
                file_id=a_txt["file_id"],
                relative_path="notes/a.txt",
                expected_digest=None,
                byte_range=None,
                line_range=LineRange(start_line=1, max_lines=10),
                cursor=None,
            )
        )
        golden = read_golden_json(GOLDEN_MCP / "tool_happy_paths.json")
        assert _scrub(result.model_dump(mode="json")) == _scrub_golden(golden["3"]["payload"])
    finally:
        store.close()


def test_search_files_matches_golden_full_envelope(tmp_path: Path) -> None:
    """Oracle-required tightening: full-envelope byte-parity (hit_id scrubbed)."""

    adapter, _generation_id, _records, store = _adapter_on_seeded_corpus(tmp_path)
    try:
        result = adapter.search_files(
            FilesSearchRequest(
                schema_version="1.0.0",
                root_id="research-root",
                mode="full_text",
                query="beta",
                max_hits=10,
                max_snippet_bytes=200,
                cursor=None,
            )
        )
        golden = read_golden_json(GOLDEN_MCP / "tool_happy_paths.json")
        assert _scrub(result.model_dump(mode="json")) == _scrub_golden(golden["4"]["payload"])
    finally:
        store.close()


def test_get_outline_matches_golden(tmp_path: Path) -> None:
    adapter, generation_id, records, store = _adapter_on_seeded_corpus(tmp_path)
    try:
        zh_md = records["notes/中文.md"]
        result = adapter.get_outline(
            FilesOutlineRequest(
                schema_version="1.0.0",
                root_id="research-root",
                generation_id=generation_id,
                file_id=zh_md["file_id"],
                expected_digest=zh_md["digest"],
                max_nodes=50,
                cursor=None,
            )
        )
        golden = read_golden_json(GOLDEN_MCP / "tool_happy_paths.json")
        assert _scrub(result.model_dump(mode="json")) == _scrub_golden(golden["5"]["payload"])
    finally:
        store.close()


def test_get_context_matches_golden(tmp_path: Path) -> None:
    adapter, generation_id, records, store = _adapter_on_seeded_corpus(tmp_path)
    try:
        a_txt = records["notes/a.txt"]
        result = adapter.get_context(
            FilesContextRequest(
                schema_version="1.0.0",
                root_id="research-root",
                generation_id=generation_id,
                file_id=a_txt["file_id"],
                expected_digest=a_txt["digest"],
                hit_id=None,
                location=SourceLocation(
                    start_byte=6, end_byte=10, start_line=2, end_line=2
                ),
                before_lines=5,
                after_lines=5,
            )
        )
        golden = read_golden_json(GOLDEN_MCP / "tool_happy_paths.json")
        assert _scrub(result.model_dump(mode="json")) == _scrub_golden(golden["6"]["payload"])
    finally:
        store.close()
