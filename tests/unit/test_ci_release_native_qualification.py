"""Manual native release qualification retains actual complete execution data."""

from __future__ import annotations

import hashlib
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


def _step(name: str) -> dict:
    return next(
        step
        for step in _workflow()["jobs"]["native-release-qualification"]["steps"]
        if step.get("name") == name
    )


def _condition(value: str, event: str, release: bool, nightly: bool = False) -> bool:
    expression = value.replace("&&", " and ").replace("||", " or ")
    expression = re.sub(r"(?<![=!])!(?!=)", " not ", expression)
    return bool(
        eval(
            expression,
            {"__builtins__": {}},
            {
                "github": SimpleNamespace(event_name=event),
                "inputs": SimpleNamespace(
                    release_native_qualification=release,
                    nightly_native_sanitizers=nightly,
                ),
            },
        )
    )


@pytest.mark.parametrize(
    "event", ["push", "pull_request", "schedule", "workflow_dispatch"]
)
@pytest.mark.parametrize("release", [False, True])
@pytest.mark.parametrize("nightly", [False, True])
def test_manual_release_profile_is_exclusive(
    event: str, release: bool, nightly: bool
) -> None:
    workflow = _workflow()
    trigger = workflow["on"]["workflow_dispatch"]["inputs"][
        "release_native_qualification"
    ]
    assert trigger == {
        "description": "Run complete upstream, ASan/UBSan and TSan release qualification",
        "type": "boolean",
        "default": "false",
    }
    jobs = workflow["jobs"]
    manual_release = event == "workflow_dispatch" and release
    assert (
        _condition(jobs["native-release-qualification"]["if"], event, release, nightly)
        is manual_release
    )
    assert (
        _condition(jobs["native-security"]["if"], event, release, nightly)
        is not manual_release
    )
    for name in ("codex-overlay", "python", "package-boundary", "macos-core"):
        expected = event != "schedule" and not (
            event == "workflow_dispatch" and (release or nightly)
        )
        assert _condition(jobs[name]["if"], event, release, nightly) is expected
    assert "'release-native' || 'regular'" in workflow["concurrency"]["group"]


def test_native_matrix_uses_the_reviewed_materialization_recipe_and_full_upload() -> (
    None
):
    jobs = _workflow()["jobs"]
    job = jobs["native-release-qualification"]
    assert job["strategy"]["fail-fast"] == "false"
    assert job["strategy"]["matrix"]["include"] == [
        {"suite": "upstream", "sanitizers": "none"},
        {"suite": "asan-ubsan", "sanitizers": "asan,ubsan"},
        {"suite": "tsan", "sanitizers": "tsan"},
    ]
    assert job["permissions"] == {"contents": "read"}
    assert job["env"]["MAKEFLAGS"] == "-j2"
    for name in (
        "Install native test prerequisites",
        "Restore legal receipt and materialize pinned native source",
    ):
        original = next(
            step
            for step in jobs["native-security"]["steps"]
            if step.get("name") == name
        )
        assert _step(name)["run"] == original["run"]
    upload = _step("Retain complete native qualification including failed results")
    assert upload["if"] == "always()"
    assert upload["uses"] == "actions/upload-artifact@v7"
    assert upload["with"] == {
        "name": "release-native-${{ matrix.suite }}-${{ github.run_id }}-${{ github.run_attempt }}",
        "path": "build/release-native-transfer/${{ matrix.suite }}",
        "include-hidden-files": "true",
        "if-no-files-found": "error",
    }
    collector = _step("Collect complete native evidence without rewriting results")
    assert collector["if"] == "always()"
    assert "technical_qualification" not in collector["run"]
    assert "shutil.copytree(evidence, output / 'evidence')" in collector["run"]


@pytest.mark.parametrize(
    ("suite", "sanitizers", "libraries"),
    [
        ("upstream", "none", ()),
        ("asan-ubsan", "asan,ubsan", ("libasan.so", "libubsan.so")),
        ("tsan", "tsan", ("libtsan.so",)),
    ],
)
@pytest.mark.parametrize("command_status", [0, 70])
def test_native_shell_passes_exact_runtime_identity_and_preserves_failure(
    tmp_path: Path,
    suite: str,
    sanitizers: str,
    libraries: tuple[str, ...],
    command_status: int,
) -> None:
    (tmp_path / "compiler-libs").mkdir()
    for library in libraries:
        (tmp_path / "compiler-libs" / f"{library}.1.2.3").write_bytes(library.encode())
    compiler = tmp_path / "cc"
    compiler.write_text(
        "#!/usr/bin/env python3\nimport os,sys\nfrom pathlib import Path\n"
        "print(Path(os.environ['ARW_TEST_LIBRARY_ROOT']) / "
        "(sys.argv[1].split('=', 1)[1] + '.1.2.3'))\n"
    )
    compiler.chmod(0o755)
    sudo = tmp_path / "sudo"
    sudo.write_text(
        "#!/usr/bin/env python3\nimport json,os,sys\nfrom pathlib import Path\n"
        "Path(os.environ['ARW_TEST_SUDO_ARGS']).write_text(json.dumps(sys.argv[1:]))\n"
        "sys.exit(int(os.environ['ARW_TEST_COMMAND_STATUS']))\n"
    )
    sudo.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{tmp_path}:{env['PATH']}",
            "ARW_NATIVE_SUITE": suite,
            "ARW_NATIVE_SANITIZERS": sanitizers,
            "ARW_TEST_LIBRARY_ROOT": str(tmp_path / "compiler-libs"),
            "ARW_TEST_SUDO_ARGS": str(tmp_path / "sudo.json"),
            "ARW_TEST_COMMAND_STATUS": str(command_status),
        }
    )
    result = subprocess.run(
        [
            "bash",
            "-e",
            "-o",
            "pipefail",
            "-c",
            _step("Run complete native suite under privileged network denial")["run"],
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == command_status, result.stderr
    args = json.loads((tmp_path / "sudo.json").read_text())
    expected = [
        "--preserve-env",
        "env",
        f"PATH={env['PATH']}",
        f"HOME={env['HOME']}",
        "MAKEFLAGS=-j2",
    ]
    if libraries:
        expected.append(f"ARW_SANITIZER_RUNTIME_DIR={tmp_path}/build/sanitizer-runtime")
    expected += [
        "./scripts/offline-exec",
        "--evidence-root",
        f"build/evidence/release-native/{suite}",
        "./scripts/build-file-base",
        "--clean",
        "--ci-ephemeral",
        "--run-upstream-tests",
    ]
    if libraries:
        expected += ["--sanitizers", sanitizers]
    assert args == expected
    for library in libraries:
        runtime = tmp_path / "build/sanitizer-runtime" / library
        assert runtime.is_symlink()
        assert runtime.resolve().parent == runtime.parent
        assert runtime.read_bytes() == library.encode()


@pytest.mark.parametrize(
    "failure_stage", ["before-execution", "test-failure", "network-failure"]
)
def test_always_collector_preserves_complete_truthful_graph(
    tmp_path: Path, failure_stage: str
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    manifest = tmp_path / "vendor/source-manifest.json"
    manifest.parent.mkdir()
    manifest.write_bytes(b'{"native_test_tree":"bound-to-source"}\n')
    subprocess.run(
        ["git", "add", "vendor/source-manifest.json"], cwd=tmp_path, check=True
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=EvidenceTest",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "source",
        ],
        cwd=tmp_path,
        check=True,
    )
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    evidence = tmp_path / "build/evidence/release-native/tsan"
    original = {}
    if failure_stage != "before-execution":
        original = {
            name: f"actual failure data: {name}\n".encode()
            for name in (
                "flags.json",
                "sanitizer-runtime.json",
                "test-inventory.json",
                "compiler.json",
                "patches.json",
                "network.strace",
                "test-stdout.log",
                "test-stderr.log",
                "stdout.log",
                "stderr.log",
                "status.txt",
                ".hidden-receipt",
                "nested/command.json",
            )
        }
        original["verdict.json"] = (
            b'{"technical_qualification":"BLOCKED","command_status":70}\n'
        )
        original["large.log"] = (
            b"original stream\n" * 150000
        )  # Over the old 2 MB filter.
        for name, data in original.items():
            path = evidence / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    env = os.environ.copy()
    env.update(
        {
            "ARW_NATIVE_SUITE": "tsan",
            "ARW_NATIVE_SANITIZERS": "tsan",
            "GITHUB_REPOSITORY": "owner/repo",
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REF": "refs/heads/qualification",
            "GITHUB_SHA": sha,
            "GITHUB_WORKFLOW_REF": "owner/repo/.github/workflows/ci.yml@refs/heads/qualification",
            "GITHUB_WORKFLOW_SHA": sha,
        }
    )
    result = subprocess.run(
        [
            "bash",
            "-e",
            "-o",
            "pipefail",
            "-c",
            _step("Collect complete native evidence without rewriting results")["run"],
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    output = tmp_path / "build/release-native-transfer/tsan"
    inventory = json.loads((output / "raw-evidence-inventory.json").read_text())
    assert {record["path"] for record in inventory} == set(original)
    for record in inventory:
        raw = original[record["path"]]
        assert record["sha256"] == hashlib.sha256(raw).hexdigest()
        assert record["size_bytes"] == len(raw)
        assert (output / "evidence" / record["path"]).read_bytes() == raw
    identity = json.loads((output / "qualification-source.json").read_text())
    assert identity["source_commit"] == identity["expected_source_commit"] == sha
    assert identity["run_id"] == 123 and identity["run_attempt"] == 1
    assert identity["suite"] == "tsan"
    assert identity["native_binary_sha256"] is None
    assert identity["native_build_evidence_sha256"] is None
    assert (output / "source-manifest.json").read_bytes() == manifest.read_bytes()
    assert not (output / "evidence/sanitizer-verdict.json").exists()
    assert not (output / "binary.sha256").exists()
