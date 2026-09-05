"""Regression coverage for PR15 historical findings against the store-backed
files MCP transport.

Targets four review-node findings the prior audit pinned against
``src/arw/files_store_mcp.py`` and the installed launcher:

* ``degraded`` / ``no_structure`` outline/context results must NOT be
  delivered as ``isError=True`` envelopes (PRRC_kwDOTWKrXs7pZqjr — status).
* Argument ``ValidationError`` must surface as ``error_code="invalid_request"``
  rather than the generic ``"tool_error"`` (PRRC_kwDOTWKrXs7pZqj1 —
  validation).
* The mutable cache's ``canonical_path`` MUST be cross-checked against the
  externally configured allowed root; tampered or mismatched caches must be
  refused (PRRC_kwDOTWKrXs7pZqj9 — root).
* The installed launcher routes through the store-backed reader when the
  store exists; falls back to the v1 reader only when no store is present
  (PRRC_kwDOTWKrXs7pZqjj — routing).
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest
from arw_ext.local_store import LocalProjectionStore, LocalStoreFilesAdapter
from arw_ext.local_store.ingest import ingest_files_generation

from arw.adapters.files import FileProviderError
from arw.file_models import (
    FilesContextRequest,
    FilesOutlineRequest,
    SourceLocation,
)
from arw.files import FilesAdminService, load_query_generation
from arw.files_store_mcp import (
    _handle,
    _open_store_adapter,
    _resolve_allowed_root,
    build_parser,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _service_factory(control: Path) -> FilesAdminService:
    """Build a FilesAdminService with a per-call unique ID salt.

    The counter alone is deterministic per call, which previously caused
    generation_id collisions across sequential sync attempts in the same
    control directory (e.g. tests that re-sync after mutating the live
    corpus — the second sync could not rename its candidate onto the
    final path because the first sync's directory was still there).
    Embedding a per-instance UUID salt keeps IDs unique within a single
    test process without disturbing the human-readable prefix.
    """
    sequence = itertools.count(1)
    salt = uuid.uuid4().hex[:8]
    return FilesAdminService(
        control,
        id_factory=lambda kind: f"{kind}_test_{salt}_{next(sequence):03d}",
        clock=lambda: "2026-07-14T00:00:00Z",
    )


def _write_corpus(root: Path, corpus: dict[str, str]) -> None:
    """Write text corpus under ``root`` (utf-8)."""
    for relative_path, content in corpus.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _sync_and_ingest(
    control: Path,
    root_id: str,
    *,
    store_path: Path,
) -> str:
    """Run ``service.sync`` then ingest the new generation into ``store_path``.

    Returns the selected generation_id.
    """
    service = _service_factory(control)
    receipt = service.sync(root_id, extractor_version="1.0.0")
    assert receipt.selected_generation_id is not None
    generation = load_query_generation(control, root_id)
    store = LocalProjectionStore(store_path)
    store.open()
    ingest_files_generation(store.connection, generation)
    store.connection.commit()
    store.close()
    return receipt.selected_generation_id


def _seed_corpus(
    tmp_path: Path,
    *,
    corpus: dict[str, str],
) -> tuple[Path, Path, str, str]:
    """Seed a registered root, sync, and ingest into a workspace-local store.

    Returns (root, control, root_id, generation_id).
    """
    root = tmp_path / "root"
    _write_corpus(root, corpus)
    control = tmp_path / "control"
    service = _service_factory(control)
    service.register_root(
        root_id="research-root", root_path=root, policy_id="research-files-v1"
    )
    store_path = tmp_path / "arw.db"
    generation_id = _sync_and_ingest(
        control, "research-root", store_path=store_path
    )
    return root, control, "research-root", generation_id


def _resync_and_reingest(
    control: Path,
    root_id: str,
    *,
    store_path: Path,
) -> str:
    """Re-sync the registered root (so live changes are picked up) and re-ingest.

    Returns the new selected generation_id.
    """
    service = _service_factory(control)
    receipt = service.sync(root_id, extractor_version="1.0.0")
    assert receipt.selected_generation_id is not None
    generation = load_query_generation(control, root_id)
    store = LocalProjectionStore(store_path)
    store.open()
    ingest_files_generation(store.connection, generation)
    store.connection.commit()
    store.close()
    return receipt.selected_generation_id


def _open_adapter(store_path: Path):
    store = LocalProjectionStore(store_path)
    store.open_readonly()
    return LocalStoreFilesAdapter(store)


# ---------------------------------------------------------------------------
# Finding #1 (status): degraded / no_structure outline/context → isError=False
# ---------------------------------------------------------------------------


def test_degraded_outline_status_is_not_error(tmp_path: Path) -> None:
    """A text file with non-UTF-8 bytes produces ``degraded`` outline status.

    The MCP envelope must deliver that body with ``isError=False`` so the
    client can still read the structured status (PR15 PRRC_kwDOTWKrXs7pZqjr).
    A regression here would mark it ``isError=True`` and hide the body.
    """
    # Stage 1: register + initial sync (text placeholder).
    root = tmp_path / "root"
    control = tmp_path / "control"
    (root / "notes").mkdir(parents=True)
    (root / "notes/bad.txt").write_text("", encoding="utf-8")
    service = _service_factory(control)
    service.register_root(
        root_id="research-root", root_path=root, policy_id="research-files-v1"
    )
    store_path = tmp_path / "arw.db"
    _sync_and_ingest(control, "research-root", store_path=store_path)

    # Stage 2: overwrite live file with non-UTF-8 bytes + resync + re-ingest.
    (root / "notes/bad.txt").write_bytes(b"\xff\x00\x80abc")
    generation_id = _resync_and_reingest(
        control, "research-root", store_path=store_path
    )

    adapter = _open_adapter(store_path)
    listed = adapter.list_files(_make_list_request("research-root", generation_id))
    assert listed.files, "list_files should report at least the seeded file"
    entry = next(
        entry for entry in listed.files if entry.relative_path == "notes/bad.txt"
    )
    # ``FileListEntry.indexed_digest`` is ``Sha256 | None``; the request
    # contract requires a concrete digest, so we narrow before building it.
    assert entry.indexed_digest is not None, (
        f"seeded entry must carry an indexed digest; got {entry!r}"
    )
    request = FilesOutlineRequest(
        schema_version="1.0.0",
        root_id="research-root",
        generation_id=generation_id,
        file_id=entry.file_id,
        expected_digest=entry.indexed_digest,
        max_nodes=20,
        cursor=None,
    )

    response = _handle(adapter, _tools_call("get_outline", 1, request.model_dump(mode="json")))
    assert response is not None
    assert response.get("error") is None
    envelope = response["result"]
    assert isinstance(envelope, dict), (
        f"tool envelope must be a dict; got {type(envelope).__name__}"
    )
    assert envelope["isError"] is False, (
        "degraded outline must NOT be marked isError (v1 wire parity)"
    )
    payload = json.loads(envelope["content"][0]["text"])
    assert isinstance(payload, dict), (
        f"tool payload must be a JSON object; got {type(payload).__name__}"
    )
    assert payload["status"] == "degraded", (
        f"expected degraded, got {payload['status']!r}"
    )


def test_no_structure_outline_status_is_not_error(tmp_path: Path) -> None:
    """Plain-text files produce ``no_structure`` (empty node list).

    The envelope must carry ``isError=False`` — a regression would mark it
    as an error and lose the structured status payload.
    """
    _, _control, root_id, generation_id = _seed_corpus(
        tmp_path,
        corpus={
            # plain .txt -> no markdown headings -> no_structure
            "notes/plain.txt": "alpha line\nbeta line\n",
        },
    )

    adapter = _open_adapter(tmp_path / "arw.db")
    listed = adapter.list_files(_make_list_request(root_id, generation_id))
    plain_entry = next(
        entry for entry in listed.files if entry.relative_path == "notes/plain.txt"
    )
    # ``FileListEntry.indexed_digest`` is ``Sha256 | None``; narrow before
    # passing into a request field that requires ``Sha256``.
    assert plain_entry.indexed_digest is not None, (
        f"seeded entry must carry an indexed digest; got {plain_entry!r}"
    )
    request = FilesOutlineRequest(
        schema_version="1.0.0",
        root_id=root_id,
        generation_id=generation_id,
        file_id=plain_entry.file_id,
        expected_digest=plain_entry.indexed_digest,
        max_nodes=20,
        cursor=None,
    )

    response = _handle(adapter, _tools_call("get_outline", 1, request.model_dump(mode="json")))
    assert response is not None
    assert response.get("error") is None
    envelope = response["result"]
    assert isinstance(envelope, dict), (
        f"tool envelope must be a dict; got {type(envelope).__name__}"
    )
    assert envelope["isError"] is False, (
        "no_structure outline must NOT be marked isError (v1 wire parity)"
    )
    payload = json.loads(envelope["content"][0]["text"])
    assert isinstance(payload, dict), (
        f"tool payload must be a JSON object; got {type(payload).__name__}"
    )
    assert payload["status"] == "no_structure"


def test_degraded_context_status_is_not_error(tmp_path: Path) -> None:
    """A text file with non-UTF-8 bytes produces ``degraded`` context status.

    The envelope must carry ``isError=False`` (PR15 finding).
    """
    # Stage 1: register + initial sync (text placeholder).
    root = tmp_path / "root"
    control = tmp_path / "control"
    (root / "notes").mkdir(parents=True)
    (root / "notes/bad.txt").write_text("", encoding="utf-8")
    service = _service_factory(control)
    service.register_root(
        root_id="research-root", root_path=root, policy_id="research-files-v1"
    )
    store_path = tmp_path / "arw.db"
    _sync_and_ingest(control, "research-root", store_path=store_path)

    # Stage 2: overwrite with non-UTF-8 bytes + resync + re-ingest.
    (root / "notes/bad.txt").write_bytes(b"\xff\x00\x80abc")
    generation_id = _resync_and_reingest(
        control, "research-root", store_path=store_path
    )

    adapter = _open_adapter(store_path)
    listed = adapter.list_files(_make_list_request("research-root", generation_id))
    entry = next(
        entry for entry in listed.files if entry.relative_path == "notes/bad.txt"
    )
    # ``FileListEntry.indexed_digest`` is ``Sha256 | None``; narrow before
    # passing into a request field that requires ``Sha256``.
    assert entry.indexed_digest is not None, (
        f"seeded entry must carry an indexed digest; got {entry!r}"
    )
    request = FilesContextRequest(
        schema_version="1.0.0",
        root_id="research-root",
        generation_id=generation_id,
        file_id=entry.file_id,
        expected_digest=entry.indexed_digest,
        hit_id=None,
        location=SourceLocation(
            start_byte=0, end_byte=1, start_line=1, end_line=1
        ),
        before_lines=2,
        after_lines=2,
    )

    response = _handle(adapter, _tools_call("get_context", 1, request.model_dump(mode="json")))
    assert response is not None
    assert response.get("error") is None
    envelope = response["result"]
    assert isinstance(envelope, dict), (
        f"tool envelope must be a dict; got {type(envelope).__name__}"
    )
    assert envelope["isError"] is False, (
        "degraded context must NOT be marked isError (v1 wire parity)"
    )
    payload = json.loads(envelope["content"][0]["text"])
    assert isinstance(payload, dict), (
        f"tool payload must be a JSON object; got {type(payload).__name__}"
    )
    assert payload["status"] == "degraded", (
        f"expected degraded, got {payload['status']!r}"
    )


# ---------------------------------------------------------------------------
# Finding #2 (validation): ValidationError -> invalid_request (not tool_error)
# ---------------------------------------------------------------------------


def test_invalid_arguments_surfaces_invalid_request_error(tmp_path: Path) -> None:
    """An invalid request body surfaces ``error_code="invalid_request"``.

    The previous code mapped ``ValidationError`` to the generic
    ``"tool_error"`` bucket, which differs from v1 (``"invalid_request"``)
    and breaks clients that branch on the documented taxonomy.
    """
    _, _control, root_id, _ = _seed_corpus(
        tmp_path,
        corpus={"notes/a.txt": "alpha\nbeta\n"},
    )
    store_path = tmp_path / "arw.db"
    adapter = _open_adapter(store_path)

    # ``max_nodes=0`` violates the ge=1 contract -> ValidationError.
    bad_arguments = {
        "schema_version": "1.0.0",
        "root_id": root_id,
        "generation_id": "ignored",
        "file_id": "ignored",
        "expected_digest": hashlib.sha256(b"x").hexdigest(),
        "max_nodes": 0,  # invalid: minimum is 1
        "cursor": None,
    }
    response = _handle(adapter, _tools_call("get_outline", 1, bad_arguments))
    assert response is not None
    assert response.get("error") is None
    envelope = response["result"]
    assert isinstance(envelope, dict), (
        f"tool envelope must be a dict; got {type(envelope).__name__}"
    )
    assert envelope["isError"] is True
    payload = json.loads(envelope["content"][0]["text"])
    assert isinstance(payload, dict), (
        f"tool payload must be a JSON object; got {type(payload).__name__}"
    )
    assert payload["error_code"] == "invalid_request", (
        f"expected invalid_request, got {payload['error_code']!r}"
    )
    assert payload["error_code"] != "tool_error"


def test_unknown_tool_surfaces_unknown_tool_error(tmp_path: Path) -> None:
    """The unknown-tool path stays as ``unknown_tool`` (not tool_error).

    Guards against an accidental catch-all that swallows dispatch failures.
    """
    _, _control, _root_id, _ = _seed_corpus(
        tmp_path,
        corpus={"notes/a.txt": "alpha\nbeta\n"},
    )
    store_path = tmp_path / "arw.db"
    adapter = _open_adapter(store_path)

    response = _handle(adapter, _tools_call("not_a_real_tool", 1, {}))
    assert response is not None
    envelope = response["result"]
    assert isinstance(envelope, dict), (
        f"tool envelope must be a dict; got {type(envelope).__name__}"
    )
    assert envelope["isError"] is True
    payload = json.loads(envelope["content"][0]["text"])
    assert isinstance(payload, dict), (
        f"tool payload must be a JSON object; got {type(payload).__name__}"
    )
    assert payload["error_code"] == "unknown_tool"


# ---------------------------------------------------------------------------
# Finding #3 (root): cache canonical_path / root_id cross-checked
# ---------------------------------------------------------------------------


def test_constructor_accepts_matching_allowed_root(tmp_path: Path) -> None:
    """When the cache and the registered root agree, construction succeeds.

    Positive control for the security check below.
    """
    _, _control, root_id, _ = _seed_corpus(
        tmp_path,
        corpus={"notes/a.txt": "alpha\nbeta\n"},
    )
    store_path = tmp_path / "arw.db"
    store = LocalProjectionStore(store_path)
    store.open_readonly()
    try:
        adapter = LocalStoreFilesAdapter(
            store,
            allowed_root=tmp_path / "root",
            expected_root_id=root_id,
        )
    finally:
        store.close()
    # And the adapter actually serves the corpus.
    assert adapter._canonical_path == str((tmp_path / "root").resolve())


def test_constructor_rejects_tampered_canonical_path(tmp_path: Path) -> None:
    """If the cache's ``canonical_path`` lies, the adapter refuses to start.

    The cache is mutable on disk; without this check, an attacker who
    rewrites ``projection_meta`` could redirect live reads anywhere on the
    filesystem.
    """
    _, _control, root_id, _ = _seed_corpus(
        tmp_path,
        corpus={"notes/a.txt": "alpha\nbeta\n"},
    )
    store_path = tmp_path / "arw.db"

    # Tamper: rewrite the cached canonical_path to point OUTSIDE the root.
    import sqlite3
    with sqlite3.connect(store_path) as connection:
        connection.execute(
            "UPDATE projection_meta SET value = ? WHERE key = 'files.canonical_path'",
            (str(tmp_path / "somewhere_else"),),
        )
        connection.commit()

    store = LocalProjectionStore(store_path)
    store.open_readonly()
    try:
        with pytest.raises(FileProviderError) as caught:
            LocalStoreFilesAdapter(
                store,
                allowed_root=tmp_path / "root",
                expected_root_id=root_id,
            )
        assert caught.value.code == "root_denied"
    finally:
        store.close()


def test_constructor_rejects_mismatched_root_id(tmp_path: Path) -> None:
    """If the cache's recorded ``root_id`` mismatches, the adapter refuses.

    Defense in depth against a swapped cache binding (a stored cache from
    root A served as if it were root B).
    """
    _, _control, _root_id, _ = _seed_corpus(
        tmp_path,
        corpus={"notes/a.txt": "alpha\nbeta\n"},
    )
    store_path = tmp_path / "arw.db"
    store = LocalProjectionStore(store_path)
    store.open_readonly()
    try:
        with pytest.raises(FileProviderError) as caught:
            LocalStoreFilesAdapter(
                store,
                allowed_root=tmp_path / "root",
                expected_root_id="not-the-registered-root",
            )
        assert caught.value.code == "root_denied"
    finally:
        store.close()


def test_constructor_requires_paired_allowed_root_and_root_id(tmp_path: Path) -> None:
    """Supplying one anchor without the other is refused.

    Catches a partial-overrides typo at the launch site.
    """
    _, _control, root_id, _ = _seed_corpus(
        tmp_path,
        corpus={"notes/a.txt": "alpha\nbeta\n"},
    )
    store_path = tmp_path / "arw.db"
    store = LocalProjectionStore(store_path)
    store.open_readonly()
    try:
        with pytest.raises(FileProviderError) as caught:
            LocalStoreFilesAdapter(
                store,
                allowed_root=tmp_path / "root",
                expected_root_id=None,
            )
        assert caught.value.code == "root_denied"
    finally:
        store.close()

    store = LocalProjectionStore(store_path)
    store.open_readonly()
    try:
        with pytest.raises(FileProviderError) as caught:
            LocalStoreFilesAdapter(
                store,
                allowed_root=None,
                expected_root_id=root_id,
            )
        assert caught.value.code == "root_denied"
    finally:
        store.close()


def test_resolve_allowed_root_reads_authoritative_registration(tmp_path: Path) -> None:
    """``_resolve_allowed_root`` reads root.json, NOT a path formula.

    The brief explicitly distrusts the suggested
    ``<control_root>/<root_id>`` formula.  This test pins that we read
    ``root.json`` so the canonical_path matches the registered one.
    """
    _, control, root_id, _ = _seed_corpus(
        tmp_path,
        corpus={"notes/a.txt": "alpha\nbeta\n"},
    )
    allowed_root, resolved_root_id = _resolve_allowed_root(control, root_id)
    assert allowed_root == (tmp_path / "root").resolve()
    assert resolved_root_id == root_id


# ---------------------------------------------------------------------------
# Finding #4 (routing): process accepts --control-root/--root-id
# ---------------------------------------------------------------------------


def test_parser_requires_control_root_and_root_id_together(tmp_path: Path) -> None:
    """The CLI parser leaves --control-root/--root-id optional but
    ``main()`` rejects them missing (fail-closed); the parser itself
    tolerates the legacy test shape (no flags → no args) so unit tests
    can exercise it without touching the runtime check.
    """
    parser = build_parser()
    # No flags: argparse still parses (defaults); main() rejects it.
    args = parser.parse_args(["--store", str(tmp_path / "store.db")])
    assert args.store == tmp_path / "store.db"
    assert args.control_root is None
    assert args.root_id is None
    # Pair is accepted.
    args = parser.parse_args(
        [
            "--store",
            str(tmp_path / "store.db"),
            "--control-root",
            str(tmp_path / "control"),
            "--root-id",
            "research-root",
        ]
    )
    assert args.control_root == tmp_path / "control"
    assert args.root_id == "research-root"


def test_main_rejects_missing_anchor(tmp_path: Path) -> None:
    """``main()`` exits 64 (fail-closed) when --control-root/--root-id
    are absent.  The legacy in-process path that opened without external
    anchors is gone, so a missing anchor is no longer a "happy path".
    """
    from arw.files_store_mcp import main

    exit_code = main(
        [
            "--store",
            str(tmp_path / "store.db"),
        ]
    )
    assert exit_code == 64, (
        f"missing anchor must fail closed (64), got {exit_code}"
    )


def test_main_rejects_paired_only_one_flag(tmp_path: Path) -> None:
    """One of --control-root/--root-id without the other is rejected."""
    from arw.files_store_mcp import main

    exit_code = main(
        [
            "--store",
            str(tmp_path / "store.db"),
            "--control-root",
            str(tmp_path / "control"),
        ]
    )
    assert exit_code == 64
    exit_code = main(
        [
            "--store",
            str(tmp_path / "store.db"),
            "--root-id",
            "research-root",
        ]
    )
    assert exit_code == 64


def test_open_store_adapter_uses_registered_canonical_path(tmp_path: Path) -> None:
    """``_open_store_adapter`` returns an adapter bound to the registered root.

    Guards against an accidental swap to ``<control_root>/<root_id>`` or
    the raw caller-supplied path.
    """
    _, control, root_id, _ = _seed_corpus(
        tmp_path,
        corpus={"notes/a.txt": "alpha\nbeta\n"},
    )
    store_path = tmp_path / "arw.db"
    allowed_root, expected_root_id = _resolve_allowed_root(control, root_id)
    adapter = _open_store_adapter(
        store_path, allowed_root=allowed_root, expected_root_id=expected_root_id
    )
    try:
        assert adapter._canonical_path == str((tmp_path / "root").resolve())
        assert adapter._root_id == root_id
    finally:
        # The adapter is constructed over a store opened by the helper;
        # close it on teardown so we don't leak the read-only connection.
        adapter._store.close()


# ---------------------------------------------------------------------------
# Finding #5 (subprocess): installed shim + store MCP fail-closed
# ---------------------------------------------------------------------------


def _seed_corpus_with_root_id(tmp_path: Path, root_id: str) -> tuple[Path, Path]:
    """Seed a registered root with a caller-chosen root_id."""
    root = tmp_path / "root"
    _write_corpus(root, {"notes/a.txt": "alpha\nbeta\n"})
    control = tmp_path / "control"
    service = _service_factory(control)
    service.register_root(
        root_id=root_id, root_path=root, policy_id="research-files-v1"
    )
    store_path = tmp_path / "arw.db"
    _sync_and_ingest(control, root_id, store_path=store_path)
    return control, store_path


def _invoke_store_mcp(
    *,
    arguments: list[str],
    stdin_payload: bytes | None = None,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Spawn the installed store MCP as a real subprocess.

    The shim binary itself is exercised separately below; this helper
    bypasses the shim so the test can pin a precise exit code independent
    of the shim's STORE_ABSENT-fallback policy.  We clear PYTHONPATH so
    the venv python resolves ``arw.files_store_mcp`` from the working
    tree regardless of the parent shell.
    """
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "TMPDIR": os.environ.get("TMPDIR", tempfile.gettempdir()),
    }
    if env_extra:
        environment.update(env_extra)
    # Keep PYTHONPATH unset so the venv wins; the venv is the python we
    # invoke, so we let PYTHONHOME etc. fall through naturally.
    environment.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, "-m", "arw.files_store_mcp", *arguments],
        input=stdin_payload,
        capture_output=True,
        env=environment,
        timeout=30,
        check=False,
    )


def _invoke_shim(
    *,
    plugin_root: Path,
    control_root: Path,
    root_id: str,
    store_path: Path | None = None,
    stdin_payload: bytes | None = None,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Spawn the shim from an isolated plugin copy as a real subprocess.

    The shim hardcodes ``$PLUGIN_ROOT/bin/arw``; since we can't redirect
    that, we point the shim at a tmp_path plugin root whose ``bin/arw``
    is a pass-through stub (see :func:`_stage_stub_plugin`).  No real
    repository file is touched; concurrent or aborted test runs are safe
    because the stub plugin lives entirely under tmp_path.
    """
    shim = plugin_root / "scripts" / "file-base-mcp"
    environment = os.environ.copy()
    environment["ARW_FILES_CONTROL_ROOT"] = str(control_root)
    environment["ARW_FILES_ROOT_ID"] = root_id
    if store_path is not None:
        environment["ARW_FILES_STORE"] = str(store_path)
    if env_extra:
        environment.update(env_extra)
    return subprocess.run(
        [str(shim)],
        input=stdin_payload,
        capture_output=True,
        env=environment,
        timeout=30,
        check=False,
    )


_STUB_BIN_ARW_TEMPLATE = """#!/usr/bin/env bash
# Test-only stub for bin/arw. Bypasses the real bootstrap (the in-repo
# wheelhouse.lock.json at HEAD has a pre-existing inconsistency that is
# out of scope for this patch) and forwards directly to the in-repo
# venv python for the subcommands the shim routes to.
set -euo pipefail
REAL_VENV="{real_venv}"

case "$1" in
  _files-mcp)
    shift
    exec "$REAL_VENV" -m arw.files_mcp "$@"
    ;;
  _files-store-mcp)
    shift
    exec "$REAL_VENV" -m arw.files_store_mcp "$@"
    ;;
  *)
    echo "stub-bin-arw: unsupported subcommand: $1" >&2
    exit 64
    ;;
esac
"""


def _stage_stub_plugin(tmp_path: Path) -> Path:
    """Create an isolated plugin copy with a stub ``bin/arw``.

    Returns the plugin root directory.  The shim computes its
    ``PLUGIN_ROOT`` from its own location, so by placing a copy of the
    shim under ``<tmp>/plugin/scripts/`` we redirect its dispatch into
    ``<tmp>/plugin/bin/arw`` — the stub.  The stub calls the real venv
    python directly, so we exercise the shim's full dispatch logic
    (routing, fallback, env validation) without going through the real
    ``bin/arw`` bootstrap or any installed-mode machinery.

    The real repository is not modified.  Everything lives under tmp_path;
    concurrent test runs and SIGKILL are both safe.
    """
    plugin_root = tmp_path / "plugin"
    bin_dir = plugin_root / "bin"
    scripts_dir = plugin_root / "scripts"
    bin_dir.mkdir(parents=True)
    scripts_dir.mkdir(parents=True)

    real_venv = REPOSITORY_ROOT / ".venv" / "bin" / "python"
    (bin_dir / "arw").write_text(
        _STUB_BIN_ARW_TEMPLATE.format(real_venv=str(real_venv))
    )
    (bin_dir / "arw").chmod(0o755)

    shim_src = REPOSITORY_ROOT / "scripts" / "file-base-mcp"
    shim_dst = scripts_dir / "file-base-mcp"
    shim_dst.write_text(shim_src.read_text())
    shim_dst.chmod(0o755)

    return plugin_root


def test_subprocess_shim_dispatches_to_store_mcp(tmp_path: Path) -> None:
    """End-to-end: the installed shim really launches the store MCP.

    Not a string search on the shim — we spawn it as a subprocess and
    exchange a JSON-RPC ``initialize`` handshake, asserting the response
    carries the store MCP server name (``academic-research-files-store``,
    distinct from v1's ``academic-research-files``).  A regression that
    routes back to v1 would echo the v1 name and fail this test.
    """
    control, store_path = _seed_corpus_with_root_id(tmp_path, "research-root")
    plugin_root = _stage_stub_plugin(tmp_path)
    request = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        }
    ).encode("utf-8") + b"\n"

    completed = _invoke_shim(
        plugin_root=plugin_root,
        control_root=control,
        root_id="research-root",
        store_path=store_path,
        stdin_payload=request,
    )
    assert completed.returncode == 0, (
        f"shim must exit 0 on a healthy initialize, got "
        f"{completed.returncode}; stderr={completed.stderr!r}"
    )
    line = next(
        (
            chunk
            for chunk in completed.stdout.splitlines()
            if chunk.strip().startswith(b"{")
        ),
        b"",
    )
    assert line, (
        f"shim produced no JSON-RPC response; stdout={completed.stdout!r}"
    )
    response = json.loads(line)
    server_info = response["result"]["serverInfo"]
    assert server_info["name"] == "academic-research-files-store", (
        f"shim dispatched to {server_info['name']!r}, expected the store "
        f"MCP; a v1 fallback would have produced 'academic-research-files'"
    )


def test_subprocess_missing_anchor_exits_64(tmp_path: Path) -> None:
    """Invoking the store MCP without --control-root/--root-id fails
    closed with exit code 64 (the no-anchor legacy branch is gone).
    """
    completed = _invoke_store_mcp(
        arguments=["--store", str(tmp_path / "missing-store.db")],
    )
    assert completed.returncode == 64, (
        f"missing anchor must fail closed (64), got {completed.returncode}; "
        f"stderr={completed.stderr.decode('utf-8', errors='replace')!r}"
    )
    # The legacy 'in-process test path' branch is gone: the server must
    # never start a JSON-RPC loop without an external anchor.
    assert b"STORE_ABSENT" not in completed.stderr, (
        "missing anchor is a configuration error (64), not STORE_ABSENT (69)"
    )


def test_subprocess_store_absent_returns_69_before_stdin(
    tmp_path: Path,
) -> None:
    """When --control-root/--root-id are valid but the resolved store
    file does not exist, the store MCP exits 69 (STORE_ABSENT) BEFORE
    reading any stdin.  This is the dedicated signal for "store not set
    up yet" so the shim can fall back to v1 only on this path.
    """
    root = tmp_path / "root"
    root.mkdir(parents=True)
    (root / "notes").mkdir(parents=True)
    (root / "notes/a.txt").write_text("alpha\n", encoding="utf-8")
    control = tmp_path / "control"
    service = _service_factory(control)
    service.register_root(
        root_id="research-root", root_path=root, policy_id="research-files-v1"
    )
    # Sync once so the registered root has a selected generation (needed
    # by ``load_query_generation`` to resolve the security anchors); the
    # store file is intentionally NOT created at the resolved path, so
    # the server reaches the STORE_ABSENT check after the anchor step.
    service.sync("research-root", extractor_version="1.0.0")
    absent_store = tmp_path / "absent.db"
    request = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        }
    ).encode("utf-8") + b"\n"

    completed = _invoke_store_mcp(
        arguments=[
            "--store",
            str(absent_store),
            "--control-root",
            str(control),
            "--root-id",
            "research-root",
        ],
        stdin_payload=request,
    )
    assert completed.returncode == 69, (
        f"store absent must exit 69 (STORE_ABSENT), got "
        f"{completed.returncode}; stderr="
        f"{completed.stderr.decode('utf-8', errors='replace')!r}"
    )
    stderr_text = completed.stderr.decode("utf-8", errors="replace")
    assert "STORE_ABSENT" in stderr_text
    # Pre-protocol: no JSON-RPC response is written.
    assert completed.stdout.strip() == b"", (
        "STORE_ABSENT is signaled before stdin consumption; no JSON-RPC "
        f"output expected, got stdout={completed.stdout!r}"
    )


def test_subprocess_denied_root_returns_78_no_fallback(tmp_path: Path) -> None:
    """Tampered cache canonical_path → store MCP exits 78 (denied).
    The shim must NOT fall back to the v1 reader; it must propagate 78
    so a security mismatch can never silently bypass the gate.
    """
    root = tmp_path / "root"
    root.mkdir(parents=True)
    control = tmp_path / "control"
    service = _service_factory(control)
    service.register_root(
        root_id="research-root", root_path=root, policy_id="research-files-v1"
    )
    store_path = tmp_path / "arw.db"
    _sync_and_ingest(control, "research-root", store_path=store_path)
    # Tamper with the cache's recorded canonical_path.
    import sqlite3

    with sqlite3.connect(store_path) as connection:
        connection.execute(
            "UPDATE projection_meta SET value = ? "
            "WHERE key = 'files.canonical_path'",
            (str(tmp_path / "somewhere_else"),),
        )
        connection.commit()

    plugin_root = _stage_stub_plugin(tmp_path)
    request = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        }
    ).encode("utf-8") + b"\n"

    completed = _invoke_shim(
        plugin_root=plugin_root,
        control_root=control,
        root_id="research-root",
        store_path=store_path,
        stdin_payload=request,
    )
    # The shim must propagate 78 (NOT fall back to v1, which would echo
    # exit 0 and a different serverInfo name).
    assert completed.returncode == 78, (
        f"denied root must propagate 78 (no v1 fallback), got "
        f"{completed.returncode}; stderr="
        f"{completed.stderr.decode('utf-8', errors='replace')!r}"
    )
    stderr_text = completed.stderr.decode("utf-8", errors="replace")
    assert "root_denied" in stderr_text, (
        "denied root should surface as root_denied, not a generic 78"
    )
    # And no JSON-RPC traffic was emitted (denial happens pre-transport).
    assert completed.stdout.strip() == b"", (
        "denied root is signaled pre-transport; no JSON-RPC output expected"
    )


def test_subprocess_explicit_legacy_reader_uses_v1(tmp_path: Path) -> None:
    """ARW_FILES_LEGACY_READER=1 forces the shim to use the v1 reader,
    bypassing the store MCP entirely.  This is the explicit legacy opt-in.
    """
    control, store_path = _seed_corpus_with_root_id(tmp_path, "research-root")
    plugin_root = _stage_stub_plugin(tmp_path)
    request = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        }
    ).encode("utf-8") + b"\n"

    completed = _invoke_shim(
        plugin_root=plugin_root,
        control_root=control,
        root_id="research-root",
        store_path=store_path,
        stdin_payload=request,
        env_extra={"ARW_FILES_LEGACY_READER": "1"},
    )
    assert completed.returncode == 0, (
        f"legacy opt-in must route to v1 successfully, got "
        f"{completed.returncode}; stderr="
        f"{completed.stderr.decode('utf-8', errors='replace')!r}"
    )
    line = next(
        (
            chunk
            for chunk in completed.stdout.splitlines()
            if chunk.strip().startswith(b"{")
        ),
        b"",
    )
    response = json.loads(line)
    server_info = response["result"]["serverInfo"]
    assert server_info["name"] == "academic-research-files", (
        f"legacy opt-in must route to v1, got {server_info['name']!r}"
    )


def test_subprocess_shim_falls_back_on_store_absent(tmp_path: Path) -> None:
    """Shim routes a STORE_ABSENT (69) from the store MCP into the v1
    reader (exit 0 + v1 serverInfo).  This is the only fallback path
    the shim may take; generic 78, capability denial, root mismatch,
    corruption, or post-transport errors do NOT trigger fallback.
    """
    root = tmp_path / "root"
    root.mkdir(parents=True)
    (root / "notes").mkdir(parents=True)
    (root / "notes/a.txt").write_text("alpha\n", encoding="utf-8")
    control = tmp_path / "control"
    service = _service_factory(control)
    service.register_root(
        root_id="research-root", root_path=root, policy_id="research-files-v1"
    )
    service.sync("research-root", extractor_version="1.0.0")
    plugin_root = _stage_stub_plugin(tmp_path)
    # Point the store at a path that does NOT exist so the store MCP
    # returns STORE_ABSENT (69) before any transport work.
    absent_store = tmp_path / "absent.db"
    request = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        }
    ).encode("utf-8") + b"\n"

    completed = _invoke_shim(
        plugin_root=plugin_root,
        control_root=control,
        root_id="research-root",
        store_path=absent_store,
        stdin_payload=request,
    )
    assert completed.returncode == 0, (
        f"shim must fall back to v1 on STORE_ABSENT (69), got "
        f"{completed.returncode}; stderr="
        f"{completed.stderr.decode('utf-8', errors='replace')!r}"
    )
    line = next(
        (
            chunk
            for chunk in completed.stdout.splitlines()
            if chunk.strip().startswith(b"{")
        ),
        b"",
    )
    response = json.loads(line)
    server_info = response["result"]["serverInfo"]
    assert server_info["name"] == "academic-research-files", (
        f"STORE_ABSENT must route to v1 (legacy fallback), got "
        f"{server_info['name']!r}"
    )


def test_store_absent_does_not_bypass_denied_manifest_gate(
    tmp_path: Path,
) -> None:
    """Even when the store is missing, a manifest that does not
    declare ``files`` must short-circuit to 78 (capability denial)
    BEFORE STORE_ABSENT can be signaled.  The pre-store check
    (``_check_manifest_declares_files``) exists precisely so a
    missing store cannot be a back door to a denied capability.
    """
    root = tmp_path / "root"
    root.mkdir(parents=True)
    control = tmp_path / "control"
    service = _service_factory(control)
    service.register_root(
        root_id="research-root", root_path=root, policy_id="research-files-v1"
    )
    service.sync("research-root", extractor_version="1.0.0")
    # Synthesize a manifest that withholds ``files``; bind it via
    # ``ARW_PLUGIN_MANIFEST`` so the store MCP's source-tree fallback
    # is skipped.
    manifest = tmp_path / "no-files.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "name": "no-files-plugin",
                "version": "0.0.0",
                "interface": {"capabilities": ["graph", "provenance"]},
            }
        ),
        encoding="utf-8",
    )
    request = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        }
    ).encode("utf-8") + b"\n"

    completed = _invoke_store_mcp(
        arguments=[
            "--store",
            str(tmp_path / "absent.db"),
            "--control-root",
            str(control),
            "--root-id",
            "research-root",
        ],
        stdin_payload=request,
        env_extra={"ARW_PLUGIN_MANIFEST": str(manifest)},
    )
    # Manifest denial wins, even though the store is absent.
    assert completed.returncode == 78, (
        f"denied manifest must surface as 78 (not STORE_ABSENT 69), got "
        f"{completed.returncode}; stderr="
        f"{completed.stderr.decode('utf-8', errors='replace')!r}"
    )
    stderr_text = completed.stderr.decode("utf-8", errors="replace")
    assert "capability_unavailable" in stderr_text
    # The actual STORE_ABSENT signal is the line "store not found at <path>";
    # a denial message may mention "STORE_ABSENT" as commentary, so we
    # look for the unique store-not-found string instead.
    assert "store not found at" not in stderr_text, (
        "manifest denial must short-circuit before STORE_ABSENT detection; "
        f"stderr={stderr_text!r}"
    )
    # No JSON-RPC traffic — denial is pre-transport.
    assert completed.stdout.strip() == b""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_list_request(root_id: str, generation_id: str):
    from arw.file_models import FilesListRequest

    return FilesListRequest(
        schema_version="1.0.0",
        root_id=root_id,
        cursor=None,
        max_files=200,
    )


def _tools_call(name: str, identifier: int, arguments: dict[str, object]) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": identifier,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
