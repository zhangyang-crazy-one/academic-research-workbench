"""Projection health reporting (task 5.3).

``collect_health(store)`` assembles the operator-facing health view of one
opened store: schema version, projection checkpoints, row counts, checksum
verification outcome, and audit-fault count.  The store is a disposable
projection — health faults are surfaced for rebuild, never treated as
canonical truth.
"""

from __future__ import annotations

from typing import Any

from .store import LocalProjectionStore
from .verify import verify_checksums


def collect_health(store: LocalProjectionStore) -> dict[str, Any]:
    """Return the projection-health summary for one opened store."""

    store.assert_open()
    connection = store.connection
    snapshot = store.snapshot

    checkpoints = [
        {
            "projection_name": str(row[0]),
            # pi-lens-ignore: unchecked-throwing-call-python
            "last_ledger_sequence": int(row[1]),
            "last_ledger_event_digest": str(row[2]),
            "last_applied_at": str(row[3]),
            "projection_version": str(row[4]),
        }
        for row in connection.execute(
            "SELECT projection_name, last_ledger_sequence, last_ledger_event_digest,"
            "       last_applied_at, projection_version"
            "  FROM projection_checkpoints ORDER BY projection_name"
        ).fetchall()
    ]

    # Static literal SQL per table — no interpolation, no variables.
    counts = {
        # pi-lens-ignore: unchecked-throwing-call-python
        "nodes": int(connection.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]),
        # pi-lens-ignore: unchecked-throwing-call-python
        "edges": int(connection.execute("SELECT COUNT(*) FROM edges").fetchone()[0]),
        # pi-lens-ignore: unchecked-throwing-call-python
        "assertions": int(connection.execute("SELECT COUNT(*) FROM assertions").fetchone()[0]),
        # pi-lens-ignore: unchecked-throwing-call-python
        "provenance": int(connection.execute("SELECT COUNT(*) FROM provenance").fetchone()[0]),
        # pi-lens-ignore: unchecked-throwing-call-python
        "files": int(connection.execute("SELECT COUNT(*) FROM files").fetchone()[0]),
    }

    checksum_faults = verify_checksums(connection)
    fault_list = [
        {"code": fault.code, "message": fault.message, "affected_rows": fault.affected_rows}
        for fault in checksum_faults
    ]

    return {
        "schema_version": snapshot.schema_version,
        "projection_version": snapshot.projection_version,
        "database_path": str(snapshot.database_path),
        "checkpoints": checkpoints,
        "counts": counts,
        "checksum_status": "ok" if not checksum_faults else "audit_fault",
        "checksum_faults": fault_list,
    }


__all__ = ["collect_health"]
