"""Release compatibility is capability-based; evidence integrity remains checked."""

from __future__ import annotations

import runpy
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from arw.kernel.core.canonical import canonical_json_bytes
from arw.kernel.policy.release_qualification import (
    CHECKS,
    PLANS,
    RECEIPT,
    SCHEMA,
    digest,
    stage_digest,
    verify,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def portable(tmp_path: Path):
    root = tmp_path / "qualification"
    stage = root / "stage"
    wheel = stage / "share/arw/wheels/candidate.whl"
    wheel.parent.mkdir(parents=True)
    wheel.write_bytes(b"candidate")
    build = stage / "share/arw/evidence/candidate-build.json"
    build.parent.mkdir()
    build.write_bytes(
        canonical_json_bytes(
            {"artifacts": [{"kind": "wheel", "sha256": digest(wheel)}]}
        )
    )
    rows = []
    for name, argv in PLANS.items():
        command = root / "commands" / name
        command.mkdir(parents=True)
        stdout = (
            canonical_json_bytes(
                {
                    "schema_version": "arw.release-core-probe.v1",
                    "status": "PASS",
                    "checks": list(CHECKS),
                }
            )
            if name == "installed-core"
            else b"stage valid\n"
        )
        (command / "stdout.log").write_bytes(stdout)
        (command / "stderr.log").write_bytes(b"")
        row = {
            "name": name,
            "argv": argv,
            "returncode": 0,
            "stdout_sha256": digest(command / "stdout.log"),
            "stderr_sha256": digest(command / "stderr.log"),
        }
        (command / "result.json").write_bytes(canonical_json_bytes(row))
        rows.append(row)
    receipt = {
        "schema_version": SCHEMA,
        "source_commit": "a" * 40,
        "wheel_sha256": digest(wheel),
        "build_evidence_sha256": digest(build),
        "stage_sha256": stage_digest(stage),
        "technical_qualification": "PASS",
        "commands": rows,
        "observations": {"python": "an-observed-version", "harness": "not-installed"},
    }
    (root / RECEIPT).write_bytes(canonical_json_bytes(receipt))
    return root, receipt


def validate(root, receipt):
    return verify(
        root,
        source_commit="a" * 40,
        wheel_sha256=receipt["wheel_sha256"],
        build_sha256=receipt["build_evidence_sha256"],
    )


def test_no_harness_host_lock_or_pinned_tool_version_is_required(portable):
    root, receipt = portable
    for tool in ("pi/K3", "claude/arbitrary", "codex/future-version", "none"):
        receipt["observations"] = {"harness": tool, "version": "updated"}
        (root / RECEIPT).write_bytes(canonical_json_bytes(receipt))
        assert validate(root, receipt)["technical_qualification"] == "PASS"


@pytest.mark.parametrize(
    "damage",
    [
        "stage",
        "log",
        "failed",
        "bool-exit",
        "plan",
        "probe",
        "extra",
        "mixed",
        "symlink",
        "source",
        "build",
    ],
)
def test_changed_incomplete_or_unsafe_evidence_is_rejected(portable, damage):
    root, receipt = portable
    if damage == "stage":
        (root / "stage/extra").write_bytes(b"mutation")
    elif damage == "log":
        (root / "commands/installed-core/stdout.log").write_bytes(b"altered")
    elif damage in {"failed", "bool-exit", "plan"}:
        row = receipt["commands"][0]
        if damage == "plan":
            row["argv"] = ["echo", "PASS"]
        else:
            row["returncode"] = False if damage == "bool-exit" else 1
        (root / "commands/stage-validate/result.json").write_bytes(
            canonical_json_bytes(row)
        )
    elif damage == "probe":
        p = root / "commands/installed-core/stdout.log"
        p.write_bytes(canonical_json_bytes({"status": "PASS", "checks": []}))
        receipt["commands"][1]["stdout_sha256"] = digest(p)
        (p.parent / "result.json").write_bytes(
            canonical_json_bytes(receipt["commands"][1])
        )
    elif damage == "extra":
        (root / "extra.json").write_bytes(b"{}")
    elif damage == "mixed":
        (root / "phase-7-verification.json").write_bytes(b"{}")
    elif damage == "symlink":
        (root / "alias").symlink_to(root / "stage")
    elif damage == "source":
        receipt["source_commit"] = "b" * 40
    elif damage == "build":
        receipt["build_evidence_sha256"] = "0" * 64
    (root / RECEIPT).write_bytes(canonical_json_bytes(receipt))
    with pytest.raises(ValueError):
        validate(
            root,
            receipt
            if damage != "build"
            else {**receipt, "build_evidence_sha256": "1" * 64},
        )


def test_relative_and_absolute_transferred_paths_have_same_verdict(
    portable, monkeypatch, tmp_path
):
    root, receipt = portable
    moved = tmp_path / "download/qualification"
    shutil.copytree(root, moved)
    monkeypatch.chdir(tmp_path)
    assert validate(moved, receipt) == validate(Path("download/qualification"), receipt)


def test_export_reader_accepts_portable_profile_without_prior_phase_pins(portable):
    root, receipt = portable
    code = runpy.run_path(str(ROOT / "scripts/phase7-release-evidence"))
    assert code["verify_qualification"](root, ROOT, "a" * 40) == receipt


def test_bundle_reader_uses_original_candidate_build_identity(portable, tmp_path):
    root, receipt = portable
    bundle = tmp_path / "bundle"
    shutil.copytree(root, bundle / "qualification")
    build = bundle / "build-evidence.json"
    shutil.copyfile(root / "stage/share/arw/evidence/candidate-build.json", build)
    code = runpy.run_path(str(ROOT / "scripts/candidate-bundle"))
    code["verify_qualification"](
        bundle, {"source_identity": {"git_commit": "a" * 40}}, receipt["wheel_sha256"]
    )
    build.write_bytes(b"changed")
    with pytest.raises(SystemExit, match="candidate identity"):
        code["verify_qualification"](
            bundle,
            {"source_identity": {"git_commit": "a" * 40}},
            receipt["wheel_sha256"],
        )


@pytest.mark.parametrize("change", ["wheel", "source"])
def test_producer_rejects_candidate_substitution_before_any_execution(
    portable, tmp_path, monkeypatch, change
):
    root, receipt = portable
    build = root / "stage/share/arw/evidence/candidate-build.json"
    payload = {
        "source_identity": {"git_commit": "a" * 40, "git_status": ""},
        "artifacts": [{"kind": "wheel", "sha256": receipt["wheel_sha256"]}],
    }
    build.write_bytes(canonical_json_bytes(payload))
    original = tmp_path / "original-build.json"
    original.write_bytes(build.read_bytes())
    if change == "wheel":
        next((root / "stage/share/arw/wheels").glob("*.whl")).write_bytes(
            b"substituted"
        )
    code = runpy.run_path(str(ROOT / "scripts/qualify-release-candidate"))
    monkeypatch.setattr(
        code["subprocess"],
        "run",
        lambda *a, **k: pytest.fail("unbound candidate executed"),
    )
    args = SimpleNamespace(
        stage_root=root / "stage",
        build_evidence=original,
        qualification_root=tmp_path / "output",
        source_commit="b" * 40 if change == "source" else None,
    )
    with pytest.raises(ValueError, match="differ"):
        code["create"](args)
    assert not args.qualification_root.exists()


def test_failed_actual_command_record_is_retained_without_pass_or_retry(
    portable, tmp_path, monkeypatch
):
    root, receipt = portable
    build = root / "stage/share/arw/evidence/candidate-build.json"
    build.write_bytes(
        canonical_json_bytes(
            {
                "source_identity": {"git_commit": "a" * 40, "git_status": ""},
                "artifacts": [{"kind": "wheel", "sha256": receipt["wheel_sha256"]}],
            }
        )
    )
    code = runpy.run_path(str(ROOT / "scripts/qualify-release-candidate"))
    calls = []

    def failed(argv, **kwargs):
        calls.append(argv)
        kwargs["stderr"].write(b"real command failure fixture\n")
        return SimpleNamespace(returncode=65)

    monkeypatch.setattr(code["subprocess"], "run", failed)
    args = SimpleNamespace(
        stage_root=root / "stage",
        build_evidence=build,
        qualification_root=tmp_path / "output",
        source_commit=None,
    )
    with pytest.raises(ValueError, match="failed"):
        code["create"](args)
    assert len(calls) == 1
    assert not args.qualification_root.exists()
    retained = tmp_path / "output.failed"
    assert not (retained / RECEIPT).exists()
    assert (
        read_result(retained / "commands/stage-validate/result.json")["returncode"]
        == 65
    )


def read_result(path):
    from arw.kernel.core.canonical import strict_json_loads

    return strict_json_loads(path.read_bytes())
