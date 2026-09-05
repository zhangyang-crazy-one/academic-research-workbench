"""Store/run sidecar keys must preserve identity within filesystem limits."""

import os
from pathlib import Path

import pytest
from arw_semantica import (  # pyright: ignore[reportMissingImports]
    SemanticaSQLiteAdapter,
)

from arw.cli import _provenance_sidecar_path

RUN_ID = "run-00000000-0000-4000-8000-000000000051"
EVENT_ID = "evt-00000000-0000-4000-8000-000000000001"
EVENT_DIGEST = "a" * 64
ARTIFACT_ID = "artifact-boundary"


@pytest.mark.parametrize("name", ["x" * 200 + ".db", "研" * 80 + ".db"])
def test_long_names_have_creatable_sidecar_and_audit_paths(
    tmp_path: Path, name: str
) -> None:
    store = tmp_path / name
    store.touch()
    sidecar = _provenance_sidecar_path(store, RUN_ID)
    audit = Path(f"{sidecar}.audit")
    assert sidecar.parent == tmp_path
    assert len(os.fsencode(audit.name)) <= 255
    sidecar.touch()
    audit.mkdir()
    assert _provenance_sidecar_path(store, RUN_ID) == sidecar


def test_short_names_preserve_existing_paths_and_store_suffixes(tmp_path: Path) -> None:
    first = _provenance_sidecar_path(tmp_path / "research.db", RUN_ID)
    second = _provenance_sidecar_path(tmp_path / "research.sqlite3", RUN_ID)
    assert first.name == f"research.db.{RUN_ID}.semantica.sqlite3"
    assert first != second


def test_long_names_and_runs_remain_isolated(tmp_path: Path) -> None:
    first = tmp_path / ("x" * 200 + ".db")
    second = tmp_path / ("x" * 200 + ".sqlite3")
    assert _provenance_sidecar_path(first, RUN_ID) != _provenance_sidecar_path(
        second, RUN_ID
    )
    assert _provenance_sidecar_path(first, RUN_ID) != _provenance_sidecar_path(
        first, RUN_ID[:-1] + "2"
    )


def test_literal_hash_name_cannot_alias_long_store(tmp_path: Path) -> None:
    long_store = tmp_path / ("x" * 200 + ".db")
    sidecar = _provenance_sidecar_path(long_store, RUN_ID)
    literal_name = sidecar.name.removesuffix(f".{RUN_ID}.semantica.sqlite3")
    assert _provenance_sidecar_path(tmp_path / literal_name, RUN_ID) != sidecar


def _boundary_store(tmp_path: Path, *, hashed: bool) -> Path:
    """Build a store whose auxiliary basename reaches the exact budget edge."""
    # Budget compares ``len(name) + len(suffix + "-journal")`` against 255.
    # ``-journal`` is two bytes longer than ``.audit`` and is the longest
    # generated SQLite auxiliary suffix, so it is the strict budget driver.
    auxiliary_len = len(f".{RUN_ID}.semantica.sqlite3-journal")
    # Exactly 255 bytes (name + aux) keeps the sidecar literal; 256 forces
    # the hash so the auxiliary still respects the filesystem cap.
    name_len = 255 - auxiliary_len + (1 if hashed else 0)
    filler_len = name_len - len(".db")
    assert filler_len > 0
    return tmp_path / ("x" * filler_len + ".db")


def test_exact_boundary_keeps_literal_names_at_255_bytes(tmp_path: Path) -> None:
    # store.name (188 chars) + auxiliary (67 chars) = 255 bytes exactly, so
    # the literal sidecar survives; the journal/audit/shm/wal auxiliaries
    # all fit under the 255-byte filesystem limit.
    store = _boundary_store(tmp_path, hashed=False)
    sidecar = _provenance_sidecar_path(store, RUN_ID)
    assert not sidecar.name.startswith("__arw_store_sha256__")
    assert len(os.fsencode(sidecar.name)) <= 255
    assert len(os.fsencode(f"{sidecar.name}-journal")) <= 255
    assert len(os.fsencode(f"{sidecar.name}.audit")) <= 255


def test_exact_boundary_hashes_names_above_255_bytes(tmp_path: Path) -> None:
    # store.name (189 chars) + auxiliary (67 chars) = 256 bytes, one past the
    # limit, so the sidecar must be hashed to stay within budget.
    store = _boundary_store(tmp_path, hashed=True)
    sidecar = _provenance_sidecar_path(store, RUN_ID)
    assert sidecar.name.startswith("__arw_store_sha256__")
    assert len(os.fsencode(sidecar.name)) <= 255
    assert len(os.fsencode(f"{sidecar.name}-journal")) <= 255


def test_boundary_literal_sidecar_initializes_real_semantica_adapter(
    tmp_path: Path,
) -> None:
    # At the 255-byte boundary the literal sidecar must initialize a real
    # Semantica adapter so SQLite's -journal/-wal/-shm probes never overflow.
    store = _boundary_store(tmp_path, hashed=False)
    sidecar = _provenance_sidecar_path(store, RUN_ID)
    SemanticaSQLiteAdapter(
        sidecar,
        canonical_event_digests={EVENT_ID: EVENT_DIGEST},
        accepted_artifact_ids_by_event={EVENT_ID: (ARTIFACT_ID,)},
        accepted_artifact_sha256_by_event={EVENT_ID: "0" * 64},
        expected_provenance_record_sha256={},
    )
    assert len(os.fsencode(f"{sidecar.name}-journal")) <= 255


def test_boundary_hashed_sidecar_initializes_real_semantica_adapter(
    tmp_path: Path,
) -> None:
    # Above the boundary the hashed sidecar must initialize a real Semantica
    # adapter so the safety probe never overflows the filesystem limit.
    store = _boundary_store(tmp_path, hashed=True)
    sidecar = _provenance_sidecar_path(store, RUN_ID)
    SemanticaSQLiteAdapter(
        sidecar,
        canonical_event_digests={EVENT_ID: EVENT_DIGEST},
        accepted_artifact_ids_by_event={EVENT_ID: (ARTIFACT_ID,)},
        accepted_artifact_sha256_by_event={EVENT_ID: "0" * 64},
        expected_provenance_record_sha256={},
    )
    assert len(os.fsencode(f"{sidecar.name}-journal")) <= 255
