"""Explicit learning operations backed by the existing canonical run writer."""

import json
import uuid
from contextlib import contextmanager
from pathlib import Path

import portalocker

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.core.privacy import reject_secret_shapes
from arw.kernel.ledger.journal import (
    append_runtime_event_unlocked,
    build_runtime_event,
    locked_replay,
)
from arw.kernel.ledger.reducer import reduce_events
from arw.kernel.ledger.research_records import (
    BodyUnavailable,
    publish_once,
    unlink_retained,
)
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.state.models import ResearchLearningPayload
from arw.kernel.state.research_learning import (
    Applicability,
    EvaluationPolicy,
    EvaluationSample,
    HeuristicInput,
    LearningObservation,
    ResearchHeuristic,
)

from .operations import ACTIVE_INTENT, command_path, replayable
from .store import (
    LearningDisabled,
    LearningFault,
    ReevaluationRequired,
    accepted_artifact,
    body_path,
    configuration,
    identity,
    inventory,
    load_body,
    marker_path,
    rebuild,
)


class ResearchLearningService:
    def __init__(self, project_root, *, run_root=None, boundary=lambda _: None):
        self.root = Path(project_root).absolute()
        self.project_id = identity(self.root).project_id
        self.run_root = Path(run_root).absolute() if run_root is not None else None
        if self.run_root is not None and not self.run_root.is_relative_to(self.root):
            raise LearningFault("run is outside selected project")
        self.boundary = boundary

    @contextmanager
    def _writer(self, request):
        policy = configuration(self.root)
        if not policy.enabled or request.run_id in policy.disabled_run_ids:
            raise LearningDisabled(
                "new learning writes are disabled by project/run policy"
            )
        if identity(self.root).project_id != self.project_id:
            raise LearningFault("project identity changed")
        if self.run_root is None or request.actor_role != "parent_control_plane":
            raise LearningFault("learning writes require a parent-bound run")
        publish_once(self.root, ".arw/learning/.lock", b"")
        lock = self.root / ".arw/learning/.lock"
        if lock.is_symlink():
            raise LearningFault("unsafe learning lock")
        with portalocker.Lock(lock, mode="rb", timeout=5):  # noqa: SIM117 -- project lock precedes run lock
            with locked_replay(self.run_root) as (_, state):
                if state.run_id != request.run_id or state.recovery_health != "healthy":
                    raise LearningFault("run identity or recovery prevents learning")
                relative = self.run_root.relative_to(self.root).as_posix()
                manifest = read_retained_bytes(
                    self.run_root, "run-manifest.json", max_bytes=65536
                )
                publish_once(
                    self.root,
                    f".arw/learning/runs/{state.run_id}.json",
                    canonical_json_bytes(
                        {
                            "project_id": self.project_id,
                            "run_id": state.run_id,
                            "relative_root": "" if relative == "." else relative,
                            "manifest_sha256": sha256_hex(manifest),
                        }
                    ),
                )
                yield state

    def _commit(
        self, state, request, kind, body, *, prior=None, sources=(), **metadata
    ):
        raw = canonical_json_bytes(body)
        reject_secret_shapes(raw)
        if len(raw) > 65536:
            raise LearningFault("learning body exceeds byte budget")
        digest = sha256_hex(raw)
        record_id = body.get(
            "record_id", body.get("heuristic_id", body.get("observation_id"))
        )
        payload = ResearchLearningPayload(
            record_id=record_id,
            project_id=self.project_id,
            content_digest=digest,
            scope=metadata.pop(
                "scope", body.get("scope", prior.payload.scope if prior else "project")
            ),
            previous_event_sha256=prior.event_sha256 if prior else None,
            source_event_ids=[e.event_id for e in sources],
            source_digests=[
                getattr(e.payload, "artifact_sha256", e.event_sha256) for e in sources
            ],
            **metadata,
        )
        old = next(
            (e for e in state.events if e.command_id == request.command_id), None
        )
        if old is not None:
            # A retry reuses frozen content and the original prior state, not a new transition.
            if (
                old.event_type != kind
                or old.payload.content_digest != digest
                or old.payload.record_id != record_id
            ):
                raise LearningFault("command already binds different learning content")
            return self._receipt(old, True)
        if state.revision != request.expected_revision:
            raise LearningFault("stale learning revision")
        event = build_runtime_event(
            state,
            event_type=kind,
            event_id=request.event_id,
            command_id=request.command_id,
            occurred_at=request.occurred_at,
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            payload=payload,
        )
        reduce_events(state.workflow_definition_id, (*state.events, event))
        if ACTIVE_INTENT.get() is not None:
            publish_once(
                self.root,
                command_path(request.command_id),
                canonical_json_bytes(ACTIVE_INTENT.get()),
            )
        publish_once(self.root, body_path(digest), raw)
        self.boundary("files_durable")
        append_runtime_event_unlocked(self.run_root, state, event)
        self.boundary("event_durable")
        return self._receipt(event, False)

    def _receipt(self, event, idempotent):
        return {
            "accepted": True,
            "record_id": event.payload.record_id,
            "status": event.payload.status,
            "content_digest": event.payload.content_digest,
            "event_id": event.event_id,
            "event_sha256": event.event_sha256,
            "idempotent": idempotent,
            "interpretation": "Advisory heuristic; no executable workflow or policy is generated.",
        }

    def _finish(self, result):
        rebuild(self.root)
        self.boundary("projection_updated")
        return result

    def status(self):
        policy = configuration(self.root)
        records, _ = inventory(self.root)
        return {
            "project_id": self.project_id,
            "learning": policy.model_dump(mode="json"),
            "records": len(records),
            "workflow_evolution": "unavailable: research-workflow-evolver",
        }

    @replayable
    def observe(self, event_id, *, request):
        with self._writer(request) as state:
            source = next((e for e in state.events if e.event_id == event_id), None)
            if source is None:
                raise LearningFault(
                    "observation requires an accepted canonical source event"
                )
            kinds = {
                "artifact.accepted": "artifact_receipt",
                "research_artifact_accepted": "artifact_receipt",
                "lifecycle.transitioned": "transition",
                "gate.evaluated": "validation",
                "human_decision.recorded": "human_signal",
                "human_authority.accepted": "human_signal",
                "experiment.provenance.accepted": "experiment",
                "hook.observed": "tool_receipt",
                "proposal.rejected": "validation",
                "attempt.lifecycle": "validation",
            }
            if source.event_type not in kinds:
                raise LearningFault("source is not in the observation vocabulary")
            records, _ = inventory(self.root, held=(self.run_root, state))
            source_digest = getattr(
                source.payload, "artifact_sha256", source.event_sha256
            )
            artifact_ids = ()
            if kinds[source.event_type] == "artifact_receipt":
                artifact_ids = (source.payload.artifact_id,)
                _, raw = accepted_artifact(self.run_root, state.events, artifact_ids[0])
                reject_secret_shapes(raw)
            record_id = "observation-" + str(
                uuid.UUID(request.command_id.removeprefix("cmd-"))
            )
            if len(records) >= 1024 and record_id not in records:
                raise LearningFault("learning record budget exceeded")
            duplicates = [
                entry
                for key, entry in records.items()
                if key != record_id
                and entry["body"]
                and entry["head"].payload.status == "recorded"
                and entry["body"]["ledger_event_id"] == event_id
                and entry["body"]["source_digest"] == source_digest
                and entry["body"]["duplicate_of"] is None
            ]
            duplicate_of = (
                duplicates[0]["head"].payload.record_id if duplicates else None
            )
            body = LearningObservation(
                observation_id=record_id,
                project_id=self.project_id,
                run_id=state.run_id,
                ledger_event_id=event_id,
                observation_kind=kinds[source.event_type],
                source_activity_id=getattr(source.payload, "attempt_id", None),
                source_tool_id=None,
                source_artifact_ids=artifact_ids,
                trigger=source.event_type,
                outcome=f"Canonical {source.event_type} accepted at revision {source.resulting_revision}",
                human_signal="accepted canonical human signal"
                if kinds[source.event_type] == "human_signal"
                else None,
                created_at=request.occurred_at,
                source_digest=source_digest,
                duplicate_of=duplicate_of,
            )
            result = self._commit(
                state,
                request,
                "learning_observation_recorded",
                body.model_dump(mode="json"),
                sources=[source],
                status="recorded",
            )
            result["duplicate_of"] = duplicate_of
            result["dedup_policy"] = body.dedup_policy
        return self._finish(result)

    @replayable
    def extract(self, value: HeuristicInput, *, request):
        # Canonical input is validated even for direct Python callers.
        value = HeuristicInput.model_validate_json(value.model_dump_json())
        reject_secret_shapes(canonical_json_bytes(value.model_dump(mode="json")))
        if value.scope not in {"run", "project"}:
            raise LearningFault("broader scopes require explicit qualified promotion")
        with self._writer(request) as state:
            records, _ = inventory(self.root, held=(self.run_root, state))
            existing = records.get(value.heuristic_id)
            old_command = next(
                (e for e in state.events if e.command_id == request.command_id), None
            )
            if existing and old_command is None:
                raise LearningFault(
                    "heuristic identity exists; create a successor version"
                )
            if len(records) >= 1024 and existing is None:
                raise LearningFault("learning record budget exceeded")
            observations = []
            for observation_id in (
                *value.supporting_observation_ids,
                *value.counterexample_observation_ids,
                *(u.observation_id for u in value.unknown),
            ):
                entry = records.get(observation_id)
                if (
                    not entry
                    or entry["head"].payload.status != "recorded"
                    or entry["body"] is None
                ):
                    raise LearningFault(
                        "heuristic evidence must reference available canonical observations"
                    )
                if entry["body"]["duplicate_of"] is not None:
                    raise LearningFault(
                        "duplicate observation must reference the original sample"
                    )
                observations.append(entry)
            if value.supersedes:
                predecessor = records.get(value.supersedes)
                if not predecessor or predecessor["head"].payload.status in {
                    "recorded",
                    "superseded",
                }:
                    raise LearningFault(
                        "supersession requires an existing unsuperseded heuristic"
                    )
                if predecessor["run_root"] != self.run_root:
                    raise LearningFault(
                        "successor must use the predecessor canonical run"
                    )
            supporting_runs = tuple(
                sorted(
                    {
                        records[x]["body"]["run_id"]
                        for x in value.supporting_observation_ids
                    }
                )
            )
            counterexample_runs = tuple(
                sorted(
                    {
                        records[x]["body"]["run_id"]
                        for x in value.counterexample_observation_ids
                    }
                )
            )
            body = ResearchHeuristic(
                **value.model_dump(),
                project_id=self.project_id,
                run_id=state.run_id,
                supporting_run_ids=supporting_runs,
                counterexample_run_ids=counterexample_runs,
                created_at=request.occurred_at,
                updated_at=request.occurred_at,
                status="candidate",
                trust="unreviewed",
            )
            # References to other registered runs are retained in the body; this run binds its own events.
            sources = [
                e["head"] for e in observations if e["run_root"] == self.run_root
            ]
            result = self._commit(
                state,
                request,
                "research_heuristic_proposed",
                body.model_dump(mode="json"),
                sources=sources,
                status="candidate",
            )
        if value.supersedes:
            self._supersede(value.supersedes, value.heuristic_id, request)
        return self._finish(result)

    def import_heuristic(self, value, *, request):
        # External status/approval is discarded, never restored as local authority.
        payload = {k: v for k, v in value.items() if k in HeuristicInput.model_fields}
        payload["scope"] = "project"
        return self.extract(
            HeuristicInput.model_validate_json(json.dumps(payload)), request=request
        )

    def _entry(self, records, record_id, *, writable=False):
        entry = records.get(record_id)
        if not entry or entry["head"].payload.status == "recorded":
            raise LearningFault("heuristic does not exist")
        if entry["tombstoned"] or entry["body"] is None or entry["candidate"] is None:
            raise BodyUnavailable(f"heuristic {record_id} body is unavailable")
        if writable and entry["run_root"] != self.run_root:
            raise LearningFault("heuristic lifecycle must use its originating run")
        return entry

    def inspect(self, heuristic_id):
        records, runs = inventory(self.root)
        entry = self._entry(records, heuristic_id)
        p = entry["head"].payload
        result = dict(entry["candidate"])
        result.update(
            status=p.status,
            scope=p.scope,
            trust="advisory" if p.status == "promoted" else "unreviewed",
            qualification_receipt_id=p.qualification_receipt_id,
            accepted_ledger_event_id=entry["head"].event_id
            if p.status == "promoted"
            else None,
            updated_at=entry["head"].occurred_at,
            lifecycle_receipt=entry["body"],
        )
        if p.evaluation_receipt_id:
            result["evaluation"] = load_body(self.root, p.evaluation_receipt_id, runs)
        return result

    def list(self, *, max_items=20):
        if not isinstance(max_items, int) or not 1 <= max_items <= 50:
            raise LearningFault("max_items must be between 1 and 50")
        records, _ = inventory(self.root)
        entries = [
            (key, entry)
            for key, entry in sorted(records.items())
            if entry["head"].payload.status != "recorded"
        ]
        return {
            "items": [
                {
                    "heuristic_id": key,
                    "status": "tombstoned"
                    if entry["tombstoned"]
                    else entry["head"].payload.status,
                    "scope": entry["head"].payload.scope,
                    "body_recoverable": not entry["tombstoned"],
                }
                for key, entry in entries[:max_items]
            ],
            "truncated": len(entries) > max_items,
        }

    def rebuild(self):
        return rebuild(self.root)

    def _policy(self, state):
        artifact_id = configuration(self.root).evaluation_policy_artifact_id
        if not artifact_id:
            raise LearningFault("an accepted versioned evaluation policy is required")
        event, raw = accepted_artifact(self.run_root, state.events, artifact_id)
        return EvaluationPolicy.model_validate_json(raw), event

    @replayable
    def evaluate(self, heuristic_id, sample_artifact_ids, *, request):
        if (
            not sample_artifact_ids
            or len(sample_artifact_ids) > 256
            or len(sample_artifact_ids) != len(set(sample_artifact_ids))
        ):
            raise LearningFault("evaluation requires unique bounded accepted samples")
        with self._writer(request) as state:
            records, runs = inventory(self.root, held=(self.run_root, state))
            entry = self._entry(records, heuristic_id, writable=True)
            policy, policy_event = self._policy(state)
            if entry["head"].payload.status not in {
                "candidate",
                "evaluated",
                "qualified",
            }:
                raise LearningFault(
                    "terminal heuristic requires a new successor version"
                )
            samples, sources = [], [policy_event]
            # Explicit IDs resolve only among this project's registered canonical runs.
            for artifact_id in sample_artifact_ids:
                matches = [
                    (root, run)
                    for root, run in runs.values()
                    if any(
                        e.event_type
                        in {"artifact.accepted", "research_artifact_accepted"}
                        and e.payload.artifact_id == artifact_id
                        for e in run.events
                    )
                ]
                if len(matches) != 1:
                    raise LearningFault(
                        "sample artifact reference is missing or ambiguous across runs"
                    )
                root, run = matches[0]
                event, raw = accepted_artifact(root, run.events, artifact_id)
                reject_secret_shapes(raw)
                sample = EvaluationSample.model_validate_json(raw)
                if (
                    sample.run_id != run.run_id
                    or sample.heuristic_id != heuristic_id
                    or sample.policy_id != policy.policy_id
                    or sample.policy_version != policy.version
                    or sample.mode != policy.mode
                    or sample.metric != policy.metric
                ):
                    raise LearningFault(
                        "evaluation sample identity/policy/mode/metric mismatch"
                    )
                if sample.proposed_action != entry["candidate"]["proposed_action"]:
                    raise LearningFault("sample does not evaluate the candidate action")
                if policy.mode == "human-review" and (
                    not sample.reviewer or sample.approved is None
                ):
                    raise LearningFault(
                        "human review requires an actual recorded reviewer decision"
                    )
                samples.append(
                    {
                        "artifact_id": artifact_id,
                        "event_id": event.event_id,
                        "source_digest": event.payload.artifact_sha256,
                        "sample": sample.model_dump(mode="json"),
                    }
                )
                if root == self.run_root:
                    sources.append(event)
            run_ids = [sample["sample"]["run_id"] for sample in samples]
            if len(set(run_ids)) != len(run_ids) or set(run_ids) != set(
                policy.run_subset
            ):
                raise LearningFault(
                    "samples must use the exact recorded independent run subset"
                )
            deltas = [s["sample"]["outcome"] - s["sample"]["baseline"] for s in samples]
            mean_delta = sum(deltas) / len(deltas)
            passed = (
                mean_delta >= policy.minimum_delta
                and all(s["sample"]["approved"] is True for s in samples)
                if policy.mode == "human-review"
                else mean_delta >= policy.minimum_delta
            )
            candidate = entry["candidate"]
            confidence = None
            if policy.use_confidence:
                supporting = len(candidate["supporting_observation_ids"])
                counter = len(candidate["counterexample_observation_ids"])
                confidence = {
                    "formula_id": policy.formula_id,
                    "formula_version": policy.formula_version,
                    "inputs": {"supporting": supporting, "counterexample": counter},
                    "value": supporting / (supporting + counter),
                    "advisory": True,
                }
            body = {
                "schema_version": "arw.heuristic-evaluation.v1",
                "record_id": heuristic_id,
                "project_id": self.project_id,
                "heuristic_digest": entry["creation"].payload.content_digest,
                "policy": policy.model_dump(mode="json"),
                "policy_digest": policy_event.payload.artifact_sha256,
                "mode": policy.mode,
                "samples": samples,
                "run_ids": run_ids,
                "metrics": {"mean_delta": mean_delta, "sample_count": len(samples)},
                "qualification": "PASS" if passed else "FAIL",
                "supporting": candidate["supporting_observation_ids"],
                "counterexample": candidate["counterexample_observation_ids"],
                "unknown": candidate["unknown"],
                "search_coverage": candidate["search_coverage"],
                "evaluation_coverage": candidate["evaluation_coverage"],
                "confidence": confidence,
                "workflow_modified": False,
            }
            digest = sha256_hex(canonical_json_bytes(body))
            result = self._commit(
                state,
                request,
                "research_heuristic_evaluated",
                body,
                prior=entry["head"],
                sources=sources,
                status="evaluated",
                evaluation_receipt_id=digest,
            )
            result.update(qualification=body["qualification"], metrics=body["metrics"])
        return self._finish(result)

    @replayable
    def qualify(self, heuristic_id, *, request):
        with self._writer(request) as state:
            records, runs = inventory(self.root, held=(self.run_root, state))
            entry = self._entry(records, heuristic_id, writable=True)
            _policy, policy_event = self._policy(state)
            p = entry["head"].payload
            if p.status != "evaluated" or not p.evaluation_receipt_id:
                raise LearningFault("qualification requires an explicit evaluation")
            evaluation = load_body(self.root, p.evaluation_receipt_id, runs)
            if evaluation["policy_digest"] != policy_event.payload.artifact_sha256:
                raise ReevaluationRequired("evaluation policy changed; evaluate again")
            if evaluation["qualification"] != "PASS":
                raise LearningFault("failed evaluation cannot qualify")
            body = {
                "schema_version": "arw.heuristic-qualification.v1",
                "record_id": heuristic_id,
                "project_id": self.project_id,
                "evaluation_receipt_id": p.evaluation_receipt_id,
                "policy_digest": evaluation["policy_digest"],
                "qualification": "PASS",
                "confidence": evaluation["confidence"],
            }
            digest = sha256_hex(canonical_json_bytes(body))
            result = self._commit(
                state,
                request,
                "research_heuristic_qualified",
                body,
                prior=entry["head"],
                sources=[policy_event],
                status="qualified",
                evaluation_receipt_id=p.evaluation_receipt_id,
                qualification_receipt_id=digest,
            )
        return self._finish(result)

    @replayable
    def promote(
        self,
        heuristic_id,
        *,
        to_scope="project",
        consent=False,
        approval_artifact_id,
        request,
    ):
        if consent is not True:
            raise LearningFault("promotion requires explicit consent")
        if to_scope not in {"run", "project", "domain", "global"}:
            raise LearningFault("unknown promotion scope")
        with self._writer(request) as state:
            records, runs = inventory(self.root, held=(self.run_root, state))
            entry = self._entry(records, heuristic_id, writable=True)
            p = entry["head"].payload
            if p.status != "qualified":
                raise LearningFault(
                    "promotion requires qualified status; rejected versions need a new successor"
                )
            _, policy_event = self._policy(state)
            evaluation = load_body(self.root, p.evaluation_receipt_id, runs)
            qualification = load_body(self.root, p.qualification_receipt_id, runs)
            if (
                evaluation["policy_digest"] != policy_event.payload.artifact_sha256
                or qualification["evaluation_receipt_id"] != p.evaluation_receipt_id
            ):
                raise ReevaluationRequired(
                    "qualification or current policy requires re-evaluation"
                )
            approval_event, raw = accepted_artifact(
                self.run_root, state.events, approval_artifact_id
            )
            reject_secret_shapes(raw)
            approval = json.loads(raw)
            required = {
                "action": "promote_heuristic",
                "heuristic_id": heuristic_id,
                "heuristic_digest": entry["creation"].payload.content_digest,
                "qualification_receipt_id": p.qualification_receipt_id,
                "to_scope": to_scope,
                "status": "APPROVED",
            }
            if (
                any(approval.get(k) != v for k, v in required.items())
                or not isinstance(approval.get("reviewer"), str)
                or not approval["reviewer"].strip()
            ):
                raise LearningFault(
                    "reviewer approval must bind candidate, qualification and target scope"
                )
            scopes = ["run", "project", "domain", "global"]
            if scopes.index(to_scope) < scopes.index(p.scope):
                raise LearningFault("promotion cannot silently narrow scope")
            projects = {self.project_id}
            # Broader transfer evidence is an accepted, explicitly reviewed receipt; it does not grant cross-root reads.
            transfer = approval.get("cross_project_evidence", [])
            if not isinstance(transfer, list) or len(transfer) > 64:
                raise LearningFault("invalid transfer evidence budget")
            for item in transfer:
                if not isinstance(item, dict) or not all(
                    item.get(k)
                    for k in (
                        "project_id",
                        "run_id",
                        "source_digest",
                        "evaluation_receipt_id",
                        "reviewer",
                    )
                ):
                    raise LearningFault(
                        "transfer evidence requires project/run/digest/evaluation/reviewer bindings"
                    )
                from pydantic import TypeAdapter

                from arw.kernel.state.models import RunId, Sha256, StableRuntimeId

                TypeAdapter(StableRuntimeId).validate_python(
                    item["project_id"], strict=True
                )
                TypeAdapter(RunId).validate_python(item["run_id"], strict=True)
                TypeAdapter(Sha256).validate_python(item["source_digest"], strict=True)
                TypeAdapter(Sha256).validate_python(
                    item["evaluation_receipt_id"], strict=True
                )
                projects.add(item["project_id"])
            if to_scope in {"domain", "global"} and (
                len(projects) < 2 or approval.get("allow_cross_project") is not True
            ):
                raise LearningFault(
                    "broader promotion requires cross-project evidence and explicit transfer authorization"
                )
            body = {
                "schema_version": "arw.heuristic-promotion.v1",
                "record_id": heuristic_id,
                "project_id": self.project_id,
                "from_scope": p.scope,
                "to_scope": to_scope,
                "evaluation_receipt_id": p.evaluation_receipt_id,
                "qualification_receipt_id": p.qualification_receipt_id,
                "qualification": "PASS",
                "approval_artifact_id": approval_artifact_id,
                "approval_digest": approval_event.payload.artifact_sha256,
                "reviewer": approval["reviewer"],
                "consent": True,
                "supporting_projects": sorted(projects),
                "supporting_runs": evaluation["run_ids"],
                "counterexamples": entry["candidate"]["counterexample_observation_ids"],
                "cross_project_evidence": transfer,
                "executable": False,
            }
            result = self._commit(
                state,
                request,
                "research_heuristic_promoted",
                body,
                prior=entry["head"],
                sources=[policy_event, approval_event],
                scope=to_scope,
                status="promoted",
                evaluation_receipt_id=p.evaluation_receipt_id,
                qualification_receipt_id=p.qualification_receipt_id,
                approval_artifact_id=approval_artifact_id,
                consent=True,
                from_scope=p.scope,
                supporting_projects=sorted(projects),
                supporting_runs=evaluation["run_ids"],
                counterexample_ids=entry["candidate"]["counterexample_observation_ids"],
            )
        return self._finish(result)

    @replayable
    def reject(self, heuristic_id, *, reason, request):
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1200:
            raise LearningFault("rejection requires a bounded reason")
        reject_secret_shapes(reason.encode())
        with self._writer(request) as state:
            records, _ = inventory(self.root, held=(self.run_root, state))
            entry = self._entry(records, heuristic_id, writable=True)
            body = {
                "schema_version": "arw.heuristic-rejection.v1",
                "record_id": heuristic_id,
                "project_id": self.project_id,
                "reason": reason,
            }
            result = self._commit(
                state,
                request,
                "research_heuristic_rejected",
                body,
                prior=entry["head"],
                status="rejected",
            )
        return self._finish(result)

    def _supersede(self, predecessor, successor, request):
        op = uuid.UUID(request.command_id.removeprefix("cmd-"))
        derived = str(uuid.UUID(bytes=uuid.uuid5(op, "supersession").bytes, version=4))
        request = request.model_copy(
            update={
                "command_id": "cmd-" + derived,
                "event_id": "evt-" + derived,
                "expected_revision": request.expected_revision + 1,
            }
        )
        with self._writer(request) as state:
            records, _ = inventory(self.root, held=(self.run_root, state))
            old = self._entry(records, predecessor, writable=True)
            new = self._entry(records, successor, writable=True)
            if new["candidate"]["supersedes"] != predecessor:
                raise LearningFault("successor does not bind predecessor")
            body = {
                "schema_version": "arw.heuristic-supersession.v1",
                "record_id": predecessor,
                "project_id": self.project_id,
                "successor_id": successor,
                "successor_digest": new["creation"].payload.content_digest,
            }
            self._commit(
                state,
                request,
                "research_heuristic_superseded",
                body,
                prior=old["head"],
                sources=[new["creation"]],
                status="superseded",
                successor_id=successor,
            )

    def purge(self, digest, *, consent, authorization_artifact_id, request):
        if consent is not True:
            raise LearningFault("retention requires explicit consent")
        with self._writer(request) as state:
            _records, runs = inventory(self.root, held=(self.run_root, state))
            referenced = {
                e.payload.content_digest
                for _, s in runs.values()
                for e in s.events
                if e.event_type.startswith(
                    ("research_heuristic_", "learning_observation_")
                )
            }
            if digest not in referenced:
                raise LearningFault(
                    "retention target is not canonical learning evidence"
                )
            event, raw = accepted_artifact(
                self.run_root, state.events, authorization_artifact_id
            )
            auth = json.loads(raw)
            if (
                auth.get("action") != "purge_learning"
                or auth.get("content_digest") != digest
            ):
                raise LearningFault(
                    "retention authorization does not bind target digest"
                )
            marker = {
                "content_digest": digest,
                "body_recoverable": False,
                "authorization_run_id": state.run_id,
                "authorization_artifact_id": authorization_artifact_id,
                "authorization_sha256": event.payload.artifact_sha256,
            }
            publish_once(self.root, marker_path(digest), canonical_json_bytes(marker))
            unlink_retained(self.root, body_path(digest))
        self.rebuild()
        return {
            "content_digest": digest,
            "body_recoverable": False,
            "status": "tombstoned",
        }

    def applicable(self, conditions: Applicability, *, max_items=10):
        if not configuration(self.root).enabled:
            return {"items": [], "activation": "disabled", "executable": False}
        if not 1 <= max_items <= 20:
            raise LearningFault("applicable lesson budget must be 1..20")
        records, _ = inventory(self.root)
        result = []
        for key, entry in sorted(records.items()):
            if (
                entry["head"].payload.status != "promoted"
                or entry["candidate"] is None
                or entry["candidate"]["applicability"]
                != conditions.model_dump(mode="json")
            ):
                continue
            # Reading the current receipt verifies retained qualification/evaluation evidence.
            item = self.inspect(key)
            result.append(
                {
                    "heuristic_id": key,
                    "suggested_action": item["proposed_action"],
                    "applicability": item["applicability"],
                    "supporting": item["supporting_observation_ids"],
                    "counterexample": item["counterexample_observation_ids"],
                    "unknown": item["unknown"],
                    "promotion_event_id": item["accepted_ledger_event_id"],
                    "author_choice_required": True,
                    "outcome": "unmeasured until an accepted decision/outcome receipt exists",
                }
            )
            if len(result) >= max_items:
                break
        return {"items": result, "executable": False}

    def decision_context(self, heuristic_id, decision_artifact_id):
        """Inspect an already accepted author choice; this read grants no authority."""
        from arw.kernel.ledger.journal import replay_run

        if self.run_root is None:
            raise LearningFault("decision inspection requires its canonical run")
        item = self.inspect(heuristic_id)
        if item["status"] != "promoted":
            raise LearningFault("decision lesson is no longer promoted")
        state = replay_run(self.run_root)
        event, raw = accepted_artifact(
            self.run_root, state.events, decision_artifact_id
        )
        decision = json.loads(raw)
        if (
            decision.get("schema_version") != "arw.learning-decision.v1"
            or decision.get("heuristic_id") != heuristic_id
            or decision.get("promotion_event_id") != item["accepted_ledger_event_id"]
            or decision.get("applicability") != item["applicability"]
        ):
            raise LearningFault(
                "author decision must bind the applicable promoted lesson"
            )
        if (
            not isinstance(decision.get("author"), str)
            or not decision["author"].strip()
            or not isinstance(decision.get("chosen_action"), str)
            or not decision["chosen_action"].strip()
        ):
            raise LearningFault(
                "accepted author choice must name the author and action"
            )
        outcome = decision.get("outcome")
        if not isinstance(outcome, dict) or type(outcome.get("measured")) is not bool:
            raise LearningFault(
                "decision must distinguish measured and unmeasured outcomes"
            )
        if outcome["measured"]:
            source, source_raw = accepted_artifact(
                self.run_root, state.events, outcome.get("source_artifact_id")
            )
            measured = json.loads(source_raw)
            if (
                measured.get("metric") != item["applicability"]["metric"]
                or measured.get("value") != outcome.get("value")
                or source.sequence >= event.sequence
            ):
                raise LearningFault(
                    "measured outcome must bind prior accepted metric evidence"
                )
        elif outcome.get("value") is not None:
            raise LearningFault(
                "unmeasured outcomes cannot assert numeric improvements"
            )
        return {
            "heuristic_id": heuristic_id,
            "suggested_action": item["proposed_action"],
            "author": decision["author"],
            "chosen_action": decision["chosen_action"],
            "outcome": outcome,
            "decision_event_id": event.event_id,
            "decision_digest": event.payload.artifact_sha256,
            "executable": False,
        }
