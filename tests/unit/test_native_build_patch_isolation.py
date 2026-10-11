"""Native patch application must work beneath an unrelated Git checkout."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_repository_local_native_temporary_tree_applies_actual_patch(tmp_path: Path) -> None:
    parent = tmp_path / "parent-repository"
    parent.mkdir()
    subprocess.run(["git", "init", "--quiet", str(parent)], check=True)
    parent_file = parent / "file.txt"
    parent_file.write_text("parent must stay unchanged\n")
    work = parent / "build/tmp/native-work"
    source = work / "file-base"
    source.mkdir(parents=True)
    target = source / "file.txt"
    target.write_text("before\n")
    patch = tmp_path / "native.patch"
    patch.write_text(
        "diff --git a/file.txt b/file.txt\n--- a/file.txt\n+++ b/file.txt\n"
        "@@ -1 +1 @@\n-before\n+after\n"
    )
    script = (ROOT / "scripts/build-file-base").read_text()
    function = re.search(r"(?m)^apply_native_patch\(\) \{\n.*?^\}", script, re.DOTALL)
    assert function is not None
    result = subprocess.run(
        ["bash", "-c", function.group() + '\napply_native_patch --check "$1"\napply_native_patch "$1"',
         "native-patch-test", str(patch)],
        env={**os.environ, "WORK_ROOT": str(work), "BUILD_SOURCE": str(source)},
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert target.read_text() == "after\n"
    assert parent_file.read_text() == "parent must stay unchanged\n"
