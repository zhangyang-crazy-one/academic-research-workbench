"""Shared pytest configuration for the whole test tree.

Staged and installed-plugin tests build full plugin stages with
``scripts/stage-plugin``; each stage copies the ~258 MB ``libexec/file-base-mcp``
binary, and several integration fixtures publish multi-GB evidence trees. A full
``uv run pytest`` run writes well over 10 GB through the default pytest temp
base on ``/tmp`` — which on this host is a 16 GB tmpfs — so runs repeatedly
exhaust the quota and fail arbitrary later tests with "超出磁盘配额" / ENOSPC
(the failing test is whichever one happens to write next, so the failure set
drifts between runs).

Redirecting the temp base to the repository filesystem (a large NVMe mount)
keeps all test bytes off the tmpfs entirely. Digest / inventory / lock-binding
assertions are byte-for-byte unchanged — only the location of the copies moves.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TEST_TMP_BASE = REPOSITORY_ROOT / "build" / "pytest-tmp"


def pytest_configure(config: pytest.Config) -> None:
    # Drop leftovers from interrupted runs before every invocation.
    shutil.rmtree(TEST_TMP_BASE, ignore_errors=True)
    config.option.basetemp = str(TEST_TMP_BASE)


def pytest_unconfigure(config: pytest.Config) -> None:
    # Release the copied stage bytes once the session is over.
    shutil.rmtree(TEST_TMP_BASE, ignore_errors=True)
