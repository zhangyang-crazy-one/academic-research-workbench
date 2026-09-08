"""Create-only memory and bounded recall; governance stays with the parent writer."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import portalocker

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.core.privacy import reject_secret_shapes
from arw.kernel.ledger.journal import (
    append_runtime_event_unlocked,
    build_runtime_event,
    locked_replay,
    replay_run,
)
from arw.kernel.ledger.manifests import (
    load_artifact_manifest,
    validate_accepted_event_manifests,
)
from arw.kernel.ledger.reducer import reduce_events
from arw.kernel.ledger.research_records import (
    BodyUnavailable,
    publish_once,
    unlink_retained,
)
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.state.models import ResearchMemoryPayload
from arw.kernel.state.research_memory import (
    MemoryInput,
    MemoryQuery,
    ResearchMemory,
    logical_memory_payload,
)

from .project import MemoryAccessDenied, authorization, project_identity
from .store import (
    MAX_DOCUMENT_BYTES,
    MAX_MEMORIES,
    MemoryConflict,
    MemoryIntegrityError,
    _names,
    accepted_artifact,
    body_path,
    build_index,
    cycle_ids,
    load_inventory,
    persist_index,
    tombstone_path,
    validate_links,
)

INTERPRETATION = "Advisory context; verify material claims against canonical sources before governed use."


class ResearchMemoryService:
    def __init__(
        self, project_root, *, run_root=None, harness="codex", boundary=lambda _: None
    ):
        if harness not in {"codex", "claude", "cursor", "other"}:
            raise MemoryAccessDenied("unsupported harness")
        self.project_root = Path(project_root).absolute()
        self.identity = project_identity(self.project_root)
        self.policy = authorization(self.project_root)
        self.run_root = Path(run_root).absolute() if run_root is not None else None
        if self.run_root is not None and not self.run_root.is_relative_to(
            self.project_root
        ):
            raise MemoryAccessDenied("run is outside the selected project")
        self.harness = harness
        self.boundary = boundary

    def _scope(self, query):
        if project_identity(self.project_root) != self.identity:
            raise MemoryAccessDenied("active project identity changed")
        policy = authorization(self.project_root)
        if query.scope == "user" and not policy.allow_user_scope:
            raise MemoryAccessDenied("user scope is not authorized")
        selected = query.project_id or self.identity.project_id
        if selected == self.identity.project_id:
            return self.project_root, selected
        grants = {g.project_id: Path(g.root) for g in policy.cross_project_roots}
        if not query.cross_project or selected not in grants:
            raise MemoryAccessDenied("cross-project recall is not authorized")
        root = grants[selected]
        if project_identity(root).project_id != selected:
            raise MemoryAccessDenied("cross-project identity mismatch")
        return root, selected

    @contextmanager
    def _writer(self):
        if self.run_root is None:
            raise MemoryAccessDenied("memory writes require a canonical run")
        self._scope(MemoryQuery())
        publish_once(self.project_root, ".arw/memory/.lock", b"")
        path = self.project_root / ".arw/memory/.lock"
        if path.is_symlink():
            raise MemoryAccessDenied("unsafe memory lock")
        with portalocker.Lock(path, mode="rb", timeout=5):
            yield

    def _register(self, state):
        relative = self.run_root.relative_to(self.project_root).as_posix()
        if relative == ".":
            # Root-level runs are valid; the stored relative path is empty.
            relative = ""
        manifest = read_retained_bytes(
            self.run_root, "run-manifest.json", max_bytes=65_536
        )
        publish_once(
            self.project_root,
            f".arw/memory/runs/{state.run_id}.json",
            canonical_json_bytes(
                {
                    "run_id": state.run_id,
                    "relative_root": relative,
                    "manifest_sha256": sha256_hex(manifest),
                }
            ),
        )

    def _append(self, request, event_type, payload, *, publish=lambda _: None):
        if request.actor_role != "parent_control_plane":
            raise MemoryAccessDenied("only the parent writer can admit memory")
        with locked_replay(self.run_root) as (_, state):
            if request.run_id != state.run_id or state.recovery_health != "healthy":
                raise MemoryAccessDenied("run identity or recovery health mismatch")
            existing = next(
                (e for e in state.events if e.command_id == request.command_id), None
            )
            if existing is not None:
                if existing.event_type != event_type or existing.payload != payload:
                    raise MemoryConflict(
                        "command identity binds different memory content"
                    )
                return existing
            if state.revision != request.expected_revision:
                raise MemoryConflict("stale memory command revision")
            validate_accepted_event_manifests(self.run_root, state.events)
            self._register(state)
            publish(state)
            self.boundary("memory_body_durable")
            event = build_runtime_event(
                state,
                event_type=event_type,
                event_id=request.event_id,
                command_id=request.command_id,
                occurred_at=request.occurred_at,
                actor_id=request.actor_id,
                actor_role=request.actor_role,
                payload=payload,
            )
            reduce_events(state.workflow_definition_id, (*state.events, event))
            append_runtime_event_unlocked(self.run_root, state, event)
            self.boundary("memory_event_durable")
            return event

    def _inventory(self, *, extra=False):
        current = (
            (self.run_root, replay_run(self.run_root))
            if extra and self.run_root
            else None
        )
        return load_inventory(
            self.project_root, self.identity.project_id, extra_run=current
        )

    @staticmethod
    def _receipt(entry, idempotent=False):
        p = entry.head.payload
        return {
            "memory_id": p.memory_id,
            "content_digest": p.content_digest,
            "project_id": p.project_id,
            "scope": p.scope,
            "status": p.status,
            "trust": p.trust,
            "event_id": entry.head.event_id,
            "event_sha256": entry.head.event_sha256,
            "idempotent": idempotent,
            "interpretation": INTERPRETATION,
        }

    def save(self, value: MemoryInput, *, request):
        reject_secret_shapes(canonical_json_bytes(value.model_dump(mode="json")))
        if request.actor_role != "parent_control_plane":
            raise MemoryAccessDenied("only the parent writer can admit memory")
        self._scope(MemoryQuery(scope=value.scope))
        with self._writer():
            entries, faults, runs = self._inventory(extra=True)
            if faults:
                raise MemoryIntegrityError(
                    "memory integrity faults require explicit review"
                )
            state = (
                runs[request.run_id][1]
                if request.run_id in runs
                else replay_run(self.run_root)
            )
            if state.run_id != request.run_id:
                raise MemoryAccessDenied("run identity mismatch")
            if value.handoff and (
                value.handoff.source_run_harness.run_id != request.run_id
                or value.handoff.source_run_harness.harness != self.harness
            ):
                raise MemoryAccessDenied(
                    "handoff source identity differs from configured harness/run"
                )
            logical = logical_memory_payload(
                value.model_dump(mode="json"),
                project_id=self.identity.project_id,
                run_id=request.run_id,
            )
            if value.memory_id in entries:
                entry = entries[value.memory_id]
                if (
                    entry.document is None
                    or entry.document.logical_payload() != logical
                ):
                    raise MemoryConflict(
                        "memory ID already binds different immutable content"
                    )
                self._finish_save(entry.document, request)
                return self._receipt(entry, True)
            for entry in entries.values():
                if entry.document and entry.document.logical_payload() == logical:
                    self._finish_save(entry.document, request)
                    return self._receipt(entry, True)
            if len(entries) >= MAX_MEMORIES:
                raise MemoryIntegrityError("memory inventory capacity reached")
            memory_id = (
                value.memory_id
                or "memory-" + sha256_hex(canonical_json_bytes(logical))[:32]
            )
            for previous in value.supersedes:
                if (
                    previous not in entries
                    or entries[previous].document is None
                    or entries[previous].head.payload.scope != value.scope
                ):
                    raise MemoryConflict(
                        "supersession target is absent or has a different scope"
                    )
            edges = [
                (mid, parent)
                for mid, e in entries.items()
                if e.document
                for parent in e.document.supersedes
            ] + [(memory_id, p) for p in value.supersedes]
            if cycle_ids(edges):
                raise MemoryConflict("supersession cycle")
            data = {
                **value.model_dump(mode="json"),
                "schema_version": "arw.research-memory.v1",
                "memory_id": memory_id,
                "project_id": self.identity.project_id,
                "run_id": request.run_id,
                "source_harness": self.harness,
                "source_agent": request.actor_id,
                "created_at": request.occurred_at,
                "status": "created",
                "trust": "unreviewed",
                "content_digest": "0" * 64,
            }
            doc = ResearchMemory.model_validate_json(json.dumps(data))
            doc = doc.model_copy(
                update={
                    "content_digest": sha256_hex(
                        canonical_json_bytes(doc.digest_payload())
                    )
                }
            )
            raw = canonical_json_bytes(doc.model_dump(mode="json"))
            if len(raw) > MAX_DOCUMENT_BYTES - 1024:
                raise MemoryIntegrityError(
                    "memory document exceeds retained-body budget"
                )
            validate_links(doc, self.run_root, state.events, entries)
            payload = ResearchMemoryPayload(
                memory_id=memory_id,
                project_id=doc.project_id,
                source_run_id=doc.run_id,
                kind=doc.kind,
                scope=doc.scope,
                content_digest=doc.content_digest,
                document_sha256=sha256_hex(raw),
                source_harness=self.harness,
                source_event_ids=list(doc.source_ledger_event_ids),
                source_artifact_ids=list(doc.source_artifact_ids),
                status="created",
                trust="unreviewed",
            )

            def publish(state):
                validate_links(doc, self.run_root, state.events, entries)
                publish_once(self.project_root, body_path(doc.content_digest), raw)

            self._append(
                request,
                "research_handoff_created"
                if doc.kind == "handoff"
                else "research_memory_created",
                payload,
                publish=publish,
            )
            # Supersession is separately recorded, with a stable command per predecessor.
            for previous in doc.supersedes:
                self._govern_locked(
                    previous,
                    "supersede",
                    request=request,
                    successor=memory_id,
                    derived=True,
                )
            entries, faults, _ = self._inventory()
            if faults:
                raise MemoryIntegrityError("new memory did not replay cleanly")
            persist_index(self.project_root, entries)
            self.boundary("memory_index_updated")
            return self._receipt(entries[memory_id])

    def _finish_save(self, doc, request):
        entries, faults, _ = self._inventory()
        if faults:
            raise MemoryIntegrityError("retry requires intact canonical memory")
        for previous in doc.supersedes:
            predecessor = entries[previous]
            if (
                predecessor.head.payload.status == "superseded"
                and predecessor.head.payload.successor_memory_id == doc.memory_id
            ):
                continue
            self._govern_locked(
                previous,
                "supersede",
                request=request,
                successor=doc.memory_id,
                derived=True,
            )
        entries, faults, _ = self._inventory()
        persist_index(self.project_root, entries)

    def search(self, query: MemoryQuery):
        root, project_id = self._scope(query)
        entries, faults, _ = load_inventory(root, project_id)
        if faults:
            raise MemoryIntegrityError("recall cannot use a damaged memory inventory")
        conn = build_index(entries)
        try:
            run_id = query.run_id
            if query.scope == "run" and run_id is None:
                if self.run_root is None:
                    raise MemoryAccessDenied("run scope requires explicit run identity")
                run_id = replay_run(self.run_root).run_id
            rows = conn.execute(
                """SELECT memory_id FROM research_memories WHERE project_id=? AND scope=? AND body_recoverable=1 AND status IN ('created','active') AND instr(search_text,?)>0 AND (? IS NULL OR run_id=?) AND (? IS NULL OR kind=?) AND (? IS NULL OR created_at>=?) ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END,created_at DESC,memory_id LIMIT ?""",
                (
                    project_id,
                    query.scope,
                    query.query.casefold(),
                    run_id,
                    run_id,
                    query.kind,
                    query.kind,
                    query.since,
                    query.since,
                    query.max_items + 1,
                ),
            ).fetchall()
        finally:
            conn.close()
        response = {
            "matches": [],
            "rank_order": [],
            "truncated": False,
            "reason_code": None,
            "budget_units": "utf8_bytes_upper_bound",
            "interpretation": INTERPRETATION,
        }
        for (mid,) in rows:
            doc = entries[mid].document
            p = entries[mid].head.payload
            card = {
                "memory_id": mid,
                "kind": doc.kind,
                "scope": doc.scope,
                "project_id": doc.project_id,
                "source_project_id": doc.project_id,
                "run_id": doc.run_id,
                "title": doc.title,
                "summary": doc.body[:200] + "…"
                if len(doc.body) > 320
                else f"{doc.kind} with {len(doc.source_artifact_ids)} accepted artifact references; explicit read required.",
                "created_at": doc.created_at,
                "source_harness": doc.source_harness,
                "status": p.status,
                "trust": p.trust,
                "source_ledger_event_ids": list(doc.source_ledger_event_ids[:4]),
                "source_artifact_ids": list(doc.source_artifact_ids[:4]),
                "links": [l.model_dump(mode="json") for l in doc.links[:4]],
                "links_truncated": len(doc.links) > 4,
            }
            candidate = {
                **response,
                "matches": [*response["matches"], card],
                "rank_order": [*response["rank_order"], mid],
            }
            if (
                len(response["matches"]) >= query.max_items
                or len(canonical_json_bytes(candidate)) + 64 > query.max_tokens
            ):
                response["truncated"] = True
                response["reason_code"] = "RecallBudgetExceeded"
                break
            response = candidate
        if len(canonical_json_bytes(response)) > query.max_tokens:
            return {
                "matches": [],
                "rank_order": [],
                "truncated": True,
                "reason_code": "RecallBudgetExceeded",
            }
        return response

    def list(self, query):
        return self.search(query.model_copy(update={"query": ""}))

    def read(self, memory_id, *, query: MemoryQuery):
        root, project_id = self._scope(query)
        entries, faults, _ = load_inventory(root, project_id)
        if faults:
            raise MemoryIntegrityError("memory integrity verification failed")
        entry = entries.get(memory_id)
        if entry is None or entry.head.payload.scope != query.scope:
            raise MemoryAccessDenied(
                "memory is absent from the explicitly selected scope"
            )
        effective_run = query.run_id
        if query.scope == "run" and effective_run is None:
            if self.run_root is None:
                raise MemoryAccessDenied("run scope requires explicit run identity")
            effective_run = replay_run(self.run_root).run_id
        if effective_run and entry.head.payload.source_run_id != effective_run:
            raise MemoryAccessDenied("memory run scope mismatch")
        if entry.tombstone is not None:
            raise BodyUnavailable("memory body was intentionally purged")
        if entry.document is None:
            raise MemoryIntegrityError("memory body unavailable")
        return {
            "memory": entry.document.model_dump(mode="json"),
            "lifecycle": self._receipt(entry),
            "interpretation": INTERPRETATION,
        }

    def rebuild(self):
        with self._writer():
            entries, faults, _ = self._inventory()
            if faults:
                raise MemoryIntegrityError(
                    "cannot rebuild from invalid canonical memory"
                )
            persist_index(self.project_root, entries)
            return {
                "rebuilt": len(entries),
                "tombstones": sum(e.tombstone is not None for e in entries.values()),
            }

    def doctor(self):
        self._scope(MemoryQuery())
        entries, faults, _ = self._inventory()
        for mid, entry in entries.items():
            if entry.tombstone:
                faults.append(
                    {
                        "code": "memory_body_tombstoned",
                        "memory_id": mid,
                        "body_recoverable": False,
                    }
                )
        try:
            admitted = {
                e.creation.payload.content_digest + ".json" for e in entries.values()
            }
            for name in _names(self.project_root, ".arw/memory/bodies", 1024):
                if name not in admitted:
                    faults.append(
                        {
                            "code": "memory_unaccepted_body",
                            "path_digest": sha256_hex(name.encode()),
                        }
                    )
            index = self.project_root / ".arw/memory/index.sqlite3"
            if index.is_symlink():
                raise MemoryIntegrityError("unsafe index")
            if index.exists():
                from urllib.parse import quote

                conn = sqlite3.connect(f"file:{quote(str(index))}?mode=ro", uri=True)
                try:
                    conn.execute("PRAGMA trusted_schema=OFF")
                    ticks = 0

                    def budget():
                        nonlocal ticks
                        ticks += 1
                        return int(ticks > 1000)

                    conn.set_progress_handler(budget, 1000)
                    expected_db = build_index(entries)
                    try:
                        for table in (
                            "research_memories",
                            "memory_links",
                            "memory_tags",
                            "memory_targets",
                            "memory_supersession",
                        ):
                            actual = conn.execute(
                                f"SELECT * FROM {table} LIMIT 65537"
                            ).fetchall()
                            expected = expected_db.execute(
                                f"SELECT * FROM {table}"
                            ).fetchall()
                            if sorted(actual, key=repr) != sorted(expected, key=repr):
                                faults.append(
                                    {"code": "memory_index_drift", "table": table}
                                )
                    finally:
                        expected_db.close()
                    edges = conn.execute(
                        "SELECT memory_id,supersedes FROM memory_supersession LIMIT 16385"
                    ).fetchall()
                    if cycle_ids(edges):
                        faults.append({"code": "memory_supersession_cycle"})
                finally:
                    conn.close()
        except (ValueError, RuntimeError, OSError, sqlite3.Error):
            faults.append({"code": "memory_path_or_index_unsafe"})
        return {
            "status": "FAIL" if faults else "PASS",
            "faults": faults,
            "memories": len(entries),
        }

    def _govern_locked(
        self,
        memory_id,
        action,
        *,
        request,
        successor=None,
        authorization_artifact_id=None,
        derived=False,
    ):
        import uuid

        actions = {
            "activate": ("research_memory_activated", "active"),
            "reject": ("research_memory_rejected", "rejected"),
            "distill": ("research_memory_distilled", "distilled"),
            "verify": ("research_memory_verified", None),
            "supersede": ("research_memory_superseded", "superseded"),
        }
        if action not in actions:
            raise MemoryAccessDenied("unsupported memory governance action")
        if request.actor_role != "parent_control_plane":
            raise MemoryAccessDenied("memory governance requires parent authority")
        entries, faults, _ = self._inventory(extra=True)
        if faults or memory_id not in entries or entries[memory_id].document is None:
            raise MemoryIntegrityError("governance requires intact admitted memory")
        entry = entries[memory_id]
        old = entry.head.payload
        state = replay_run(self.run_root)
        if derived:
            command = "cmd-" + str(
                uuid.UUID(
                    bytes=uuid.uuid5(
                        uuid.NAMESPACE_URL, f"{request.command_id}/{memory_id}/{action}"
                    ).bytes,
                    version=4,
                )
            )
            event_id = "evt-" + str(
                uuid.UUID(
                    bytes=uuid.uuid5(
                        uuid.NAMESPACE_URL, f"{request.event_id}/{memory_id}/{action}"
                    ).bytes,
                    version=4,
                )
            )
            request = request.model_copy(
                update={
                    "command_id": command,
                    "event_id": event_id,
                    "expected_revision": state.revision,
                }
            )
        existing = next(
            (e for e in state.events if e.command_id == request.command_id), None
        )
        event_type, status = actions[action]
        if existing is not None:
            if (
                existing.event_type,
                existing.payload.memory_id,
                existing.payload.successor_memory_id,
                existing.payload.authorization_artifact_id,
            ) != (event_type, memory_id, successor, authorization_artifact_id):
                raise MemoryConflict("governance command identity conflict")
            return self._receipt(entry, True)
        if old.status not in {"created", "active"}:
            raise MemoryConflict("terminal memory cannot be reactivated or rewritten")
        changes = {
            "status": status or old.status,
            "prior_status": old.status,
            "prior_trust": old.trust,
            "previous_memory_event_sha256": entry.head.event_sha256,
            "successor_memory_id": successor,
            "authorization_artifact_id": None,
            "authorization_event_id": None,
            "authorization_sha256": None,
        }
        if action == "supersede":
            next_entry = entries.get(successor)
            if (
                next_entry is None
                or next_entry.document is None
                or memory_id not in next_entry.document.supersedes
            ):
                raise MemoryConflict("successor does not declare this predecessor")
        if action in {"verify", "distill"}:
            if authorization_artifact_id is None:
                raise MemoryAccessDenied("accepted governed evidence is required")
            event, raw = accepted_artifact(
                self.run_root, state.events, authorization_artifact_id
            )
            evidence = json.loads(raw)
            if (
                evidence.get("action"),
                evidence.get("memory_id"),
                evidence.get("content_digest"),
            ) != (action + "_memory", memory_id, old.content_digest):
                raise MemoryAccessDenied(
                    "evidence is not scoped to this memory and action"
                )
            evidence_ids = evidence.get("source_artifact_ids")
            if (
                not isinstance(evidence_ids, list)
                or not evidence_ids
                or len(evidence_ids) > 64
                or any(not isinstance(aid, str) for aid in evidence_ids)
            ):
                raise MemoryAccessDenied(
                    "authorization source list is invalid or unbounded"
                )
            if not evidence.get("source_artifact_ids") or not set(
                entry.document.source_artifact_ids
            ) <= set(evidence["source_artifact_ids"]):
                raise MemoryAccessDenied(
                    "verification must reference accepted source evidence"
                )
            for aid in evidence["source_artifact_ids"]:
                accepted_artifact(self.run_root, state.events, aid)
            changes.update(
                authorization_artifact_id=authorization_artifact_id,
                authorization_event_id=event.event_id,
                authorization_sha256=event.payload.artifact_sha256,
            )
            if action == "verify":
                changes["trust"] = "verified"
        payload = ResearchMemoryPayload.model_validate({**old.model_dump(), **changes})
        self._append(request, event_type, payload)
        entries, faults, _ = self._inventory()
        if faults:
            raise MemoryIntegrityError("governance replay failed")
        persist_index(self.project_root, entries)
        return self._receipt(entries[memory_id])

    def govern(self, memory_id, action, *, request, authorization_artifact_id=None):
        with self._writer():
            return self._govern_locked(
                memory_id,
                action,
                request=request,
                authorization_artifact_id=authorization_artifact_id,
            )

    def purge(self, memory_id, *, authorization_artifact_id, authorized=False):
        if not authorized:
            raise MemoryAccessDenied("explicit purge authorization is required")
        with self._writer():
            entries, faults, _ = self._inventory(extra=True)
            if faults or memory_id not in entries:
                raise MemoryIntegrityError("purge requires an intact memory inventory")
            entry = entries[memory_id]
            state = replay_run(self.run_root)
            event, raw = accepted_artifact(
                self.run_root, state.events, authorization_artifact_id
            )
            auth = json.loads(raw)
            if (
                auth.get("action"),
                auth.get("memory_id"),
                auth.get("content_digest"),
            ) != ("purge_memory", memory_id, entry.head.payload.content_digest):
                raise MemoryAccessDenied(
                    "purge authorization does not bind this memory"
                )
            self._register(state)
            marker = {
                "memory_id": memory_id,
                "content_digest": entry.head.payload.content_digest,
                "authorization_artifact_id": authorization_artifact_id,
                "authorization_run_id": state.run_id,
                "authorization_event_sha256": event.event_sha256,
                "body_recoverable": False,
            }
            publish_once(
                self.project_root,
                tombstone_path(memory_id),
                canonical_json_bytes(marker),
            )
            self.boundary("memory_tombstone_durable")
            unlink_retained(
                self.project_root, body_path(entry.head.payload.content_digest)
            )
            entries, faults, _ = self._inventory()
            if faults:
                raise MemoryIntegrityError("purge replay failed")
            persist_index(self.project_root, entries)
            return marker

    def resume_handoff(self, memory_id, *, query):
        result = self.read(memory_id, query=query)
        document = ResearchMemory.model_validate_json(json.dumps(result["memory"]))
        if document.handoff is None:
            raise MemoryIntegrityError("resume requires a structured handoff")
        if self.run_root is None:
            raise MemoryAccessDenied("resume requires the current canonical run")
        state = replay_run(self.run_root)
        if state.run_id != document.run_id:
            raise MemoryAccessDenied("handoff resume must select its canonical run")
        targets = [link for link in document.links if link.kind == "author_target"]
        if not targets:
            raise MemoryIntegrityError(
                "handoff continuation requires an accepted author-target reference"
            )
        validate_links(document, self.run_root, state.events, self._inventory()[0])
        linked_decisions = {
            link.target_id for link in document.links if link.kind == "decision"
        }
        current_decisions = []
        stale = []
        for event in state.events:
            if event.event_type not in {
                "human_decision.recorded",
                "human_decision.resolved",
            }:
                continue
            decision = getattr(event.payload, "decision", event.payload)
            decision_id = getattr(decision, "decision_id", None)
            supersedes = getattr(decision, "supersedes_decision_id", None)
            if supersedes in linked_decisions:
                stale.append(supersedes)
            if decision_id:
                current_decisions.append(
                    {
                        "decision_id": decision_id,
                        "event_id": event.event_id,
                        "event_sha256": event.event_sha256,
                        "decision": decision.model_dump(mode="json"),
                    }
                )
        target_values = []
        for link in targets:
            event, raw = accepted_artifact(self.run_root, state.events, link.target_id)
            target_values.append(
                {
                    "artifact_id": link.target_id,
                    "sha256": event.payload.artifact_sha256,
                    "value": json.loads(raw),
                }
            )
            for later in state.events[event.sequence :]:
                if getattr(later.payload, "supersedes", None) == link.target_id:
                    stale.append(link.target_id)
                if (
                    later.event_type == "artifact.accepted"
                    and load_artifact_manifest(
                        self.run_root, later.payload.manifest_sha256
                    ).artifact_kind
                    == "author-target"
                ):
                    latest, latest_raw = accepted_artifact(
                        self.run_root, state.events, later.payload.artifact_id
                    )
                    stale.append(link.target_id)
                    target_values.append(
                        {
                            "artifact_id": latest.payload.artifact_id,
                            "sha256": latest.payload.artifact_sha256,
                            "value": json.loads(latest_raw),
                        }
                    )
        # Any later author decision requires reconciliation before continuing a suggestion.
        linked_events = set(document.source_ledger_event_ids) | {
            link.event_id for link in document.links
        }
        last_reference = max(
            (e.sequence for e in state.events if e.event_id in linked_events), default=0
        )
        if any(
            e.event_type in {"human_decision.recorded", "human_decision.resolved"}
            and e.sequence > last_reference
            for e in state.events
        ):
            stale.append("later_author_decision")
        result = {
            "memory_id": memory_id,
            "canonical_author_targets": target_values,
            "canonical_decisions": current_decisions,
            "requires_reconciliation": bool(stale),
            "stale_references": sorted(set(stale)),
            "completed_work": list(document.handoff.completed_work),
            "next_concrete_action": None
            if stale
            else document.handoff.next_concrete_action,
            "interpretation": INTERPRETATION,
        }

        if len(canonical_json_bytes(result)) > query.max_tokens:
            raise MemoryIntegrityError(
                "handoff exceeds explicit continuation context budget"
            )
        return result
