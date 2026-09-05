"""Semantica audit-directory reconciliation regression tests.

The audit directory must reconcile only regular files: stale FIFO, directory,
symlink, or non-semantica-named nonregular entries must fail reconciliation
rather than be silently ignored. Otherwise ``verify()`` returns success while
the status loader reports read failure because the inventory still contains a
non-traversable entry.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from pathlib import Path

import pytest
from arw_semantica import (  # pyright: ignore[reportMissingImports]
    ProvenanceRecord,
    SemanticaSQLiteAdapter,
)

EVENT_ID = "evt-00000000-0000-4000-8000-000000000051"
EVENT_DIGEST = "a" * 64
ARTIFACT_ID = "artifact-reconciliation"
RECORD_ID = "prov-reconciliation"


def _record() -> ProvenanceRecord:
    return ProvenanceRecord(
        schema_version="1.0.0",
        record_id=RECORD_ID,
        entity_id="claim.reconciliation",
        entity_type="Claim",
        artifact_id=ARTIFACT_ID,
        ledger_event_id=EVENT_ID,
        ledger_event_digest=EVENT_DIGEST,
        activity_id="activity.reconciliation",
        agent_id="agent.reconciliation",
        created_at="2026-09-05T00:00:00Z",
        derived_from=(),
        attributes={},
    )


def _adapter(
    tmp_path: Path,
    *,
    canonical: Mapping[str, ProvenanceRecord] | None = None,
    expected_provenance_record_sha256: Mapping[str, str] | None = None,
) -> SemanticaSQLiteAdapter:
    canonical = canonical or {RECORD_ID: _record()}
    return SemanticaSQLiteAdapter(
        tmp_path / "provenance.sqlite3",
        canonical_event_digests={
            str(record.ledger_event_id): str(record.ledger_event_digest)
            for record in canonical.values()
        },
        accepted_artifact_ids_by_event={
            str(record.ledger_event_id): (record.artifact_id,) for record in canonical.values()
        },
        accepted_artifact_sha256_by_event={
            str(record.ledger_event_id): record.checksum for record in canonical.values()
        },
        expected_provenance_record_sha256=(
            expected_provenance_record_sha256
            if expected_provenance_record_sha256 is not None
            else {record.record_id: record.checksum for record in canonical.values()}
        ),
        audit_database_path=tmp_path / "projection.sqlite3",
    )


def test_replace_audit_faults_rejects_stale_fifo_with_semantica_name(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    adapter.record(_record())
    audit_directory = tmp_path / "projection.sqlite3.audit"
    audit_directory.mkdir(mode=0o700)
    fifo_name = (
        "semantica-stale-fifo-0000000000000000000000-aaaaaaaaaaaaaaaaaaaa.json"
    )
    fifo_path = audit_directory / fifo_name
    os.mkfifo(fifo_path, mode=0o600)
    assert not fifo_path.is_file()

    with pytest.raises(RuntimeError, match="regular file"):
        adapter.verify()
    assert fifo_path.exists()


def test_replace_audit_faults_rejects_stale_directory_with_semantica_name(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    adapter.record(_record())
    audit_directory = tmp_path / "projection.sqlite3.audit"
    audit_directory.mkdir(mode=0o700)
    stale_dir = audit_directory / (
        "semantica-stale-dir-0000000000000000000000-aaaaaaaaaaaaaaaaaaaa.json"
    )
    stale_dir.mkdir(mode=0o700)
    assert not stale_dir.is_file()

    with pytest.raises(RuntimeError, match="regular file"):
        adapter.verify()
    # Reconciliation must not recursively prune the directory.
    assert stale_dir.exists()


def test_replace_audit_faults_rejects_stale_symlink_with_semantica_name(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    adapter.record(_record())
    audit_directory = tmp_path / "projection.sqlite3.audit"
    audit_directory.mkdir(mode=0o700)
    # A symlink with a Semantica-style name is rejected before any directory
    # pruning, so the regular file it points at survives intact.
    target = tmp_path / "external-receipt.json"
    target.write_bytes(b'{"stale":true}')
    target.chmod(0o600)
    symlink_path = audit_directory / (
        "semantica-stale-symlink-0000000000000000000000-aaaaaaaaaaaaaaaaaaaa.json"
    )
    symlink_path.symlink_to(target)
    assert symlink_path.is_symlink()
    symlink_mode = symlink_path.lstat().st_mode
    assert stat.S_ISLNK(symlink_mode)
    assert not stat.S_ISREG(symlink_mode)

    with pytest.raises(RuntimeError, match="symlink"):
        adapter.verify()
    assert target.exists()


def test_replace_audit_faults_replaces_stale_regular_receipt(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    adapter.record(_record())
    audit_directory = tmp_path / "projection.sqlite3.audit"
    audit_directory.mkdir(mode=0o700)
    stale = audit_directory / (
        "semantica-stale-reg-0000000000000000000000-aaaaaaaaaaaaaaaaaaaa.json"
    )
    stale.write_bytes(b'{"stale":true}')
    stale.chmod(0o600)
    assert stale.is_file()

    adapter.verify()
    assert not stale.exists()


def test_replace_audit_faults_does_not_touch_unrelated_nonregular_entries(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    adapter.record(_record())
    audit_directory = tmp_path / "projection.sqlite3.audit"
    audit_directory.mkdir(mode=0o700)
    # An entry that does not match the ``semantica-*.json`` namespace must be
    # left alone; only Semantica-named entries are reconciled.
    untouched_dir = audit_directory / "user-attached.bin"
    untouched_dir.mkdir(mode=0o700)
    untouched_fifo = audit_directory / "user-fifo.bin"
    os.mkfifo(untouched_fifo, mode=0o600)

    adapter.verify()
    assert untouched_dir.exists()
    assert untouched_fifo.exists()