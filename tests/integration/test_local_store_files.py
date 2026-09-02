"""LocalStoreFilesAdapter behavior tests beyond the golden wire fixtures.

Covers the D4-amended search routing (trigram ≥3 chars / LIKE <3 chars),
the substring-divergence trap (pure unicode61 token search would MISS the
"alphabet" → "beta" substring; the trigram bridge must NOT), CJK and
multilingual relevance (task 4.2), dual-adapter parity with the v1
LocalFilesAdapter, and the stale_metadata freshness branch.
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any

import pytest
from arw_ext.local_store import (  # pyright: ignore[reportMissingImports]
    LocalProjectionStore,
    LocalStoreFilesAdapter,
    ingest_files_generation,
)

from arw.adapters.files import FileProviderError, LocalFilesAdapter
from arw.file_models import FilesSearchRequest
from arw.files import FilesAdminService, load_query_generation


def _seed(
    tmp_path: Path,
    corpus: dict[str, str],
) -> tuple[LocalStoreFilesAdapter, LocalFilesAdapter, LocalProjectionStore, str]:
    """Seed one corpus through the v1 admin path, then ingest into the store.

    Returns (store_adapter, v1_adapter, store, root_id) — both adapters point
    at the same canonical content so dual-adapter parity is checkable.
    """

    root = tmp_path / "root"
    for relative_path, content in corpus.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    control = tmp_path / "control"
    sequence = itertools.count(1)
    service = FilesAdminService(
        control,
        id_factory=lambda kind: f"{kind}_test_{next(sequence):03d}",
        clock=lambda: "2026-07-14T00:00:00Z",
    )
    service.register_root(
        root_id="research-root", root_path=root, policy_id="research-files-v1"
    )
    receipt = service.sync("research-root", extractor_version="1.0.0")
    assert receipt.selected_generation_id is not None
    generation = load_query_generation(control, "research-root")

    store = LocalProjectionStore(tmp_path / "arw.db")
    store.open()
    ingest_files_generation(store.connection, generation)
    return (
        LocalStoreFilesAdapter(store),
        LocalFilesAdapter(generation),
        store,
        "research-root",
    )


def _search(adapter: Any, query: str, *, mode: str = "full_text"):
    return adapter.search_files(
        FilesSearchRequest(
            schema_version="1.0.0",
            root_id="research-root",
            mode=mode,  # type: ignore[arg-type]
            query=query,
            max_hits=10,
            max_snippet_bytes=200,
            cursor=None,
        )
    )


def _paths(result: Any) -> list[str]:
    return [hit.relative_path for hit in result.hits]


# ---------------------------------------------------------------------------
# Substring divergence trap (oracle-required)
# ---------------------------------------------------------------------------


def test_trigram_bridge_catches_substring_inside_token(tmp_path: Path) -> None:
    """body="betatest betatest", query="beta" MUST hit.

    A pure unicode61 token index would miss this ("beta" is not a token in
    "betatest"); the trigram bridge preserves the v1 substring semantics.
    """

    store_adapter, _v1, store, _ = _seed(
        tmp_path, {"notes/word.txt": "betatest betatest\n"}
    )
    try:
        result = _search(store_adapter, "beta")
        assert _paths(result) == ["notes/word.txt"]
        assert result.hits[0].score == 2.0
    finally:
        store.close()


# ---------------------------------------------------------------------------
# CJK / multilingual relevance (task 4.2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("中文证据", ["notes/cjk.md"]),  # ≥3-char CJK → trigram
        ("中", ["notes/cjk.md"]),  # single-char → LIKE fallback
        ("证据", ["notes/cjk.md", "notes/mixed.md"]),  # 2-char → LIKE fallback
        ("标题 证据", ["notes/cjk.md"]),  # mixed multi-term AND
        ("beta", ["notes/mixed.md"]),  # Latin term in CJK doc
        ("证据行 beta", ["notes/mixed.md"]),  # CJK+Latin multi-term
        ("不存在词", []),  # no match
    ],
)
def test_cjk_and_mixed_relevance(
    tmp_path: Path, query: str, expected: list[str]
) -> None:
    store_adapter, _v1, store, _ = _seed(
        tmp_path,
        {
            "notes/cjk.md": "# 标题\n\n中文证据行\n",
            "notes/mixed.md": "证据行 beta 混合\n",
        },
    )
    try:
        result = _search(store_adapter, query)
        assert _paths(result) == expected
        assert result.tokenizer_id == "unicode61-cjk-v1"
        assert result.ranking_version == "files-rank-v1"
    finally:
        store.close()


def test_doi_citation_key_and_latex_queries(tmp_path: Path) -> None:
    """DOI / citation-key / LaTeX queries mirror the v1 relevance corpus."""

    store_adapter, _v1, store, _ = _seed(
        tmp_path,
        {
            "refs.bib": "@article{smith2024,\n  doi = {10.1000/xyz123},\n}\n",
            "main.tex": "\\section{Introduction}\nSee \\cite{smith2024}.\n",
        },
    )
    try:
        assert _paths(_search(store_adapter, "10.1000/xyz123")) == ["refs.bib"]
        assert _paths(_search(store_adapter, "smith2024")) == ["main.tex", "refs.bib"]
        assert _paths(_search(store_adapter, "\\section")) == ["main.tex"]
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Dual-adapter parity (oracle-required)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    ["beta", "中文", "中", "标题 证据", "alpha", "证据行 beta"],
)
def test_dual_adapter_parity(tmp_path: Path, query: str) -> None:
    """Same corpus, both adapters, identical results (minus HMAC tokens)."""

    store_adapter, v1_adapter, store, _ = _seed(
        tmp_path,
        {
            "notes/a.txt": "alpha\nbeta\ngamma\n",
            "notes/cjk.md": "# 标题\n\n中文证据行\n",
            "notes/mixed.md": "证据行 beta 混合\n",
        },
    )
    try:
        store_result = _search(store_adapter, query)
        v1_result = _search(v1_adapter, query)

        def _strip(result: Any) -> Any:
            payload = result.model_dump(mode="json")
            for hit in payload["hits"]:
                hit["hit_id"] = None
            payload["next_cursor"] = None
            # generation ids differ by construction (v1 generation vs store
            # projection label); everything else must be identical.
            payload["generation_id"] = None
            return payload

        assert _strip(store_result) == _strip(v1_result)
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Freshness: stale_metadata branch
# ---------------------------------------------------------------------------


def test_stale_file_surfaces_stale_metadata_branch(tmp_path: Path) -> None:
    """Mutating a file after ingest flips its hits to stale_metadata."""

    root_file = tmp_path / "root" / "notes" / "a.txt"
    store_adapter, _v1, store, _ = _seed(
        tmp_path, {"notes/a.txt": "alpha\nbeta\ngamma\n"}
    )
    try:
        # Fresh hit first.
        fresh = _search(store_adapter, "beta")
        assert fresh.hits[0].freshness == "current"
        assert fresh.hits[0].score == 1.0

        # Mutate the file; the indexed digest no longer matches live.
        root_file.write_text("alpha\nbeta CHANGED\ngamma\n", encoding="utf-8")
        stale = _search(store_adapter, "beta")
        assert stale.hits[0].freshness == "stale_metadata"
        assert stale.hits[0].sync_required is True
        assert stale.hits[0].score is None
        assert stale.hits[0].location is None
        assert stale.hits[0].snippet is None
        assert stale.hits[0].hit_id is None
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Adapter-level guards
# ---------------------------------------------------------------------------


def test_uningested_store_raises_typed_fault(tmp_path: Path) -> None:
    store = LocalProjectionStore(tmp_path / "arw.db")
    store.open()
    try:
        with pytest.raises(FileProviderError) as exc_info:
            LocalStoreFilesAdapter(store)
        assert exc_info.value.code == "files_not_ingested"
    finally:
        store.close()


def test_root_denied_for_foreign_root(tmp_path: Path) -> None:
    store_adapter, _v1, store, _ = _seed(tmp_path, {"notes/a.txt": "alpha\n"})
    try:
        request = FilesSearchRequest(
            schema_version="1.0.0",
            root_id="another-root",
            mode="full_text",
            query="alpha",
            max_hits=10,
            max_snippet_bytes=200,
            cursor=None,
        )
        with pytest.raises(FileProviderError) as exc_info:
            store_adapter.search_files(request)
        assert exc_info.value.code == "root_denied"
    finally:
        store.close()
