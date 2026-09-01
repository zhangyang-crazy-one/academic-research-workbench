"""Port contract tests: adapters satisfy the frozen v2-compat fixtures.

The same golden fixtures that pin the v1 wire behavior are replayed through
the adapter seam, proving the port preserves behavior byte-for-byte.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any

import pytest

from arw.adapters.files import LocalFilesAdapter
from arw.adapters.knowledge import GraphProjectionAdapter
from arw.file_models import (
    FilesContextRequest,
    FilesListRequest,
    FilesOutlineRequest,
    FilesReadRequest,
    FilesSearchRequest,
    LineRange,
    SourceLocation,
)
from arw.files import FilesAdminService
from arw.graph_models import GraphQueryRequest
from arw.graph_store import GraphStore

from .normalize import read_golden_json
from .test_projection_equivalence import _fixture_records

pytestmark = pytest.mark.v2_compat

GOLDEN_MCP = Path(__file__).parent / "golden" / "mcp"


def _adapter_on_seeded_corpus(tmp_path: Path) -> tuple[LocalFilesAdapter, str, dict[str, Any]]:
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
    from arw.files import load_query_generation
    from arw.files_mcp import FilesMcpServer

    generation = load_query_generation(control, "research-root")
    server = FilesMcpServer(generation)
    adapter = LocalFilesAdapter.__new__(LocalFilesAdapter)
    adapter._server = server
    manifest = json.loads(
        (service.generation_path("research-root", generation_id) / "identity-manifest.json")
        .read_text(encoding="utf-8")
    )
    records = {item["relative_path"]: item for item in manifest["records"]}
    return adapter, generation_id, records


def test_file_provider_adapter_satisfies_golden_wire_behavior(tmp_path: Path) -> None:
    """The adapter must reproduce the pinned happy-path envelopes exactly."""
    adapter, generation_id, records = _adapter_on_seeded_corpus(tmp_path)
    golden = read_golden_json(GOLDEN_MCP / "tool_happy_paths.json")
    a_txt = records["notes/a.txt"]
    zh_md = records["notes/中文.md"]

    list_result = adapter.list_files(
        FilesListRequest(
            schema_version="1.0.0", root_id="research-root", max_files=50, cursor=None
        )
    )
    assert list_result.complete_page
    assert list_result.next_cursor is None
    golden_list = golden["2"]["payload"]
    assert [entry["relative_path"] for entry in list_result.model_dump(mode="json")["files"]] == [
        entry["relative_path"] for entry in golden_list["files"]
    ]

    read_result = adapter.read_file(
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
    assert read_result.status == "ok"
    golden_read = golden["3"]["payload"]
    assert read_result.content == golden_read["content"]

    search_result = adapter.search_files(
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
    golden_search = golden["4"]["payload"]
    assert [hit["relative_path"] for hit in search_result.model_dump(mode="json")["hits"]] == [
        hit["relative_path"] for hit in golden_search["hits"]
    ]

    outline = adapter.get_outline(
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
    golden_outline = golden["5"]["payload"]
    assert outline.status == golden_outline["status"]

    context = adapter.get_context(
        FilesContextRequest(
            schema_version="1.0.0",
            root_id="research-root",
            generation_id=generation_id,
            file_id=a_txt["file_id"],
            expected_digest=a_txt["digest"],
            hit_id=None,
            location=SourceLocation(start_byte=6, end_byte=10, start_line=2, end_line=2),
            before_lines=1,
            after_lines=1,
        )
    )
    golden_context = golden["6"]["payload"]
    assert context.status == golden_context["status"]
    assert context.context == golden_context["context"]


def test_knowledge_provider_adapter_matches_projection_oracle(tmp_path: Path) -> None:
    """The graph adapter must satisfy the pinned projection digest and
    delete-and-rebuild equivalence through the port."""
    from arw.graph_projection import project_canonical_records
    from arw.kernel.core.canonical import sha256_hex

    records = _fixture_records()
    projection = project_canonical_records(
        records, ledger_watermark=10, ledger_head_sha256="a" * 64
    )

    golden = read_golden_json(
        Path(__file__).parent / "golden" / "projection" / "projection_digest.json"
    )
    store = GraphStore(tmp_path / "store", "research-root")
    adapter = GraphProjectionAdapter(store)
    receipt = adapter.build_full(projection)
    assert receipt.input_sha256 == sha256_hex(projection.canonical_bytes())
    assert sha256_hex(projection.canonical_bytes()) == golden["projection_sha256"]

    # delete-and-rebuild through the port
    rebuilt = adapter.delete_and_rebuild(projection)
    receipt_golden = read_golden_json(
        Path(__file__).parent / "golden" / "projection" / "rebuild_receipt.json"
    )
    assert rebuilt.input_sha256 == receipt_golden["input_sha256"]


def test_null_knowledge_provider_raises_unavailable() -> None:
    """L0: with no knowledge backend, the port raises a typed fault."""
    from arw.ports.knowledge import KnowledgeUnavailable, NullKnowledgeProvider

    provider = NullKnowledgeProvider()
    with pytest.raises(KnowledgeUnavailable, match="not enabled"):
        provider.query(
            GraphQueryRequest(
                schema_version="1.0.0",
                operation="trace_claim",
                entity_id="claim-004",
                max_depth=1,
                max_rows=10,
            )
        )
