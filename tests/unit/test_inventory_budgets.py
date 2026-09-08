"""Inventory guards reject resource exhaustion before returning query content."""

import sqlite3
import time

import pytest
from arw_ext.local_store import inventory


def _cache() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE files (file_id TEXT, relative_path TEXT, file_type TEXT, "
        "size_bytes INTEGER, source_digest TEXT, index_state TEXT, "
        "degraded_reason TEXT, extraction_registration_sha256 TEXT, "
        "body TEXT, body_nfkc_folded TEXT)"
    )
    connection.execute(
        "INSERT INTO files VALUES ('id', 'a.txt', 'text', 200, 'digest', "
        "'indexed', NULL, NULL, ?, ?)",
        ("x" * 200, "x" * 200),
    )
    connection.execute(
        "CREATE VIRTUAL TABLE files_fts_trigram USING fts5("
        'file_id UNINDEXED, body_nfkc_folded, tokenize="trigram")'
    )
    connection.execute(
        "INSERT INTO files_fts_trigram SELECT file_id, body_nfkc_folded FROM files"
    )
    return connection


def test_oversized_body_rejected_before_text_decoding(monkeypatch):
    connection = _cache()

    def refuse_text(raw):
        pytest.fail("oversized body was materialized in Python")

    connection.text_factory = refuse_text
    monkeypatch.setattr(inventory, "MAX_INVENTORY_BODY_BYTES", 100)
    try:
        with pytest.raises(inventory.InventoryBudgetExceeded):
            inventory.compute_actual_inventory_fingerprint(
                connection, deadline=time.monotonic() + 5
            )
    finally:
        connection.close()


@pytest.mark.parametrize("probe", ["fingerprint", "fts"])
def test_sql_checks_share_deadline_and_release_handler(monkeypatch, probe):
    connection = _cache()
    ticks = iter([0.0, 2.0])
    monkeypatch.setattr(inventory.time, "monotonic", lambda: next(ticks, 2.0))
    try:
        with pytest.raises(inventory.InventoryBudgetExceeded):
            if probe == "fts":
                inventory.verify_fts_trigram_consistency(connection, deadline=1.0)
            else:
                inventory.compute_actual_inventory_fingerprint(connection, deadline=1.0)
        assert connection.execute("SELECT count(*) FROM files").fetchone() == (1,)
    finally:
        connection.close()


@pytest.mark.parametrize("probe", ["fingerprint", "fts"])
def test_sql_vm_budget_is_effective(monkeypatch, probe):
    connection = _cache()
    monkeypatch.setattr(inventory, "MAX_INVENTORY_VM_STEPS", 1)
    try:
        with pytest.raises(inventory.InventoryBudgetExceeded):
            if probe == "fts":
                inventory.verify_fts_trigram_consistency(
                    connection, deadline=time.monotonic() + 5
                )
            else:
                inventory.compute_actual_inventory_fingerprint(
                    connection, deadline=time.monotonic() + 5
                )
    finally:
        connection.close()


def test_null_to_empty_substitution_changes_inventory():
    connection = _cache()
    try:
        before = inventory.compute_actual_inventory_fingerprint(
            connection, deadline=time.monotonic() + 5
        )
        connection.execute("UPDATE files SET degraded_reason = ''")
        after = inventory.compute_actual_inventory_fingerprint(
            connection, deadline=time.monotonic() + 5
        )
        assert before != after
    finally:
        connection.close()
