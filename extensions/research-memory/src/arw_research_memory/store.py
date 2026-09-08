"""Immutable project memory bodies and a disposable SQLite projection."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.ledger.journal import replay_run
from arw.kernel.ledger.manifests import load_artifact_manifest
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.state.models import RESEARCH_MEMORY_EVENT_TYPES, ArtifactAcceptedPayload
from arw.kernel.state.research_memory import ResearchMemory

MAX_DOCUMENT_BYTES = 65_536
MAX_MEMORIES = 1024
MAX_AGGREGATE_BYTES = 8_388_608


class MemoryIntegrityError(ValueError):
    code = "memory_integrity_error"


class MemoryConflict(ValueError):
    code = "memory_conflict"


@dataclass
class Entry:
    creation: object
    head: object
    run_root: Path
    document: ResearchMemory | None
    tombstone: dict | None = None


def body_path(digest):
    return f".arw/memory/bodies/{digest}.json"


def tombstone_path(memory_id):
    return f".arw/memory/tombstones/{memory_id}.json"


def _names(root, relative, limit):
    directory = Path(root) / relative
    if not directory.exists():
        return []
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        raise MemoryIntegrityError("unsafe memory directory")
    names = []
    with os.scandir(directory) as entries:
        for entry in entries:
            if len(names) >= limit:
                raise MemoryIntegrityError("memory inventory budget exceeded")
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                raise MemoryIntegrityError("unsafe memory inventory entry")
            names.append(entry.name)
    return sorted(names)


def accepted_artifact(root, events, artifact_id, cache=None):
    key = (str(root), artifact_id)
    if cache is not None and key in cache:
        return cache[key]
    found = [
        e
        for e in events
        if e.event_type in {"artifact.accepted", "research_artifact_accepted"}
        and isinstance(e.payload, ArtifactAcceptedPayload)
        and e.payload.artifact_id == artifact_id
    ]
    if len(found) != 1:
        raise MemoryIntegrityError("missing or ambiguous accepted artifact reference")
    event = found[0]
    manifest = load_artifact_manifest(root, event.payload.manifest_sha256)
    raw = read_retained_bytes(root, manifest.content_path)
    if sha256_hex(raw) != event.payload.artifact_sha256:
        raise MemoryIntegrityError("source artifact digest mismatch")
    if cache is not None:
        size = cache.get("bytes", 0) + len(raw)
        if size > MAX_AGGREGATE_BYTES:
            raise MemoryIntegrityError("source reference byte budget exceeded")
        cache["bytes"] = size
        cache[key] = (event, raw)
    return event, raw


def validate_links(document, root, events, memories, cache=None):
    if cache is None:
        cache = {}
    event_map = {e.event_id: e for e in events}
    if not set(document.source_ledger_event_ids) <= set(event_map):
        raise MemoryIntegrityError("missing ledger reference")
    artifact_ids = {
        e.payload.artifact_id
        for e in events
        if e.event_type in {"artifact.accepted", "research_artifact_accepted"}
        and isinstance(e.payload, ArtifactAcceptedPayload)
    }
    for artifact_id in document.source_artifact_ids:
        accepted_artifact(root, events, artifact_id, cache)
    for link in document.links:
        if link.event_id is not None and link.event_id not in event_map:
            raise MemoryIntegrityError("missing linked event")
        if link.kind == "memory":
            if link.target_id not in memories:
                raise MemoryIntegrityError("missing memory link")
        elif link.kind in {"artifact", "author_target"}:
            if link.target_id not in artifact_ids:
                raise MemoryIntegrityError("missing accepted artifact link")
            event, _ = accepted_artifact(root, events, link.target_id, cache)
            if (
                link.kind == "author_target"
                and load_artifact_manifest(
                    root, event.payload.manifest_sha256
                ).artifact_kind
                != "author-target"
            ):
                raise MemoryIntegrityError(
                    "author target must reference an accepted author-target artifact"
                )
            if link.sha256 is not None and link.sha256 != event.payload.artifact_sha256:
                raise MemoryIntegrityError("linked artifact digest mismatch")
            if link.event_id is not None and link.event_id != event.event_id:
                raise MemoryIntegrityError("linked artifact event mismatch")
        elif link.kind == "decision":
            found = [
                e
                for e in events
                if (
                    getattr(e.payload, "decision_id", None) == link.target_id
                    or getattr(
                        getattr(e.payload, "decision", None), "decision_id", None
                    )
                    == link.target_id
                )
                and e.event_type
                in {"human_decision.resolved", "human_decision.recorded"}
            ]
            if not found:
                raise MemoryIntegrityError("missing accepted author decision")
            if link.event_id is not None and link.event_id not in {
                e.event_id for e in found
            }:
                raise MemoryIntegrityError("decision event mismatch")
            if link.sha256 is not None and link.sha256 not in {
                e.event_sha256 for e in found
            }:
                raise MemoryIntegrityError("decision digest mismatch")
        elif link.kind == "file":
            key = (str(root), "file", link.target_id)
            if key not in cache:
                raw = read_retained_bytes(
                    root, link.target_id, max_bytes=MAX_AGGREGATE_BYTES
                )
                cache["bytes"] = cache.get("bytes", 0) + len(raw)
                if cache["bytes"] > MAX_AGGREGATE_BYTES:
                    raise MemoryIntegrityError("source reference byte budget exceeded")
                cache[key] = raw
            raw = cache[key]
            if link.sha256 is not None and sha256_hex(raw) != link.sha256:
                raise MemoryIntegrityError("file link digest mismatch")


def cycle_ids(edges):
    graph = {}
    for source, target in edges:
        graph.setdefault(source, []).append(target)
    colors, cycles = {}, set()
    for start in graph:
        if colors.get(start):
            continue
        stack = [(start, iter(graph.get(start, ())))]
        colors[start] = 1
        path = [start]
        while stack:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                colors[node] = 2
                stack.pop()
                path.pop()
            elif colors.get(child) == 1:
                cycles.update(path[path.index(child) :])
            elif not colors.get(child):
                colors[child] = 1
                path.append(child)
                stack.append((child, iter(graph.get(child, ()))))
    return cycles


def load_inventory(project_root, project_id, *, extra_run=None):
    """Replay registered runs; only their memory events admit file bodies."""
    runs = {}
    faults = []
    try:
        names = _names(project_root, ".arw/memory/runs", 256)
    except (ValueError, OSError):
        return {}, [{"code": "memory_path_unsafe"}], {}
    for name in names:
        try:
            registration = json.loads(
                read_retained_bytes(
                    project_root, f".arw/memory/runs/{name}", max_bytes=4096
                )
            )
            if set(registration) != {"run_id", "relative_root", "manifest_sha256"}:
                raise ValueError()
            manifest_bytes = read_retained_bytes(
                project_root,
                (
                    registration["relative_root"] + "/"
                    if registration["relative_root"]
                    else ""
                )
                + "run-manifest.json",
                max_bytes=65_536,
            )
            if sha256_hex(manifest_bytes) != registration["manifest_sha256"]:
                raise ValueError()
            run_root = Path(project_root) / registration["relative_root"]
            state = replay_run(run_root)
            if state.run_id != registration["run_id"] or name != state.run_id + ".json":
                raise ValueError()
            runs[state.run_id] = (run_root, state)
        except (ValueError, RuntimeError, OSError, KeyError):
            faults.append({"code": "memory_run_registration_invalid"})
    if extra_run is not None:
        root, state = extra_run
        if state.run_id in runs and runs[state.run_id][0] != root:
            raise MemoryConflict("run identity has a different registered location")
        runs[state.run_id] = (root, state)
    entries = {}
    lifecycle = []
    total = 0
    source_cache = {}
    for root, state in runs.values():
        for event in state.events:
            if event.event_type not in RESEARCH_MEMORY_EVENT_TYPES:
                continue
            payload = event.payload
            if payload.project_id != project_id:
                faults.append(
                    {"code": "memory_project_mismatch", "memory_id": payload.memory_id}
                )
                continue
            if event.event_type not in {
                "research_memory_created",
                "research_handoff_created",
            }:
                lifecycle.append(event)
                continue
            if payload.memory_id in entries:
                faults.append(
                    {"code": "memory_duplicate_id", "memory_id": payload.memory_id}
                )
                continue
            if len(entries) >= MAX_MEMORIES:
                faults.append({"code": "memory_inventory_truncated"})
                return entries, faults, runs
            document = None
            tombstone = None
            fault_code = "memory_path_unsafe"
            try:
                marker = Path(project_root) / tombstone_path(payload.memory_id)
                if marker.exists() or marker.is_symlink():
                    tombstone = json.loads(
                        read_retained_bytes(
                            project_root,
                            tombstone_path(payload.memory_id),
                            max_bytes=4096,
                        )
                    )
                    auth_root, auth_state = runs[tombstone["authorization_run_id"]]
                    auth_event, auth_raw = accepted_artifact(
                        auth_root,
                        auth_state.events,
                        tombstone["authorization_artifact_id"],
                    )
                    auth = json.loads(auth_raw)
                    if (
                        auth.get("action") != "purge_memory"
                        or auth.get("memory_id") != payload.memory_id
                        or auth.get("content_digest") != payload.content_digest
                        or auth_event.event_sha256
                        != tombstone["authorization_event_sha256"]
                        or tombstone.get("content_digest") != payload.content_digest
                    ):
                        raise ValueError()
                else:
                    raw = read_retained_bytes(
                        project_root,
                        body_path(payload.content_digest),
                        max_bytes=MAX_DOCUMENT_BYTES,
                    )
                    total += len(raw)
                    if total > MAX_AGGREGATE_BYTES:
                        raise MemoryIntegrityError(
                            "aggregate memory body budget exceeded"
                        )
                    fault_code = "memory_schema_invalid"
                    document = ResearchMemory.model_validate_json(raw)
                    fault_code = "memory_digest_mismatch"
                    if (
                        (document.status, document.trust) != ("created", "unreviewed")
                        or tuple(document.source_ledger_event_ids)
                        != tuple(payload.source_event_ids)
                        or tuple(document.source_artifact_ids)
                        != tuple(payload.source_artifact_ids)
                    ):
                        raise MemoryIntegrityError(
                            "memory body metadata differs from admission"
                        )
                    if (
                        sha256_hex(raw) != payload.document_sha256
                        or canonical_json_bytes(document.model_dump(mode="json")) != raw
                        or not document.verify_digest()
                    ):
                        raise ValueError()
                    if document.handoff and (
                        document.handoff.source_run_harness.run_id != document.run_id
                        or document.handoff.source_run_harness.harness
                        != document.source_harness
                    ):
                        raise ValueError()
                    if (
                        document.memory_id,
                        document.project_id,
                        document.run_id,
                        document.scope,
                        document.kind,
                        document.source_harness,
                    ) != (
                        payload.memory_id,
                        project_id,
                        state.run_id,
                        payload.scope,
                        payload.kind,
                        payload.source_harness,
                    ):
                        raise ValueError()
            except (ValueError, RuntimeError, OSError, KeyError):
                faults.append(
                    {
                        "code": fault_code,
                        "memory_id": payload.memory_id,
                        "quarantined": True,
                        "tombstone": {"kind": "path-security", "durable": False}
                        if fault_code == "memory_path_unsafe"
                        else None,
                        "body_recoverable": False,
                    }
                )
                document = None
                tombstone = None
            entries[payload.memory_id] = Entry(event, event, root, document, tombstone)
    pending = sorted(lifecycle, key=lambda e: e.event_id)
    while pending:
        ready = []
        for event in pending:
            entry = entries.get(event.payload.memory_id)
            if (
                entry is not None
                and entry.head.event_sha256
                == event.payload.previous_memory_event_sha256
            ):
                ready.append(event)
        if not ready:
            faults.append({"code": "memory_lifecycle_broken_chain"})
            break
        for event in ready:
            entry = entries[event.payload.memory_id]
            if entry.head.event_sha256 != event.payload.previous_memory_event_sha256:
                faults.append(
                    {
                        "code": "memory_lifecycle_fork",
                        "memory_id": event.payload.memory_id,
                    }
                )
                pending.remove(event)
                continue
            old, new = entry.head.payload, event.payload
            if event.event_type in {
                "research_memory_verified",
                "research_memory_distilled",
            }:
                try:
                    auth_root, auth_state = runs[event.run_id]
                    auth_event, auth_raw = accepted_artifact(
                        auth_root,
                        auth_state.events[: event.sequence - 1],
                        new.authorization_artifact_id,
                        source_cache,
                    )
                    authorization = json.loads(auth_raw)
                    action = (
                        "verify_memory"
                        if event.event_type == "research_memory_verified"
                        else "distill_memory"
                    )
                    if (
                        authorization.get("action"),
                        authorization.get("memory_id"),
                        authorization.get("content_digest"),
                        auth_event.event_id,
                        auth_event.payload.artifact_sha256,
                    ) != (
                        action,
                        new.memory_id,
                        new.content_digest,
                        new.authorization_event_id,
                        new.authorization_sha256,
                    ):
                        raise MemoryIntegrityError("invalid governance authorization")
                    evidence_ids = authorization.get("source_artifact_ids")
                    if (
                        not isinstance(evidence_ids, list)
                        or not evidence_ids
                        or len(evidence_ids) > 64
                    ):
                        raise MemoryIntegrityError(
                            "invalid authorization source budget"
                        )
                    for artifact_id in evidence_ids:
                        accepted_artifact(
                            auth_root,
                            auth_state.events[: event.sequence - 1],
                            artifact_id,
                            source_cache,
                        )
                except (ValueError, RuntimeError, OSError, KeyError, TypeError):
                    faults.append(
                        {
                            "code": "memory_authorization_invalid",
                            "memory_id": new.memory_id,
                        }
                    )
                    pending.remove(event)
                    continue
            identity_fields = (
                "project_id",
                "source_run_id",
                "kind",
                "scope",
                "source_harness",
                "source_event_ids",
                "source_artifact_ids",
            )
            if any(
                getattr(old, field) != getattr(new, field) for field in identity_fields
            ):
                faults.append(
                    {
                        "code": "memory_lifecycle_identity_mismatch",
                        "memory_id": new.memory_id,
                    }
                )
                pending.remove(event)
                continue
            if (old.content_digest, old.document_sha256, old.status, old.trust) != (
                new.content_digest,
                new.document_sha256,
                new.prior_status,
                new.prior_trust,
            ):
                faults.append(
                    {"code": "memory_lifecycle_mismatch", "memory_id": new.memory_id}
                )
            else:
                entry.head = event
            pending.remove(event)
    for memory_id, entry in entries.items():
        if entry.document is None:
            continue
        try:
            validate_links(
                entry.document,
                entry.run_root,
                runs[entry.document.run_id][1].events,
                entries,
                source_cache,
            )
            if any(m not in entries for m in entry.document.supersedes):
                raise MemoryIntegrityError("missing superseded memory")
        except (ValueError, RuntimeError, OSError):
            faults.append({"code": "memory_broken_reference", "memory_id": memory_id})
    edges = [
        (mid, parent)
        for mid, entry in entries.items()
        if entry.document
        for parent in entry.document.supersedes
    ]
    for mid in sorted(cycle_ids(edges)):
        faults.append({"code": "memory_supersession_cycle", "memory_id": mid})
    return entries, faults, runs


_INDEX_SQL = """
CREATE TABLE research_memories(memory_id TEXT PRIMARY KEY,content_digest TEXT NOT NULL,project_id TEXT NOT NULL,run_id TEXT NOT NULL,scope TEXT NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL,trust TEXT NOT NULL,title TEXT,summary TEXT,created_at TEXT,source_harness TEXT,search_text TEXT,body_recoverable INTEGER NOT NULL);
CREATE TABLE memory_links(memory_id TEXT NOT NULL,kind TEXT NOT NULL,target_id TEXT NOT NULL);
CREATE TABLE memory_tags(memory_id TEXT NOT NULL,tag TEXT NOT NULL);
CREATE TABLE memory_targets(memory_id TEXT NOT NULL,harness TEXT NOT NULL);
CREATE TABLE memory_supersession(memory_id TEXT NOT NULL,supersedes TEXT NOT NULL);
"""


def build_index(entries):
    conn = sqlite3.connect(":memory:")
    conn.executescript(_INDEX_SQL)
    for mid, entry in sorted(entries.items()):
        doc = entry.document
        p = entry.head.payload
        tombstone = entry.tombstone is not None
        conn.execute(
            "INSERT INTO research_memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                mid,
                p.content_digest,
                p.project_id,
                p.source_run_id,
                p.scope,
                p.kind,
                "tombstoned" if tombstone else p.status,
                p.trust,
                doc.title if doc else None,
                doc.body[:240] if doc else None,
                doc.created_at if doc else None,
                p.source_harness,
                (doc.title + "\n" + doc.body).casefold() if doc else "",
                int(doc is not None and not tombstone),
            ),
        )
        if doc:
            conn.executemany(
                "INSERT INTO memory_links VALUES (?,?,?)",
                [(mid, l.kind, l.target_id) for l in doc.links],
            )
            conn.executemany(
                "INSERT INTO memory_tags VALUES (?,?)", [(mid, t) for t in doc.tags]
            )
            conn.executemany(
                "INSERT INTO memory_supersession VALUES (?,?)",
                [(mid, s) for s in doc.supersedes],
            )
            if doc.handoff:
                conn.execute(
                    "INSERT INTO memory_targets VALUES (?,?)",
                    (mid, doc.handoff.intended_target_harness),
                )
    conn.commit()
    return conn


def persist_index(root, entries):
    parent = Path(root) / ".arw/memory"
    if any(p.is_symlink() for p in (parent, *parent.parents)):
        raise MemoryIntegrityError("unsafe index directory")
    connection = build_index(entries)
    descriptor, name = tempfile.mkstemp(prefix=".index-", suffix=".sqlite3", dir=parent)
    os.close(descriptor)
    try:
        destination = sqlite3.connect(name)
        try:
            connection.backup(destination)
        finally:
            destination.close()
        with open(name, "rb") as stream:
            os.fsync(stream.fileno())
        target = parent / "index.sqlite3"
        if target.is_symlink():
            raise MemoryIntegrityError("index symlink rejected")
        os.replace(name, target)
    finally:
        connection.close()
        Path(name).unlink(missing_ok=True)
