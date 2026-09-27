"""External test prerequisites for the whole pytest tree."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_SNAPSHOTS = (
    "vendor/sources/academic-research-skills/LICENSE",
    "vendor/sources/experiment-agent/LICENSE",
    "vendor/sources/file-base/LICENSE",
)
CANDIDATE_INPUTS = ("ARW_CANDIDATE_WHEEL", "ARW_BUILD_EVIDENCE", "ARW_CANDIDATE_EVIDENCE_ROOT")


def _candidate_missing() -> list[str]:
    return [name for name in CANDIDATE_INPUTS if not os.environ.get(name) or not Path(os.environ[name]).exists()]


def _offline_network_missing() -> list[str]:
    """Mirror the tools and namespace probes required by scripts/offline-exec."""
    if sys.platform != "linux":
        return ["offline network isolation requires Linux network namespaces"]

    tracer = shutil.which("strace")
    bundled_tracer = REPOSITORY_ROOT / "build/tools/strace/root/usr/bin/strace"
    if tracer is None and bundled_tracer.is_file() and os.access(bundled_tracer, os.X_OK):
        tracer = str(bundled_tracer)
    if tracer is None:
        return ["offline network isolation requires strace; install it or provide build/tools/strace/root/usr/bin/strace"]

    def works(command: list[str]) -> bool:
        try:
            return subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    if not works([tracer, "-o", os.devnull, "--", "/bin/true"]):
        return ["offline network isolation requires working strace/ptrace; verify strace /bin/true"]
    if shutil.which("bwrap") and works(["bwrap", "--die-with-parent", "--unshare-net", "--dev-bind", "/", "/", "--", "/bin/true"]):
        return []
    if shutil.which("unshare") and works(["unshare", "--user", "--map-root-user", "--net", "/bin/true"]):
        return []
    return ["offline network isolation requires a working bwrap or unshare network namespace; enable user/network namespaces and verify scripts/offline-exec"]


def missing_prerequisites(item: pytest.Item) -> list[str]:
    """Describe only external inputs declared by this selected test."""
    missing = []
    if item.get_closest_marker("requires_native_file_base"):
        binary = REPOSITORY_ROOT / ".file-base/bin/file-base"
        if not binary.is_file() or not os.access(binary, os.X_OK):
            missing.append("native file-base: .file-base/bin/file-base; run scripts/offline-exec --evidence-root build/evidence/local-native ./scripts/build-file-base --clean")
    if item.get_closest_marker("requires_materialized_sources"):
        absent = [path for path in SOURCE_SNAPSHOTS if not (REPOSITORY_ROOT / path).is_file()]
        if absent:
            missing.append(f"materialized sources: {', '.join(absent)}; run scripts/materialize-sources")
    if item.get_closest_marker("requires_offline_network_isolation"):
        missing.extend(_offline_network_missing())
    for marker in item.iter_markers("requires_retained_evidence"):
        for value in marker.args:
            if not isinstance(value, str) or not value:
                raise pytest.UsageError("requires_retained_evidence expects nonempty path or env:VARIABLE strings")
            if value.startswith("env:"):
                name = value[4:]
                if not os.environ.get(name):
                    missing.append(f"retained stage/evidence input {name}; set {name} to the required staged or evidence path")
            elif value == "qualification:phase7":
                from tests.qualification_support import discover_bundled_qualification

                if discover_bundled_qualification() is None:
                    missing.append("retained Phase 7 stage/lock/canary bound to this Codex host; run scripts/verify-phase-7")
            elif value in {"candidate", "candidate_or_phase7", "candidate_or_phase2_stage"}:
                retained_stage = None
                if value == "candidate_or_phase7":
                    from tests.qualification_support import (
                        discover_bundled_qualification,
                    )

                    retained_stage = discover_bundled_qualification()
                elif value == "candidate_or_phase2_stage":
                    stage_root = os.environ.get("ARW_PHASE2_STAGE_ROOT")
                    if stage_root and (Path(stage_root) / "bin/arw").is_file():
                        retained_stage = stage_root
                if retained_stage is None:
                    absent = _candidate_missing()
                    if absent:
                        missing.append(f"gated candidate inputs: {', '.join(absent)}; set ARW_CANDIDATE_WHEEL, ARW_BUILD_EVIDENCE, ARW_CANDIDATE_EVIDENCE_ROOT after building and gating a candidate")
                    if value in {"candidate_or_phase7", "candidate_or_phase2_stage"}:
                        binary = REPOSITORY_ROOT / ".file-base/bin/file-base"
                        if not binary.is_file() or not os.access(binary, os.X_OK):
                            missing.append("native file-base: .file-base/bin/file-base; run scripts/offline-exec --evidence-root build/evidence/local-native ./scripts/build-file-base --clean")
                        absent_sources = [path for path in SOURCE_SNAPSHOTS if not (REPOSITORY_ROOT / path).is_file()]
                        if absent_sources:
                            missing.append(f"materialized sources: {', '.join(absent_sources)}; run scripts/materialize-sources")
            elif not (REPOSITORY_ROOT / value).exists():
                missing.append(f"retained evidence: {value}; run the corresponding scripts/verify-phase-* qualification")
    if item.get_closest_marker("codex_host"):
        launcher = os.environ.get("ARW_CODEX_LAUNCHER") or shutil.which("codex")
        if not launcher or not (Path(launcher).is_file() or shutil.which(launcher)):
            missing.append("Codex host binary; install Codex or set ARW_CODEX_LAUNCHER")
    return missing


def pytest_runtest_setup(item: pytest.Item) -> None:
    missing = missing_prerequisites(item)
    if not missing:
        return
    reason = "missing test prerequisite(s): " + "; ".join(missing)
    if os.environ.get("ARW_STRICT_PREREQS") == "1":
        pytest.fail(reason, pytrace=False)
    pytest.skip(reason)
