"""Keep scheduled and manually dispatched native qualification on one path."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _workflow() -> dict:
    return yaml.load(
        (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )


def _condition(value: str, event: str, nightly: bool) -> bool:
    """Evaluate the small Actions expression subset used by the native branch."""
    expression = value.replace("&&", " and ").replace("||", " or ")
    expression = re.sub(r"(?<![=!])!(?!=)", " not ", expression)
    return bool(
        eval(
            expression,
            {"__builtins__": {}},
            {
                "github": SimpleNamespace(event_name=event),
                "inputs": SimpleNamespace(nightly_native_sanitizers=nightly),
                "always": lambda: True,
            },
        )
    )


def test_dispatch_reuses_the_whole_scheduled_branch() -> None:
    workflow = _workflow()
    trigger = workflow["on"]["workflow_dispatch"]["inputs"]["nightly_native_sanitizers"]
    assert trigger["type"] == "boolean"
    assert trigger["default"] == "false"

    jobs = workflow["jobs"]
    native_steps = {
        step["name"]: step
        for step in jobs["native-security"]["steps"]
        if "name" in step
    }
    nightly_step = native_steps["Run nightly ASan and UBSan suite"]
    regular_step = native_steps["Build native test binary under network denial"]
    evidence_step = native_steps["Retain nightly sanitizer and network audit evidence"]

    for event, nightly, expected_nightly in (
        ("schedule", False, True),
        ("workflow_dispatch", True, True),
        ("workflow_dispatch", False, False),
        ("pull_request", False, False),
        ("push", False, False),
    ):
        assert _condition(nightly_step["if"], event, nightly) is expected_nightly
        assert _condition(regular_step["if"], event, nightly) is not expected_nightly
        assert _condition(evidence_step["if"], event, nightly) is expected_nightly
        for job_name in ("codex-overlay", "python", "package-boundary", "macos-core"):
            assert (
                _condition(jobs[job_name]["if"], event, nightly) is not expected_nightly
            )

    assert evidence_step["with"]["path"] == "build/evidence/ci-native-sanitized"
    assert evidence_step["with"]["if-no-files-found"] == "warn"


@pytest.mark.parametrize("versioned_libraries", [False, True])
def test_nightly_shell_passes_sanitizer_runtime_and_user_identity_to_sudo(
    tmp_path: Path,
    versioned_libraries: bool,
) -> None:
    steps = _workflow()["jobs"]["native-security"]["steps"]
    nightly = next(
        step for step in steps if step.get("name") == "Run nightly ASan and UBSan suite"
    )
    sudo = tmp_path / "sudo"
    sudo.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['ARW_TEST_SUDO_ARGS']).write_text(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    sudo.chmod(0o755)
    libraries = tmp_path / "compiler-libs"
    libraries.mkdir()
    for library in ("libasan.so", "libubsan.so"):
        name = f"{library}.1" if versioned_libraries else library
        (libraries / name).write_text(library, encoding="utf-8")
    compiler = tmp_path / "cc"
    compiler.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "from pathlib import Path\n"
        "name = sys.argv[1].split('=', 1)[1]\n"
        "if os.environ['ARW_TEST_VERSIONED_LIBRARIES'] == '1': name += '.1'\n"
        "print(Path(os.environ['ARW_TEST_LIBRARY_ROOT']) / name)\n",
        encoding="utf-8",
    )
    compiler.chmod(0o755)
    arguments = tmp_path / "sudo-arguments.json"
    environment = os.environ.copy()
    environment["PATH"] = f"{tmp_path}:{environment['PATH']}"
    environment["ARW_TEST_SUDO_ARGS"] = str(arguments)
    environment["ARW_TEST_LIBRARY_ROOT"] = str(libraries)
    environment["ARW_TEST_VERSIONED_LIBRARIES"] = str(int(versioned_libraries))
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", nightly["run"]],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    argv = json.loads(arguments.read_text(encoding="utf-8"))
    assert argv == [
        "--preserve-env",
        "env",
        f"PATH={environment['PATH']}",
        f"HOME={environment['HOME']}",
        f"ARW_SANITIZER_RUNTIME_DIR={tmp_path}/build/sanitizer-runtime",
        "./scripts/offline-exec",
        "--evidence-root",
        "build/evidence/ci-native-sanitized",
        "./scripts/build-file-base",
        "--clean",
        "--ci-ephemeral",
        "--run-upstream-tests",
        "--sanitizers",
        "asan,ubsan",
    ]
    for library in ("libasan.so", "libubsan.so"):
        runtime = tmp_path / "build/sanitizer-runtime" / library
        assert runtime.resolve().is_file()
        assert runtime.is_symlink() is versioned_libraries
