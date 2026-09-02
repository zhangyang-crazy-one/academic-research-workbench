"""Store location policy (design D5; tasks 6.1-6.2).

Default store path lives under the per-user cache directory (via
``platformdirs``, already a sanctioned v1 dependency choice), keyed by a
digest of the workspace root so multiple workspaces never share one file.
A workspace-local store (``.arw/arw.db``) is opt-in via an explicit path and
is refused on detected network filesystems — SQLite journaling (WAL or
rollback) is unsafe on NFS/sshfs/SMB, and the store must fail loudly rather
than corrupt silently.

The DB is disposable (rebuildable from the canonical ledger), so a refused
network path never loses data: the operator re-runs against a local path.
"""

from __future__ import annotations

import sys
from pathlib import Path

from platformdirs import user_cache_path

from .errors import LocalStoreError

#: Filesystem type names (Linux /proc/mounts, statfs f_fstypename on macOS)
#: that SQLite documentation flags as unsafe for WAL/rollback journaling over
#: the network.  Local filesystems (ext4/xfs/apfs/ntfs/tmpfs/...) are fine.
NETWORK_FS_TYPES: frozenset[str] = frozenset(
    {
        "nfs",
        "nfs4",
        "cifs",
        "smbfs",
        "smb3",
        "sshfs",
        "fuse.sshfs",
        "9p",
        "fuse",
        "lustre",
        "glusterfs",
        "ceph",
        "davfs",
        "fuse.davfs2",
    }
)


class StoreLocationError(LocalStoreError):
    """The requested store location violates the placement policy."""

    code = "store_location_unsafe"


def _mounts_fs_types() -> dict[str, str]:
    """Return ``mount_point -> fs_type`` from /proc/mounts (Linux only)."""

    mounts: dict[str, str] = {}
    try:
        with open("/proc/mounts", encoding="utf-8") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) >= 3:
                    mounts[parts[1]] = parts[2]
    except OSError:
        pass
    return mounts


def detect_fs_type(path: Path) -> str | None:
    """Best-effort filesystem type for ``path`` (its longest mount prefix).

    Returns ``None`` when detection is impossible (non-Linux without
    statfs support, unreadable /proc/mounts).  ``None`` means "unknown",
    which the policy treats as local (fail-open for usability; the WAL
    default is already the safe journal_mode=DELETE).
    """

    resolved = path.resolve()
    if sys.platform.startswith("win"):
        # UNC paths (\\server\share) are network by definition.
        return "cifs" if str(resolved).startswith("\\\\") else None
    mounts = _mounts_fs_types()
    best: str | None = None
    best_len = -1
    for mount_point, fs_type in mounts.items():
        if (
            str(resolved) == mount_point
            or str(resolved).startswith(mount_point.rstrip("/") + "/")
        ) and len(mount_point) > best_len:
            best = fs_type
            best_len = len(mount_point)
    return best


def is_network_filesystem(path: Path) -> bool:
    """Return True when ``path`` sits on a detected network filesystem."""

    fs_type = detect_fs_type(path)
    return fs_type is not None and fs_type in NETWORK_FS_TYPES


def default_store_path(workspace_root: Path) -> Path:
    """Per-user cache location for ``workspace_root``'s projection store."""

    from arw.kernel.core.canonical import sha256_hex

    workspace_key = sha256_hex(str(workspace_root.resolve()).encode("utf-8"))[:16]
    return (
        user_cache_path("arw", appauthor=False) / "local-store" / f"{workspace_key}.db"
    )


def resolve_store_path(
    workspace_root: Path,
    *,
    explicit_path: Path | None = None,
) -> Path:
    """Resolve the store path per the placement policy.

    * ``explicit_path is None`` → the per-user cache default (task 6.1).
    * ``explicit_path`` on a detected network filesystem →
      :class:`StoreLocationError` (task 6.2; the store never opens there).
    * ``explicit_path`` on a local/unknown filesystem → the explicit path.
    """

    if explicit_path is None:
        return default_store_path(workspace_root)
    resolved = explicit_path.resolve()
    if is_network_filesystem(resolved):
        raise StoreLocationError(
            f"store path {resolved} is on a network filesystem "
            f"({detect_fs_type(resolved)}); SQLite journaling is unsafe there — "
            f"use the per-user cache default or a local filesystem path"
        )
    return resolved


__all__ = [
    "NETWORK_FS_TYPES",
    "StoreLocationError",
    "default_store_path",
    "detect_fs_type",
    "is_network_filesystem",
    "resolve_store_path",
]
