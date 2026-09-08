"""Parent-owned candidate/review receipts bound to accepted source bytes."""

from pathlib import Path

from arw.kernel.core.canonical import (
    canonical_json_bytes,
    sha256_hex,
    strict_json_loads,
)
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger.journal import locked_replay
from arw.kernel.ledger.manifests import (
    load_artifact_manifest,
    validate_accepted_event_manifests,
)
from arw.kernel.ledger.research_records import publish_once
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.state.models import ArtifactAcceptanceRequest, RuntimeCommandRequest

from .transformer import SessionWritingTransformer


class WritingService(SessionWritingTransformer):
    def __init__(self, run_root):
        self.run_root = Path(run_root)

    def _source(self, artifact_id):
        with locked_replay(self.run_root) as (root, replay):
            validate_accepted_event_manifests(root, replay.events)
            matches = [
                e
                for e in replay.events
                if e.event_type in {"artifact.accepted", "research_artifact_accepted"}
                and e.payload.artifact_id == artifact_id
            ]
            if len(matches) != 1:
                raise ValueError("accepted source is missing or ambiguous")
            event = matches[0]
            manifest = load_artifact_manifest(root, event.payload.manifest_sha256)
            raw = read_retained_bytes(root, manifest.content_path, max_bytes=65536)
            if sha256_hex(raw) != event.payload.artifact_sha256:
                raise ValueError("accepted source digest mismatch")
            return raw, {
                "artifact_id": artifact_id,
                "sha256": sha256_hex(raw),
                "event_id": event.event_id,
                "event_sha256": event.event_sha256,
                "artifact_kind": manifest.artifact_kind,
                "manifest_sha256": event.payload.manifest_sha256,
            }

    def prepare(self, source_id, proposal):
        raw, binding = self._source(source_id)
        result = self.transform(raw.decode("utf-8"), proposal)
        result["source_binding"] = binding
        return result

    def record(self, source_id, proposal, *, request, review_artifact_id=None):
        request = RuntimeCommandRequest.model_validate(request.model_dump(mode="json"))
        result = self.prepare(source_id, proposal)
        result["review_binding"] = None
        # Rejected/ineffective candidates can be recorded as evidence, never accepted prose.
        if review_artifact_id is not None:
            raw, binding = self._source(review_artifact_id)
            review = strict_json_loads(raw)
            expected = {
                "schema_version": "arw.writing-review.v1",
                "source_sha256": result["source_sha256"],
                "candidate_sha256": result["candidate_sha256"],
                "proposal_sha256": result["proposal_sha256"],
                "verification_sha256": result["verification_sha256"],
                "decision": "APPROVED",
                "reviewed_dimensions": result["verification"]["unresolved_dimensions"],
            }
            if (
                binding["artifact_kind"] != "writing-human-review"
                or not isinstance(review, dict)
                or any(review.get(k) != v for k, v in expected.items())
                or not isinstance(review.get("reviewer"), str)
                or not review["reviewer"].strip()
                or not isinstance(review.get("rationale"), str)
                or not review["rationale"].strip()
            ):
                raise ValueError(
                    "explicit accepted review is missing, stale or incomplete"
                )
            if result["disposition"] == "reject" or not result["controls_effective"]:
                raise ValueError(
                    "hard preservation drift or ineffective controls cannot be approved"
                )
            result.update(
                disposition="accepted_after_human_review",
                accepted=True,
                review_binding=binding,
            )
        result["request_identity"] = request.model_dump(mode="json")
        body = canonical_json_bytes(result)
        digest = sha256_hex(body)
        path = f"writing/{sha256_hex(request.command_id.encode())}.json"
        artifact_id = "writing." + sha256_hex(request.command_id.encode())[:32]
        canonical_request = ArtifactAcceptanceRequest.model_validate(
            {
                **request.model_dump(mode="json"),
                "artifact_id": artifact_id,
                "artifact_kind": "writing-derived"
                if result["accepted"]
                else "writing-review-receipt",
                "media_type": "application/json",
                "content_path": path,
                "content_sha256": digest,
                "base_revision": request.expected_revision,
                "consumed_sha256": [result["source_binding"]["manifest_sha256"]]
                + (
                    [result["review_binding"]["manifest_sha256"]]
                    if result["review_binding"]
                    else []
                ),
            }
        )
        # Exact retries retain the same binding; changing review or proposal conflicts.
        with locked_replay(self.run_root) as (_root, replay):
            for event in replay.events:
                if (
                    event.command_id == request.command_id
                    or event.event_id == request.event_id
                ):
                    if (
                        event.event_type == "artifact.accepted"
                        and event.command_id == request.command_id
                        and event.event_id == request.event_id
                        and event.payload.artifact_id == artifact_id
                        and event.payload.artifact_sha256 == digest
                    ):
                        return {
                            "status": "already_recorded",
                            "event_id": event.event_id,
                            "artifact_id": artifact_id,
                            "bundle_path": path,
                            "disposition": result["disposition"],
                            "candidate_accepted": result["accepted"],
                        }
                    raise ValueError("writing command identity conflict")
        publish_once(self.run_root, path, body)
        outcome = RuntimeCommandService(self.run_root).accept_artifact(
            canonical_request
        )
        if not outcome.accepted:
            return {
                "status": "rejected",
                "reason_code": outcome.rejection.code,
                "candidate_accepted": False,
                "bundle_path": path,
            }
        return {
            "status": "recorded",
            "event_id": outcome.event.event_id,
            "artifact_id": artifact_id,
            "bundle_path": path,
            "disposition": result["disposition"],
            "candidate_accepted": result["accepted"],
        }
