"""Real offline sqlite-vec qualification; fixture relevance is not efficacy."""

import hashlib
import json
import sqlite3

import pytest

from arw.kernel.core.canonical import canonical_json_bytes

from .test_precise_source_locators import accept, seed


def model(tmp_path, **overrides):
    data = {
        "format": "arw.token-vectors.v1",
        "model_id": "fixture-concepts",
        "version": "1",
        "dimensions": 3,
        "tokens": {
            "heart": [1, 0, 0],
            "cardiac": [1, 0, 0],
            "star": [0, 1, 0],
            "stellar": [0, 1, 0],
            "cell": [0, 0, 1],
            "cellular": [0, 0, 1],
        },
    }
    data.update(overrides)
    path = tmp_path / "model.json"
    path.write_bytes(canonical_json_bytes(data))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def prepared(tmp_path):
    pytest.importorskip("sqlite_vec")
    from arw_ext.local_store.local_embedding import LocalTokenEmbedding
    from arw_ext.local_store.semantic import LocalSemanticRetriever

    root, _ = seed(tmp_path)
    for i, (name, text) in enumerate(
        [
            ("heart", "heart response in experiments"),
            ("star", "star spectra"),
            ("cell", "cell analysis"),
        ],
        100,
    ):
        path = f"{name}.txt"
        (root / path).write_text(text)
        assert accept(root, f"paper.{name}", path, i, kind="source").accepted
    path, digest = model(tmp_path)
    provider = LocalSemanticRetriever(
        tmp_path / "semantic.db",
        root,
        LocalTokenEmbedding(path, expected_digest=digest),
    )
    return root, provider, ["paper.heart", "paper.star", "paper.cell"]


def test_real_offline_neighbors_fusion_and_rebuild(tmp_path):
    _root, provider, ids = prepared(tmp_path)
    receipt = provider.build(ids)
    result = provider.search("cardiac")
    assert result["rows"][0]["artifact_id"] == "paper.heart"
    assert result["rows"][0]["semantic_distance"] == pytest.approx(0)
    assert provider.search("stellar")["rows"][0]["artifact_id"] == "paper.star"
    fused = provider.search(
        "cardiac", lexical_ids=["paper.star"], graph_ids=["paper.star"]
    )
    assert fused["rows"][0]["artifact_id"] == "paper.star"
    assert fused["rows"][0]["ranks"]["lexical"] == 1
    provider.store_path.unlink()
    assert provider.build(ids, rebuild=True) == receipt
    assert provider.search("cardiac") == result


def test_model_drift_explicit_rebuild_and_digest(tmp_path):
    from arw_ext.local_store.local_embedding import LocalTokenEmbedding
    from arw_ext.local_store.semantic import (
        LocalSemanticRetriever,
        SemanticRebuildRequired,
    )

    root, provider, ids = prepared(tmp_path)
    provider.build(ids)
    path, digest = model(tmp_path, version="2")
    updated = LocalSemanticRetriever(
        provider.store_path, root, LocalTokenEmbedding(path, expected_digest=digest)
    )
    with pytest.raises(SemanticRebuildRequired):
        updated.search("heart")
    with pytest.raises(SemanticRebuildRequired):
        updated.build(ids)
    updated.build(ids, rebuild=True)
    assert updated.search("heart")["model"]["embedding"]["version"] == "2"
    with pytest.raises(ValueError, match="digest"):
        LocalTokenEmbedding(path, expected_digest="0" * 64)


def test_failed_backend_preserves_index_and_rejects_bad_fusion(tmp_path):
    from arw_ext.local_store.semantic import SemanticFault

    _root, provider, ids = prepared(tmp_path)
    provider.build(ids)
    before = provider.search("heart")
    original = provider.backend.embed
    provider.backend.embed = lambda texts: [[float("nan")] * 3 for _ in texts]
    with pytest.raises(SemanticFault):
        provider.build(ids, rebuild=True)
    provider.backend.embed = original
    assert provider.search("heart") == before
    with pytest.raises(SemanticFault):
        provider.search("heart", graph_ids=["invented"])
    with pytest.raises(ValueError, match="vocabulary"):
        provider.search("unknown")
    with pytest.raises(SemanticFault):
        provider.search("heart", limit=1000)


def test_source_drift_rejected_and_reads_do_not_write(tmp_path):
    from arw_ext.local_store.semantic import SemanticFault

    from arw.kernel.ledger.journal import replay_run
    from arw.kernel.ledger.manifests import load_artifact_manifest

    root, provider, ids = prepared(tmp_path)
    provider.build(ids)
    before = provider.store_path.read_bytes()
    provider.search("cellular")
    assert provider.store_path.read_bytes() == before
    state = replay_run(root)
    event = next(
        e
        for e in state.events
        if e.event_type == "artifact.accepted" and e.payload.artifact_id == "paper.cell"
    )
    manifest = load_artifact_manifest(root, event.payload.manifest_sha256)
    (root / manifest.content_path).write_bytes(b"changed")
    with pytest.raises(SemanticFault, match="bytes"):
        provider.search("heart")


def test_optional_imports_are_lazy(monkeypatch):
    from arw import composition
    from arw.kernel.capabilities import CapabilityUnavailable

    original = composition.import_module
    attempted = []

    def blocked(name):
        if name == "sqlite_vec":
            attempted.append(name)
            raise ImportError("minimal installation")
        return original(name)

    monkeypatch.setattr(composition, "import_module", blocked)
    router = composition.default_router()
    assert not attempted
    router.resolve("research.literature")
    assert not attempted
    with pytest.raises(CapabilityUnavailable):
        router.resolve("knowledge.semantic_search")
    assert attempted == ["sqlite_vec"]


def test_migration_from_previous_store_does_not_load_vectors(tmp_path, monkeypatch):
    import builtins

    from arw_ext.local_store.schema import MIGRATION_0001_SQL, MIGRATION_0002_SQL
    from arw_ext.local_store.store import LocalProjectionStore

    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.executescript(MIGRATION_0001_SQL + MIGRATION_0002_SQL)
        db.executemany(
            "INSERT INTO projection_meta(key,value) VALUES (?,?)",
            [
                ("schema_version", "2"),
                ("applied_migrations", "1,2"),
                ("projection_version", "0"),
            ],
        )
    original = builtins.__import__

    def guard(name, *args, **kwargs):
        assert name != "sqlite_vec", "minimal migration imported optional vectors"
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    store = LocalProjectionStore(path)
    try:
        assert store.open().schema_version == 3
        assert store.connection.execute(
            "SELECT name FROM sqlite_master WHERE name='semantic_documents'"
        ).fetchone()
        assert (
            store.connection.execute(
                "SELECT name FROM sqlite_master WHERE name='semantic_vectors'"
            ).fetchone()
            is None
        )
    finally:
        store.close()


def test_database_failure_rolls_back_vector_replacement(tmp_path):
    _root, provider, ids = prepared(tmp_path)
    provider.build(ids)
    before = provider.search("heart")
    with sqlite3.connect(provider.store_path) as db:
        db.execute(
            "CREATE TRIGGER fail_semantic BEFORE INSERT ON semantic_documents BEGIN SELECT RAISE(ABORT, 'injected'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        provider.build(ids, rebuild=True)
    assert provider.search("heart") == before


def test_cli_explicit_build_query_and_bad_model(tmp_path, capsys):
    from arw.cli import main

    root, provider, ids = prepared(tmp_path)
    path, digest = model(tmp_path)
    args = [
        "--store",
        str(provider.store_path),
        "--run-root",
        str(root),
        "--model",
        str(path),
        "--model-sha256",
        digest,
    ]
    assert (
        main(
            [
                "semantic",
                "build",
                *args,
                *[v for i in ids for v in ("--artifact-id", i)],
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "projected"
    assert main(["semantic", "search", *args, "--query", "stellar"]) == 0
    assert json.loads(capsys.readouterr().out)["rows"][0]["artifact_id"] == "paper.star"
    args[-1] = "0" * 64
    assert main(["semantic", "search", *args, "--query", "stellar"]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "semantic_invalid"


def test_model_and_corpus_bounds_and_symlink(tmp_path):
    from arw_ext.local_store.local_embedding import LocalTokenEmbedding
    from arw_ext.local_store.semantic import LocalSemanticRetriever, SemanticFault

    root, provider, ids = prepared(tmp_path)
    with pytest.raises(SemanticFault):
        provider.build([])
    with pytest.raises(SemanticFault):
        provider.build(ids * 2)
    path, digest = model(tmp_path)
    link = tmp_path / "linked-model.json"
    link.symlink_to(path)
    with pytest.raises((OSError, ValueError, RuntimeError)):
        LocalTokenEmbedding(link, expected_digest=digest)
    db_link = tmp_path / "linked.db"
    db_link.symlink_to(tmp_path / "target.db")
    with pytest.raises((OSError, ValueError, RuntimeError)):
        LocalSemanticRetriever(db_link, root, provider.backend).build(ids)
    assert not (tmp_path / "target.db").exists()
