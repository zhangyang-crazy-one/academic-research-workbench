"""Store location policy + projection health (PR4 tasks 5.3, 6.1-6.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from arw_ext.local_store import (  # pyright: ignore[reportMissingImports]
    LocalProjectionStore,
)
from arw_ext.local_store.health import (  # pyright: ignore[reportMissingImports]
    collect_health,
)
from arw_ext.local_store.location import (  # pyright: ignore[reportMissingImports]
    StoreLocationError,
    default_store_path,
    is_network_filesystem,
    resolve_store_path,
)

# ---------------------------------------------------------------------------
# Location policy (6.1 / 6.2)
# ---------------------------------------------------------------------------


def test_default_store_path_is_under_user_cache(tmp_path: Path) -> None:
    path = default_store_path(tmp_path)
    text = str(path)
    assert "arw" in text
    assert "local-store" in text
    assert path.suffix == ".db"
    # Keyed by workspace: two workspaces must not share one file.
    other = default_store_path(tmp_path / "other")
    assert path != other


def test_resolve_explicit_local_path(tmp_path: Path) -> None:
    explicit = tmp_path / ".arw" / "arw.db"
    assert resolve_store_path(tmp_path, explicit_path=explicit) == explicit.resolve()


def test_resolve_default_uses_cache(tmp_path: Path) -> None:
    assert resolve_store_path(tmp_path) == default_store_path(tmp_path)


def test_network_filesystem_explicit_path_faults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit path on a detected network mount is refused (task 6.2)."""

    from arw_ext.local_store import location  # pyright: ignore[reportMissingImports]

    monkeypatch.setattr(
        location, "_mounts_fs_types", lambda: {str(tmp_path): "nfs4"}
    )
    assert is_network_filesystem(tmp_path / "arw.db")
    with pytest.raises(StoreLocationError) as exc_info:
        resolve_store_path(tmp_path, explicit_path=tmp_path / "arw.db")
    assert exc_info.value.code == "store_location_unsafe"
    assert "network filesystem" in str(exc_info.value)


def test_unknown_filesystem_is_treated_as_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Undetectable filesystem → fail-open (journal_mode=DELETE stays safe)."""

    from arw_ext.local_store import location  # pyright: ignore[reportMissingImports]

    monkeypatch.setattr(location, "_mounts_fs_types", dict)
    assert not is_network_filesystem(tmp_path / "arw.db")
    assert (
        resolve_store_path(tmp_path, explicit_path=tmp_path / "arw.db")
        == (tmp_path / "arw.db").resolve()
    )


# ---------------------------------------------------------------------------
# Projection health (5.3)
# ---------------------------------------------------------------------------


def test_collect_health_reports_schema_checkpoints_and_counts(tmp_path: Path) -> None:
    store = LocalProjectionStore(tmp_path / "arw.db")
    store.open()
    try:
        health = collect_health(store)
    finally:
        store.close()
    assert health["schema_version"] >= 1
    assert health["checksum_status"] == "ok"
    assert health["checksum_faults"] == []
    assert health["checkpoints"] == []
    assert health["counts"]["nodes"] == 0
    assert health["counts"]["files"] == 0


def test_collect_health_detects_checksum_tampering(tmp_path: Path) -> None:
    """A tampered assertion row surfaces as an audit fault in health (5.4)."""

    store = LocalProjectionStore(tmp_path / "arw.db")
    store.open()
    try:
        # Insert a node + assertion with a deliberately wrong checksum.
        store.connection.execute(
            "INSERT INTO nodes(entity_type, entity_id, source_digest, payload_digest,"
            " supersession_state, ledger_watermark, attributes_json)"
            " VALUES ('Source', 'source-x', ?, ?, 'active', 1, '{}')",
            ("a" * 64, "0" * 64),
        )
        store.connection.execute(
            "INSERT INTO assertions(assertion_id, entity_type, entity_id, edge_type,"
            " supersession_state, source_digest, ledger_watermark, projection_version,"
            " record_checksum)"
            " VALUES ('asrt-x', 'Source', 'source-x', NULL, 'active', ?, 1, '1', 'tampered')",
            ("a" * 64,),
        )
        health = collect_health(store)
    finally:
        store.close()
    assert health["checksum_status"] == "audit_fault"
    assert any(f["code"] == "checksum_mismatch" for f in health["checksum_faults"])


# ---------------------------------------------------------------------------
# CLI wiring: arw status --store
# ---------------------------------------------------------------------------


def test_status_json_includes_projection_health_only_with_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The additive --store flag appends projection_health; the default
    envelope is unchanged (v2-compat golden covers the no-store path)."""

    from arw.cli import main

    # Minimal run root via the CLI itself: the seed's immutable input file
    # must exist relative to the run root (mirrors the v1 compat harness).
    seed_dir = Path("tests/fixtures/recovery/seed")
    run_root = tmp_path / "run"
    (run_root / "input").mkdir(parents=True)
    (run_root / "input" / "source.txt").write_bytes(
        (seed_dir / "input" / "source.txt").read_bytes()
    )
    assert (
        main(
            [
                "init",
                "--run-root",
                str(run_root),
                "--request",
                str(seed_dir / "init-request.json"),
            ]
        )
        == 0
    )

    store = LocalProjectionStore(tmp_path / "arw.db")
    store.open()
    store.close()

    capsys.readouterr()  # drain the init output

    # Without --store: no projection_health key.
    assert main(["status", "--run-root", str(run_root), "--json"]) == 0
    assert "projection_health" not in json.loads(capsys.readouterr().out)

    # With --store: projection_health present and well-formed.
    assert (
        main(
            [
                "status",
                "--run-root",
                str(run_root),
                "--json",
                "--store",
                str(tmp_path / "arw.db"),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    health = payload["projection_health"]
    assert health["schema_version"] >= 1
    assert health["checksum_status"] == "ok"
