"""Integrity digests read live bytes with memory independent of payload size."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tracemalloc
from pathlib import Path

import pytest

from arw.kernel.core.canonical import sha256_file
from arw.kernel.policy import build_identity, core_integrity, integration_lock
from tests.unit.test_integration_lock import (
    integration_fixture as integration_fixture,  # noqa: PLC0414 -- re-export pytest fixture
)

READERS = [sha256_file, core_integrity._digest, integration_lock._digest]
MIB = 1024 * 1024


@pytest.mark.parametrize("reader", READERS)
@pytest.mark.parametrize("size", [0, 37, MIB - 1, MIB + 1])
def test_digest_matches_reference_for_empty_binary_and_chunk_boundary(
    tmp_path, reader, size
):
    raw = (bytes(range(256)) * (size // 256 + 1))[:size]
    path = tmp_path / "payload"
    path.write_bytes(raw)
    assert reader(path) == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("reader", READERS)
def test_hash_allocation_stays_bounded_from_32_to_512_mib(tmp_path, reader):
    path = tmp_path / "large-payload"
    for size in (32 * MIB, 512 * MIB):
        with path.open("wb") as stream:
            stream.truncate(size)
        with path.open("rb") as stream:
            expected = hashlib.file_digest(stream, "sha256").hexdigest()
        tracemalloc.start()
        try:
            actual = reader(path)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert actual == expected
        assert peak < 4 * MIB


@pytest.mark.parametrize("reader", READERS)
def test_read_errors_never_return_a_partial_digest(tmp_path, monkeypatch, reader):
    class FailingReader:
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.closed = True

        def read(self, size):
            if hasattr(self, "started"):
                raise OSError("injected read failure")
            self.started = True
            return b"partial bytes"

    stream = FailingReader()
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: stream)
    with pytest.raises((OSError, integration_lock.IntegrationLockError)):
        reader(tmp_path / "payload")
    assert stream.closed


@pytest.mark.parametrize("reader", READERS)
def test_missing_file_still_fails_closed(tmp_path, reader):
    with pytest.raises((OSError, integration_lock.IntegrationLockError)):
        reader(tmp_path / "missing")


def test_file_binding_rechecks_replacement_and_symlink(tmp_path):
    path = tmp_path / "payload"
    path.write_bytes(b"original")
    binding = integration_lock.FileBinding.from_path(tmp_path, path.name)
    assert integration_lock._bound_file(tmp_path, binding) == path
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"replaced")
    replacement.replace(path)
    with pytest.raises(integration_lock.IntegrationLockError, match="digest drift"):
        integration_lock._bound_file(tmp_path, binding)
    path.unlink()
    path.write_bytes(b"original")
    assert integration_lock._bound_file(tmp_path, binding) == path
    if os.name != "nt":
        outside = tmp_path / "outside"
        outside.write_bytes(b"original")
        path.unlink()
        path.symlink_to(outside)
        with pytest.raises(integration_lock.IntegrationLockError, match="symlink"):
            integration_lock._bound_file(tmp_path, binding)


def test_packaged_identity_hashes_payload_without_full_file_read(
    integration_fixture, monkeypatch
):
    root = integration_fixture["stage"]
    identity_path = root / "share/arw/build-identity.json"
    shutil.copytree(
        Path(__file__).parents[2] / "schemas/v1",
        root / "share/arw/schemas",
        dirs_exist_ok=True,
    )
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(root))
    monkeypatch.setenv("ARW_BUILD_IDENTITY", str(identity_path))
    monkeypatch.setenv("ARW_SCHEMA_ROOT", str(root / "share/arw/schemas"))
    before, identity_digest = build_identity.load_packaged_build_identity()
    payload = root / "libexec/file-base-mcp"
    original_read = Path.read_bytes

    def guarded_read(path):
        assert path != payload, "native payload must not be allocated in full"
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    assert build_identity.load_packaged_build_identity() == (before, identity_digest)
    payload.write_bytes(b"altered native bytes")
    with pytest.raises(
        build_identity.BuildIdentityError, match="payload digest mismatch"
    ):
        build_identity.load_packaged_build_identity()


def test_fresh_process_rehashes_changed_file(tmp_path):
    path = tmp_path / "payload"
    code = (
        "from pathlib import Path; import sys; "
        "from arw.kernel.core.canonical import sha256_file; "
        "print(sha256_file(Path(sys.argv[1])))"
    )
    results = []
    for raw in (b"before", b"after"):
        path.write_bytes(raw)
        result = subprocess.run(
            [sys.executable, "-c", code, str(path)],
            text=True,
            capture_output=True,
            timeout=30,
            check=True,
        )
        results.append(result.stdout.strip())
        assert results[-1] == hashlib.sha256(raw).hexdigest()
    assert results[0] != results[1]


def test_launcher_reuses_one_large_payload_within_the_same_identity_check(tmp_path):
    launcher = (
        Path(__file__).resolve().parents[2] / "bin/arw"
    ).read_text(encoding="utf-8")
    start = launcher.index("def sha(path):")
    end = launcher.index("def object_at(relative):", start)
    namespace = {"digest_cache": {}, "os": os, "hashlib": hashlib}
    exec(launcher[start:end], namespace)
    payload = tmp_path / "native-payload"
    payload.write_bytes(b"native" * 300000)
    reads = {"count": 0}
    real_open = Path.open

    def counted_open(self, *args, **kwargs):
        if self == payload:
            reads["count"] += 1
        return real_open(self, *args, **kwargs)

    Path.open = counted_open
    try:
        first = namespace["sha"](payload)
        second = namespace["sha"](payload)
    finally:
        Path.open = real_open
    assert first == second == hashlib.sha256(payload.read_bytes()).hexdigest()
    assert reads["count"] == 1
    payload.write_bytes(b"changed native bytes")
    assert namespace["sha"](payload) == hashlib.sha256(payload.read_bytes()).hexdigest()
