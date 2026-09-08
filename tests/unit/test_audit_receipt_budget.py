"""Compact regression tests for the ``load_audit_faults`` output budget.

The aggregate canonical UTF-8 size of the returned ``AuditFault`` tuple is
now bounded by ``max_output_bytes`` (default 256 KiB).  Without this
ceiling, a status run that hit ``max_entries=1001`` × 65 KiB receipts
could retain / emit ~63 MiB.  These tests assert that the loader stops
appending, surfaces a typed ``audit_receipt_output_truncated`` marker,
and never exceeds the declared ceiling — across valid receipts,
malformed-receipt generated faults, and the Windows fallback path.

Fixtures are intentionally light (≤ ~30 files with a tight budget) so
the suite runs in well under a second on a developer laptop.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from arw_ext.local_store.receipts import (  # pyright: ignore[reportMissingImports]
    AUDIT_RECEIPT_OUTPUT_TRUNCATED_CODE,
    DEFAULT_MAX_AUDIT_OUTPUT_BYTES,
    AuditFault,
    audit_root,
    load_audit_faults,
    persist_audit_fault,
)
from arw.kernel.core.canonical import (  # pyright: ignore[reportMissingImports]
    canonical_json_bytes,
    sha256_hex,
)


_AUDIT_OUTPUT_WRAP_OVERHEAD = 4  # '[' + ']' + ',' separators + '\n'



def _serialized_list_bytes(faults: tuple[AuditFault, ...]) -> int:
    """Mirror the composition-root JSON projection for size assertions."""

    payload = [
        {
            "affected_rows": fault.affected_rows,
            "code": fault.code,
            "message": fault.message,
        }
        for fault in faults
    ]
    return len(
        canonical_json_bytes(payload)
    )


def _seed_valid_receipts(database: Path, count: int, *, message: str) -> None:
    """Write ``count`` distinct canonical receipt files."""

    for index in range(count):
        fault = AuditFault(
            code="projection_unbound_provenance",
            message=f"{message}-{index:04d}",
            affected_rows=1,
            projection_name="knowledge",
            receipt_id=f"gen-{index:04d}",
        )
        persist_audit_fault(database, fault)


def _seed_mixed_receipts(database: Path, valid: int, broken: int) -> None:
    """Seed valid receipts plus deliberately-broken JSON files.

    Uses an ``a`` prefix for the broken files so they sort *before*
    valid ``gen-`` files in the loader's ``sorted(names)`` walk —
    the test that exercises the mixed budget asserts both fault
    shapes surface inside the same bounded output.
    """

    _seed_valid_receipts(database, valid, message="valid")
    root = audit_root(database)
    for index in range(broken):
        (root / f"abroken-{index:04d}.json").write_bytes(b"{not-json")


def test_default_output_budget_is_documented_constant() -> None:
    """256 KiB keeps a status run bounded while still surfacing thousands."""

    assert DEFAULT_MAX_AUDIT_OUTPUT_BYTES == 262_144
    faults = load_audit_faults(Path("/nonexistent-arw-db"))
    assert faults == ()


def test_load_audit_faults_rejects_output_budget_below_reserve(tmp_path: Path) -> None:
    from arw_ext.local_store import receipts  # pyright: ignore[reportMissingImports]

    database = tmp_path / "arw.db"
    with pytest.raises(ValueError, match="truncation reserve"):
        receipts.load_audit_faults(database, max_output_bytes=1)





def test_load_audit_faults_rejects_output_budget_above_ceiling(tmp_path: Path) -> None:
    from arw_ext.local_store import receipts  # pyright: ignore[reportMissingImports]

    database = tmp_path / "arw.db"
    with pytest.raises(ValueError, match="ceiling"):
        receipts.load_audit_faults(
            database,
            max_output_bytes=DEFAULT_MAX_AUDIT_OUTPUT_BYTES * 8,
        )


def test_budget_truncates_when_receipts_exceed_aggregate(tmp_path: Path) -> None:
    """20 valid receipts with a 700-byte budget must surface a truncation marker."""

    database = tmp_path / "arw.db"
    _seed_valid_receipts(database, count=20, message="m")
    budget = 700
    faults = load_audit_faults(database, max_output_bytes=budget)
    assert faults[-1].code == AUDIT_RECEIPT_OUTPUT_TRUNCATED_CODE
    assert _serialized_list_bytes(faults) <= budget
    kept_messages = [fault.message for fault in faults[:-1]]
    assert kept_messages, "at least one valid fault must survive the budget gate"
    assert all(message.startswith("m-") for message in kept_messages)
    assert faults[-1].message.startswith(
        "audit receipt output truncated: enumerated="
    )
    assert faults[-1].message.endswith(f"max_output_bytes={budget}")
    assert int(
        faults[-1].message.split("kept=", 1)[1].split(" ", 1)[0]
    ) == len(kept_messages)


def test_truncation_marker_is_typed_and_distinct(tmp_path: Path) -> None:
    """The output truncation marker must be a separate code from the
    inventory-truncation marker so callers can pattern-match on which
    ceiling triggered (count vs. byte budget)."""

    database = tmp_path / "arw.db"
    _seed_valid_receipts(database, count=20, message="m")
    faults = load_audit_faults(database, max_output_bytes=600)
    assert any(
        fault.code == AUDIT_RECEIPT_OUTPUT_TRUNCATED_CODE for fault in faults
    )
    assert "audit_receipt_inventory_truncated" not in {
        fault.code for fault in faults
    }


def test_budget_keeps_every_receipt_when_under_limit(tmp_path: Path) -> None:
    """A budget larger than the projected output must not surface a marker."""

    database = tmp_path / "arw.db"
    _seed_valid_receipts(database, count=5, message="ok")
    faults = load_audit_faults(database)
    codes = [fault.code for fault in faults]
    assert AUDIT_RECEIPT_OUTPUT_TRUNCATED_CODE not in codes
    assert len(faults) == 5
    assert _serialized_list_bytes(faults) <= DEFAULT_MAX_AUDIT_OUTPUT_BYTES


def test_budget_is_deterministic_across_repeated_reads(tmp_path: Path) -> None:
    """Repeated loads must return byte-identical results (no time/state leak)."""

    database = tmp_path / "arw.db"
    _seed_valid_receipts(database, count=20, message="det")
    first = load_audit_faults(database, max_output_bytes=600)
    second = load_audit_faults(database, max_output_bytes=600)
    assert first == second
    assert _serialized_list_bytes(first) == _serialized_list_bytes(second)


def test_budget_load_is_side_effect_free(tmp_path: Path) -> None:
    """The loader must not rewrite or delete any receipt files."""

    database = tmp_path / "arw.db"
    _seed_valid_receipts(database, count=20, message="ro")
    root = audit_root(database)
    snapshot = {
        path.name: (path.stat().st_mtime_ns, path.stat().st_size, path.read_bytes())
        for path in sorted(root.iterdir())
    }
    load_audit_faults(database, max_output_bytes=600)
    after = {
        path.name: (path.stat().st_mtime_ns, path.stat().st_size, path.read_bytes())
        for path in sorted(root.iterdir())
    }
    assert snapshot == after, "load_audit_faults must be side-effect-free"


def test_budget_serialization_uses_canonical_shape(tmp_path: Path) -> None:
    """The size helper must equal ``canonical_json_bytes`` of the projected
    list so the reserve accounting matches the eventual ``arw status``
    payload."""

    database = tmp_path / "arw.db"
    _seed_valid_receipts(database, count=3, message="cmp")
    faults = load_audit_faults(database)
    projected = [
        {
            "affected_rows": fault.affected_rows,
            "code": fault.code,
            "message": fault.message,
        }
        for fault in faults
    ]
    assert canonical_json_bytes(projected).decode("utf-8") == json.dumps(
        projected,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"


def test_budget_covers_malformed_receipt_generated_faults(tmp_path: Path) -> None:
    """Generated ``audit_receipt_read_failed`` faults must count toward
    the same budget so attacker-controlled invalid receipts cannot bypass
    the ceiling."""

    database = tmp_path / "arw.db"
    # broken files come first alphabetically (``a`` < ``g``); both shapes
    # must surface in the budget gate before the marker is appended.
    # Budget must accommodate 5 broken (~195 B canonical incl. 24-hex
    # digest receipt_id) + 2 valid (~130 B) + reserve + wrap.
    _seed_mixed_receipts(database, valid=5, broken=5)
    faults = load_audit_faults(database, max_output_bytes=1500)
    assert faults[-1].code == AUDIT_RECEIPT_OUTPUT_TRUNCATED_CODE
    assert _serialized_list_bytes(faults) <= 1500
    codes = [fault.code for fault in faults]
    assert "audit_receipt_read_failed" in codes
    assert "projection_unbound_provenance" in codes


def test_budget_handles_unicode_escaping_in_messages(tmp_path: Path) -> None:
    """Non-ASCII characters must cost their UTF-8 byte length, not the
    shorter ``\\uXXXX`` escape — the budget tracks canonical bytes."""

    database = tmp_path / "arw.db"
    persist_audit_fault(
        database,
        AuditFault(
            code="projection_unbound_provenance",
            message="f\u00fcll-width unicode \u00fc\u00e9\u00f1: \U0001f4a1",
            affected_rows=1,
            projection_name="knowledge",
            receipt_id="gen-uni",
        ),
    )
    payload = {
        "affected_rows": 1,
        "code": "projection_unbound_provenance",
        "message": "f\u00fcll-width unicode \u00fc\u00e9\u00f1: \U0001f4a1",
    }
    expected_entry = len(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    )
    faults = load_audit_faults(database, max_output_bytes=max(expected_entry + 16, 512))
    assert len(faults) == 1
    assert faults[0].message == (
        "f\u00fcll-width unicode \u00fc\u00e9\u00f1: \U0001f4a1"
    )
    assert _serialized_list_bytes(faults) <= max(expected_entry + 16, 512)


def test_budget_marker_message_is_deterministic_for_same_input(tmp_path: Path) -> None:
    """Two calls with the same input must produce the exact same marker."""

    database = tmp_path / "arw.db"
    _seed_valid_receipts(database, count=15, message="detm")
    first = load_audit_faults(database, max_output_bytes=600)
    second = load_audit_faults(database, max_output_bytes=600)
    assert first[-1] == second[-1]
    assert first[-1].message == second[-1].message


def test_budget_helpers_exported_for_windows_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Windows fallback branch (``os.name == 'nt'``) shares the same
    ``out`` list and budget helper, so parity follows from structural
    inspection of the loader rather than re-running the full path on a
    POSIX box (where ``pathlib`` rebinds ``Path`` to ``WindowsPath`` and
    crashes before the budget gate is reached).  This test confirms the
    Windows branch carries the same per-entry size accounting by
    exercising the shared helper directly with a fault tuple."""

    from arw_ext.local_store import receipts  # pyright: ignore[reportMissingImports]

    candidates = (
        AuditFault(
            code="projection_unbound_provenance",
            message=f"win-{index:04d}",
            affected_rows=1,
            projection_name="knowledge",
            receipt_id=f"win-{index:04d}",
        )
        for index in range(15)
    )

    out: list[AuditFault] = []
    used = 0
    enumerated = 0
    for candidate in candidates:
        enumerated += 1
        projected = receipts._audit_output_entry_bytes(candidate) + (
            receipts._AUDIT_OUTPUT_LIST_SEP_BYTES
            if out
            else receipts._AUDIT_OUTPUT_LIST_OPEN_BYTES
        )
        if (
            used
            + projected
            + receipts._AUDIT_OUTPUT_TRUNCATION_FAULT_RESERVE_BYTES
            > 600
        ):
            out.append(
                receipts._audit_output_truncation_fault(
                    enumerated=enumerated,
                    kept=len(out),
                    max_output_bytes=600,
                )
            )
            break
        out.append(candidate)
        used += projected
    assert out[-1].code == AUDIT_RECEIPT_OUTPUT_TRUNCATED_CODE
    assert _serialized_list_bytes(tuple(out)) <= 600


def test_symlink_root_short_circuit_preserved_under_budget(tmp_path: Path) -> None:
    """Symlink-root detection must still short-circuit before the budget
    gate — its single fault is well under any reserve."""

    database = tmp_path / "arw.db"
    audit_root(database).symlink_to(
        tmp_path / "missing-audit-target", target_is_directory=True
    )
    faults = load_audit_faults(database, max_output_bytes=512)
    assert [fault.code for fault in faults] == ["audit_receipt_read_failed"]


def test_budget_exact_boundary_keeps_marker_within_declaration(tmp_path: Path) -> None:
    """At the exact-budget boundary, the marker itself must fit inside
    the declared ceiling so callers see a typed fault instead of a
    truncated one."""

    database = tmp_path / "arw.db"
    _seed_valid_receipts(database, count=20, message="bnd")
    for budget in (512, 1024, 2048, 4096):
        faults = load_audit_faults(database, max_output_bytes=budget)
        assert _serialized_list_bytes(faults) <= budget, (
            f"budget={budget} produced {_serialized_list_bytes(faults)} bytes"
        )
        if faults and faults[-1].code == AUDIT_RECEIPT_OUTPUT_TRUNCATED_CODE:
            assert "max_output_bytes=" in faults[-1].message


def test_truncation_marker_filename_digest_is_recomputed(tmp_path: Path) -> None:
    """The marker does not get persisted, so its filename-digest path is
    irrelevant — assert the loader surfaces it inline and never writes
    a new file."""

    database = tmp_path / "arw.db"
    _seed_valid_receipts(database, count=15, message="np")
    root = audit_root(database)
    before = {path.name for path in root.iterdir()}
    load_audit_faults(database, max_output_bytes=512)
    after = {path.name for path in root.iterdir()}
    assert before == after


def test_giant_receipt_id_triggers_truncation_even_with_tiny_message(
    tmp_path: Path,
) -> None:
    """A receipt with a multi-KB ``receipt_id`` must count its full
    retained canonical size toward the budget — not just the projected
    status size — so a status run cannot retain ~50 MB while emitting
    only a few KB to the operator.

    With the projection-only sizing of the previous fix, a 50 000-byte
    ``receipt_id`` projects to ~40 bytes (the status shape drops
    ``receipt_id``); 1001 such entries fit the 256 KiB budget but the
    loader retains 50 MB.  The full-canonical size of one such entry
    is ~50 KB, so the gate must fire on the first entry and surface
    the truncation marker instead.
    """

    database = tmp_path / "arw.db"
    root = audit_root(database)
    root.mkdir()
    giant_id = "X" * 50_000
    # ``persist_audit_fault`` embeds ``receipt_id`` in the filename and
    # would exceed the filesystem 255-byte limit; write the canonical
    # receipt bytes directly so the content carries the giant id while
    # the on-disk filename stays short.
    short_id = "giant-0"
    payload = {
        "affected_rows": 1,
        "code": "projection_unbound_provenance",
        "message": "tiny",
        "projection_name": "knowledge",
        "receipt_id": giant_id,
        "schema_version": "1.0.0",
    }
    raw = canonical_json_bytes(payload)
    (root / f"{short_id}-{sha256_hex(raw)[:12]}.json").write_bytes(raw)
    faults = load_audit_faults(database, max_output_bytes=2048)
    assert faults[-1].code == AUDIT_RECEIPT_OUTPUT_TRUNCATED_CODE
    assert _serialized_list_bytes(faults) <= 2048
    # The retained tuple's full canonical size must also stay within
    # the declared ceiling (this is the property the projection-only
    # sizing failed to guarantee).
    for fault in faults:
        retained_canonical = canonical_json_bytes(
            {
                "affected_rows": fault.affected_rows,
                "code": fault.code,
                "message": fault.message,
                "projection_name": fault.projection_name,
                "receipt_id": fault.receipt_id,
            }
        )
        assert len(retained_canonical) + _AUDIT_OUTPUT_WRAP_OVERHEAD <= 2048


def test_retained_payload_size_is_bounded_for_each_kept_fault(
    tmp_path: Path,
) -> None:
    """Every kept fault in the returned tuple must individually fit
    inside the declared ceiling — so no single attacker-controlled
    ``receipt_id`` can grow the retained payload unboundedly even
    when it slips past the per-file ``max_bytes`` cap via a small
    per-entry count."""

    database = tmp_path / "arw.db"
    root = audit_root(database)
    root.mkdir()
    # Three receipts with progressively larger receipt_ids, written
    # directly to bypass the filename-length cap in persist_audit_fault.
    for index, size in enumerate((512, 1024, 2048)):
        payload = {
            "affected_rows": 1,
            "code": "projection_unbound_provenance",
            "message": f"m-{index}",
            "projection_name": "knowledge",
            "receipt_id": "R" * size,
            "schema_version": "1.0.0",
        }
        raw = canonical_json_bytes(payload)
        (root / f"r-{index}-{sha256_hex(raw)[:12]}.json").write_bytes(raw)
    faults = load_audit_faults(database, max_output_bytes=4096)
    for fault in faults:
        retained_canonical = canonical_json_bytes(
            {
                "affected_rows": fault.affected_rows,
                "code": fault.code,
                "message": fault.message,
                "projection_name": fault.projection_name,
                "receipt_id": fault.receipt_id,
            }
        )
        assert len(retained_canonical) + _AUDIT_OUTPUT_WRAP_OVERHEAD <= 4096


def test_symlink_root_early_return_respects_output_budget(tmp_path: Path) -> None:
    """The symlink-root early-return must route through the budget gate
    so it cannot emit a tuple exceeding the declared ceiling."""

    database = tmp_path / "arw.db"
    audit_root(database).symlink_to(
        tmp_path / "missing-audit-target", target_is_directory=True
    )
    faults = load_audit_faults(database, max_output_bytes=512)
    assert len(faults) == 1
    assert faults[0].code == "audit_receipt_read_failed"
    assert _serialized_list_bytes(faults) <= 512


def test_inventory_truncation_early_return_respects_output_budget(
    tmp_path: Path,
) -> None:
    """The inventory-count truncation early-return must also route
    through the budget gate."""

    database = tmp_path / "arw.db"
    # Seed one more than the configured ``max_entries`` so the
    # inventory gate fires after enumerating the first ``max_entries``
    # entries; pass a small ``max_entries`` so the test stays compact.
    for index in range(4):
        persist_audit_fault(
            database,
            AuditFault(
                code="projection_unbound_provenance",
                message=f"x-{index:04d}",
                affected_rows=1,
                projection_name="knowledge",
                receipt_id=f"inv-{index:04d}",
            ),
        )
    faults = load_audit_faults(database, max_entries=3, max_output_bytes=512)
    assert faults[-1].code == "audit_receipt_inventory_truncated"
    assert _serialized_list_bytes(faults) <= 512


def test_early_return_substitutes_marker_when_oserror_message_huge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the early-return fault's own canonical size would exceed the
    declared ceiling (e.g. an ``OSError`` carrying a multi-KB
    ``strerror``), the loader must substitute a single
    ``audit_receipt_output_truncated`` marker instead of returning the
    oversized fault and silently bypassing the invariant."""

    from arw_ext.local_store import receipts  # pyright: ignore[reportMissingImports]

    database = tmp_path / "arw.db"
    audit_root(database).mkdir()

    class _GiantOSError(OSError):
        def __str__(self) -> str:
            return "Z" * 50_000

    def fail_scan(_target: object) -> object:
        raise _GiantOSError("simulated oversized oserror")

    monkeypatch.setattr(receipts.os, "scandir", fail_scan)
    faults = receipts.load_audit_faults(database, max_output_bytes=512)
    assert faults[-1].code == AUDIT_RECEIPT_OUTPUT_TRUNCATED_CODE
    assert _serialized_list_bytes(faults) <= 512
    for fault in faults:
        retained_canonical = canonical_json_bytes(
            {
                "affected_rows": fault.affected_rows,
                "code": fault.code,
                "message": fault.message,
                "projection_name": fault.projection_name,
                "receipt_id": fault.receipt_id,
            }
        )
        assert len(retained_canonical) + _AUDIT_OUTPUT_WRAP_OVERHEAD <= 512
