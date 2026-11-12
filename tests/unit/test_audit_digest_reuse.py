"""Single-audit digest reuse must preserve live-file rejection boundaries."""

from __future__ import annotations

import hashlib
import inspect
import os
import shutil
import subprocess
import sys
import tracemalloc
from collections import Counter

import pytest

from arw.kernel.policy import integration_lock as lock
from tests.unit.test_integration_lock import (
    _build,
    _verify,
    integration_fixture as integration_fixture,  # noqa: PLC0414
)


def test_same_length_rewrite_with_restored_mtime_is_rejected(tmp_path):
    path = tmp_path / "payload"
    path.write_bytes(b"before")
    cache = lock._AuditDigestCache()
    cache.digest(path)
    before = path.stat()
    path.write_bytes(b"after!")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_mtime_ns == before.st_mtime_ns
    with pytest.raises(lock.IntegrationLockError, match="changed"):
        cache.digest(path)


@pytest.mark.parametrize("mutation", ["replace", "chmod", "symlink", "missing"])
def test_cached_identity_drift_rejects_even_identical_bytes(tmp_path, mutation):
    path = tmp_path / "payload"
    path.write_bytes(b"original")
    cache = lock._AuditDigestCache()
    cache.digest(path)
    if mutation == "chmod":
        path.chmod(path.stat().st_mode ^ 0o100)
    elif mutation == "missing":
        path.unlink()
    else:
        replacement = tmp_path / "replacement"
        replacement.write_bytes(b"original")
        if mutation == "replace":
            replacement.replace(path)
        else:
            path.unlink()
            path.symlink_to(replacement)
    with pytest.raises(lock.IntegrationLockError):
        cache.digest(path)


@pytest.mark.parametrize("mutation", ["rewrite", "replace", "symlink", "error"])
def test_change_or_read_failure_during_hash_never_returns_digest(
    tmp_path, monkeypatch, mutation
):
    path = tmp_path / "payload"
    path.write_bytes(b"original")
    original = hashlib.file_digest

    def interrupted(stream, algorithm):
        result = original(stream, algorithm)
        if mutation == "rewrite":
            before = path.stat()
            path.write_bytes(b"modified")
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        elif mutation == "error":
            raise OSError("injected read failure")
        else:
            replacement = tmp_path / "replacement"
            replacement.write_bytes(b"original")
            if mutation == "replace":
                replacement.replace(path)
            else:
                path.unlink()
                path.symlink_to(replacement)
        return result

    monkeypatch.setattr(hashlib, "file_digest", interrupted)
    with pytest.raises(lock.IntegrationLockError):
        lock._AuditDigestCache().digest(path)


def test_audit_hashes_native_payload_once_per_invocation(
    integration_fixture, monkeypatch
):
    stage = integration_fixture["stage"]
    payload = stage / "libexec/file-base-mcp"
    payload_stat = payload.stat()
    counts = Counter()
    original = hashlib.file_digest

    def counted(stream, algorithm):
        observed = os.fstat(stream.fileno())
        if (observed.st_dev, observed.st_ino) == (
            payload_stat.st_dev,
            payload_stat.st_ino,
        ):
            counts["reads"] += 1
            counts["bytes"] += observed.st_size
        return original(stream, algorithm)

    monkeypatch.setattr(hashlib, "file_digest", counted)
    for invocation in (1, 2):
        lock.validate_live_audit_manifests(stage, verify_host_canary_closure=False)
        assert counts == {
            "reads": invocation,
            "bytes": invocation * payload_stat.st_size,
        }
    payload.write_bytes(b"tampered")
    with pytest.raises(lock.IntegrationLockError, match="digest"):
        lock.validate_live_audit_manifests(stage, verify_host_canary_closure=False)


def test_audit_rejects_late_mutation_of_an_already_checked_payload(
    integration_fixture, monkeypatch
):
    stage = integration_fixture["stage"]
    target = stage / "libexec/file-base-mcp"
    identity = lock._read_pretty_sorted_json(
        stage, lock.AUDIT_BUILD_IDENTITY_RELATIVE, label="build identity"
    )
    last_payload = stage / identity["staged_payloads"][-1]["path"]
    original = lock._AuditDigestCache.digest
    encounters = 0

    def mutate_after_last_check(cache, path):
        nonlocal encounters
        result = original(cache, path)
        if path == last_payload:
            encounters += 1
            # covered_files followed by staged_payloads; mutate after both.
            if encounters == 2:
                target.write_bytes(b"late mutation")
        return result

    monkeypatch.setattr(lock._AuditDigestCache, "digest", mutate_after_last_check)
    with pytest.raises(lock.IntegrationLockError, match="changed"):
        lock.validate_live_audit_manifests(stage, verify_host_canary_closure=False)


def test_cache_rejects_directories(tmp_path):
    path = tmp_path / "payload"
    path.mkdir()
    with pytest.raises(lock.IntegrationLockError):
        lock._AuditDigestCache().digest(path)


@pytest.mark.parametrize("mutation", ["replacement", "symlink"])
@pytest.mark.parametrize("warmed", [False, True])
def test_replacement_between_path_check_and_open_fails_closed(
    tmp_path, monkeypatch, mutation, warmed
):
    path = tmp_path / "payload"
    path.write_bytes(b"original")
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"original")
    cache = lock._AuditDigestCache()
    if warmed:
        cache.digest(path)
    original = os.open

    def replaced_open(name, flags, *args, **kwargs):
        if name == str(path):
            if mutation == "symlink":
                path.unlink()
                path.symlink_to(replacement)
            else:
                replacement.replace(path)
        return original(name, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", replaced_open)
    with pytest.raises(lock.IntegrationLockError):
        cache.digest(path)


@pytest.mark.parametrize("missing_field", ["st_ino", "st_ctime_ns"])
@pytest.mark.parametrize("unusable", [0, None])
def test_unusable_change_identity_rehashes_instead_of_reusing(
    tmp_path, monkeypatch, missing_field, unusable
):
    path = tmp_path / "payload"
    path.write_bytes(b"unchanged")
    original = os.fstat

    # A filesystem reporting no change identity must retain independent reads.
    class NoIdentity:
        def __init__(self, observed):
            self.observed = observed

        def __getattr__(self, name):
            return unusable if name == missing_field else getattr(self.observed, name)

    original_lstat = type(path).lstat
    monkeypatch.setattr(type(path), "lstat", lambda p: NoIdentity(original_lstat(p)))
    monkeypatch.setattr(os, "fstat", lambda fd: NoIdentity(original(fd)))
    original_digest = hashlib.file_digest
    reads = 0

    def counted(stream, algorithm):
        nonlocal reads
        reads += 1
        return original_digest(stream, algorithm)

    monkeypatch.setattr(hashlib, "file_digest", counted)
    cache = lock._AuditDigestCache()
    for _ in range(2):
        assert cache.digest(path) == hashlib.sha256(b"unchanged").hexdigest()
    assert reads == 2


@pytest.mark.parametrize("race", [False, True])
def test_fifo_rejection_is_bounded_in_a_fresh_process(tmp_path, race):
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO unavailable")
    code = """
import os
import shutil
import sys
from pathlib import Path
from arw.kernel.policy.integration_lock import _AuditDigestCache, IntegrationLockError
path = Path(sys.argv[1]) / 'payload'
if sys.argv[2] == 'True':
    path.write_bytes(b'original')
    replacement = path.with_name('replacement')
    os.mkfifo(replacement)
    original = os.open
    def replaced_open(name, flags):
        replacement.replace(path)
        return original(name, flags)
    os.open = replaced_open
else:
    os.mkfifo(path)
try:
    _AuditDigestCache().digest(path)
except IntegrationLockError:
    pass
else:
    raise AssertionError('FIFO was accepted')
"""
    subprocess.run(
        [sys.executable, "-c", code, str(tmp_path), str(race)],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )


def test_cached_streaming_allocation_is_bounded_for_large_files(tmp_path):
    path = tmp_path / "payload"
    mib = 1024 * 1024
    for size in (32 * mib, 512 * mib):
        with path.open("wb") as stream:
            stream.truncate(size)
        with path.open("rb") as stream:
            expected = hashlib.file_digest(stream, "sha256").hexdigest()
        cache = lock._AuditDigestCache()
        tracemalloc.start()
        try:
            assert cache.digest(path) == expected
            assert cache.digest(path) == expected
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert peak < 4 * mib


@pytest.mark.parametrize(
    "entrypoint",
    [
        lock.FileBinding.from_path,
        lock.build_integration_lock,
        lock.validate_live_audit_manifests,
        lock.observe_build_identity_binding,
        lock.verify_integration_lock,
    ],
)
def test_public_entrypoints_do_not_accept_caller_cache(entrypoint):
    # A caller must not carry authenticated digest state into another audit.
    assert "cache" not in inspect.signature(entrypoint).parameters
    with pytest.raises(TypeError, match="cache"):
        entrypoint(cache=lock._AuditDigestCache())


@pytest.mark.parametrize("entrypoint", ["build", "verify", "observe"])
def test_public_calls_rehash_native_payload_with_private_shared_cache(
    integration_fixture, monkeypatch, entrypoint
):
    paths = integration_fixture
    stage = paths["stage"]
    expected = _build(paths)
    payload = stage / "libexec/file-base-mcp"
    identity = payload.stat()
    reads = 0
    original = hashlib.file_digest

    def counted(stream, algorithm):
        nonlocal reads
        observed = os.fstat(stream.fileno())
        if (observed.st_dev, observed.st_ino) == (identity.st_dev, identity.st_ino):
            reads += 1
        return original(stream, algorithm)

    monkeypatch.setattr(hashlib, "file_digest", counted)
    source = lock._read_object(stage / "vendor/source-manifest.json", label="source")
    for invocation in (1, 2):
        if entrypoint == "build":
            assert lock.integration_lock_bytes(
                _build(paths)
            ) == lock.integration_lock_bytes(expected)
        elif entrypoint == "verify":
            assert _verify(paths, expected).technical_qualification == "PASS"
        else:
            assert (
                lock.observe_build_identity_binding(stage, source)
                == expected.build_identity
            )
        # Counts descriptor-cache hashes, not independent tree/host preflights.
        if os.name == "posix":
            assert reads == invocation
        else:
            assert reads >= invocation
    payload.write_bytes(b"changed between public calls")
    with pytest.raises(lock.IntegrationLockError):
        if entrypoint == "build":
            _build(paths)
        elif entrypoint == "verify":
            _verify(paths, expected)
        else:
            lock.observe_build_identity_binding(stage, source)


@pytest.mark.parametrize("entrypoint", ["build", "verify", "observe"])
def test_public_calls_reject_mutation_after_last_internal_check(
    integration_fixture, monkeypatch, entrypoint
):
    paths = integration_fixture
    stage = paths["stage"]
    expected = _build(paths)
    source = lock._read_object(stage / "vendor/source-manifest.json", label="source")
    target = stage / "libexec/file-base-mcp"
    helper = {
        "build": "_build_integration_lock",
        "verify": "_validate_live_audit_manifests",
        "observe": "_observe_build_identity_binding",
    }[entrypoint]
    original = getattr(lock, helper)

    def mutate_after_checks(*args, **kwargs):
        result = original(*args, **kwargs)
        target.write_bytes(b"late mutation")
        return result

    monkeypatch.setattr(lock, helper, mutate_after_checks)
    with pytest.raises(lock.IntegrationLockError, match="changed"):
        if entrypoint == "build":
            _build(paths)
        elif entrypoint == "verify":
            _verify(paths, expected)
        else:
            lock.observe_build_identity_binding(stage, source)


def test_non_posix_change_identity_independently_rehashes(tmp_path, monkeypatch):
    path = tmp_path / "payload"
    path.write_bytes(b"original")
    original = hashlib.file_digest
    reads = 0

    class NonPosix:
        name = "nt"

        def __getattr__(self, name):
            return getattr(os, name)

    def counted(stream, algorithm):
        nonlocal reads
        reads += 1
        return original(stream, algorithm)

    monkeypatch.setattr(lock, "os", NonPosix())
    monkeypatch.setattr(hashlib, "file_digest", counted)
    cache = lock._AuditDigestCache()
    assert (
        cache.digest(path)
        == cache.digest(path)
        == hashlib.sha256(b"original").hexdigest()
    )
    cache.verify_unchanged(tmp_path)
    assert reads == 3


def test_cached_hit_reopens_file_and_propagates_permission_error(tmp_path, monkeypatch):
    path = tmp_path / "payload"
    path.write_bytes(b"unchanged")
    cache = lock._AuditDigestCache()
    cache.digest(path)

    def denied(*args, **kwargs):
        raise PermissionError("injected cached reopen denial")

    monkeypatch.setattr(os, "open", denied)
    with pytest.raises(lock.IntegrationLockError, match="cached reopen denial"):
        cache.digest(path)


def test_host_canary_closure_rechecks_cached_bindings_before_return(
    integration_fixture, monkeypatch
):
    stage = integration_fixture["stage"]
    target = stage / "supply-chain/host-canary"
    shutil.copytree(integration_fixture["canary"].parent, target)
    canary = target / integration_fixture["canary"].name
    original = lock._load_canonical_bound_model
    bundle = target / "evidence-bundle.json"
    mutated = False

    def mutate_after_parity(*args, **kwargs):
        nonlocal mutated
        result = original(*args, **kwargs)
        if args[2] is lock.HookParityEvidenceRecord and not mutated:
            bundle.write_bytes(b"late mutation")
            mutated = True
        return result

    monkeypatch.setattr(lock, "_load_canonical_bound_model", mutate_after_parity)
    with pytest.raises(lock.IntegrationLockError, match="changed"):
        lock._referenced_host_canary_paths(stage, canary)
    assert mutated
