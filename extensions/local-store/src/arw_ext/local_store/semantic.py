"""Lazy sqlite-vec projection over explicitly selected accepted artifacts."""

import dataclasses
import json
import math
import re
from pathlib import Path

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.ledger.journal import locked_replay
from arw.kernel.ledger.manifests import load_artifact_manifest
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.ports.semantic import EmbeddingIdentity

from .store import LocalProjectionStore


class SemanticFault(ValueError):
    code = "semantic_invalid"


class SemanticRebuildRequired(SemanticFault):
    code = "semantic_rebuild_required"


class LocalSemanticRetriever:
    def __init__(self, store_path, run_root, backend):
        # This module is only resolved for an explicit optional capability.
        import sqlite_vec

        self.vec = sqlite_vec
        self.store_path = Path(store_path)
        if any(p.is_symlink() for p in (self.store_path, *self.store_path.parents)):
            raise SemanticFault("semantic store path traverses a symlink")
        self.run_root = run_root
        self.backend = backend
        identity = backend.identity
        if not isinstance(identity, EmbeddingIdentity) or (
            not isinstance(identity.digest, str)
            or not re.fullmatch(r"[a-f0-9]{64}", identity.digest)
            or type(identity.dimensions) is not int
            or not 1 <= identity.dimensions <= 2048
            or any(
                not isinstance(v, str) or not 1 <= len(v) <= 256
                for v in (identity.model_id, identity.version, identity.implementation)
            )
        ):
            raise SemanticFault("invalid pinned embedding identity")
        self.identity = dataclasses.asdict(identity)

    def _load(self, connection):
        connection.enable_load_extension(True)
        try:
            self.vec.load(connection)
        finally:
            connection.enable_load_extension(False)
        return connection.execute("SELECT vec_version()").fetchone()[0]

    def _model(self, connection):
        return {
            "embedding": self.identity,
            "sqlite_vec_version": self._load(connection),
            "vector_index_version": "arw.semantic.l2-normalized.v1",
        }

    def _vectors(self, texts):
        if dataclasses.asdict(self.backend.identity) != self.identity:
            raise SemanticRebuildRequired("backend identity changed")
        vectors = self.backend.embed(texts)
        if len(vectors) != len(texts):
            raise SemanticFault("embedding batch length mismatch")
        encoded = []
        for vector in vectors:
            if len(vector) != self.identity["dimensions"] or any(
                type(x) not in {int, float} or not math.isfinite(x) or abs(x) > 1e10
                for x in vector
            ):
                raise SemanticFault(
                    "embedding vector must have exact finite dimensions"
                )
            norm = math.sqrt(sum(x * x for x in vector))
            if not norm:
                raise SemanticFault("embedding vector has zero norm")
            encoded.append(self.vec.serialize_float32([x / norm for x in vector]))
        return encoded

    def _sources(self, state, artifact_ids):
        if not 1 <= len(artifact_ids) <= 128 or len(set(artifact_ids)) != len(
            artifact_ids
        ):
            raise SemanticFault("select 1 to 128 unique accepted artifact IDs")
        sources, total = [], 0
        for artifact_id in sorted(artifact_ids):
            events = [
                e
                for e in state.events
                if e.event_type in {"artifact.accepted", "research_artifact_accepted"}
                and e.payload.artifact_id == artifact_id
            ]
            if len(events) != 1:
                raise SemanticFault("selected artifact is missing or ambiguous")
            event = events[0]
            manifest = load_artifact_manifest(
                self.run_root, event.payload.manifest_sha256
            )
            raw = read_retained_bytes(
                self.run_root, manifest.content_path, max_bytes=65_536
            )
            if (
                sha256_hex(raw) != event.payload.artifact_sha256
                or manifest.content_sha256 != event.payload.artifact_sha256
            ):
                raise SemanticFault("accepted source bytes do not match manifest")
            try:
                text = raw.decode("utf-8")
            except UnicodeError as error:
                raise SemanticFault(
                    "semantic corpus requires UTF-8 text artifacts"
                ) from error
            if not text.strip() or "\x00" in text:
                raise SemanticFault("empty or binary semantic source")
            total += len(raw)
            if total > 4_194_304:
                raise SemanticFault("semantic corpus aggregate byte cap exceeded")
            sources.append(
                {
                    "artifact_id": artifact_id,
                    "event_id": event.event_id,
                    "event_digest": event.event_sha256,
                    "source_digest": event.payload.artifact_sha256,
                    "text": text,
                }
            )
        return sources

    @staticmethod
    def _bindings(sources):
        return [{k: v for k, v in s.items() if k != "text"} for s in sources]

    def build(self, artifact_ids, *, rebuild=False):
        with locked_replay(self.run_root, read_only=True) as (_, state):
            sources = self._sources(state, artifact_ids)
            store = LocalProjectionStore(self.store_path)
            store.open()
            try:
                db = store.connection
                model = self._model(db)
                old = db.execute(
                    "SELECT value FROM semantic_meta WHERE key='identity'"
                ).fetchone()
                if old and not rebuild and json.loads(old[0]) != model:
                    raise SemanticRebuildRequired(
                        "model/index identity changed; explicit rebuild required"
                    )
                # Generate before deleting prior projection; failed backends preserve it.
                vectors = self._vectors([s["text"] for s in sources])
                binding = self._bindings(sources)
                with db:
                    db.execute("BEGIN IMMEDIATE")
                    db.execute("DROP TABLE IF EXISTS semantic_vectors")
                    db.execute("DELETE FROM semantic_documents")
                    db.execute("DELETE FROM semantic_meta")
                    dimensions = self.identity["dimensions"]
                    db.execute(
                        f"CREATE VIRTUAL TABLE semantic_vectors USING vec0(embedding float[{dimensions}])"
                    )
                    for rowid, (source, vector) in enumerate(
                        zip(binding, vectors, strict=True), 1
                    ):
                        db.execute(
                            "INSERT INTO semantic_documents(rowid,artifact_id,event_id,event_digest,source_digest) VALUES (?,?,?,?,?)",
                            (
                                rowid,
                                source["artifact_id"],
                                source["event_id"],
                                source["event_digest"],
                                source["source_digest"],
                            ),
                        )
                        db.execute(
                            "INSERT INTO semantic_vectors(rowid,embedding) VALUES (?,?)",
                            (rowid, vector),
                        )
                    for key, value in {
                        "identity": model,
                        "selection_digest": sha256_hex(canonical_json_bytes(binding)),
                        "run_id": state.run_id,
                    }.items():
                        db.execute(
                            "INSERT INTO semantic_meta(key,value) VALUES (?,?)",
                            (key, json.dumps(value, sort_keys=True)),
                        )
                return {
                    "status": "projected",
                    "model": model,
                    "selection_digest": sha256_hex(canonical_json_bytes(binding)),
                    "artifact_ids": [s["artifact_id"] for s in sources],
                    "authority": "advisory_projection",
                }
            finally:
                store.close()

    def search(self, query, *, lexical_ids=(), graph_ids=(), limit=10):
        if (
            not isinstance(query, str)
            or not 1 <= len(query.encode("utf-8")) <= 4096
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise SemanticFault("invalid query or result cap")
        if len(lexical_ids) > 128 or len(graph_ids) > 128:
            raise SemanticFault("fusion input cap exceeded")
        with locked_replay(self.run_root, read_only=True) as (_, state):
            store = LocalProjectionStore(self.store_path)
            store.open_readonly()
            try:
                db = store.connection
                model = self._model(db)
                try:
                    meta = {
                        k: json.loads(v)
                        for k, v in db.execute("SELECT key,value FROM semantic_meta")
                    }
                    records = [
                        dict(
                            zip(
                                (
                                    "artifact_id",
                                    "event_id",
                                    "event_digest",
                                    "source_digest",
                                ),
                                row,
                                strict=True,
                            )
                        )
                        for row in db.execute(
                            "SELECT artifact_id,event_id,event_digest,source_digest FROM semantic_documents ORDER BY artifact_id LIMIT 129"
                        )
                    ]
                except Exception as error:
                    raise SemanticRebuildRequired(
                        "semantic projection unavailable"
                    ) from error
                if meta.get("identity") != model or meta.get("run_id") != state.run_id:
                    raise SemanticRebuildRequired(
                        "model or canonical run identity changed"
                    )
                sources = self._sources(state, [s["artifact_id"] for s in records])
                bindings = self._bindings(sources)
                if records != bindings or sha256_hex(
                    canonical_json_bytes(bindings)
                ) != meta.get("selection_digest"):
                    raise SemanticRebuildRequired("canonical corpus binding changed")
                known = {s["artifact_id"]: s for s in bindings}
                if any(i not in known for i in (*lexical_ids, *graph_ids)):
                    raise SemanticFault(
                        "fusion result is outside selected canonical corpus"
                    )
                vector = self._vectors([query])[0]
                hits = db.execute(
                    "SELECT d.artifact_id,v.distance FROM semantic_vectors v JOIN semantic_documents d ON d.rowid=v.rowid WHERE v.embedding MATCH ? AND k=? ORDER BY v.distance,d.artifact_id",
                    (vector, min(50, len(records))),
                ).fetchall()
                ranks = {}
                for path, ids in (
                    ("semantic", [r[0] for r in hits]),
                    ("lexical", lexical_ids),
                    ("graph", graph_ids),
                ):
                    for rank, item in enumerate(dict.fromkeys(ids), 1):
                        ranks.setdefault(item, {})[path] = rank
                distances = dict(hits)
                result = [
                    {
                        **known[i],
                        "ranks": paths,
                        "score": sum(1 / (60 + r) for r in paths.values()),
                        "semantic_distance": distances.get(i),
                    }
                    for i, paths in ranks.items()
                ]
                result.sort(key=lambda r: (-r["score"], r["artifact_id"]))
                return {
                    "status": "ok",
                    "model": model,
                    "ranking": "reciprocal-rank-fusion-k60.v1",
                    "rows": result[:limit],
                    "authority": "advisory_projection",
                    "selection_digest": meta["selection_digest"],
                }
            finally:
                store.close()
