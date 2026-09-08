"""Canonical command retries without retaining a second copy of learning bodies."""

import inspect
import json
from contextvars import ContextVar
from functools import wraps

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.core.privacy import reject_secret_shapes
from arw.kernel.ledger.journal import replay_run
from arw.kernel.ledger.source_locations import read_retained_bytes

from .store import LearningDisabled, LearningFault, configuration, inventory

ACTIVE_INTENT = ContextVar("learning_command_intent", default=None)


def command_path(command_id):
    return f".arw/learning/commands/{command_id}.json"


def _json(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def replayable(method):
    signature = inspect.signature(method)

    @wraps(method)
    def execute(self, *args, **kwargs):
        bound = signature.bind(self, *args, **kwargs)
        bound.apply_defaults()
        values = {
            key: _json(value)
            for key, value in bound.arguments.items()
            if key not in {"self", "request"}
        }
        request = bound.arguments["request"]
        raw = canonical_json_bytes({"operation": method.__name__, "values": values})
        reject_secret_shapes(raw)
        intent = {
            "intent_sha256": sha256_hex(raw),
            "request_sha256": sha256_hex(
                canonical_json_bytes(request.model_dump(mode="json"))
            ),
        }
        policy = configuration(self.root)
        if not policy.enabled or request.run_id in policy.disabled_run_ids:
            raise LearningDisabled(
                "new learning writes are disabled by project/run policy"
            )
        state = replay_run(self.run_root)
        existing = next(
            (e for e in state.events if e.command_id == request.command_id), None
        )
        if existing is not None:
            old = json.loads(
                read_retained_bytes(
                    self.root, command_path(request.command_id), max_bytes=4096
                )
            )
            if old != intent or existing.run_id != request.run_id:
                raise LearningFault(
                    "command retry changes its original operation or request"
                )
            records, _ = inventory(self.root)
            result = self._receipt(existing, True)
            if method.__name__ == "extract" and bound.arguments["value"].supersedes:
                value = bound.arguments["value"]
                prior = records[value.supersedes]
                if prior["head"].payload.status != "superseded":
                    self._supersede(value.supersedes, value.heuristic_id, request)
            if method.__name__ == "observe":
                result["duplicate_of"] = records[existing.payload.record_id]["body"][
                    "duplicate_of"
                ]
                result["dedup_policy"] = "ledger-event-and-source-digest-v1"
            if method.__name__ == "evaluate":
                from .store import load_body

                _, runs = inventory(self.root)
                evaluation = load_body(self.root, existing.payload.content_digest, runs)
                result.update(
                    qualification=evaluation["qualification"],
                    metrics=evaluation["metrics"],
                )
            return self._finish(result)
        token = ACTIVE_INTENT.set(intent)
        try:
            return method(self, *args, **kwargs)
        finally:
            ACTIVE_INTENT.reset(token)

    return execute
