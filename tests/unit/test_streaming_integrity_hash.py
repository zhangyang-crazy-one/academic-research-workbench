"""Integrity digests read live bytes with memory independent of payload size."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tracemalloc
from pathlib import Path
from types import SimpleNamespace

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
    namespace = {"os": os, "stat": stat, "hashlib": hashlib}
    exec("digest_cache = {}\n" + launcher[start:end], namespace)
    payload = tmp_path / "native-payload"
    payload.write_bytes(b"native" * 300000)
    reads = {"count": 0}
    real_open = Path.open

    def counted_open(self, *args, **kwargs):
        mode = kwargs.get("mode", args[0] if args else "r")
        if self == payload and "b" in mode and "w" not in mode and "a" not in mode and "+" not in mode:
            reads["count"] += 1
        return real_open(self, *args, **kwargs)

    Path.open = counted_open
    try:
        first = namespace["sha"](payload)
        second = namespace["sha"](payload)
    finally:
        Path.open = real_open
    assert first == second == hashlib.sha256(payload.read_bytes()).hexdigest()
    assert reads["count"] == (1 if os.name == "posix" else 2)
    payload.write_bytes(b"changed native bytes")
    Path.open = counted_open
    try:
        changed = namespace["sha"](payload)
    finally:
        Path.open = real_open
    assert changed == hashlib.sha256(payload.read_bytes()).hexdigest()
    assert reads["count"] == (2 if os.name == "posix" else 3)



def _launcher_digest_reader():
    launcher = (Path(__file__).resolve().parents[2] / "bin/arw").read_text(
        encoding="utf-8"
    )
    start = launcher.index("def sha(path):")
    end = launcher.index("def object_at(relative):", start)
    namespace = {"os": os, "stat": stat, "hashlib": hashlib}
    exec("digest_cache = {}\n" + launcher[start:end], namespace)
    return namespace["sha"]


@pytest.mark.parametrize("kind", ["audit", "launcher"])
def test_digest_cache_rehashes_real_same_size_write_with_restored_mtime(tmp_path, kind):
    reader = (integration_lock._AuditDigestCache().digest
              if kind == "audit" else _launcher_digest_reader())
    path = tmp_path / "payload"
    path.write_bytes(b"alpha")
    before = path.stat()
    first = reader(path)
    path.write_bytes(b"omega")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = path.stat()
    # Real stat objects retain nanoseconds; tuple-built os.stat_result does not.
    assert (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) == (
        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns
    )
    assert reader(path) == hashlib.sha256(b"omega").hexdigest() != first


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX change time")
@pytest.mark.parametrize("kind", ["audit", "launcher"])
def test_digest_cache_rejects_same_size_mutation_during_hash(tmp_path, monkeypatch, kind):
    reader = (integration_lock._AuditDigestCache().digest
              if kind == "audit" else _launcher_digest_reader())
    path = tmp_path / "payload"
    path.write_bytes(b"alpha")
    before = path.stat()
    real_open = Path.open

    class MutatingReader:
        def __enter__(self):
            self.stream = real_open(path, "rb")
            return self

        def __exit__(self, *args):
            self.stream.close()

        def read(self, size):
            data = self.stream.read(size)
            if data:
                with real_open(path, "wb") as target:
                    target.write(b"omega")
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
            return data

    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: MutatingReader())
    with pytest.raises((integration_lock.IntegrationLockError, SystemExit),
                       match="changed while hashing"):
        reader(path)
    monkeypatch.setattr(Path, "open", real_open)
    assert reader(path) == hashlib.sha256(b"omega").hexdigest()


@pytest.mark.parametrize("kind", ["audit", "launcher"])
@pytest.mark.parametrize("unsupported", ["ctime", "platform", "regular"])
def test_digest_cache_rehashes_without_change_detection(tmp_path, monkeypatch, kind, unsupported):
    reader = (integration_lock._AuditDigestCache().digest
              if kind == "audit" else _launcher_digest_reader())
    path = tmp_path / "payload"
    path.write_bytes(b"alpha")
    reads = []
    real_open = Path.open
    real_stat = Path.stat

    def counted_open(self, *args, **kwargs):
        reads.append(self)
        return real_open(self, *args, **kwargs)

    def unsupported_stat(self, *args, **kwargs):
        result = real_stat(self, *args, **kwargs)
        return SimpleNamespace(
            st_dev=result.st_dev, st_ino=result.st_ino, st_size=result.st_size,
            st_mtime_ns=result.st_mtime_ns,
            st_ctime_ns=None if unsupported == "ctime" else result.st_ctime_ns,
            st_mode=stat.S_IFIFO if unsupported == "regular" else result.st_mode,
        )

    if unsupported == "platform":
        # Change only the helper's os binding, not pathlib's global platform.
        fake_os = SimpleNamespace(name="nt", fspath=os.fspath)
        if kind == "audit":
            monkeypatch.setattr(integration_lock, "os", fake_os)
        else:
            reader.__globals__["os"] = fake_os
    else:
        monkeypatch.setattr(Path, "stat", unsupported_stat)
    monkeypatch.setattr(Path, "open", counted_open)
    assert reader(path) == reader(path) == hashlib.sha256(b"alpha").hexdigest()
    assert reads == [path, path]


@pytest.mark.parametrize("kind", ["audit", "launcher"])
def test_digest_cache_rechecks_replacement_missing_file_and_read_error(tmp_path, monkeypatch, kind):
    def new_reader():
        return (integration_lock._AuditDigestCache().digest
                if kind == "audit" else _launcher_digest_reader())

    reader = new_reader()
    path = tmp_path / "payload"
    path.write_bytes(b"alpha")
    first = reader(path)
    before = path.stat()
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"omega")
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    replacement.replace(path)
    expected = hashlib.sha256(b"omega").hexdigest()
    assert reader(path) == new_reader()(path) == expected != first
    path.unlink()
    with pytest.raises((OSError, integration_lock.IntegrationLockError)):
        reader(path)
    path.write_bytes(b"new payload")
    real_open = Path.open

    def denied_open(*args, **kwargs):
        raise PermissionError("injected read denial")

    monkeypatch.setattr(Path, "open", denied_open)
    with pytest.raises((OSError, integration_lock.IntegrationLockError), match="injected read denial"):
        reader(path)
    monkeypatch.setattr(Path, "open", real_open)
    assert reader(path) == hashlib.sha256(b"new payload").hexdigest()
