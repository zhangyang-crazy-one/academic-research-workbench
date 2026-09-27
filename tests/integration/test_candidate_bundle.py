"""Release transfer accepts only the wheel and artifacts in its candidate manifest."""

from __future__ import annotations

import hashlib
import json
import runpy
import shutil
import stat
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/candidate-bundle"
RELEASE_CHECK = SCRIPT.with_name("check-release-candidate")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def candidate(tmp_path: Path) -> tuple[Path, Path, Path]:
    build = tmp_path / "build"
    evidence = tmp_path / "evidence"
    wheel = build / "dist/academic_research_workbench-0.1.0-py3-none-any.whl"
    source = build / "dist/academic_research_workbench-0.1.0.tar.gz"
    wheel.parent.mkdir(parents=True)
    wheel.write_bytes(b"candidate-wheel")
    source.write_bytes(b"candidate-source")
    build_observation = {
        "python": {"version": "3.14.6", "executable": "/tmp/builder/bin/python"},
        "backend": {"name": "hatchling", "version": "1.32.4"},
        "inventory": [{"name": "hatchling", "version": "1.32.4", "license": "MIT", "installed_content_sha256": "1" * 64}],
    }
    runtime = {"python": {"version": "3.14.6", "executable": "/tmp/runtime/bin/python"},
               "inventory": []}
    write(build / "build-evidence.json", {
        "source_identity": {"git_commit": "a" * 40, "git_status": ""},
        "build": build_observation,
        "resolved_runtime_inventory": [],
        "runtime_resolution_environment": runtime,
        "artifacts": [
            {"kind": "wheel", "path": f"dist/{wheel.name}", "size": wheel.stat().st_size, "sha256": sha(wheel)},
            {"kind": "sdist", "path": f"dist/{source.name}", "size": source.stat().st_size, "sha256": sha(source)},
        ]
    })
    write(evidence / "SBOM.cdx.json", {"components": [{
        "bom-ref": f"first-party-wheel:{wheel.name}",
        "hashes": [{"alg": "SHA-256", "content": sha(wheel)}],
    }, {"bom-ref": "python:hatchling@1.32.4", "name": "hatchling", "version": "1.32.4",
        "hashes": [{"alg": "SHA-256", "content": "1" * 64}], "licenses": [{"expression": "MIT"}]}]})
    write(evidence / "supply-chain/use-distribution.json", {
        "evidence_hashes": [{"path": "SBOM.cdx.json", "sha256": sha(evidence / "SBOM.cdx.json")}]
    })
    write(evidence / "supply-chain/license-verdict.json", {
        "technical_qualification": "PASS", "release_qualification": "BLOCKED"
    })
    write(evidence / "license-evidence/inventory.json", {
        "build_evidence": {"sha256": sha(build / "build-evidence.json")},
        "build_observation": build_observation,
        "runtime_resolution_environment": runtime,
        "python_packages_observed": build_observation["inventory"],
        "first_party_wheel": {"file": wheel.name, "sha256": sha(wheel)},
    })
    return build / "build-evidence.json", evidence, wheel


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], text=True, capture_output=True, check=False)


def qualification_root(root: Path, phase7: Path, stage: Path, lock: Path, canary: Path) -> Path:
    qualified = root / "qualification-source"
    qualified.mkdir()
    for source, name in ((phase7, "phase-7-verification.json"), (lock, "integration-lock.json"),
                         (canary, "host-canary.json")):
        shutil.copy2(source, qualified / name)
    shutil.copytree(stage, qualified / "stage")
    return qualified


def test_bundle_transfer_rechecks_digests_and_selects_explicit_files(tmp_path: Path) -> None:
    build, evidence, wheel = candidate(tmp_path)
    bundle = tmp_path / "upload"
    created = run("create", "--wheel", str(wheel), "--build-evidence", str(build),
                  "--candidate-evidence-root", str(evidence), "--output-root", str(bundle))
    assert created.returncode == 0, created.stderr
    downloaded = tmp_path / "download"
    downloaded.mkdir()
    for item in bundle.rglob("*"):
        target = downloaded / item.relative_to(bundle)
        if item.is_dir():
            target.mkdir(exist_ok=True)
        else:
            target.write_bytes(item.read_bytes())
    unrelated = downloaded / "dist/unrelated.whl"
    unrelated.write_bytes(b"must not publish")
    selected = tmp_path / "publish-files.txt"
    verified = run("verify", "--bundle-root", str(downloaded), "--files-output", str(selected))
    assert verified.returncode == 0, verified.stderr
    published = [Path(row) for row in selected.read_text().splitlines()]
    assert published == [downloaded / "dist" / wheel.name,
                         downloaded / "dist/academic_research_workbench-0.1.0.tar.gz"]
    assert unrelated not in published
    published[0].write_bytes(b"substituted after download")
    rejected = run("verify", "--bundle-root", str(downloaded))
    assert rejected.returncode != 0
    assert "digest mismatch" in rejected.stderr


def test_bundle_executable_permission_survives_archive_and_detects_chmod(tmp_path: Path) -> None:
    build, evidence, wheel = candidate(tmp_path)
    executable = evidence / "bin/qualified-tool"
    executable.parent.mkdir()
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    bundle = tmp_path / "bundle"
    created = run("create", "--wheel", str(wheel), "--build-evidence", str(build),
                  "--candidate-evidence-root", str(evidence), "--output-root", str(bundle))
    assert created.returncode == 0, created.stderr
    listed = bundle / "evidence/bin/qualified-tool"
    manifest = json.loads((bundle / "bundle-manifest.json").read_text())
    row = next(item for item in manifest["files"] if item["path"] == "evidence/bin/qualified-tool")
    assert row["executable_bits"] == 0o111
    listed.chmod(0o644)
    rejected = run("verify", "--bundle-root", str(bundle))
    assert rejected.returncode != 0
    assert "executable permission mismatch" in rejected.stderr
    archive = tmp_path / "bundle.tar.gz"
    rejected_archive = run("archive", "--bundle-root", str(bundle), "--output", str(archive))
    assert rejected_archive.returncode != 0
    assert not archive.exists()
    listed.chmod(0o755)
    archived = run("archive", "--bundle-root", str(bundle), "--output", str(archive))
    assert archived.returncode == 0, archived.stderr
    restored = tmp_path / "restored"
    extracted = run("extract", "--archive", str(archive), "--output-root", str(restored))
    assert extracted.returncode == 0, extracted.stderr
    restored_executable = restored / "evidence/bin/qualified-tool"
    assert stat.S_IMODE(restored_executable.stat().st_mode) == 0o755
    restored_executable.chmod(0o644)
    rejected_restored = run("verify", "--bundle-root", str(restored))
    assert rejected_restored.returncode != 0
    assert "executable permission mismatch" in rejected_restored.stderr


def test_bundle_rejects_missing_ambiguous_and_mismatched_inputs(tmp_path: Path) -> None:
    build, evidence, wheel = candidate(tmp_path)
    missing = run("create", "--wheel", str(tmp_path / "missing.whl"),
                  "--build-evidence", str(build), "--candidate-evidence-root", str(evidence),
                  "--output-root", str(tmp_path / "bundle"))
    assert missing.returncode != 0
    assert not (tmp_path / "bundle").exists()
    payload = json.loads(build.read_text())
    payload["artifacts"].append(dict(payload["artifacts"][0]))
    write(build, payload)
    ambiguous = run("create", "--wheel", str(wheel), "--build-evidence", str(build),
                    "--candidate-evidence-root", str(evidence), "--output-root", str(tmp_path / "bundle"))
    assert ambiguous.returncode != 0
    assert "duplicated" in ambiguous.stderr
    payload["artifacts"].pop()
    write(build, payload)
    wheel.write_bytes(b"wrong wheel")
    mismatch = run("create", "--wheel", str(wheel), "--build-evidence", str(build),
                   "--candidate-evidence-root", str(evidence), "--output-root", str(tmp_path / "bundle"))
    assert mismatch.returncode != 0
    assert "differs from build evidence" in mismatch.stderr
    assert not (tmp_path / "bundle").exists()


def test_publish_list_rejects_newline_artifact_and_root_paths(tmp_path: Path) -> None:
    build, evidence, wheel = candidate(tmp_path)
    payload = json.loads(build.read_text())
    payload["artifacts"][0]["path"] = f"dist/{wheel.name}\n/tmp/unlisted-secret.txt"
    write(build, payload)
    rejected = run("create", "--wheel", str(wheel), "--build-evidence", str(build),
                   "--candidate-evidence-root", str(evidence), "--output-root", str(tmp_path / "bundle"))
    assert rejected.returncode != 0
    assert "unsafe characters" in rejected.stderr
    assert not (tmp_path / "bundle").exists()

    build, evidence, wheel = candidate(tmp_path / "fresh")
    bundle = tmp_path / "bundle\n/tmp/second-upload.txt"
    created = run("create", "--wheel", str(wheel), "--build-evidence", str(build),
                  "--candidate-evidence-root", str(evidence), "--output-root", str(bundle))
    assert created.returncode == 0, created.stderr
    selected = tmp_path / "publish-files.txt"
    rejected = run("verify", "--bundle-root", str(bundle), "--files-output", str(selected))
    assert rejected.returncode != 0
    assert not selected.exists()


def test_changed_build_observations_cannot_reuse_gate_inventory(tmp_path: Path) -> None:
    build, evidence, wheel = candidate(tmp_path)
    payload = json.loads(build.read_text())
    payload["build"]["python"]["version"] = "3.99.0"
    payload["build"]["backend"]["version"] = "999.0"
    payload["build"]["inventory"] = [{"name": "hatchling", "version": "999.0", "license": "MIT", "installed_content_sha256": "2" * 64}]
    write(build, payload)
    rejected = run("verify-inputs", "--wheel", str(wheel), "--build-evidence", str(build),
                   "--candidate-evidence-root", str(evidence))
    assert rejected.returncode != 0
    assert "does not bind the supplied build evidence" in rejected.stderr


def test_technical_candidate_does_not_grant_human_or_host_release_approval(tmp_path: Path) -> None:
    build, evidence, wheel = candidate(tmp_path)
    bundle = tmp_path / "bundle"
    result = run("create", "--wheel", str(wheel), "--build-evidence", str(build),
                 "--candidate-evidence-root", str(evidence), "--output-root", str(bundle))
    assert result.returncode == 0, result.stderr
    checked = subprocess.run([sys.executable, str(RELEASE_CHECK), "--bundle-root", str(bundle),
                              "--source-commit", "a" * 40], text=True, capture_output=True, check=False)
    assert checked.returncode != 0
    assert "release blocked" in checked.stderr
    assert json.loads((bundle / "evidence/supply-chain/license-verdict.json").read_text())["release_qualification"] == "BLOCKED"


def test_forged_pass_receipts_and_text_wheel_cannot_grant_release(tmp_path: Path) -> None:
    build, evidence, wheel = candidate(tmp_path)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SCRIPT.parents[1], text=True).strip()
    build_payload = json.loads(build.read_text())
    build_payload["source_identity"]["git_commit"] = head
    write(build, build_payload)
    inventory = json.loads((evidence / "license-evidence/inventory.json").read_text())
    inventory["build_evidence"]["sha256"] = sha(build)
    write(evidence / "license-evidence/inventory.json", inventory)
    use = json.loads((evidence / "supply-chain/use-distribution.json").read_text())
    for key, status in (("intended_use", "declared"), ("distribution_class", "declared"),
                        ("accountable_approval", "approved")):
        use[key] = {"status": status}
    use["permission_references"] = ["self-reported-permission"]
    write(evidence / "supply-chain/use-distribution.json", use)
    write(evidence / "supply-chain/license-verdict.json", {
        "technical_qualification": "PASS", "release_qualification": "PASS",
    })
    stage = tmp_path / "stage"
    staged_wheel = stage / "share/arw/wheels" / wheel.name
    staged_wheel.parent.mkdir(parents=True)
    staged_wheel.write_bytes(wheel.read_bytes())
    staged_build = stage / "share/arw/evidence/candidate-build.json"
    staged_build.parent.mkdir(parents=True)
    staged_build.write_bytes(build.read_bytes())
    (stage / "share/arw/evidence/license-inventory.json").write_bytes(
        (evidence / "license-evidence/inventory.json").read_bytes()
    )
    lock, canary = tmp_path / "lock.json", tmp_path / "canary.json"
    lock.write_text("{}\n", encoding="utf-8")
    canary.write_text("{}\n", encoding="utf-8")
    canonical = runpy.run_path(str(SCRIPT.with_name("verify-phase-7")))["canonical"]
    stage_sha = hashlib.sha256(canonical(sorted((path.relative_to(stage).as_posix(), sha(path))
                                                 for path in stage.rglob("*") if path.is_file()))).hexdigest()
    phase7 = tmp_path / "phase7.json"
    write(phase7, {"git_head": head, "technical_qualification": "PASS",
                   "release_qualification": "PASS", "evidence_bound": True,
                   "stage": {"stage_sha256": stage_sha, "integration_lock_sha256": sha(lock),
                             "host_canary_sha256": sha(canary)}})
    bundle = tmp_path / "bundle"
    qualified = qualification_root(tmp_path, phase7, stage, lock, canary)
    created = run("create", "--wheel", str(wheel), "--build-evidence", str(build),
                  "--candidate-evidence-root", str(evidence), "--qualification-root", str(qualified),
                  "--output-root", str(bundle))
    assert created.returncode == 0, created.stderr
    checked = subprocess.run([sys.executable, str(RELEASE_CHECK), "--bundle-root", str(bundle),
                              "--source-commit", head], text=True, capture_output=True, check=False)
    assert checked.returncode != 0
    assert "candidate wheel or builder evidence failed source validation" in checked.stderr


def test_qualification_root_binds_the_candidate_without_granting_release(tmp_path: Path) -> None:
    build, evidence, wheel = candidate(tmp_path)
    stage = tmp_path / "qualified-stage"
    staged_wheel = stage / "share/arw/wheels" / wheel.name
    staged_wheel.parent.mkdir(parents=True)
    staged_wheel.write_bytes(wheel.read_bytes())
    staged_build = stage / "share/arw/evidence/candidate-build.json"
    staged_build.parent.mkdir(parents=True)
    staged_build.write_bytes(build.read_bytes())
    (staged_build.parent / "license-inventory.json").write_bytes((evidence / "license-evidence/inventory.json").read_bytes())
    for relative in (".codex-plugin/plugin.json", ".mcp.json", ".file-base/build-evidence.json"):
        hidden = stage / relative
        hidden.parent.mkdir(parents=True, exist_ok=True)
        hidden.write_text("{}\n", encoding="utf-8")
    executable = stage / "bin/arw"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    stage_rows = sorted((path.relative_to(stage).as_posix(), sha(path)) for path in stage.rglob("*") if path.is_file())
    phase7_canonical = runpy.run_path(str(SCRIPT.with_name("verify-phase-7")))["canonical"]
    stage_sha = hashlib.sha256(phase7_canonical(stage_rows)).hexdigest()
    lock = tmp_path / "integration-lock.json"
    canary = tmp_path / "host-canary.json"
    lock.write_text("{}\n", encoding="utf-8")
    canary.write_text("{}\n", encoding="utf-8")
    phase7 = tmp_path / "phase-7-verification.json"
    write(phase7, {
        "git_head": "a" * 40,
        "technical_qualification": "PASS",
        "release_qualification": "BLOCKED",
        "stage": {"stage_sha256": stage_sha, "integration_lock_sha256": sha(lock),
                  "host_canary_sha256": sha(canary)},
    })
    qualified = qualification_root(tmp_path, phase7, stage, lock, canary)
    arguments = ("create", "--wheel", str(wheel), "--build-evidence", str(build),
                 "--candidate-evidence-root", str(evidence), "--qualification-root", str(qualified),
                 "--output-root", str(tmp_path / "bundle"))
    created = run(*arguments)
    assert created.returncode == 0, created.stderr
    transferred = tmp_path / "bundle"
    assert run("verify", "--bundle-root", str(transferred)).returncode == 0
    archive = tmp_path / "bundle.tar.gz"
    assert run("archive", "--bundle-root", str(transferred), "--output", str(archive)).returncode == 0
    extracted = tmp_path / "extracted"
    unpacked = run("extract", "--archive", str(archive), "--output-root", str(extracted))
    assert unpacked.returncode == 0, unpacked.stderr
    assert run("verify", "--bundle-root", str(extracted)).returncode == 0
    tampered_inventory = extracted / "qualification/stage/share/arw/evidence/license-inventory.json"
    tampered = json.loads(tampered_inventory.read_text())
    tampered["build_evidence"]["sha256"] = "0" * 64
    write(tampered_inventory, tampered)
    manifest_path = extracted / "bundle-manifest.json"
    bundle_manifest = json.loads(manifest_path.read_text())
    inventory_row = next(row for row in bundle_manifest["files"]
                         if row["path"] == "qualification/stage/share/arw/evidence/license-inventory.json")
    inventory_row.update(size=tampered_inventory.stat().st_size, sha256=sha(tampered_inventory))
    write(manifest_path, bundle_manifest)
    rejected_inventory = run("verify", "--bundle-root", str(extracted))
    assert rejected_inventory.returncode != 0
    assert "license inventory does not bind original build evidence" in rejected_inventory.stderr
    for relative in (".codex-plugin/plugin.json", ".mcp.json", ".file-base/build-evidence.json"):
        assert (extracted / "qualification/stage" / relative).is_file()
    assert stat.S_IMODE((extracted / "qualification/stage/bin/arw").stat().st_mode) == 0o755
    rejected_release = subprocess.run(
        [sys.executable, str(RELEASE_CHECK), "--bundle-root", str(transferred),
         "--source-commit", "a" * 40], text=True, capture_output=True, check=False,
    )
    assert rejected_release.returncode != 0
    assert "release blocked" in rejected_release.stderr

    (transferred / "qualification/stage/share/arw/wheels" / wheel.name).write_bytes(b"substituted")
    changed = run("verify", "--bundle-root", str(transferred))
    assert changed.returncode != 0
    assert "digest mismatch" in changed.stderr

    phase7_payload = json.loads(phase7.read_text(encoding="utf-8"))
    phase7_payload["stage"]["stage_sha256"] = "0" * 64
    write(phase7, phase7_payload)
    shutil.copy2(phase7, qualified / "phase-7-verification.json")
    bad_arguments = list(arguments)
    bad_arguments[-1] = str(tmp_path / "bad-bundle")
    inconsistent = run(*bad_arguments)
    assert inconsistent.returncode != 0
    assert "does not bind the qualified stage" in inconsistent.stderr
    assert not (tmp_path / "bad-bundle").exists()


def test_explicit_phase7_inputs_must_be_complete(tmp_path: Path) -> None:
    build, evidence, wheel = candidate(tmp_path)
    result = run("create", "--wheel", str(wheel), "--build-evidence", str(build),
                 "--candidate-evidence-root", str(evidence),
                 "--phase7-verification", str(tmp_path / "phase7.json"),
                 "--output-root", str(tmp_path / "bundle"))
    assert result.returncode != 0
    assert "all required" in result.stderr
    assert not (tmp_path / "bundle").exists()


def test_explicit_canary_evidence_survives_archive_and_strict_validation(tmp_path: Path) -> None:
    unit = runpy.run_path(str(SCRIPT.parents[1] / "tests/unit/test_integration_lock.py"))
    host_root = tmp_path / "host"
    host_root.mkdir()
    paths = unit["integration_fixture"].__wrapped__(host_root)
    lock_model = unit["_build"](paths)
    stage = paths["stage"]
    build, evidence, wheel = candidate(tmp_path / "candidate")
    staged_wheel = stage / "share/arw/wheels" / wheel.name
    wheel.write_bytes(staged_wheel.read_bytes())
    build_payload = json.loads(build.read_text())
    build_payload["artifacts"][0].update(size=wheel.stat().st_size, sha256=sha(wheel))
    write(build, build_payload)
    sbom_path = evidence / "SBOM.cdx.json"
    sbom = json.loads(sbom_path.read_text())
    sbom["components"][0]["hashes"][0]["content"] = sha(wheel)
    write(sbom_path, sbom)
    use_path = evidence / "supply-chain/use-distribution.json"
    use = json.loads(use_path.read_text())
    use["evidence_hashes"][0]["sha256"] = sha(sbom_path)
    write(use_path, use)
    inventory_path = evidence / "license-evidence/inventory.json"
    inventory = json.loads(inventory_path.read_text())
    inventory["build_evidence"]["sha256"] = sha(build)
    inventory["first_party_wheel"]["sha256"] = sha(wheel)
    write(inventory_path, inventory)
    staged_build = stage / "share/arw/evidence/candidate-build.json"
    staged_build.parent.mkdir(parents=True, exist_ok=True)
    staged_build.write_bytes(build.read_bytes())
    (staged_build.parent / "license-inventory.json").write_bytes(inventory_path.read_bytes())
    unit["_refresh_canary_stage_identity"](paths)
    stage_rows = sorted((path.relative_to(stage).as_posix(), sha(path))
                        for path in stage.rglob("*") if path.is_file())
    phase7_canonical = runpy.run_path(str(SCRIPT.with_name("verify-phase-7")))["canonical"]
    lock_path = tmp_path / "integration-lock.json"
    lock_path.write_text("{}\n", encoding="utf-8")
    phase7 = tmp_path / "phase-7-verification.json"
    write(phase7, {"git_head": "a" * 40,
                   "stage": {"stage_sha256": hashlib.sha256(phase7_canonical(stage_rows)).hexdigest(),
                             "integration_lock_sha256": sha(lock_path),
                             "host_canary_sha256": sha(paths["canary"])}})
    arguments = ("create", "--wheel", str(wheel), "--build-evidence", str(build),
                 "--candidate-evidence-root", str(evidence), "--phase7-verification", str(phase7),
                 "--qualified-stage", str(stage), "--integration-lock", str(lock_path),
                 "--host-canary", str(paths["canary"]),
                 "--canary-evidence-root", str(paths["canary"].parent))
    missing_root = run(*arguments[:-2], "--output-root", str(tmp_path / "missing-root"))
    assert missing_root.returncode != 0
    assert "all required" in missing_root.stderr
    wrong_root = run(*arguments[:-1], str(tmp_path), "--output-root", str(tmp_path / "wrong-root"))
    assert wrong_root.returncode != 0
    assert "direct file" in wrong_root.stderr
    bundle = tmp_path / "bundle"
    created = run(*arguments, "--output-root", str(bundle))
    assert created.returncode == 0, created.stderr
    copied = {path.relative_to(bundle / "qualification").as_posix()
              for path in (bundle / "qualification").rglob("*") if path.is_file()}
    assert {"evidence-bundle.json", "fresh-home-1.json", "fresh-home-2.json",
            "fresh-home-3.json"} <= copied
    bundler = runpy.run_path(str(SCRIPT))
    expected_bound = {path.relative_to(paths["canary"].parent).as_posix()
                      for path in bundler["canary_bound_files"](paths["canary"].parent, paths["canary"])}
    expected_bound.remove(paths["canary"].name)
    expected_bound.add("host-canary.json")
    assert expected_bound <= copied
    assert len(expected_bound) == 11  # canary, bundle, three homes, five parity rows, official receipt
    unrelated = paths["canary"].parent / "unbound-secret.txt"
    unrelated.write_text("do not transfer", encoding="utf-8")
    another = tmp_path / "bundle-with-unrelated"
    assert run(*arguments, "--output-root", str(another)).returncode == 0
    assert not (another / "qualification/unbound-secret.txt").exists()
    evidence_bundle = paths["canary"].parent / "evidence-bundle.json"
    original_bundle = evidence_bundle.read_bytes()
    evidence_bundle.write_bytes(original_bundle + b" ")
    drifted = run(*arguments, "--output-root", str(tmp_path / "drifted"))
    assert drifted.returncode != 0
    assert "digest drift" in drifted.stderr
    evidence_bundle.write_bytes(original_bundle)
    from arw.kernel.core.canonical import canonical_json_bytes
    original_canary = paths["canary"].read_bytes()
    unsafe_canary = json.loads(original_canary)
    unsafe_canary["evidence_bundle"]["path"] = "../escape.json"
    paths["canary"].write_bytes(canonical_json_bytes(unsafe_canary))
    unsafe = run(*arguments, "--output-root", str(tmp_path / "unsafe"))
    assert unsafe.returncode != 0
    assert not (tmp_path / "unsafe").exists()
    paths["canary"].write_bytes(original_canary)
    archive = tmp_path / "bundle.tar.gz"
    assert run("archive", "--bundle-root", str(bundle), "--output", str(archive)).returncode == 0
    restored = tmp_path / "restored"
    extracted = run("extract", "--archive", str(archive), "--output-root", str(restored))
    assert extracted.returncode == 0, extracted.stderr
    assert expected_bound <= {path.relative_to(restored / "qualification").as_posix()
                              for path in (restored / "qualification").rglob("*") if path.is_file()}
    from arw.kernel.policy.integration_lock import _validate_hook
    _validate_hook(restored / "qualification/stage", restored / "qualification/host-canary.json",
                   lock_model.codex_host, lock_model.arw_runtime)
    bound_file = restored / "qualification/evidence-bundle.json"
    bound_file.unlink()
    rejected = run("verify", "--bundle-root", str(restored))
    assert rejected.returncode != 0


def test_release_rejects_uncommitted_candidate_source(tmp_path: Path) -> None:
    build, evidence, wheel = candidate(tmp_path)
    payload = json.loads(build.read_text())
    payload["source_identity"]["git_status"] = " M src/arw/changed.py"
    write(build, payload)
    inventory_path = evidence / "license-evidence/inventory.json"
    inventory = json.loads(inventory_path.read_text())
    inventory["build_evidence"]["sha256"] = sha(build)
    write(inventory_path, inventory)
    bundle = tmp_path / "bundle"
    result = run("create", "--wheel", str(wheel), "--build-evidence", str(build),
                 "--candidate-evidence-root", str(evidence), "--output-root", str(bundle))
    assert result.returncode == 0, result.stderr
    checked = subprocess.run([sys.executable, str(RELEASE_CHECK), "--bundle-root", str(bundle),
                              "--source-commit", "a" * 40], text=True, capture_output=True, check=False)
    assert checked.returncode != 0
    assert "uncommitted source tree" in checked.stderr
