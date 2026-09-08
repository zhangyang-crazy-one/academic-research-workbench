"""Parent-orchestrated research figure compilation and historical inspection."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.core.privacy import reject_secret_shapes
from arw.kernel.ledger.journal import locked_replay, replay_run
from arw.kernel.ledger.research_records import (
    BodyUnavailable,
    ResearchRecordError,
    commit_artifact_pipeline,
    publish_once,
    unlink_retained,
)
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.state.models import StableRuntimeId
from arw.kernel.state.research_artifact import (
    OutputDigest,
    ResearchArtifactIR,
    ResearchArtifactReceipt,
)

from .builder import SQLiteArtifactIRBuilder
from .renderer import SvgRenderer
from .validation import EvidenceValidator, IRValidationFault, accepted_content


class ResearchArtifactService:
    def __init__(self, *, renderer=None, validator=None, boundary=lambda _: None):
        self.renderer = renderer or SvgRenderer()
        self.validator = validator or EvidenceValidator()
        self.boundary = boundary

    def build(self, specification, *, run_root, store_path=None):
        return SQLiteArtifactIRBuilder().build(
            specification, run_root=run_root, store_path=store_path
        )

    def _render(self, ir):
        if ir.renderer_hints != self.renderer.identity:
            raise IRValidationFault("pinned_renderer_unavailable")
        raw = canonical_json_bytes(ir.model_dump(mode="json"))
        reject_secret_shapes(raw)
        output = self.renderer.render(ir)
        if len(output) > 2_097_152:
            raise IRValidationFault("render_output_budget_exceeded")
        return raw, output

    def render(self, ir, *, run_root):
        raw, output = self._render(ir)
        prefix = f".arw/artifacts/candidates/{ir.artifact_id}/{sha256_hex(raw)}"
        publish_once(run_root, f"{prefix}/ir.json", raw)
        publish_once(run_root, f"{prefix}/figure.svg", output)
        return {
            "status": "candidate",
            "ir_sha256": sha256_hex(raw),
            "output_sha256": sha256_hex(output),
            "path": f"{prefix}/figure.svg",
        }

    def qualify(self, ir, *, run_root, request, visual_review_id=None):
        def prepare(events):
            raw, output = self._render(ir)
            validation, reasons, reviewer, passed = self.validator.validate(
                ir,
                output,
                run_root=run_root,
                events=events,
                visual_review_id=visual_review_id,
            )
            ir_sha = sha256_hex(raw)
            candidate = f".arw/artifacts/candidates/{ir.artifact_id}/{ir_sha}"
            accepted = f".arw/artifacts/accepted/{ir.artifact_id}"
            prefix = accepted if passed else candidate
            receipt = ResearchArtifactReceipt(
                receipt_version="arw.research-artifact-receipt.v1",
                artifact_id=ir.artifact_id,
                artifact_kind=ir.artifact_kind,
                ir_sha256=ir_sha,
                renderer=self.renderer.identity,
                inputs=ir.research_bindings,
                outputs=(
                    OutputDigest(path=f"{prefix}/ir.json", sha256=ir_sha),
                    OutputDigest(
                        path=f"{prefix}/figure.svg", sha256=sha256_hex(output)
                    ),
                ),
                validation_policy=ir.validation_policy,
                validation=validation,
                qualification="PASS" if passed else "FAIL",
                purpose="publication-critical"
                if ir.publication_critical
                else "exploratory",
                visual_reviewer=reviewer,
                reason_codes=reasons,
            )
            receipt_raw = canonical_json_bytes(receipt.model_dump(mode="json"))
            files = {
                f"{candidate}/ir.json": raw,
                f"{candidate}/figure.svg": output,
                f"{candidate}/receipt.json": receipt_raw,
            }
            if passed:
                files.update(
                    {
                        f"{accepted}/ir.json": raw,
                        f"{accepted}/figure.svg": output,
                        f"{accepted}/receipt.json": receipt_raw,
                    }
                )
            return ir, receipt, files

        return commit_artifact_pipeline(
            run_root, request, prepare, boundary=self.boundary
        )

    def inspect(self, artifact_id, *, run_root):
        TypeAdapter(StableRuntimeId).validate_python(artifact_id)
        replayed = replay_run(run_root)
        matches = [
            e
            for e in replayed.events
            if e.event_type == "research_artifact_accepted"
            and e.payload.artifact_id == artifact_id
        ]
        if len(matches) != 1:
            raise ResearchRecordError("artifact_not_accepted")
        event = matches[0]
        prefix = f".arw/artifacts/accepted/{artifact_id}"
        if (Path(run_root) / prefix / "tombstone.json").exists():
            tombstone = json.loads(
                read_retained_bytes(run_root, f"{prefix}/tombstone.json")
            )
            authorization, auth_event, _ = accepted_content(
                run_root, replayed.events, tombstone["authorization_artifact_id"]
            )
            if (
                authorization.get("action") != "purge_research_artifact"
                or authorization.get("artifact_id") != artifact_id
                or auth_event.event_sha256 != tombstone["authorization_event_sha256"]
            ):
                raise ResearchRecordError("invalid_purge_authorization")
            raise BodyUnavailable(
                f"body intentionally unavailable: {artifact_id}; authorization {auth_event.event_id}"
            )
        raw = read_retained_bytes(run_root, f"{prefix}/receipt.json")
        if sha256_hex(raw) != event.payload.artifact_sha256:
            raise ResearchRecordError("receipt_digest_mismatch")
        receipt = ResearchArtifactReceipt.model_validate_json(raw)
        for output in receipt.outputs:
            if not output.path.startswith(prefix + "/"):
                raise ResearchRecordError("accepted_output_path_mismatch")
            if sha256_hex(read_retained_bytes(run_root, output.path)) != output.sha256:
                raise ResearchRecordError("accepted_output_digest_mismatch")
        binding = json.loads(read_retained_bytes(run_root, f"{prefix}/binding.json"))
        expected = {
            "artifact_id": artifact_id,
            "ir_sha256": event.payload.ir_sha256,
            "receipt_sha256": event.payload.artifact_sha256,
            "event_id": event.event_id,
            "event_sha256": event.event_sha256,
        }
        if binding != expected:
            raise ResearchRecordError("post_freeze_binding_mismatch")
        return {
            "status": "accepted",
            "receipt": receipt.model_dump(mode="json"),
            "binding": binding,
            "supersedes": event.payload.supersedes,
            "renderer_available": receipt.renderer == self.renderer.identity,
        }

    def reproduce(self, artifact_id, *, run_root):
        inspection = self.inspect(artifact_id, run_root=run_root)
        raw = read_retained_bytes(
            run_root, f".arw/artifacts/accepted/{artifact_id}/ir.json"
        )
        ir = ResearchArtifactIR.model_validate_json(raw)
        _, output = self._render(ir)
        expected = next(
            o["sha256"]
            for o in inspection["receipt"]["outputs"]
            if o["path"].endswith("/figure.svg")
        )
        if sha256_hex(output) != expected:
            raise ResearchRecordError("reproduction_digest_mismatch")
        return {
            "status": "reproduced",
            "artifact_id": artifact_id,
            "output_sha256": expected,
            "renderer": self.renderer.identity.model_dump(mode="json"),
        }

    def doctor(self, *, run_root):
        try:
            replayed = replay_run(run_root)
        except (ValueError, RuntimeError):
            return {"status": "FAIL", "faults": [{"code": "canonical_history_invalid"}], "accepted_artifacts": None}
        accepted = [
            e for e in replayed.events if e.event_type == "research_artifact_accepted"
        ]
        predecessors = {e.payload.artifact_id: e.payload.supersedes for e in accepted}
        faults = []
        for artifact_id in predecessors:
            seen = set()
            current = artifact_id
            while current is not None:
                if current in seen:
                    faults.append(
                        {"artifact_id": artifact_id, "code": "supersession_cycle"}
                    )
                    break
                seen.add(current)
                current = predecessors.get(current)
            try:
                inspection = self.inspect(artifact_id, run_root=run_root)
                if not inspection["renderer_available"]:
                    faults.append(
                        {
                            "artifact_id": artifact_id,
                            "code": "pinned_renderer_unavailable",
                        }
                    )
            except (ValueError, RuntimeError, OSError) as error:
                faults.append(
                    {
                        "artifact_id": artifact_id,
                        "code": getattr(error, "code", "artifact_integrity_fault"),
                    }
                )
        return {
            "status": "PASS" if not faults else "FAIL",
            "faults": faults,
            "accepted_artifacts": len(accepted),
        }

    def purge(
        self, artifact_id, *, run_root, authorization_artifact_id, authorized=False
    ):
        if not authorized:
            raise ResearchRecordError("explicit_purge_authorization_required")
        TypeAdapter(StableRuntimeId).validate_python(artifact_id)
        with locked_replay(run_root) as (_, replayed):
            accepting = next(
                (
                    e
                    for e in replayed.events
                    if e.event_type == "research_artifact_accepted"
                    and e.payload.artifact_id == artifact_id
                ),
                None,
            )
            if accepting is None:
                raise ResearchRecordError("artifact_not_accepted")
            value, authorization, _ = accepted_content(
                run_root, replayed.events, authorization_artifact_id
            )
            if (
                value.get("action") != "purge_research_artifact"
                or value.get("artifact_id") != artifact_id
            ):
                raise ResearchRecordError("authorization_does_not_cover_artifact")
            prefix = f".arw/artifacts/accepted/{artifact_id}"
            tombstone = {
                "artifact_id": artifact_id,
                "body_status": "intentionally_unavailable",
                "authorization_artifact_id": authorization_artifact_id,
                "authorization_event_sha256": authorization.event_sha256,
                "accepted_receipt_sha256": accepting.payload.artifact_sha256,
            }
            publish_once(
                run_root, f"{prefix}/tombstone.json", canonical_json_bytes(tombstone)
            )
            for directory in (
                prefix,
                f".arw/artifacts/candidates/{artifact_id}/{accepting.payload.ir_sha256}",
            ):
                for filename in ("ir.json", "figure.svg", "receipt.json"):
                    relative = f"{directory}/{filename}"
                    path = Path(run_root) / relative
                    if path.exists():
                        read_retained_bytes(run_root, relative)
                        unlink_retained(run_root, relative)
            return {"status": "body_unavailable", "tombstone": tombstone}
