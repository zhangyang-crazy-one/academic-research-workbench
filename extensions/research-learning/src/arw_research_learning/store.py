"""Bounded immutable learning evidence with a disposable SQLite projection."""

import json
import os
import sqlite3
from pathlib import Path

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.ledger.journal import replay_run
from arw.kernel.ledger.manifests import load_artifact_manifest
from arw.kernel.ledger.research_records import BodyUnavailable, publish_once
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.state.models import RESEARCH_LEARNING_EVENT_TYPES
from arw.kernel.state.research_learning import (
    LearningConfiguration,
    LearningObservation,
    ResearchHeuristic,
)
from arw.kernel.state.research_memory import ProjectIdentity


class LearningFault(ValueError):
    code = "learning_invalid"


class LearningDisabled(LearningFault):
    code = "learning_disabled"


class ReevaluationRequired(LearningFault):
    code = "reevaluation_required"


def identity(root):
    try:
        return ProjectIdentity.model_validate_json(
            read_retained_bytes(root, ".arw/project.json", max_bytes=4096)
        )
    except (ValueError, OSError, RuntimeError) as error:
        raise LearningFault("stable ARW project identity is unresolved") from error


def configuration(root):
    path = Path(root) / ".arw/learning-policy.json"
    if not path.exists() and not path.is_symlink():
        return LearningConfiguration()
    return LearningConfiguration.model_validate_json(
        read_retained_bytes(root, ".arw/learning-policy.json", max_bytes=65536)
    )


def names(root, relative, limit):
    directory = Path(root) / relative
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        raise LearningFault("unsafe learning directory")
    if not directory.exists():
        return []
    result = []
    with os.scandir(directory) as entries:
        for entry in entries:
            if (
                len(result) >= limit
                or entry.is_symlink()
                or not entry.is_file(follow_symlinks=False)
            ):
                raise LearningFault("unsafe or oversized learning inventory")
            result.append(entry.name)
    return sorted(result)


def body_path(digest):
    return f".arw/learning/bodies/{digest}.json"


def marker_path(digest):
    return f".arw/learning/tombstones/{digest}.json"


def accepted_artifact(root, events, artifact_id, cache=None):
    key = (str(root), artifact_id)
    if cache is not None and key in cache:
        return cache[key]

    candidates = [
        e
        for e in events
        if e.event_type in {"artifact.accepted", "research_artifact_accepted"}
        and e.payload.artifact_id == artifact_id
    ]
    if len(candidates) != 1:
        raise LearningFault("accepted artifact reference is missing or ambiguous")
    event = candidates[0]
    manifest = load_artifact_manifest(root, event.payload.manifest_sha256)
    raw = read_retained_bytes(root, manifest.content_path, max_bytes=65536)
    if (
        sha256_hex(raw) != event.payload.artifact_sha256
        or manifest.content_sha256 != event.payload.artifact_sha256
    ):
        raise LearningFault("accepted artifact digest mismatch")
    if cache is not None:
        cache["bytes"] = cache.get("bytes", 0) + len(raw)
        if cache["bytes"] > 8_388_608:
            raise LearningFault("accepted source aggregate budget exceeded")
        cache[key] = (event, raw)
    return event, raw


def run_inventory(root, held=None):
    records = {}
    project_id = identity(root).project_id
    for name in names(root, ".arw/learning/runs", 256):
        record = json.loads(
            read_retained_bytes(root, ".arw/learning/runs/" + name, max_bytes=4096)
        )
        relative = record["relative_root"]
        if relative and (
            relative.startswith("/")
            or "\\" in relative
            or any(p in {"", ".", ".."} for p in relative.split("/"))
        ):
            raise LearningFault("unsafe registered run")
        run_root = Path(root) / relative
        if not run_root.resolve().is_relative_to(Path(root).resolve()) or any(
            p.is_symlink() for p in (run_root, *run_root.parents)
        ):
            raise LearningFault("registered run escapes project")
        manifest = read_retained_bytes(run_root, "run-manifest.json", max_bytes=65536)
        state = (
            held[1]
            if held is not None and run_root == held[0]
            else replay_run(run_root)
        )
        if (
            state.recovery_health != "healthy"
            or state.run_id != record["run_id"]
            or sha256_hex(manifest) != record["manifest_sha256"]
            or record["project_id"] != project_id
        ):
            raise LearningFault("registered run identity or ledger is invalid")
        if state.run_id in records:
            raise LearningFault("ambiguous run identity")
        records[state.run_id] = (run_root, state)
    return records


def load_body(root, digest, runs):
    marker = Path(root) / marker_path(digest)
    if marker.exists() or marker.is_symlink():
        value = json.loads(
            read_retained_bytes(root, marker_path(digest), max_bytes=65536)
        )
        run_root, state = runs[value["authorization_run_id"]]
        event, raw = accepted_artifact(
            run_root, state.events, value["authorization_artifact_id"]
        )
        auth = json.loads(raw)
        if (
            auth.get("action") != "purge_learning"
            or auth.get("content_digest") != digest
            or value.get("authorization_sha256") != event.payload.artifact_sha256
        ):
            raise LearningFault("retention authorization mismatch")
        raise BodyUnavailable(
            f"learning body {digest} intentionally unavailable; authorization {event.event_id}"
        )
    raw = read_retained_bytes(root, body_path(digest), max_bytes=65536)
    if sha256_hex(raw) != digest:
        raise LearningFault("learning body digest mismatch")
    return json.loads(raw)


def inventory(root, held=None):
    runs = run_inventory(root, held)
    records = {}
    source_cache = {}
    total = 0
    total_bytes = 0
    project_id = identity(root).project_id
    for run_root, state in runs.values():
        for event in state.events:
            if event.event_type not in RESEARCH_LEARNING_EVENT_TYPES:
                continue
            p = event.payload
            if p.project_id != project_id:
                raise LearningFault("learning project mismatch")
            if p.record_id in records and records[p.record_id]["run_root"] != run_root:
                raise LearningFault("learning identity collides across runs")
            total += 1
            if total > 4096:
                raise LearningFault("learning event budget exceeded")
            try:
                body = load_body(root, p.content_digest, runs)
            except BodyUnavailable:
                body = None
            if body is not None:
                total_bytes += len(canonical_json_bytes(body))
                if total_bytes > 8_388_608:
                    raise LearningFault("learning body aggregate budget exceeded")
                if (
                    body.get("project_id") != p.project_id
                    or body.get(
                        "record_id",
                        body.get("heuristic_id", body.get("observation_id")),
                    )
                    != p.record_id
                ):
                    raise LearningFault("learning document binding mismatch")
                if p.status == "recorded":
                    doc = LearningObservation.model_validate_json(json.dumps(body))
                    source = next(
                        (e for e in state.events if e.event_id == doc.ledger_event_id),
                        None,
                    )
                    if (
                        doc.run_id != state.run_id
                        or source is None
                        or source.event_id not in p.source_event_ids
                    ):
                        raise LearningFault("observation source is unavailable")
                    expected_digest = getattr(
                        source.payload, "artifact_sha256", source.event_sha256
                    )
                    if doc.source_digest != expected_digest:
                        raise LearningFault("observation source digest mismatch")
                    for artifact_id in doc.source_artifact_ids:
                        accepted_artifact(
                            run_root, state.events, artifact_id, source_cache
                        )
                elif p.status == "candidate":
                    doc = ResearchHeuristic.model_validate_json(json.dumps(body))
                    if (
                        doc.run_id != state.run_id
                        or doc.status != "candidate"
                        or doc.trust != "unreviewed"
                        or doc.scope != p.scope
                    ):
                        raise LearningFault("candidate authority binding mismatch")
            previous = records.get(p.record_id)
            records[p.record_id] = {
                "head": event,
                "creation": previous["creation"] if previous else event,
                "candidate": previous["candidate"] if previous else body,
                "body": body,
                "run_root": run_root,
                "tombstoned": body is None
                or (previous is not None and previous["tombstoned"]),
                "history": [*(previous["history"] if previous else []), event],
            }
    for entry in records.values():
        candidate = entry["candidate"]
        if candidate and "heuristic_id" in candidate:
            for observation_id in (
                *candidate["supporting_observation_ids"],
                *candidate["counterexample_observation_ids"],
                *(u["observation_id"] for u in candidate["unknown"]),
            ):
                observation = records.get(observation_id)
                if (
                    observation is None
                    or observation["head"].payload.status != "recorded"
                ):
                    raise LearningFault("heuristic has missing observation links")
                if observation["body"] is None:
                    entry["tombstoned"] = True
                elif observation["body"]["duplicate_of"] is not None:
                    raise LearningFault("heuristic contains duplicate samples")
    if len(records) > 1024:
        raise LearningFault("learning record budget exceeded")
    return records, runs


TABLES = (
    "learning_observations",
    "learning_memories",
    "research_heuristics",
    "heuristic_evidence",
    "heuristic_counterexamples",
    "heuristic_evaluations",
    "heuristic_promotions",
)


def projection(records):
    db = sqlite3.connect(":memory:")
    for table in TABLES:
        db.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    for record_id, entry in sorted(records.items()):
        p = entry["head"].payload
        summary = {
            "record_id": record_id,
            "scope": p.scope,
            "status": "tombstoned" if entry["tombstoned"] else p.status,
            "content_digest": p.content_digest,
            "body_recoverable": not entry["tombstoned"],
            "event_id": entry["head"].event_id,
            "body": entry["body"],
        }
        table = (
            "learning_observations" if p.status == "recorded" else "research_heuristics"
        )
        db.execute(
            f"INSERT INTO {table} VALUES (?,?)",
            (record_id, canonical_json_bytes(summary).decode()),
        )
        candidate = entry["candidate"]
        if candidate and "heuristic_id" in candidate:
            for bucket, table in [
                ("supporting_observation_ids", "heuristic_evidence"),
                ("counterexample_observation_ids", "heuristic_counterexamples"),
                ("unknown", "heuristic_evidence"),
            ]:
                for index, item in enumerate(candidate[bucket]):
                    db.execute(
                        f"INSERT INTO {table} VALUES (?,?)",
                        (
                            f"{record_id}:{bucket}:{index}",
                            json.dumps(
                                {
                                    "heuristic_id": record_id,
                                    "bucket": bucket,
                                    "evidence": item,
                                }
                            ),
                        ),
                    )
        for event in entry["history"]:
            if event.payload.status == "evaluated":
                db.execute(
                    "INSERT INTO heuristic_evaluations VALUES (?,?)",
                    (
                        event.payload.content_digest,
                        json.dumps(
                            {
                                "receipt_id": event.payload.content_digest,
                                "heuristic_id": record_id,
                            }
                        ),
                    ),
                )
            if event.payload.status == "promoted":
                db.execute(
                    "INSERT INTO heuristic_promotions VALUES (?,?)",
                    (event.event_id, event.payload.model_dump_json()),
                )
    db.commit()
    return db


def _rebuild(root):
    records, _ = inventory(root)
    db = projection(records)
    destination = Path(root) / ".arw/learning/index.sqlite3"
    if destination.is_symlink() or any(p.is_symlink() for p in destination.parents):
        raise LearningFault("unsafe learning projection path")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name("index.rebuild.sqlite3")
    if temporary.exists() or temporary.is_symlink():
        if temporary.is_symlink():
            raise LearningFault("unsafe projection temporary")
        temporary.unlink()
    try:
        with sqlite3.connect(temporary) as target:
            db.backup(target)
        os.replace(temporary, destination)
    finally:
        db.close()
    return {"records": len(records), "tables": list(TABLES), "canonical": False}


def rebuild(root):
    import portalocker

    publish_once(root, ".arw/learning/.lock", b"")
    path = Path(root) / ".arw/learning/.lock"
    if path.is_symlink():
        raise LearningFault("unsafe learning lock")
    with portalocker.Lock(path, mode="rb", timeout=5):
        return _rebuild(root)
