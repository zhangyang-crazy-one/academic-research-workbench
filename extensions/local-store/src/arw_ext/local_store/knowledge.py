"""KnowledgeProvider adapter for the local SQLite projection store (PR4 Lane B).

The adapter satisfies the ``KnowledgeProvider`` protocol
(:mod:`arw.ports.knowledge`) on top of :class:`LocalProjectionStore`.  It
mirrors :class:`arw.adapters.knowledge.GraphProjectionAdapter` byte-for-byte
at the receipt + query result level so the v2 oracle
(``arw.graph_oracle.assert_equivalent``) treats both adapters as the same
projection.

The adapter owns:

* one :class:`LocalProjectionStore` instance (passed in by the composition root),
* the canonical event stream for the run (the caller passes the
  :class:`arw.kernel.ledger.journal.ReplayState` events at build time).

The adapter writes receipts to ``<database>.receipts/<generation_id>.json``
and audit faults to ``<database>.audit/<...>.json`` (see ``receipts.py``).
"""

from __future__ import annotations

import json
import sqlite3

from arw.graph_models import (
    GRAPH_SCHEMA_VERSION,
    GraphProjectionInput,
    GraphProjectionReceipt,
    GraphQueryRequest,
    GraphQueryResult,
    GraphResultStatus,
)
from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.ledger.journal import ReplayState
from arw.kernel.ledger.reducer import RuntimeState, reduce_events

from .apply import (
    ApplyError,
    ApplyResult,
    apply_projection,
    build_graph_manifest,
)
from .query import execute_query
from .receipts import (
    clear_audit_faults,
    persist_audit_fault,
    persist_receipt,
    receipts_root,
)


class LocalStoreKnowledgeAdapter:
    """KnowledgeProvider over LocalProjectionStore.

    The ``run_state`` parameter is a :class:`ReplayState` whose events drive
    the apply path.  ``run_id`` is the canonical run identity; the adapter
    records the reducer-produced run state in the store as a side effect of
    every successful build (so status consumers in later lanes can read it).
    """

    def __init__(
        self,
        store,
        *,
        run_id: str,
        run_state: ReplayState,
        workflow_definition_id: str,
        root_id: str,
        projection_name: str = "knowledge",
    ) -> None:
        self._store = store
        self._run_id = run_id
        self._run_state = run_state
        self._workflow_definition_id = workflow_definition_id
        self._root_id = root_id
        self._projection_name = projection_name

    # ------------------------------------------------------------------
    # KnowledgeProvider protocol
    # ------------------------------------------------------------------

    def build_full(self, projection: GraphProjectionInput) -> GraphProjectionReceipt:
        return self._build(projection, incremental=False)

    def build_incremental(
        self, projection: GraphProjectionInput
    ) -> GraphProjectionReceipt:
        return self._build(projection, incremental=True)

    def delete_and_rebuild(
        self, projection: GraphProjectionInput
    ) -> GraphProjectionReceipt:
        """Build a fresh projection, then clear the previous receipts.

        The local store keeps every receipt by ``generation_id``; deleting
        a rebuild only clears the *projection tables* (the apply path
        truncates them on ``incremental=False``).  Receipt history is
        preserved unless the operator removes the sidecar directory.
        """

        receipt = self._build(projection, incremental=False)
        return receipt

    def query(self, request: GraphQueryRequest) -> GraphQueryResult:
        store = self._store
        store.assert_open()
        connection = store.connection
        cursor = connection.cursor()
        cursor.execute(
            "SELECT last_ledger_sequence, last_ledger_event_digest "
            "FROM projection_checkpoints WHERE projection_name = ?",
            (self._projection_name,),
        )
        checkpoint = cursor.fetchone()
        if checkpoint is None:
            return _unavailable(
                request, "projection_unavailable", "no projection is selected"
            )
        # pi-lens-ignore: unchecked-throwing-call-python
        selected_watermark = int(checkpoint[0])

        generation_id = self._receipt_generation_id()
        if generation_id is None:
            return _unavailable(
                request, "projection_unavailable", "no receipted generation is selected"
            )
        manifest_sha256 = self._manifest_sha256(generation_id)
        if manifest_sha256 is None:
            return _unavailable(
                request,
                "projection_corrupt",
                "selected generation has no persisted receipt",
            )

        return execute_query(
            connection,
            request,
            selected_generation_id=generation_id,
            selected_manifest_sha256=manifest_sha256,
            selected_ledger_watermark=selected_watermark,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build(
        self,
        projection: GraphProjectionInput,
        *,
        incremental: bool,
    ) -> GraphProjectionReceipt:
        store = self._store
        store.assert_open()
        connection = store.connection
        cursor = connection.cursor()
        # Deterministic generation identity: derived from the projection
        # input so repeated builds over the same input converge on the same
        # generation (and receipts overwrite rather than accumulate).
        generation_id = f"{self._projection_name}-{projection.input_sha256[:16]}"
        apply_result: ApplyResult | None = None
        try:
            cursor.execute("BEGIN")
            try:
                events = list(self._run_state.events)
                if not events:
                    raise ApplyError(
                        "apply requires at least run.initialized",
                        code="apply_projection_invalid",
                    )
                # Apply path may consume the projection.input_sha256 identity
                # to build the receipt; pass the projection through.
                apply_result = apply_projection(
                    connection,
                    run_id=self._run_id,
                    workflow_definition_id=self._workflow_definition_id,
                    events=events,
                    projection=projection,
                    projection_name=self._projection_name,
                    incremental=incremental,
                    receipt_id=generation_id,
                )
            except ApplyError:
                cursor.execute("ROLLBACK")
                raise
            except Exception:
                cursor.execute("ROLLBACK")
                raise
            else:
                cursor.execute("COMMIT")
        except sqlite3.Error as error:
            return _block_receipt(
                projection,
                self._root_id,
                code="projection_corrupt",
                message=f"apply transaction failed: {error}",
            )

        # Persist audit faults only after COMMIT: sidecar files must never
        # survive a rolled-back projection transaction.  Full rebuilds first
        # clear this projection's stale faults.
        if apply_result is None:
            raise ApplyError(
                "apply did not produce a result", code="apply_projection_invalid"
            )
        clear_audit_faults(store.database_path)
        for fault in apply_result.audit_faults:
            persist_audit_fault(store.database_path, fault)

        # Build the manifest + receipt envelope.  The receipt embeds the
        # input_sha256 + projection_manifest_sha256 so v1/v2 oracle compare.
        manifest = build_graph_manifest(
            projection_name=self._projection_name,
            projection=projection,
            generation_id=generation_id,
            last_ledger_event_digest=apply_result.last_ledger_event_digest,
            database_path_str=str(store.database_path),
        )
        manifest_bytes = canonical_json_bytes(manifest.model_dump(mode="json"))
        projection_manifest_sha256 = sha256_hex(manifest_bytes)

        receipt = GraphProjectionReceipt(
            schema_version=GRAPH_SCHEMA_VERSION,
            root_id=self._root_id,
            candidate_generation_id=generation_id,
            previous_generation_id=None,
            selected_generation_id=generation_id,
            projection_manifest_sha256=projection_manifest_sha256,
            input_sha256=projection.input_sha256,
            ledger_watermark=projection.ledger_watermark,
            status="PASS",
            reason_codes=[],
        )
        persist_receipt(store.database_path, receipt)

        # The selected-generation pointer is written LAST, in its own
        # transaction, only after the receipt sidecar exists on disk.  A
        # crash between the apply COMMIT and this point leaves the pointer
        # at the previous (fully-receipted) generation — never dangling.
        cursor.execute(
            "INSERT INTO projection_meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (
                f"projection.{self._projection_name}.selected_generation_id",
                generation_id,
            ),
        )
        connection.commit()
        return receipt

    def _receipt_generation_id(self) -> str | None:
        """Return the selected generation id recorded by the last build.

        The pointer lives in ``projection_meta`` (written in the same
        transaction as the apply) so a rolled-back build can never leave a
        dangling selection; the receipts directory is evidence, not state.
        """

        store = self._store
        store.assert_open()
        row = store.connection.execute(
            "SELECT value FROM projection_meta WHERE key = ?",
            (f"projection.{self._projection_name}.selected_generation_id",),
        ).fetchone()
        if row is None:
            return None
        return str(row[0])

    def _manifest_sha256(self, generation_id: str | None) -> str | None:
        store = self._store
        store.assert_open()
        if not generation_id:
            return None
        root = receipts_root(store.database_path)
        candidate = root / f"{generation_id}.json"
        if not candidate.is_file():
            return None
        try:
            payload = json.loads(candidate.read_bytes())
        except (OSError, ValueError):
            return None
        return payload.get("projection_manifest_sha256")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unavailable(
    request: GraphQueryRequest,
    code: str,
    message: str,
) -> GraphQueryResult:
    status: GraphResultStatus = (
        code  # type: ignore[assignment]
        if code in {"projection_stale", "projection_corrupt", "projection_unavailable"}
        else "projection_unavailable"
    )
    return GraphQueryResult(
        schema_version=GRAPH_SCHEMA_VERSION,
        operation=request.operation,
        status=status,
        projection_generation_id=None,
        projection_manifest_sha256=None,
        ledger_watermark=None,
        rows=[],
        next_cursor=None,
        reason_code=code,
    )


def _block_receipt(
    projection: GraphProjectionInput,
    root_id: str,
    *,
    code: str,
    message: str,
) -> GraphProjectionReceipt:
    return GraphProjectionReceipt(
        schema_version=GRAPH_SCHEMA_VERSION,
        root_id=root_id,
        candidate_generation_id="knowledge-blocked",
        previous_generation_id=None,
        selected_generation_id=None,
        projection_manifest_sha256=None,
        input_sha256=projection.input_sha256,
        ledger_watermark=projection.ledger_watermark,
        status="BLOCKED",
        reason_codes=[code],
    )


def reducer_state_for_replay(run_state: ReplayState) -> RuntimeState:
    """Return the reducer state for a replay (helper for composition root)."""

    return reduce_events(run_state.workflow_definition_id, run_state.events)


__all__ = [
    "ApplyResult",
    "LocalStoreKnowledgeAdapter",
    "reducer_state_for_replay",
]
