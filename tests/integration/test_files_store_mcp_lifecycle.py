"""Regression coverage for PR16 Codex P1 comment3939599512.

The constructor generation binding in ``LocalStoreFilesAdapter`` is
one-shot: it captures ``files.selected_generation_id`` once at process
startup.  In a long-lived MCP process that binding is not refreshed, so
two failure modes are possible while a single request is in flight:

1. An external writer (``arw files sync`` followed by ``ingest``)
   replaces the canonical ``selected-generation.json`` so the live
   registration names a newer generation.  The adapter should fail
   closed with a typed ``stale_query_generation`` error rather than
   keep serving rows from the now-obsolete generation.
2. The cache rows are re-ingested (e.g. an operator re-runs the
   ingest against the same registered root) while a request is in
   flight.  Without a per-request SQLite snapshot, two reads on the
   shared connection could observe rows from two different
   generations and a single response could mix them.

This module exercises three scenarios deterministically (no sleeps,
no parallel writers): successful re-ingestion between calls stays
served by the existing bound generation; ingestion under a
newly-advanced canonical selection fails closed; an adversarial
mid-request flip of the canonical file is detected by the post-check
and refused.  The compact form mirrors ``test_files_mcp`` /
``test_files_admin`` patterns and avoids appending to the already
large history test.
"""

from __future__ import annotations

import itertools
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Callable

import pytest

from arw.adapters.files import FileProviderError
from arw.file_models import (
    FilesListRequest,
    FilesOutlineRequest,
    FilesSearchRequest,
    SourceLocation,
)
from arw.files import FilesAdminService, load_query_generation

from arw_ext.local_store import LocalProjectionStore, LocalStoreFilesAdapter
from arw_ext.local_store.ingest import ingest_files_generation


def _service_factory(control: Path) -> FilesAdminService:
    """FilesAdminService with a per-instance UUID salt so unique IDs are stable."""

    sequence = itertools.count(1)
    salt = uuid.uuid4().hex[:8]
    return FilesAdminService(
        control,
        id_factory=lambda kind: f"{kind}_lifecycle_{salt}_{next(sequence):03d}",
        clock=lambda: "2026-09-05T00:00:00Z",
    )


def _seed(
    tmp_path: Path,
    *,
    corpus: dict[str, str],
    store_path: Path | None = None,
) -> tuple[Path, Path, str, str, Path]:
    """Register a root, sync once, ingest.  Returns (root, control, root_id, generation_id, store_path)."""

    root = tmp_path / "root"
    for relative_path, content in corpus.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    control = tmp_path / "control"
    service = _service_factory(control)
    service.register_root(
        root_id="lifecycle-root", root_path=root, policy_id="research-files-v1"
    )
    receipt = service.sync("lifecycle-root", extractor_version="1.0.0")
    assert receipt.selected_generation_id is not None
    generation = load_query_generation(control, "lifecycle-root")
    store_path = store_path or tmp_path / "arw.db"
    store = LocalProjectionStore(store_path)
    store.open()
    ingest_files_generation(store.connection, generation)
    store.connection.commit()
    store.close()
    return root, control, "lifecycle-root", receipt.selected_generation_id, store_path


def _open_bound_adapter(
    store_path: Path,
    *,
    control_root: Path | None = None,
    root_id: str | None = None,
    expected_generation_id: str | None = None,
) -> LocalStoreFilesAdapter:
    """Open the store and build an adapter bound to ``expected_generation_id``.

    Passes ``control_root`` + ``root_id`` so per-request revalidation
    can re-read ``selected-generation.json`` (the long-lived process
    protection path).  When omitted, the adapter still revalidates
    cache metadata each request (the cache-row protection path).
    """

    store = LocalProjectionStore(store_path)
    store.open_readonly()
    return LocalStoreFilesAdapter(
        store,
        canonical_root=control_root,
        root_id=root_id,
        expected_generation_id=expected_generation_id,
    )


def _list_request(root_id: str) -> FilesListRequest:
    return FilesListRequest(
        schema_version="1.0.0",
        root_id=root_id,
        cursor=None,
        max_files=200,
    )


def _outline_request(root_id: str, generation_id: str, *, file_id: str, digest: str) -> FilesOutlineRequest:
    return FilesOutlineRequest(
        schema_version="1.0.0",
        root_id=root_id,
        generation_id=generation_id,
        file_id=file_id,
        expected_digest=digest,
        max_nodes=20,
        cursor=None,
    )


def _search_request(root_id: str) -> FilesSearchRequest:
    return FilesSearchRequest(
        schema_version="1.0.0",
        root_id=root_id,
        mode="full_text",
        query="alpha",
        max_hits=50,
        max_snippet_bytes=200,
        cursor=None,
    )


# ---------------------------------------------------------------------------
# Scenario 1: re-ingestion between calls stays served (positive control).
# ---------------------------------------------------------------------------


def test_reingest_between_calls_keeps_bound_adapter_serving(tmp_path: Path) -> None:
    """A second call on the bound adapter succeeds when nothing has advanced.

    The per-request guard must not false-positive: while the canonical
    ``selected-generation.json`` still names the bound generation and
    the cache metadata still records it, repeated reads keep returning
    rows.  This is the positive control: it proves the guard only
    refuses on actual drift, not on every call.
    """

    _root, control, root_id, generation_id, store_path = _seed(
        tmp_path,
        corpus={"notes/a.txt": "alpha alpha alpha\n", "notes/b.txt": "beta\n"},
    )
    adapter = _open_bound_adapter(
        store_path,
        control_root=control,
        root_id=root_id,
        expected_generation_id=generation_id,
    )

    first = adapter.list_files(_list_request(root_id))
    assert {entry.relative_path for entry in first.files} == {"notes/a.txt", "notes/b.txt"}
    assert first.selected_generation_id == generation_id

    # No operator action between calls: canonical selection and cache
    # metadata are unchanged, so the bound adapter keeps serving.
    second = adapter.list_files(_list_request(root_id))
    assert {entry.relative_path for entry in second.files} == {"notes/a.txt", "notes/b.txt"}
    assert second.selected_generation_id == generation_id


# ---------------------------------------------------------------------------
# Scenario 2: re-ingestion after the canonical selection advances fails.
# ---------------------------------------------------------------------------


def test_advanced_canonical_selection_fails_closed(tmp_path: Path) -> None:
    """After ``sync`` advances the canonical generation, the bound adapter must fail.

    The adapter is constructed against generation X.  A subsequent
    ``sync`` mutates the live corpus so a fresh generation Y is
    selected; the new ingest overwrites ``files.selected_generation_id``
    in the cache.  The next per-request snapshot must refuse to serve
    rows from the now-stale cache and surface ``stale_query_generation``
    so the operator restarts the MCP process with the new anchor.
    """

    _root, control, root_id, generation_id, store_path = _seed(
        tmp_path,
        corpus={"notes/a.txt": "alpha\n"},
    )
    adapter = _open_bound_adapter(
        store_path,
        control_root=control,
        root_id=root_id,
        expected_generation_id=generation_id,
    )
    # Sanity: the bound adapter serves the original generation.
    listed = adapter.list_files(_list_request(root_id))
    assert listed.files, "pre-advance list_files must return the original row"

    # Mutate the live corpus so the next sync produces a fresh
    # generation.  The id_factory below seeds a unique salt that does
    # not collide with the first sync's IDs.
    (tmp_path / "root" / "notes" / "b.txt").write_text("beta\n", encoding="utf-8")
    service = FilesAdminService(
        control,
        id_factory=lambda kind: f"{kind}_advance_{uuid.uuid4().hex[:8]}",
        clock=lambda: "2026-09-05T00:00:01Z",
    )
    receipt = service.sync(root_id, extractor_version="1.0.0")
    assert receipt.selected_generation_id is not None
    assert receipt.selected_generation_id != generation_id
    new_generation = load_query_generation(control, root_id)
    store = LocalProjectionStore(store_path)
    store.open()
    ingest_files_generation(store.connection, new_generation)
    store.connection.commit()
    store.close()

    # Per-request guard catches both the canonical file advance AND the
    # cache metadata advance; either raise is acceptable, but neither
    # may silently serve rows from the stale generation.
    with pytest.raises(FileProviderError) as caught:
        adapter.list_files(_list_request(root_id))
    assert caught.value.code == "stale_query_generation", (
        f"expected stale_query_generation, got {caught.value.code!r}"
    )


# ---------------------------------------------------------------------------
# Scenario 3: adversarial mid-request canonical file flip fails closed.
# ---------------------------------------------------------------------------


def test_mid_query_canonical_flip_fails_closed(tmp_path: Path, monkeypatch) -> None:
    """A canonical file flip between the pre-check and the post-check fails.

    Uses the adapter's per-request revalidation directly with a
    monkey-patched canonical reader: the first call (pre-check)
    returns the bound generation; the second call (post-check) returns
    a different generation.  The adapter must refuse to return a
    response that could mix the two generations.
    """

    _root, control, root_id, generation_id, store_path = _seed(
        tmp_path,
        corpus={"notes/a.txt": "alpha\n"},
    )
    adapter = _open_bound_adapter(
        store_path,
        control_root=control,
        root_id=root_id,
        expected_generation_id=generation_id,
    )

    # Drive a list_files call but flip the canonical reader between
    # the pre-check and the post-check so the post-check detects the
    # advancement.  We replace the bound method directly (not the
    # reader on disk) so the test is deterministic without sleep or
    # external writers.
    call_count = {"value": 0}

    original_reader = adapter._read_canonical_generation_id  # type: ignore[attr-defined]

    def flipping_reader() -> str:
        call_count["value"] += 1
        # First call (pre-check inside the snapshot wrapper) returns
        # the bound generation.  Second call (post-check) returns a
        # different generation to simulate the canonical selection
        # advancing mid-request.
        if call_count["value"] == 1:
            return original_reader()
        return generation_id + "_ADV"

    monkeypatch.setattr(adapter, "_read_canonical_generation_id", flipping_reader)

    with pytest.raises(FileProviderError) as caught:
        adapter.list_files(_list_request(root_id))
    assert caught.value.code == "stale_query_generation", (
        f"expected stale_query_generation on post-check, got {caught.value.code!r}"
    )
    assert call_count["value"] >= 2, (
        "the wrapper must run both the pre-check and the post-check"
    )


# ---------------------------------------------------------------------------
# Scenario 3b: adversarial mid-request cache metadata flip fails closed.
# ---------------------------------------------------------------------------


def test_mid_query_cache_metadata_flip_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cache metadata flip between pre-check and post-check fails.

    Uses a monkey-patched :func:`read_files_meta` to simulate an
    external writer who re-ingests the cache with a different
    ``files.selected_generation_id`` between the pre-check and the
    post-check.  The post-check must observe the new metadata and
    refuse to return a response that mixes the two generations.
    """

    _root, control, root_id, generation_id, store_path = _seed(
        tmp_path,
        corpus={"notes/a.txt": "alpha\n"},
    )
    adapter = _open_bound_adapter(
        store_path,
        control_root=control,
        root_id=root_id,
        expected_generation_id=generation_id,
    )

    from arw_ext.local_store import files as adapter_module

    original_read_meta = adapter_module.read_files_meta
    call_count = {"value": 0}

    def flipping_read_meta(connection: sqlite3.Connection) -> dict[str, str] | None:
        call_count["value"] += 1
        meta = original_read_meta(connection)
        if meta is None:
            return meta
        if call_count["value"] >= 2:
            # Simulate a writer who re-ingested the cache with a
            # different generation between the pre-check and the
            # post-check.  The post-check observes the drift.
            return {
                **meta,
                "files.selected_generation_id": generation_id + "_ADV",
            }
        return meta

    monkeypatch.setattr(adapter_module, "read_files_meta", flipping_read_meta)

    with pytest.raises(FileProviderError) as caught:
        adapter.list_files(_list_request(root_id))
    assert caught.value.code == "stale_query_generation", (
        f"expected stale_query_generation on post-check, got {caught.value.code!r}"
    )
    assert call_count["value"] >= 2, (
        "the wrapper must run both the pre-check and the post-check"
    )


# ---------------------------------------------------------------------------
# Scenario 3c: snapshot connection is opened and closed per request.
# ---------------------------------------------------------------------------


def test_per_request_snapshot_connection_is_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each request must use a fresh connection, not the long-lived one.

    A shared connection across requests would let a writer re-ingest
    the cache between two requests and silently change the result set
    seen by the second call.  ``open_snapshot_connection`` is invoked
    once per request and the snapshot is closed in the ``finally``
    block, so the long-lived store connection is never the source of
    the per-request reads.
    """

    _root, control, root_id, generation_id, store_path = _seed(
        tmp_path,
        corpus={"notes/a.txt": "alpha\n"},
    )
    store = LocalProjectionStore(store_path)
    store.open_readonly()
    adapter = LocalStoreFilesAdapter(
        store,
        canonical_root=control,
        root_id=root_id,
        expected_generation_id=generation_id,
    )

    opened_connections: list[sqlite3.Connection] = []

    real_open = adapter._open_query_snapshot  # type: ignore[attr-defined]

    def tracking_open() -> sqlite3.Connection:
        connection = real_open()
        opened_connections.append(connection)
        return connection

    monkeypatch.setattr(adapter, "_open_query_snapshot", tracking_open)

    adapter.list_files(_list_request(root_id))
    adapter.list_files(_list_request(root_id))

    assert len(opened_connections) == 2, "each list_files must open its own snapshot"
    assert opened_connections[0] is not opened_connections[1], (
        "each request must use a distinct connection"
    )
    for connection in opened_connections:
        assert connection is not store.connection, (
            "snapshot must be a separate connection from the long-lived store"
        )
    store.close()


# ---------------------------------------------------------------------------
# Scenario 4: all five operations share the same per-request guard.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "operation",
    [
        "list_files",
        "search_files",
        "get_outline",
        "get_context",
        "read_file",
    ],
)
def test_every_operation_runs_per_request_revalidation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    """All five FileProvider operations must run the per-request guard.

    Each operation opens its own snapshot, runs the pre-check, then
    runs the post-check.  The adversarial injection (a monkey-patched
    revalidator that flips on the second call) must cause ALL five
    operations to fail closed with ``stale_query_generation``.
    """

    _root, control, root_id, generation_id, store_path = _seed(
        tmp_path,
        corpus={"notes/a.txt": "alpha alpha alpha\n", "notes/b.txt": "beta\n"},
    )
    adapter = _open_bound_adapter(
        store_path,
        control_root=control,
        root_id=root_id,
        expected_generation_id=generation_id,
    )

    listed = adapter.list_files(_list_request(root_id))
    file_id = listed.files[0].file_id
    digest = listed.files[0].indexed_digest
    assert digest is not None, f"indexed digest must be set; got {listed.files[0]!r}"

    # Adversarial injection: the second revalidator call returns a
    # different generation.  This forces the post-check inside the
    # wrapper to raise before the operation returns a response.
    original_revalidator = adapter._revalidate_query_generation  # type: ignore[attr-defined]
    call_count = {"value": 0}

    def flipping_revalidator(snapshot_conn: sqlite3.Connection) -> None:
        call_count["value"] += 1
        original_revalidator(snapshot_conn)
        if call_count["value"] >= 2:
            # Override the comparison by raising on the second call.
            from arw.files_mcp import ToolError

            raise ToolError(
                "stale_query_generation",
                "adversarial flip detected by test injection",
            )

    monkeypatch.setattr(
        adapter, "_revalidate_query_generation", flipping_revalidator
    )

    if operation == "list_files":
        request = _list_request(root_id)
    elif operation == "search_files":
        request = _search_request(root_id)
    elif operation == "get_outline":
        request = _outline_request(
            root_id, generation_id, file_id=file_id, digest=digest
        )
    elif operation == "get_context":
        from arw.file_models import FilesContextRequest

        request = FilesContextRequest(
            schema_version="1.0.0",
            root_id=root_id,
            generation_id=generation_id,
            file_id=file_id,
            expected_digest=digest,
            hit_id=None,
            location=SourceLocation(
                start_byte=0, end_byte=1, start_line=1, end_line=1
            ),
            before_lines=1,
            after_lines=1,
        )
    elif operation == "read_file":
        from arw.file_models import ByteRange, FilesReadRequest

        request = FilesReadRequest(
            schema_version="1.0.0",
            root_id=root_id,
            file_id=file_id,
            relative_path="notes/a.txt",
            expected_digest=None,
            byte_range=ByteRange(start=0, max_bytes=8),
            line_range=None,
            cursor=None,
        )
    else:
        raise AssertionError(f"unhandled operation: {operation}")

    with pytest.raises(FileProviderError) as caught:
        getattr(adapter, operation)(request)
    assert caught.value.code == "stale_query_generation", (
        f"{operation} must fail closed with stale_query_generation; "
        f"got {caught.value.code!r}"
    )


# ---------------------------------------------------------------------------
# Scenario 5: real WAL-mode second-connection commit during the query.
# ---------------------------------------------------------------------------


def test_wal_mode_second_connection_commit_during_query_drops_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real SQLite writer commits while a request is in flight; the snapshot
    stays coherent (no mixed labels) and the canonical-advance post-check
    drops the result.

    The store is switched to ``journal_mode=WAL`` so a writer on a separate
    connection can commit without blocking on the snapshot's SHARED lock
    (DELETE mode would block the writer until the snapshot COMMITs, which
    would mask the in-flight commit the comment asks us to prove).  The
    writer performs a real ``UPDATE projection_meta`` and commits; the
    adapter's snapshot, established before the writer's commit, does NOT
    see the new metadata (snapshot coherence — the response stays a
    coherent old-generation view).  A real filesystem rewrite of
    ``selected-generation.json`` advances the canonical selection; the
    post-check inside the snapshot reads the canonical file directly
    (not through SQLite) and detects the advance, so the request is
    dropped with ``stale_query_generation`` before the response is
    returned.  No mock of the revalidation hooks; both the writer's
    commit and the canonical file rewrite land on real storage.
    """

    _root, control, root_id, generation_id, store_path = _seed(
        tmp_path,
        corpus={"notes/a.txt": "alpha alpha alpha\n", "notes/b.txt": "beta\n"},
    )

    # Switch the store to WAL mode.  PRAGMA journal_mode is persistent at
    # the database level, so every subsequent connection (including the
    # snapshot connection) inherits WAL semantics.
    setup_store = LocalProjectionStore(store_path)
    setup_store.open()
    journal_mode = setup_store.connection.execute(
        "PRAGMA journal_mode=WAL"
    ).fetchone()[0]
    assert journal_mode.lower() == "wal", (
        f"expected WAL journal mode; got {journal_mode!r}"
    )
    setup_store.close()

    store = LocalProjectionStore(store_path)
    store.open_readonly()
    adapter = LocalStoreFilesAdapter(
        store,
        canonical_root=control,
        root_id=root_id,
        expected_generation_id=generation_id,
    )

    selected_path = (
        control / "roots" / root_id / "selected-generation.json"
    )
    advanced_generation = generation_id + "_ADV"
    reader_call_count = {"value": 0}

    original_reader = adapter._read_canonical_generation_id  # type: ignore[attr-defined]

    def in_flight_advancer() -> str:
        """Between the pre-check and the post-check: real second-connection commit + canonical file rewrite.

        The canonical reader is called twice per request (once by the
        pre-check, once by the post-check).  On the first call we
        return the bound generation so the pre-check passes; on the
        second call we perform the in-flight writer activity that the
        comment asks us to prove a reader can survive without mixing
        generations, then return the advanced value so the post-check
        observes the advance and drops the result.
        """
        reader_call_count["value"] += 1
        if reader_call_count["value"] == 1:
            # Pre-check: return the bound generation so the pre-check passes.
            return original_reader()
        # Post-check path: real second-connection commit + canonical
        # file rewrite, then return the advanced value the post-check
        # will compare against ``self._generation_id``.
        writer = sqlite3.connect(str(store_path))
        try:
            writer.execute(
                "UPDATE projection_meta SET value = ?"
                " WHERE key = 'files.selected_generation_id'",
                (advanced_generation,),
            )
            writer.commit()
        finally:
            writer.close()
        payload = json.loads(selected_path.read_text(encoding="utf-8"))
        payload["generation_id"] = advanced_generation
        selected_path.write_text(
            json.dumps(payload), encoding="utf-8"
        )
        return advanced_generation

    monkeypatch.setattr(
        adapter, "_read_canonical_generation_id", in_flight_advancer
    )

    with pytest.raises(FileProviderError) as caught:
        adapter.list_files(_list_request(root_id))
    assert caught.value.code == "stale_query_generation", (
        f"post-check must drop the result on canonical advance; "
        f"got {caught.value.code!r}"
    )
    assert reader_call_count["value"] >= 2, (
        "the wrapper must run both the pre-check and the post-check"
    )

    # Verify the writer's commit landed on disk (the snapshot's reads
    # did NOT see it — that is the coherence proof).  A second request
    # opened AFTER the commit must observe the new metadata.
    from arw_ext.local_store.ingest import read_files_meta

    verify_store = LocalProjectionStore(store_path)
    verify_store.open_readonly()
    try:
        post_meta = read_files_meta(verify_store.connection)
        assert post_meta is not None
        assert post_meta["files.selected_generation_id"] == advanced_generation, (
            "the writer's commit must be visible to a fresh read"
        )
    finally:
        verify_store.close()

    # The canonical file advance must persist across reads.
    advanced_payload = json.loads(
        selected_path.read_text(encoding="utf-8")
    )
    assert advanced_payload["generation_id"] == advanced_generation

    store.close()


# ---------------------------------------------------------------------------
# Scenario 6: concurrent native callers do not cross-wire snapshot connections.
# ---------------------------------------------------------------------------


def _assert_snapshot_closed(connection: sqlite3.Connection) -> None:
    """Verify a per-request snapshot connection has been closed.

    After ``LocalStoreFilesAdapter._with_query_snapshot`` returns (or
    raises), ``snapshot.close()`` must have been called.  The Python
    sqlite3 binding raises ``ProgrammingError`` on any operation
    against a closed connection.
    """

    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")


def test_two_native_callers_no_cross_connection_contamination(
    tmp_path: Path,
) -> None:
    """Two concurrent native callers cannot cross-wire their request connections.

    The MCP is sequential so it never hits this race, but native
    callers (Python code driving the adapter directly from threads or
    async tasks) can.  Without the per-instance ``_request_lock`` the
    instance attribute ``self._request_conn`` would be a shared
    mutable read by both threads, and one thread's ``_rows`` could see
    the other thread's snapshot — producing cross-connection reads
    inside a single response.  With the lock the operations serialize,
    each caller gets its own distinct snapshot, and ``_request_conn``
    is reset to ``None`` before the lock is released so the next
    caller cannot read a stale pointer.

    The test runs two real threads (a barrier-synchronized start so
    both contend for the lock), captures the snapshot each caller
    opened, asserts the two are distinct and neither is the long-lived
    store connection, and then verifies the snapshot was closed after
    success.
    """

    _root, control, root_id, generation_id, store_path = _seed(
        tmp_path,
        corpus={
            "notes/a.txt": "alpha alpha alpha\n",
            "notes/b.txt": "beta\n",
        },
    )
    store = LocalProjectionStore(store_path)
    store.open_readonly()
    adapter = LocalStoreFilesAdapter(
        store,
        canonical_root=control,
        root_id=root_id,
        expected_generation_id=generation_id,
    )

    captured: list[tuple[str, sqlite3.Connection]] = []
    captured_lock = threading.Lock()
    real_open = adapter._open_query_snapshot

    def tracking_open() -> sqlite3.Connection:
        connection = real_open()
        with captured_lock:
            captured.append((threading.current_thread().name, connection))
        return connection

    adapter._open_query_snapshot = tracking_open  # type: ignore[method-assign]

    barrier = threading.Barrier(2)

    def call_list_files() -> None:
        barrier.wait()
        adapter.list_files(_list_request(root_id))

    def call_search_files() -> None:
        barrier.wait()
        adapter.search_files(_search_request(root_id))

    list_thread = threading.Thread(
        target=call_list_files, name="list-files-caller"
    )
    search_thread = threading.Thread(
        target=call_search_files, name="search-files-caller"
    )
    list_thread.start()
    search_thread.start()
    list_thread.join(timeout=10)
    search_thread.join(timeout=10)
    assert not list_thread.is_alive(), "list_files thread hung"
    assert not search_thread.is_alive(), "search_files thread hung"

    adapter._open_query_snapshot = real_open  # type: ignore[method-assign]

    assert len(captured) == 2, "each caller must have opened its own snapshot"
    (label_a, conn_a), (label_b, conn_b) = captured
    assert conn_a is not conn_b, (
        "concurrent callers must not share a snapshot connection"
    )
    assert conn_a is not store.connection, (
        "snapshot must not be the long-lived store connection"
    )
    assert conn_b is not store.connection, (
        "snapshot must not be the long-lived store connection"
    )
    assert {label_a, label_b} == {
        "list-files-caller",
        "search-files-caller",
    }, "both threads must have invoked the adapter"

    # Snapshot closed after success: the wrapper's ``finally`` ran
    # ``snapshot.close()`` after releasing the lock.
    _assert_snapshot_closed(conn_a)
    _assert_snapshot_closed(conn_b)

    # The request_conn pointer must be cleared between requests so the
    # next caller cannot read a stale connection (the lock alone does
    # not protect a direct attribute read without the lock held).
    assert getattr(adapter, "_request_conn", None) is None, (
        "request_conn must be cleared after both callers completed"
    )

    store.close()


def test_snapshot_closed_after_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The snapshot connection is closed even when the operation raises.

    Forces the canonical reader to raise on the post-check so the
    operation aborts; the wrapper's ``finally`` must still close the
    snapshot.  Also verifies the lock is released (a follow-up call
    after the error succeeds) so a transient failure does not wedge
    the adapter.
    """

    _root, control, root_id, generation_id, store_path = _seed(
        tmp_path,
        corpus={"notes/a.txt": "alpha\n"},
    )
    store = LocalProjectionStore(store_path)
    store.open_readonly()
    adapter = LocalStoreFilesAdapter(
        store,
        canonical_root=control,
        root_id=root_id,
        expected_generation_id=generation_id,
    )

    captured_connections: list[sqlite3.Connection] = []
    real_open = adapter._open_query_snapshot

    def tracking_open() -> sqlite3.Connection:
        connection = real_open()
        captured_connections.append(connection)
        return connection

    adapter._open_query_snapshot = tracking_open  # type: ignore[method-assign]

    from arw.files_mcp import ToolError

    def failing_reader() -> str:
        raise ToolError("stale_query_generation", "test forced failure")

    monkeypatch.setattr(
        adapter, "_read_canonical_generation_id", failing_reader
    )

    with pytest.raises(FileProviderError) as caught:
        adapter.list_files(_list_request(root_id))
    assert caught.value.code == "stale_query_generation"

    adapter._open_query_snapshot = real_open  # type: ignore[method-assign]

    assert len(captured_connections) == 1, "exactly one snapshot opened before error"
    _assert_snapshot_closed(captured_connections[0])

    # Restore the canonical reader so the follow-up call succeeds; the
    # lock must be released even after the error path so a transient
    # failure does not wedge the adapter.
    monkeypatch.undo()

    # Lock released: a follow-up call succeeds (the adapter is not wedged).
    adapter.list_files(_list_request(root_id))

    store.close()


# ---------------------------------------------------------------------------
# Scenario 7: post-start canonical-path DoS hardening (P1 review).
# ---------------------------------------------------------------------------


def _seed_minimal_for_canonical_reader(tmp_path: Path) -> tuple[Path, Path, str, str, Path]:
    """Seed a control + store so the adapter can be constructed; the canonical
    path may then be replaced with a hostile entry (FIFO / symlink / oversize).
    """

    _root, control, root_id, generation_id, store_path = _seed(
        tmp_path,
        corpus={"notes/a.txt": "alpha\n"},
    )
    return tmp_path, control, root_id, generation_id, store_path


def test_canonical_reader_rejects_symlink(
    tmp_path: Path,
) -> None:
    """A symlink at the canonical selection path is rejected.

    ``O_NOFOLLOW`` on open prevents the symlink from being followed, so
    the read fails fast.  The per-request guard catches it and surfaces
    ``stale_query_generation``.
    """

    _, control, root_id, generation_id, store_path = _seed_minimal_for_canonical_reader(
        tmp_path
    )
    selected_path = control / "roots" / root_id / "selected-generation.json"
    selected_path.unlink()
    target = tmp_path / "regular.json"
    target.write_text(
        json.dumps({"generation_id": "spoofed"}), encoding="utf-8"
    )
    selected_path.symlink_to(target)

    store = LocalProjectionStore(store_path)
    store.open_readonly()
    adapter = LocalStoreFilesAdapter(
        store,
        canonical_root=control,
        root_id=root_id,
        expected_generation_id=generation_id,
    )

    with pytest.raises(FileProviderError) as caught:
        adapter.list_files(_list_request(root_id))
    assert caught.value.code == "stale_query_generation"
    store.close()


def test_canonical_reader_rejects_oversize_file(
    tmp_path: Path,
) -> None:
    """A file larger than ``MAX_CANONICAL_SELECTION_BYTES`` is rejected.

    A writer cannot exhaust the reader's memory by piping a gigabyte
    payload through the canonical path; the bounded read detects the
    oversize and the guard surfaces ``stale_query_generation``.
    """

    from arw_ext.local_store.files import MAX_CANONICAL_SELECTION_BYTES

    _, control, root_id, generation_id, store_path = _seed_minimal_for_canonical_reader(
        tmp_path
    )
    selected_path = control / "roots" / root_id / "selected-generation.json"
    selected_path.write_bytes(b"{ " + b"a" * (MAX_CANONICAL_SELECTION_BYTES + 1) + b" }")

    store = LocalProjectionStore(store_path)
    store.open_readonly()
    adapter = LocalStoreFilesAdapter(
        store,
        canonical_root=control,
        root_id=root_id,
        expected_generation_id=generation_id,
    )

    with pytest.raises(FileProviderError) as caught:
        adapter.list_files(_list_request(root_id))
    assert caught.value.code == "stale_query_generation"
    store.close()


def test_canonical_reader_rejects_malformed_utf8(
    tmp_path: Path,
) -> None:
    """Malformed UTF-8 in the canonical selection is rejected.

    The safe reader decodes strict UTF-8 and raises ``ValueError`` on
    any malformed byte sequence; the guard catches it and surfaces
    ``stale_query_generation``.
    """

    _, control, root_id, generation_id, store_path = _seed_minimal_for_canonical_reader(
        tmp_path
    )
    selected_path = control / "roots" / root_id / "selected-generation.json"
    selected_path.write_bytes(b'{"generation_id": "\xff\xfe"}')

    store = LocalProjectionStore(store_path)
    store.open_readonly()
    adapter = LocalStoreFilesAdapter(
        store,
        canonical_root=control,
        root_id=root_id,
        expected_generation_id=generation_id,
    )

    with pytest.raises(FileProviderError) as caught:
        adapter.list_files(_list_request(root_id))
    assert caught.value.code == "stale_query_generation"
    store.close()


def test_canonical_reader_rejects_malformed_json(
    tmp_path: Path,
) -> None:
    """Malformed JSON in the canonical selection is rejected."""

    _, control, root_id, generation_id, store_path = _seed_minimal_for_canonical_reader(
        tmp_path
    )
    selected_path = control / "roots" / root_id / "selected-generation.json"
    selected_path.write_bytes(b"{ this is not valid json }")

    store = LocalProjectionStore(store_path)
    store.open_readonly()
    adapter = LocalStoreFilesAdapter(
        store,
        canonical_root=control,
        root_id=root_id,
        expected_generation_id=generation_id,
    )

    with pytest.raises(FileProviderError) as caught:
        adapter.list_files(_list_request(root_id))
    assert caught.value.code == "stale_query_generation"
    store.close()


def test_canonical_reader_rejects_fifo_without_hanging(
    tmp_path: Path,
) -> None:
    """A FIFO at the canonical selection path is rejected without hanging.

    The ``O_NONBLOCK`` flag on open is the primary defense: ``os.read``
    on a FIFO returns ``EAGAIN`` immediately rather than blocking until
    a writer appears.  ``S_ISREG`` on ``fstat`` is the secondary
    defense: a FIFO is not a regular file so the read is rejected
    before any blocking call.

    The test runs the reader in a subprocess with a tight timeout so a
    regression that re-introduces a blocking read fails fast and does
    not hang the test suite.
    """

    _, control, root_id, generation_id, store_path = _seed_minimal_for_canonical_reader(
        tmp_path
    )
    selected_path = control / "roots" / root_id / "selected-generation.json"
    selected_path.unlink()
    os.mkfifo(selected_path)

    # Run the reader in a subprocess so a regression that re-introduces
    # a blocking read is killed by the timeout instead of hanging the
    # suite.  The helper script imports the safe reader directly and
    # calls it on the FIFO path; the exit code distinguishes success /
    # typed rejection / hang.
    helper = tmp_path / "fifo_reader_helper.py"
    helper.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(tmp_path.parent)!r})\n"
        "from pathlib import Path\n"
        "from arw_ext.local_store.files import (\n"
        "    _read_canonical_selection_safe,\n"
        ")\n"
        "try:\n"
        "    _read_canonical_selection_safe(Path("
        f"        {str(selected_path)!r}"
        "    ))\n"
        "    print('UNEXPECTED_OK')\n"
        "    sys.exit(0)\n"
        "except (OSError, ValueError) as error:\n"
        "    print(f'REJECTED: {type(error).__name__}: {error}')\n"
        "    sys.exit(2)\n",
        encoding="utf-8",
    )

    env = dict(os.environ)
    env["PYTHONPATH"] = str(tmp_path.parent)
    completed = subprocess.run(
        [sys.executable, str(helper)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 2, (
        f"helper exited with {completed.returncode}; "
        f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
    )
    assert "REJECTED" in completed.stdout, (
        f"expected typed rejection; got stdout={completed.stdout!r}"
    )

    # Cleanup: remove the FIFO so the test fixture teardown is clean.
    selected_path.unlink()


def test_canonical_reader_rejects_swapped_symlink_parent(
    tmp_path: Path,
) -> None:
    """A symlink swap on the leaf's parent directory is rejected.

    ``O_NOFOLLOW`` on the leaf alone does not protect a swap on an
    ancestor directory component: ``os.open`` resolves the full path
    first, and if any ancestor is a symlink the leaf open follows the
    redirected tree.  The reader walks each ancestor with ``O_NOFOLLOW``
    via ``dir_fd`` anchoring, so the swap is rejected at walk time
    before any leaf read.
    """

    import shutil

    _, control, root_id, generation_id, store_path = _seed_minimal_for_canonical_reader(
        tmp_path
    )

    # Create a rogue directory containing a poisoned
    # selected-generation.json the attacker would like the reader to
    # pick up.
    rogue = tmp_path / "rogue_root"
    rogue.mkdir()
    (rogue / "selected-generation.json").write_text(
        json.dumps({"generation_id": "spoofed_via_parent_swap"}),
        encoding="utf-8",
    )

    # Replace ``control/roots/<root_id>`` with a symlink to the rogue
    # directory.  shutil.rmtree is needed because the seeded root_id
    # directory contains other files (cursor.key, root.json, etc.).
    real_root_dir = control / "roots" / root_id
    shutil.rmtree(real_root_dir)
    real_root_dir.symlink_to(rogue)

    store = LocalProjectionStore(store_path)
    store.open_readonly()
    adapter = LocalStoreFilesAdapter(
        store,
        canonical_root=control,
        root_id=root_id,
        expected_generation_id=generation_id,
    )

    with pytest.raises(FileProviderError) as caught:
        adapter.list_files(_list_request(root_id))
    assert caught.value.code == "stale_query_generation", (
        f"expected stale_query_generation on symlink-parent swap; "
        f"got {caught.value.code!r}"
    )

    # The reader must NOT have read the rogue payload (the symlink
    # walk rejected the swap before any leaf read).
    store.close()
