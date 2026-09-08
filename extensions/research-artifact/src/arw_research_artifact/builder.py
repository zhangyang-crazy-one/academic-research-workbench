"""A files-authoritative IR builder using the existing SQLite artifact schema."""

import json
import sqlite3

from arw_ext.local_store.migrations import initialize_fresh

from arw.kernel.core.privacy import reject_secret_shapes
from arw.kernel.ledger.journal import replay_run
from arw.kernel.ledger.manifests import load_artifact_manifest
from arw.kernel.state.models import ArtifactAcceptedPayload
from arw.kernel.state.research_artifact import ResearchArtifactIR

from .renderer import SvgRenderer
from .validation import IRValidationFault, resolve_bindings


class SQLiteArtifactIRBuilder:
    def build(self, specification: dict, *, run_root, store_path=None):
        reject_secret_shapes(json.dumps(specification, ensure_ascii=False))
        value = {**specification}
        value.setdefault(
            "renderer_hints", SvgRenderer().identity.model_dump(mode="json")
        )
        ir = ResearchArtifactIR.model_validate_json(json.dumps(value))
        replayed = replay_run(run_root)
        # The source index is disposable. Reuse the local-store migrations and
        # artifact columns; populate only canonically accepted source metadata.
        connection = sqlite3.connect(":memory:")
        try:
            initialize_fresh(connection)
            for event in replayed.events:
                if event.event_type not in {
                    "artifact.accepted",
                    "research_artifact_accepted",
                } or not isinstance(event.payload, ArtifactAcceptedPayload):
                    continue
                manifest = load_artifact_manifest(
                    run_root, event.payload.manifest_sha256
                )
                connection.execute(
                    "INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        manifest.artifact_id,
                        manifest.artifact_kind,
                        manifest.content_path,
                        manifest.content_sha256,
                        manifest.content_sha256,
                        0,
                        event.occurred_at,
                        event.event_id,
                        event.event_sha256,
                        "research-artifact.v1",
                        "{}",
                    ),
                )
            for binding in ir.research_bindings:
                row = connection.execute(
                    "SELECT source_digest,accepting_event_id,accepting_event_digest FROM artifacts WHERE artifact_id=?",
                    (binding.artifact_id,),
                ).fetchone()
                if row != (
                    binding.sha256,
                    binding.ledger_event_id,
                    binding.ledger_event_sha256,
                ):
                    raise IRValidationFault(
                        "source metadata is absent from accepted SQLite projection"
                    )
            resolve_bindings(ir, run_root, replayed.events)
            return ir
        finally:
            connection.close()
