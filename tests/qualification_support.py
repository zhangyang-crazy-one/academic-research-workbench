"""Shared qualification discovery for phase-7 tests.

Retained build evidence (``build/evidence/*`` + ``build/stage/*``) binds an
integration lock to one exact Codex host tuple. A Codex upgrade changes the
host tuple, so any retained qualification goes stale — tests that hard-code
candidate paths start failing with "Codex host canary was produced by another
host tuple" until someone hand-edits the list after every upgrade.

Instead, this module discovers the newest retained triple (stage root,
integration lock, host canary) that still verifies end-to-end against the
current launcher/native binary. Matching is content-addressed, so a lock can
never be mixed with the wrong canary or stage:

- the lock's ``hook.host_canary_evidence_sha256`` must equal sha256(canary.json)
- the lock bytes must equal the staged ``supply-chain/integration-lock.json``
- ``verify_integration_lock`` must pass with the current Codex host
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def discover_bundled_qualification() -> tuple[Path, Path, Path] | None:
    """Return (stage_root, lock_path, canary_path) for the most recent
    retained qualification that verifies against the current Codex host, or
    ``None`` when no retained triple is currently valid."""

    from arw.kernel.policy.integration_lock import (
        IntegrationLockError,
        discover_codex_native_binary,
        load_integration_lock,
        verify_integration_lock,
    )

    evidence_root = REPOSITORY_ROOT / "build" / "evidence"
    stages_root = REPOSITORY_ROOT / "build" / "stage"
    launcher_path = shutil.which("codex")
    if launcher_path is None:
        return None
    launcher = Path(launcher_path)
    try:
        native = discover_codex_native_binary(launcher)
    except (OSError, ValueError):
        return None

    canary_by_sha256: dict[str, Path] = {}
    for canary in evidence_root.rglob("canary.json"):
        try:
            canary_by_sha256[hashlib.sha256(canary.read_bytes()).hexdigest()] = canary
        except OSError:
            continue

    stage_by_lock_bytes: dict[bytes, Path] = {}
    for staged_lock in stages_root.glob("*/supply-chain/integration-lock.json"):
        try:
            stage_by_lock_bytes[staged_lock.read_bytes()] = staged_lock.parent.parent
        except OSError:
            continue

    lock_candidates = sorted(
        evidence_root.glob("*/integration-lock.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for lock_path in lock_candidates:
        try:
            lock = load_integration_lock(lock_path)
            lock_bytes = lock_path.read_bytes()
            stage_root = stage_by_lock_bytes.get(lock_bytes)
            canary_path = canary_by_sha256.get(lock.hook.host_canary_evidence_sha256)
            if stage_root is None or canary_path is None:
                continue
            verify_integration_lock(
                lock,
                stage_root=stage_root,
                codex_launcher=launcher,
                codex_native_binary=native,
                host_canary_evidence=canary_path,
            )
            return stage_root, lock_path, canary_path
        except (OSError, ValueError, IntegrationLockError):
            continue
    return None
