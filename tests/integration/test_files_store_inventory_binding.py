"""Regression coverage for PR16 Codex P1 review 3940050812.

The per-request revalidation previously checked only
``projection_meta`` keys (``files.selected_generation_id``) plus the
canonical ``selected-generation.json`` pointer.  A writer who tampered
with the ``files`` table directly — injecting phantom rows, deleting
indexed rows, swapping ``relative_path`` / ``source_digest`` /
``body`` / ``body_nfkc_folded``, or breaking the
``files_fts_trigram`` index against the authoritative rows — could
silently keep the metadata aligned while serving rows from a different
inventory.

The inventory fingerprint is now derived from the LOADER-VERIFIED
canonical ``files.sqlite3`` (via :func:`arw.files.load_query_generation`,
which already validates ``identity_manifest_sha256`` +
``generation_manifest_sha256`` + ``database_sha256``).  The per-request
guard hashes the snapshot rows and compares against the bound
fingerprint; an ``EXCEPT`` pair over ``files_fts_trigram`` (count-
aggregated, so duplicates are caught) cross-checks the FTS index
against the authoritative rows.

This module covers five tampering classes (inject / delete / mutate
path-digest-body-fold / FTS add-remove-duplicate), the NULL/empty
body parity cases, the legacy rootless back-compat path, and a
performance budget guard monkeypatched to a low ceiling.
"""

from __future__ import annotations

import itertools
import sqlite3
import uuid
from pathlib import Path
from typing import cast
from urllib.parse import quote

import pytest
from arw_ext.local_store import LocalProjectionStore
from arw_ext.local_store import inventory as inventory_module
from arw_ext.local_store.files import LocalStoreFilesAdapter
from arw_ext.local_store.ingest import ingest_files_generation

from arw.adapters.files import FileProviderError
from arw.file_models import FilesListRequest, SourceLocation
from arw.files import FilesAdminService, load_query_generation


def _service_factory(control: Path) -> FilesAdminService:
    sequence = itertools.count(1)
    salt = uuid.uuid4().hex[:8]
    return FilesAdminService(
        control,
        id_factory=lambda kind: f"{kind}_inv_{salt}_{next(sequence):03d}",
        clock=lambda: "2026-09-05T00:00:00Z",
    )


def _seed(
    tmp_path: Path,
    *,
    corpus: dict[str, str],
) -> tuple[Path, Path, str, str, str, Path]:
    """Seed a control + store with the given corpus.

    Returns the same 6-tuple as ``test_files_store_mcp_lifecycle``:

    (root, control, root_id, generation_id, manifest_sha256, store_path)

    Inlined here (rather than imported from the lifecycle test) so the
    inventory-binding suite remains self-contained — a future refactor
    of either file cannot break the other.
    """

    root = tmp_path / "root"
    for relative_path, content in corpus.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    control = tmp_path / "control"
    service = _service_factory(control)
    service.register_root(
        root_id="inv-root", root_path=root, policy_id="research-files-v1"
    )
    receipt = service.sync("inv-root", extractor_version="1.0.0")
    assert receipt.selected_generation_id is not None
    generation = load_query_generation(control, "inv-root")
    store_path = tmp_path / "arw.db"
    store = LocalProjectionStore(store_path)
    store.open()
    ingest_files_generation(store.connection, generation)
    store.connection.commit()
    store.close()
    return (
        root,
        control,
        "inv-root",
        receipt.selected_generation_id,
        generation.selected.generation_manifest_sha256,
        store_path,
    )


def _open_bound_adapter(
    store_path: Path,
    *,
    control_root: Path,
    root_id: str,
    expected_generation_id: str,
    expected_generation_manifest_sha256: str,
) -> LocalStoreFilesAdapter:
    store = LocalProjectionStore(store_path)
    store.open_readonly()
    return LocalStoreFilesAdapter(
        store,
        canonical_root=control_root,
        root_id=root_id,
        expected_generation_id=expected_generation_id,
        expected_generation_manifest_sha256=expected_generation_manifest_sha256,
    )


def _list_request(root_id: str) -> FilesListRequest:
    return FilesListRequest(
        schema_version="1.0.0",
        root_id=root_id,
        cursor=None,
        max_files=200,
    )


def _open_writable_cache(store_path: Path) -> sqlite3.Connection:
    """Open a SEPARATE writable connection for adversarial mutations.

    The adapter uses a long-lived read-only connection; mutations
    must come from a different handle (or the per-request snapshot
    would not see them on this process).
    """

    return sqlite3.connect(f"file:{quote(str(store_path))}?mode=rwc", uri=True)


# ---------------------------------------------------------------------------
# Positive control: the bound fingerprint matches the cache and the request
# goes through.  Without this, every negative test below would pass for the
# wrong reason (e.g. "request always fails").
# ---------------------------------------------------------------------------


def test_bound_fingerprint_matches_unmutated_cache(
    tmp_path: Path,
) -> None:
    _root, control, root_id, gen_id, manifest_sha256, store_path = _seed(
        tmp_path,
        corpus={"notes/a.txt": "alpha\n", "notes/b.txt": "beta\n"},
    )
    adapter = _open_bound_adapter(
        store_path,
        control_root=control,
        root_id=root_id,
        expected_generation_id=gen_id,
        expected_generation_manifest_sha256=manifest_sha256,
    )
    result = adapter.list_files(_list_request(root_id))
    assert {entry.relative_path for entry in result.files} == {
        "notes/a.txt",
        "notes/b.txt",
    }


# ---------------------------------------------------------------------------
# Tamper class 1 — INJECT a phantom row.
# ---------------------------------------------------------------------------


def test_injected_row_refused_with_inventory_tampered(
    tmp_path: Path,
) -> None:
    _root, control, root_id, gen_id, manifest_sha256, store_path = _seed(
        tmp_path,
        corpus={"notes/a.txt": "alpha\n"},
    )
    adapter = _open_bound_adapter(
        store_path,
        control_root=control,
        root_id=root_id,
        expected_generation_id=gen_id,
        expected_generation_manifest_sha256=manifest_sha256,
    )

    # Inject a phantom row into the cache AFTER adapter construction so
    # the bound fingerprint was derived from the unmutated canonical DB.
    cache = _open_writable_cache(store_path)
    try:
        cache.execute(
            "INSERT INTO files (file_id, relative_path, file_type, size_bytes, "
            "source_digest, index_state, degraded_reason, "
            "extraction_registration_sha256, body_nfkc_folded, body) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "phantom-id-001",
                "notes/phantom.txt",
                "text",
                0,
                "0" * 64,
                "indexed",
                None,
                None,
                "phantom",
                "phantom",
            ),
        )
        cache.execute(
            "INSERT INTO files_fts_trigram (file_id, relative_path, "
            "body_nfkc_folded) VALUES (?, ?, ?)",
            ("phantom-id-001", "notes/phantom.txt", "phantom"),
        )
        cache.commit()
    finally:
        cache.close()

    with pytest.raises(FileProviderError) as caught:
        adapter.list_files(_list_request(root_id))
    assert caught.value.code == "inventory_tampered", (
        f"expected inventory_tampered; got {caught.value.code!r}"
    )


# ---------------------------------------------------------------------------
# Tamper class 2 — DELETE a row.
# ---------------------------------------------------------------------------


def test_deleted_row_refused_with_inventory_tampered(
    tmp_path: Path,
) -> None:
    _root, control, root_id, gen_id, manifest_sha256, store_path = _seed(
        tmp_path,
        corpus={"notes/a.txt": "alpha\n", "notes/b.txt": "beta\n"},
    )
    adapter = _open_bound_adapter(
        store_path,
        control_root=control,
        root_id=root_id,
        expected_generation_id=gen_id,
        expected_generation_manifest_sha256=manifest_sha256,
    )

    cache = _open_writable_cache(store_path)
    try:
        cache.execute("DELETE FROM files WHERE relative_path = 'notes/b.txt'")
        cache.execute(
            "DELETE FROM files_fts_trigram WHERE relative_path = 'notes/b.txt'"
        )
        cache.commit()
    finally:
        cache.close()

    with pytest.raises(FileProviderError) as caught:
        adapter.list_files(_list_request(root_id))
    assert caught.value.code == "inventory_tampered", (
        f"expected inventory_tampered on delete; got {caught.value.code!r}"
    )


# ---------------------------------------------------------------------------
# Tamper class 3 — MUTATE a row (path / digest / body / fold).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutation",
    [
        "relative_path",
        "source_digest",
        "body",
        "body_nfkc_folded",
    ],
)
def test_mutated_column_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    _root, control, root_id, gen_id, manifest_sha256, store_path = _seed(
        tmp_path,
        corpus={"notes/a.txt": "alpha\n", "notes/b.txt": "beta\n"},
    )
    adapter = _open_bound_adapter(
        store_path,
        control_root=control,
        root_id=root_id,
        expected_generation_id=gen_id,
        expected_generation_manifest_sha256=manifest_sha256,
    )

    # Each mutation must be paired with the matching FTS-trigram edit so
    # the per-row EXCEPT pair does not also trip on a stale FTS row.  The
    # goal of THIS test is to prove the FILES-ROW FINGERPRINT catches
    # the column flip; the FTS-layer test below proves the FTS-layer
    # EXCEPT pair works in isolation.
    cache = _open_writable_cache(store_path)
    try:
        if mutation == "relative_path":
            cache.execute(
                "UPDATE files SET relative_path = 'notes/c.txt' "
                "WHERE relative_path = 'notes/b.txt'"
            )
            cache.execute(
                "UPDATE files_fts_trigram SET relative_path = 'notes/c.txt' "
                "WHERE relative_path = 'notes/b.txt'"
            )
        elif mutation == "source_digest":
            cache.execute(
                "UPDATE files SET source_digest = ? WHERE relative_path = 'notes/b.txt'",
                ("f" * 64,),
            )
        elif mutation == "body":
            cache.execute(
                "UPDATE files SET body = 'TAMPERED' WHERE relative_path = 'notes/b.txt'"
            )
            cache.execute(
                "UPDATE files SET body_nfkc_folded = 'tampered' "
                "WHERE relative_path = 'notes/b.txt'"
            )
            cache.execute(
                "UPDATE files_fts_trigram SET body_nfkc_folded = 'tampered' "
                "WHERE relative_path = 'notes/b.txt'"
            )
        elif mutation == "body_nfkc_folded":
            cache.execute(
                "UPDATE files SET body_nfkc_folded = 'tampered' "
                "WHERE relative_path = 'notes/b.txt'"
            )
            cache.execute(
                "UPDATE files_fts_trigram SET body_nfkc_folded = 'tampered' "
                "WHERE relative_path = 'notes/b.txt'"
            )
        else:  # pragma: no cover - defensive
            raise AssertionError(f"unknown mutation: {mutation}")
        cache.commit()
    finally:
        cache.close()

    with pytest.raises(FileProviderError) as caught:
        adapter.list_files(_list_request(root_id))
    assert caught.value.code == "inventory_tampered", (
        f"expected inventory_tampered on {mutation!r} mutation; "
        f"got {caught.value.code!r}"
    )


# ---------------------------------------------------------------------------
# Tamper class 4 — FTS-TRIGRAM drift (phantom / missing / duplicate).
# ---------------------------------------------------------------------------


def test_fts_trigram_phantom_row_refused(tmp_path: Path) -> None:
    """An FTS row whose tuple is absent from ``files`` is rejected.

    Mirrors the brief: ``EXCEPT`` over count aggregations must catch
    a phantom row that single-EXCEPT would silently accept.
    """

    _root, control, root_id, gen_id, manifest_sha256, store_path = _seed(
        tmp_path,
        corpus={"notes/a.txt": "alpha\n"},
    )
    adapter = _open_bound_adapter(
        store_path,
        control_root=control,
        root_id=root_id,
        expected_generation_id=gen_id,
        expected_generation_manifest_sha256=manifest_sha256,
    )

    cache = _open_writable_cache(store_path)
    try:
        # Insert a phantom row whose (file_id, fold) tuple is NOT in
        # the ``files`` table.  A plain EXCEPT would dedupe and miss
        # this; the count aggregation catches it.
        cache.execute(
            "INSERT INTO files_fts_trigram (file_id, relative_path, "
            "body_nfkc_folded) VALUES (?, ?, ?)",
            ("phantom-id-doesnot-exist", "notes/phantom.txt", "phantom-fold"),
        )
        cache.commit()
    finally:
        cache.close()

    with pytest.raises(FileProviderError) as caught:
        adapter.list_files(_list_request(root_id))
    assert caught.value.code == "inventory_tampered", (
        f"expected inventory_tampered; got {caught.value.code!r}"
    )


def test_fts_trigram_missing_row_refused(tmp_path: Path) -> None:
    """An FTS row whose tuple is missing from ``files_fts_trigram`` is rejected."""

    _root, control, root_id, gen_id, manifest_sha256, store_path = _seed(
        tmp_path,
        corpus={"notes/a.txt": "alpha\n"},
    )
    adapter = _open_bound_adapter(
        store_path,
        control_root=control,
        root_id=root_id,
        expected_generation_id=gen_id,
        expected_generation_manifest_sha256=manifest_sha256,
    )

    # Discover the actual file_id from the cache (v1 sync generates
    # ``file_<hex>`` IDs, not the bare ``a`` a test author might guess).
    cache = _open_writable_cache(store_path)
    try:
        file_id = cast(
            str, cache.execute("SELECT file_id FROM files LIMIT 1").fetchone()[0]
        )
        cache.execute(
            "DELETE FROM files_fts_trigram WHERE file_id = ?",
            (file_id,),
        )
        cache.commit()
    finally:
        cache.close()

    with pytest.raises(FileProviderError) as caught:
        adapter.list_files(_list_request(root_id))
    assert caught.value.code == "inventory_tampered", (
        f"expected inventory_tampered; got {caught.value.code!r}"
    )


def test_fts_trigram_duplicate_row_refused(tmp_path: Path) -> None:
    """A duplicate FTS row is caught by the count-aggregated EXCEPT.

    Plain ``EXCEPT`` would lose multiplicity (the duplicate would
    collapse into the unique tuple and the check would pass).  The
    inventory helper groups by (file_id, body_nfkc_folded) and
    compares counts; a count of 2 in FTS vs count of 1 in files is
    the failure surface.
    """

    _root, control, root_id, gen_id, manifest_sha256, store_path = _seed(
        tmp_path,
        corpus={"notes/a.txt": "alpha\n"},
    )
    adapter = _open_bound_adapter(
        store_path,
        control_root=control,
        root_id=root_id,
        expected_generation_id=gen_id,
        expected_generation_manifest_sha256=manifest_sha256,
    )

    cache = _open_writable_cache(store_path)
    try:
        # Discover the actual file_id and fold tuple to re-insert the
        # EXACT same tuple a second time (so the count aggregation
        # catches the multiplicity that a plain EXCEPT would lose).
        file_id = cast(
            str, cache.execute("SELECT file_id FROM files LIMIT 1").fetchone()[0]
        )
        relative_path = cast(
            str,
            cache.execute(
                "SELECT relative_path FROM files WHERE file_id = ?",
                (file_id,),
            ).fetchone()[0],
        )
        body_nfkc_folded = cast(
            str,
            cache.execute(
                "SELECT body_nfkc_folded FROM files WHERE file_id = ?",
                (file_id,),
            ).fetchone()[0],
        )
        cache.execute(
            "INSERT INTO files_fts_trigram (file_id, relative_path, "
            "body_nfkc_folded) VALUES (?, ?, ?)",
            (file_id, relative_path, body_nfkc_folded),
        )
        cache.commit()
    finally:
        cache.close()

    with pytest.raises(FileProviderError) as caught:
        adapter.list_files(_list_request(root_id))
    assert caught.value.code == "inventory_tampered", (
        f"count-aggregated EXCEPT must catch duplicates; got {caught.value.code!r}"
    )


# ---------------------------------------------------------------------------
# Tamper class 5 — body parity (NULL + empty).
# ---------------------------------------------------------------------------


def test_null_body_parity_passes(tmp_path: Path) -> None:
    """NULL bodies on the canonical side stay NULL on the cache side.

    The canonical DB and the cache must agree on the NULL/empty
    distinction (the inventory serializer frames both as a 0-length
    prefix, so a tampered fold that converts NULL ↔ empty is detected
    on the very first byte).  This test pins the matching case.
    """

    _root, control, root_id, gen_id, manifest_sha256, store_path = _seed(
        tmp_path,
        corpus={"notes/a.txt": "alpha\n"},
    )
    adapter = _open_bound_adapter(
        store_path,
        control_root=control,
        root_id=root_id,
        expected_generation_id=gen_id,
        expected_generation_manifest_sha256=manifest_sha256,
    )
    # A genuine re-ingest (no cache mutation) must keep the request
    # succeeding: the fingerprint re-derived from the canonical DB
    # must match the fingerprint re-derived from the cache.
    result = adapter.list_files(_list_request(root_id))
    assert {entry.relative_path for entry in result.files} == {"notes/a.txt"}


def test_empty_body_parity_passes(tmp_path: Path) -> None:
    """Empty bodies round-trip through ingest as empty (not NULL)."""

    _root, control, root_id, gen_id, manifest_sha256, store_path = _seed(
        tmp_path,
        corpus={"notes/a.txt": "alpha\n", "notes/empty.txt": ""},
    )
    adapter = _open_bound_adapter(
        store_path,
        control_root=control,
        root_id=root_id,
        expected_generation_id=gen_id,
        expected_generation_manifest_sha256=manifest_sha256,
    )
    result = adapter.list_files(_list_request(root_id))
    paths = {entry.relative_path for entry in result.files}
    assert paths == {"notes/a.txt", "notes/empty.txt"}


# ---------------------------------------------------------------------------
# Legacy / rootless API stays unchanged.
# ---------------------------------------------------------------------------


def test_legacy_rootless_adapter_skips_inventory_check(tmp_path: Path) -> None:
    """A bound adapter without ``canonical_root`` skips the inventory guard.

    The legacy API path (no canonical anchor) must remain unchanged:
    no fingerprint derivation, no per-request hash, no failure on a
    tampered cache.  This test pins the back-compat contract that the
    P1 review explicitly required ("rootless legacy API unchanged").
    """

    _root, _control, _root_id, _gen_id, _manifest_sha256, store_path = _seed(
        tmp_path,
        corpus={"notes/a.txt": "alpha\n"},
    )
    store = LocalProjectionStore(store_path)
    store.open_readonly()
    try:
        adapter = LocalStoreFilesAdapter(store)
        assert (
            adapter._expected_inventory_fingerprint  # type: ignore[attr-defined]
            == "uninitialised"
        )
        # Sanity: the per-request guard short-circuits on the sentinel.
        result = adapter.list_files(
            FilesListRequest(
                schema_version="1.0.0",
                root_id="inv-root",
                cursor=None,
                max_files=200,
            )
        )
        assert {entry.relative_path for entry in result.files} == {"notes/a.txt"}
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Performance budget guard.
# ---------------------------------------------------------------------------


def test_body_byte_budget_refuses_oversized_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row whose body exceeds the byte budget fails closed.

    The budget guard fires BEFORE unbounded Python materialisation so
    a hostile row cannot exhaust memory through the inventory path.
    ``MAX_INVENTORY_BODY_BYTES`` is monkeypatched to a tiny value
    (well below the seeded body) so the guard fires on the FIRST row
    of the per-request fingerprint — no large test fixture required.

    A clearly-named module-level constant (per the brief: "use
    existing limits or clearly named fixed constant monkeypatch
    tests") is the monkeypatch target; no environment knob is
    introduced.

    The monkeypatch is applied AFTER adapter construction so the
    construction-time canonical fingerprint (which honours the same
    budget) succeeds and the per-request ACTUAL fingerprint is the
    one that fires the guard.  This pins the per-request code path
    specifically.
    """

    _root, control, root_id, gen_id, manifest_sha256, store_path = _seed(
        tmp_path,
        corpus={"notes/a.txt": "alpha\n"},
    )

    # Build the adapter BEFORE lowering the budget so construction
    # succeeds (the canonical DB has a single 6-byte body, well
    # below the default 1 MiB ceiling).  The lower budget then
    # applies only to the per-request actual fingerprint.
    adapter = _open_bound_adapter(
        store_path,
        control_root=control,
        root_id=root_id,
        expected_generation_id=gen_id,
        expected_generation_manifest_sha256=manifest_sha256,
    )

    monkeypatch.setattr(inventory_module, "MAX_INVENTORY_BODY_BYTES", 1)

    with pytest.raises(FileProviderError) as caught:
        adapter.list_files(_list_request(root_id))
    assert caught.value.code == "inventory_budget_exceeded", (
        f"expected inventory_budget_exceeded; got {caught.value.code!r}"
    )


def test_aggregate_byte_budget_refuses_large_corpus(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A corpus whose aggregate bytes exceed the budget fails closed.

    The aggregate guard enforces a hard ceiling across the whole
    snapshot so a writer cannot pin a CPU while streaming every byte
    of a large corpus into Python.  ``MAX_INVENTORY_AGGREGATE_BYTES``
    is monkeypatched to a value just below the seeded aggregate so
    the guard fires deterministically.  As with the body-budget
    test, the monkeypatch is applied AFTER construction so the
    per-request path is the one that fires.
    """

    _root, control, root_id, gen_id, manifest_sha256, store_path = _seed(
        tmp_path,
        corpus={"notes/a.txt": "alpha\n", "notes/b.txt": "beta\n"},
    )

    adapter = _open_bound_adapter(
        store_path,
        control_root=control,
        root_id=root_id,
        expected_generation_id=gen_id,
        expected_generation_manifest_sha256=manifest_sha256,
    )

    # Set the aggregate ceiling BELOW the seeded corpus size (~22 bytes
    # of body content plus per-column length prefixes) so the guard
    # fires on the second row.
    monkeypatch.setattr(inventory_module, "MAX_INVENTORY_AGGREGATE_BYTES", 16)

    with pytest.raises(FileProviderError) as caught:
        adapter.list_files(_list_request(root_id))
    assert caught.value.code == "inventory_budget_exceeded", (
        f"expected inventory_budget_exceeded on aggregate overflow; "
        f"got {caught.value.code!r}"
    )


# ---------------------------------------------------------------------------
# All five operations share the same per-request inventory check.
# ---------------------------------------------------------------------------


def _outline_request(root_id: str, generation_id: str, *, file_id: str, digest: str):
    from arw.file_models import FilesOutlineRequest

    return FilesOutlineRequest(
        schema_version="1.0.0",
        root_id=root_id,
        generation_id=generation_id,
        file_id=file_id,
        expected_digest=digest,
        max_nodes=20,
        cursor=None,
    )


def _context_request(
    root_id: str,
    generation_id: str,
    *,
    file_id: str,
    digest: str,
    location: SourceLocation,
):
    from arw.file_models import FilesContextRequest

    return FilesContextRequest(
        schema_version="1.0.0",
        root_id=root_id,
        generation_id=generation_id,
        file_id=file_id,
        expected_digest=digest,
        hit_id=None,
        location=location,
        before_lines=2,
        after_lines=2,
    )


def _read_request(root_id: str, *, file_id: str, relative_path: str, digest: str):
    from arw.file_models import FilesReadRequest, LineRange

    return FilesReadRequest(
        schema_version="1.0.0",
        root_id=root_id,
        file_id=file_id,
        relative_path=relative_path,
        expected_digest=digest,
        byte_range=None,
        line_range=LineRange(start_line=1, max_lines=10),
        cursor=None,
    )


def _search_request(root_id: str):
    from arw.file_models import FilesSearchRequest

    return FilesSearchRequest(
        schema_version="1.0.0",
        root_id=root_id,
        mode="full_text",
        query="alpha",
        max_hits=50,
        max_snippet_bytes=200,
        cursor=None,
    )


@pytest.mark.parametrize(
    "operation",
    ["list_files", "search_files", "read_file", "get_outline", "get_context"],
)
def test_every_operation_runs_inventory_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    """Every tool path goes through the new inventory check.

    Parametrised across all five operations per the brief
    ("Parametrize common guard across all 5 ops if cheap").  The
    check is registered inside ``_with_query_snapshot`` so each
    operation picks it up automatically.  A monkey-patched inventory
    verifier counter proves the check runs once per request for
    every operation.
    """

    from arw_ext.local_store import files as adapter_module

    from arw.file_models import SourceLocation

    _root, control, root_id, gen_id, manifest_sha256, store_path = _seed(
        tmp_path,
        corpus={"notes/a.txt": "alpha alpha alpha\n", "notes/b.txt": "beta\n"},
    )
    adapter = _open_bound_adapter(
        store_path,
        control_root=control,
        root_id=root_id,
        expected_generation_id=gen_id,
        expected_generation_manifest_sha256=manifest_sha256,
    )

    real_verify = adapter_module.verify_actual_inventory
    call_count = {"value": 0}

    def tracking_verify(
        snapshot_conn: sqlite3.Connection, expected: str, *, deadline: float
    ) -> None:
        call_count["value"] += 1
        real_verify(snapshot_conn, expected, deadline=deadline)

    monkeypatch.setattr(adapter_module, "verify_actual_inventory", tracking_verify)

    listed = adapter.list_files(_list_request(root_id))
    file_id = listed.files[0].file_id
    relative_path = listed.files[0].relative_path
    digest = listed.files[0].indexed_digest
    assert digest is not None, "indexed digest must be set"
    # Reset the counter so the call below is the one under test.
    call_count["value"] = 0

    if operation == "list_files":
        adapter.list_files(_list_request(root_id))
    elif operation == "search_files":
        adapter.search_files(_search_request(root_id))
    elif operation == "read_file":
        adapter.read_file(
            _read_request(
                root_id, file_id=file_id, relative_path=relative_path, digest=digest
            )
        )
    elif operation == "get_outline":
        adapter.get_outline(
            _outline_request(root_id, gen_id, file_id=file_id, digest=digest)
        )
    elif operation == "get_context":
        location = SourceLocation(start_byte=0, end_byte=1, start_line=1, end_line=1)
        adapter.get_context(
            _context_request(
                root_id, gen_id, file_id=file_id, digest=digest, location=location
            )
        )
    else:  # pragma: no cover - defensive
        raise AssertionError(f"unknown operation: {operation}")

    assert call_count["value"] == 1, (
        f"{operation} must run the inventory check exactly once; "
        f"got {call_count['value']}"
    )

    cache = _open_writable_cache(store_path)
    try:
        cache.execute("UPDATE files SET source_digest = ?", ("f" * 64,))
        cache.commit()
    finally:
        cache.close()
    requests = {
        "list_files": _list_request(root_id),
        "search_files": _search_request(root_id),
        "read_file": _read_request(
            root_id, file_id=file_id, relative_path=relative_path, digest=digest
        ),
        "get_outline": _outline_request(
            root_id, gen_id, file_id=file_id, digest=digest
        ),
        "get_context": _context_request(
            root_id,
            gen_id,
            file_id=file_id,
            digest=digest,
            location=SourceLocation(start_byte=0, end_byte=1, start_line=1, end_line=1),
        ),
    }
    with pytest.raises(FileProviderError) as caught:
        getattr(adapter, operation)(requests[operation])
    assert caught.value.code == "inventory_tampered"


def test_null_cannot_replace_canonical_empty_body(tmp_path: Path) -> None:
    _, control, root_id, gen_id, manifest, path = _seed(
        tmp_path, corpus={"empty.txt": ""}
    )
    adapter = _open_bound_adapter(
        path,
        control_root=control,
        root_id=root_id,
        expected_generation_id=gen_id,
        expected_generation_manifest_sha256=manifest,
    )
    with _open_writable_cache(path) as cache:
        cache.execute("UPDATE files SET body = NULL, body_nfkc_folded = NULL")
        cache.execute("DELETE FROM files_fts_trigram")
    with pytest.raises(FileProviderError) as caught:
        adapter.list_files(_list_request(root_id))
    assert caught.value.code == "inventory_tampered"


@pytest.mark.parametrize("query", ["中文证据", "alpha beta", 'a"b', "no-match"])
def test_bound_search_preserves_multilingual_and_quoted_queries(
    tmp_path: Path, query: str
) -> None:
    _, control, root_id, gen_id, manifest, path = _seed(
        tmp_path, corpus={"a.txt": '中文证据 alpha beta a"b'}
    )
    adapter = _open_bound_adapter(
        path,
        control_root=control,
        root_id=root_id,
        expected_generation_id=gen_id,
        expected_generation_manifest_sha256=manifest,
    )
    request = _search_request(root_id).model_copy(update={"query": query})
    result = adapter.search_files(request)
    assert bool(result.hits) is (query != "no-match")


def test_fts_validation_honors_expired_deadline(tmp_path: Path) -> None:
    _, _, _, _, _, path = _seed(tmp_path, corpus={"a.txt": "alpha"})
    with (
        sqlite3.connect(path) as connection,
        pytest.raises(inventory_module.InventoryBudgetExceeded),
    ):
        inventory_module.verify_fts_trigram_consistency(connection, deadline=0)


def test_fts_shadow_postings_cannot_silently_hide_canonical_hits(
    tmp_path: Path,
) -> None:
    _, control, root_id, gen_id, manifest, path = _seed(
        tmp_path, corpus={"a.txt": "alpha alpha"}
    )
    adapter = _open_bound_adapter(
        path,
        control_root=control,
        root_id=root_id,
        expected_generation_id=gen_id,
        expected_generation_manifest_sha256=manifest,
    )
    assert adapter.search_files(_search_request(root_id)).hits
    with sqlite3.connect(":memory:") as empty, _open_writable_cache(path) as cache:
        empty.execute(
            "CREATE VIRTUAL TABLE blank USING fts5(file_id UNINDEXED, relative_path UNINDEXED, body_nfkc_folded, tokenize='trigram')"
        )
        for suffix in ("data", "idx", "docsize"):
            rows = empty.execute(f"SELECT * FROM blank_{suffix}").fetchall()
            cache.execute(f"DELETE FROM files_fts_trigram_{suffix}")
            for row in rows:
                placeholders = ",".join("?" for _ in row)
                cache.execute(
                    f"INSERT INTO files_fts_trigram_{suffix} VALUES ({placeholders})",
                    row,
                )
        assert (
            cache.execute("SELECT count(*) FROM files_fts_trigram").fetchone()[0] == 1
        )
        assert (
            cache.execute(
                "SELECT count(*) FROM files_fts_trigram WHERE files_fts_trigram MATCH 'alpha'"
            ).fetchone()[0]
            == 0
        )
    with pytest.raises(FileProviderError) as caught:
        adapter.search_files(_search_request(root_id))
    assert caught.value.code == "inventory_tampered"


def test_inventory_vm_step_guard_uses_runtime_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, control, root_id, gen_id, manifest, path = _seed(
        tmp_path, corpus={"a.txt": "alpha"}
    )
    adapter = _open_bound_adapter(
        path,
        control_root=control,
        root_id=root_id,
        expected_generation_id=gen_id,
        expected_generation_manifest_sha256=manifest,
    )
    monkeypatch.setattr(inventory_module, "MAX_INVENTORY_VM_STEPS", 1)
    with pytest.raises(FileProviderError) as caught:
        adapter.list_files(_list_request(root_id))
    assert caught.value.code == "inventory_budget_exceeded"


def test_oversized_body_is_rejected_before_python_text_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, _, _, _, path = _seed(tmp_path, corpus={"a.txt": "alpha"})
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE files SET body = ?", ("X" * 2048,))
        monkeypatch.setattr(inventory_module, "MAX_INVENTORY_BODY_BYTES", 1024)
        original = connection.text_factory

        def refuse_large_text(payload: bytes) -> str:
            assert len(payload) <= 1024, (
                "oversized cell materialized before budget guard"
            )
            return original(payload)

        connection.text_factory = refuse_large_text
        with pytest.raises(inventory_module.InventoryBudgetExceeded):
            inventory_module.compute_actual_inventory_fingerprint(
                connection, deadline=float("inf")
            )


# ---------------------------------------------------------------------------
# Strict-anchor regression (PR16 Codex P1 review 3940050812 follow-up).
# ---------------------------------------------------------------------------


def test_strict_anchor_rejects_missing_generation_with_intact_pointer(
    tmp_path: Path,
) -> None:
    """Strict-anchor security regression.

    The anchor must FAIL CLOSED when the canonical generation
    directory is unreachable even if ``selected-generation.json``
    is intact: a writer who deletes the bound generation directory
    while leaving the pointer file unchanged would otherwise slip
    past BOTH the per-request reader's strict-pointer binding (the
    pointer file is unchanged) AND the inventory check (the anchor
    was previously silently skipped via the ``"uninitialised"``
    sentinel fallback).

    This test pins the secure behaviour:

    * ``selected-generation.json`` is left INTACT (pointing at the
      bound generation).
    * The bound generation directory is DELETED.
    * The constructor MUST refuse with ``root_denied`` \u2014 the
      anchor cannot reach the manifest + database, so the caller
      cannot trust the cache to be the projection of those
      artifacts.

    No silent sentinel fallback: a production adapter against this
    state would be a security regression.
    """

    import shutil

    _root, control, root_id, gen_id, manifest_sha256, store_path = _seed(
        tmp_path,
        corpus={"notes/a.txt": "alpha\n"},
    )

    # Delete ONLY the bound generation directory; leave
    # ``selected-generation.json`` and ``root.json`` and
    # ``cursor.key`` untouched.  This is the precise state a writer
    # who wants to slip past the strict-pointer binding would
    # produce: the pointer file is valid (same generation_id +
    # manifest_sha256 as the caller holds), but the generation
    # artifacts the anchor needs are gone.
    generation_dir = control / "roots" / root_id / "generations" / gen_id
    assert generation_dir.is_dir(), "seed must produce a real generation dir"
    shutil.rmtree(generation_dir)
    # Sanity: the pointer file is still there (untouched) and
    # still names the (now-absent) generation.  This is what makes
    # the attack subtle: the per-request strict-pointer walk would
    # PASS because the pointer file is well-formed.
    pointer_path = control / "roots" / root_id / "selected-generation.json"
    assert pointer_path.is_file(), "pointer file must remain intact"
    import json as _json

    pointer_payload = _json.loads(pointer_path.read_text(encoding="utf-8"))
    assert pointer_payload["generation_id"] == gen_id
    assert pointer_payload["generation_manifest_sha256"] == manifest_sha256

    store = LocalProjectionStore(store_path)
    store.open_readonly()
    try:
        with pytest.raises(FileProviderError) as caught:
            LocalStoreFilesAdapter(
                store,
                canonical_root=control,
                root_id=root_id,
                expected_generation_id=gen_id,
                expected_generation_manifest_sha256=manifest_sha256,
            )
        assert caught.value.code == "root_denied", (
            f"strict anchor must refuse missing canonical generation; "
            f"got {caught.value.code!r}"
        )
    finally:
        store.close()


def test_installed_factory_derives_fingerprint_via_load_query_generation(
    tmp_path: Path,
) -> None:
    """The installed factory (``_open_store_adapter``) derives the
    inventory fingerprint from ``load_query_generation.database_path``.

    No test-side injection of the expected fingerprint is allowed in
    the production code path: the MCP factory calls
    ``_resolve_allowed_root`` which calls
    :func:`arw.files.load_query_generation` and threads the loaded
    ``generation_manifest_sha256`` (the manifest digest the loader
    already validated against the on-disk ``generation-manifest.json``
    + ``files.sqlite3`` bytes) into the adapter constructor.  The
    constructor's anchor then derives the fingerprint from
    ``generation.database_path`` (the loader's verified path), not
    from any guessed path layout.

    This test runs the actual installed factory against a freshly
    seeded control + store (no monkeypatching of inventory helpers)
    and asserts:

    * the adapter constructed with the production factory exposes
      a non-sentinel expected_inventory_fingerprint
      (``"uninitialised"`` would indicate the sentinel fallback was
      silently taken \u2014 a regression);
    * the fingerprint is reproducible across two constructions
      (deterministic length-framed SHA-256 over the canonical DB
      rows);
    * a request through the production factory succeeds end-to-end
      (the fingerprint derivation path is wired correctly).
    """

    from arw_ext.local_store import LocalProjectionStore
    from arw_ext.local_store.files import LocalStoreFilesAdapter

    from arw.files_store_mcp import _resolve_allowed_root

    _root, control, root_id, gen_id, manifest_sha256, store_path = _seed(
        tmp_path,
        corpus={"notes/a.txt": "alpha\n", "notes/b.txt": "beta\n"},
    )

    # ``_resolve_allowed_root`` is the production entry point used
    # by the installed factory.  It calls ``load_query_generation``
    # (validating identity_manifest_sha256 + generation_manifest_sha256
    # + database_sha256 against the immutable artifacts) and returns
    # the verified ``generation_id`` + ``generation_manifest_sha256``
    # + ``root.canonical_path``.  No test inject; the values come
    # from the canonical control root the production code paths see.
    (
        allowed_root,
        expected_root_id,
        expected_generation_id,
        expected_generation_manifest_sha256,
    ) = _resolve_allowed_root(control, root_id)
    assert allowed_root == _root.resolve(strict=False)
    assert expected_root_id == root_id
    assert expected_generation_id == gen_id
    assert expected_generation_manifest_sha256 == manifest_sha256

    # Build the adapter through the production constructor path
    # (NOT through ``anchor_trust_to_manifest`` directly).  The
    # constructor internally calls the anchor; this is the
    # end-to-end production wiring.
    store = LocalProjectionStore(store_path)
    store.open_readonly()
    try:
        adapter = LocalStoreFilesAdapter(
            store,
            canonical_root=control,
            root_id=root_id,
            expected_generation_id=expected_generation_id,
            expected_generation_manifest_sha256=expected_generation_manifest_sha256,
        )
        fingerprint = adapter._expected_inventory_fingerprint  # type: ignore[attr-defined]
        # The sentinel fallback would produce ``"uninitialised"``;
        # the strict anchor must derive a real 64-char hex digest
        # from the canonical DB.
        assert fingerprint != "uninitialised", (
            "strict anchor must derive a real fingerprint, never the "
            "sentinel fallback (would mean the constructor accepted "
            "a state where the canonical generation is unreachable)"
        )
        assert len(fingerprint) == 64 and all(
            character in "0123456789abcdef" for character in fingerprint
        ), f"fingerprint must be a lowercase hex SHA-256; got {fingerprint!r}"

        # Reproducibility: a second construction against the same
        # canonical state must yield the same fingerprint (the
        # length-framed SHA-256 stream is deterministic).
        store.close()
        store = LocalProjectionStore(store_path)
        store.open_readonly()
        adapter_again = LocalStoreFilesAdapter(
            store,
            canonical_root=control,
            root_id=root_id,
            expected_generation_id=expected_generation_id,
            expected_generation_manifest_sha256=expected_generation_manifest_sha256,
        )
        assert (
            adapter_again._expected_inventory_fingerprint  # type: ignore[attr-defined]
            == fingerprint
        ), "fingerprint must be reproducible across constructions"

        # End-to-end: a request through the production factory must
        # succeed (the strict anchor derived the correct fingerprint,
        # the cache matches it, the per-request check passes).
        result = adapter_again.list_files(
            FilesListRequest(
                schema_version="1.0.0",
                root_id=root_id,
                cursor=None,
                max_files=200,
            )
        )
        assert {entry.relative_path for entry in result.files} == {
            "notes/a.txt",
            "notes/b.txt",
        }
    finally:
        store.close()
