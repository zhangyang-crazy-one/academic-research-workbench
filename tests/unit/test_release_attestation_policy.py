"""Offline checks for release provenance and open dependency update policy."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

from packaging.requirements import Requirement
import yaml
ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"
ARTIFACT_SUBJECTS = {"dist/*.whl", "dist/*.tar.gz"}
SBOM_SUBJECT = "evidence/SBOM.cdx.json"
SLSA = "https://slsa.dev/provenance/v1"
CYCLONEDX = "https://cyclonedx.org/bom"


def _yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    def _stringify(obj: object) -> object:
        if isinstance(obj, dict):
            res = {}
            for k, v in obj.items():
                key = "on" if k is True else str(k)
                res[key] = _stringify(v)
            return res
        if isinstance(obj, list):
            return [_stringify(v) for v in obj]
        if isinstance(obj, bool):
            return "true" if obj else "false"
        if isinstance(obj, (int, float)):
            return str(obj)
        return obj

    result = _stringify(data)
    assert isinstance(result, dict)
    return result


def _step(steps: list[dict], name: str) -> dict:
    return next(step for step in steps if step.get("name") == name)


def test_ci_attests_only_successful_main_candidate_and_python_validation() -> None:
    ci = _yaml(WORKFLOWS / "ci.yml")
    assert ci["permissions"] == {"contents": "read"}
    assert ci["on"]["push"]["branches"] == ["main"]
    job = ci["jobs"]["attest-candidate"]
    assert set(job["needs"]) == {"package-boundary", "python"}
    condition = job["if"]
    assert "github.event_name == 'push'" in condition
    assert "github.ref == 'refs/heads/main'" in condition
    assert job["permissions"] == {
        "actions": "read",
        "artifact-metadata": "write",
        "attestations": "write",
        "contents": "read",
        "id-token": "write",
    }
    for name, other in ci["jobs"].items():
        if name != "attest-candidate":
            assert all(
                value != "write"
                for value in other.get("permissions", ci["permissions"]).values()
            )
    steps = job["steps"]
    download = next(
        step
        for step in steps
        if step.get("uses", "").startswith("actions/download-artifact@")
    )
    assert (
        download["with"]["name"] == "academic-research-workbench-ci-${{ github.sha }}"
    )
    assert "run-id" not in download["with"]
    verify = _step(steps, "Extract and verify same-run candidate bundle")
    assert "scripts/candidate-bundle extract" in verify["run"]
    assert "scripts/candidate-bundle verify" in verify["run"]
    assert "GITHUB_SHA" in verify["run"]
    assert "git_status" in verify["run"]
    provenance = _step(steps, "Attest candidate wheel, sdist and SBOM file provenance")
    sbom = _step(steps, "Attest CycloneDX SBOM for wheel and sdist")
    assert steps.index(verify) < steps.index(provenance) < steps.index(sbom)
    assert provenance["uses"] == sbom["uses"] == "actions/attest@v4"
    assert "sbom-path" not in provenance["with"]
    provenance_paths = provenance["with"]["subject-path"].splitlines()
    assert {path.removeprefix("candidate-bundle/") for path in provenance_paths} == {
        *ARTIFACT_SUBJECTS,
        SBOM_SUBJECT,
    }
    assert len(provenance_paths) == 3
    assert sbom["with"]["sbom-path"] == f"candidate-bundle/{SBOM_SUBJECT}"
    sbom_paths = sbom["with"]["subject-path"].splitlines()
    assert {
        path.removeprefix("candidate-bundle/") for path in sbom_paths
    } == ARTIFACT_SUBJECTS
    assert len(sbom_paths) == 2
    assert steps.index(sbom) == len(steps) - 1
    assert [step for step in steps if "run" in step] == [verify]
    assert all("working-directory" not in step for step in steps)


def test_release_qualification_verifies_every_subject_before_transfer() -> None:
    release = _yaml(WORKFLOWS / "release.yml")
    assert all(value == "read" for value in release["permissions"].values())
    qualify = release["jobs"]["qualify"]
    assert qualify["permissions"] == {
        "actions": "read",
        "attestations": "read",
        "contents": "read",
    }
    assert release["jobs"]["publish"]["needs"] == "qualify"
    assert release["jobs"]["publish"]["permissions"] == {"contents": "write"}
    steps = qualify["steps"]
    verify = _step(steps, "Verify artifact attestations for exact candidate subjects")
    script = verify["run"]
    for flag in (
        "--repo",
        "--signer-workflow",
        "--source-ref",
        "--source-digest",
        "--predicate-type",
        "--format",
        "json",
    ):
        assert flag in script
    assert "refs/heads/main" in script
    assert ".github/workflows/ci.yml" in script
    assert "sha256" in script
    assert SLSA in script and CYCLONEDX in script
    assert "predicateType" in script and "predicate" in script
    assert (
        "wheel" in script and "sdist" in script and "evidence/SBOM.cdx.json" in script
    )
    assert "check=True" in script
    assert steps.index(verify) > steps.index(
        _step(steps, "Verify downloaded candidate bytes")
    )
    assert steps.index(verify) < steps.index(
        _step(steps, "Verify candidate release authority")
    )
    assert steps.index(verify) < steps.index(
        _step(steps, "Archive exact verified candidate files with executable modes")
    )
    assert (
        "scripts/check-release-candidate"
        in _step(steps, "Verify candidate release authority")["run"]
    )
    assert (
        "scripts/candidate-bundle verify"
        in _step(steps, "Verify downloaded candidate bytes")["run"]
    )


def test_verifier_fails_closed_on_missing_or_mismatched_predicates(
    tmp_path: Path,
) -> None:
    steps = _yaml(WORKFLOWS / "release.yml")["jobs"]["qualify"]["steps"]
    script = _step(steps, "Verify artifact attestations for exact candidate subjects")[
        "run"
    ]
    root = tmp_path / "candidate-bundle"
    (root / "dist").mkdir(parents=True)
    (root / "evidence").mkdir()
    (root / "dist/wheel.whl").write_bytes(b"wheel")
    (root / "dist/source.tar.gz").write_bytes(b"source")
    (root / "evidence/SBOM.cdx.json").write_text(
        json.dumps({"bomFormat": "CycloneDX", "components": []}), encoding="utf-8"
    )
    (root / "build-evidence.json").write_text(
        json.dumps(
            {
                "source_identity": {"git_commit": "a" * 40},
                "artifacts": [
                    {"kind": "wheel", "path": "dist/wheel.whl"},
                    {"kind": "sdist", "path": "dist/source.tar.gz"},
                ],
            }
        ),
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_gh = bin_dir / "gh"
    fake_gh.write_text(
        f"#!{sys.executable}\n"
        "import hashlib, json, os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "assert args[:2] == ['attestation', 'verify']\n"
        "assert args[args.index('--repo') + 1] == 'owner/repo'\n"
        "assert args[args.index('--signer-workflow') + 1] == 'owner/repo/.github/workflows/ci.yml'\n"
        "assert args[args.index('--source-ref') + 1] == 'refs/heads/main'\n"
        "assert args[args.index('--source-digest') + 1] == 'a' * 40\n"
        "predicate_type = args[args.index('--predicate-type') + 1]\n"
        f"assert predicate_type in ({SLSA!r}, {CYCLONEDX!r})\n"
        "path = pathlib.Path(args[2])\n"
        "with open(os.environ['FAKE_CALLS'], 'a') as calls: "
        "calls.write(json.dumps([path.name, predicate_type]) + '\\n')\n"
        "digest = hashlib.sha256(path.read_bytes()).hexdigest()\n"
        "broken_type = os.environ['FAKE_BROKEN_TYPE']\n"
        "broken_kind = os.environ['FAKE_BROKEN_KIND']\n"
        "broken = predicate_type == broken_type and path.name == os.environ['FAKE_BROKEN_NAME']\n"
        "if broken and broken_kind == 'missing':\n"
        "    print('[]'); sys.exit(0)\n"
        "if broken and broken_kind == 'digest': digest = '0' * 64\n"
        "sbom = json.loads(pathlib.Path('candidate-bundle/evidence/SBOM.cdx.json').read_text())\n"
        "if broken and broken_kind == 'content': sbom['components'] = ['wrong']\n"
        "statement = {'predicateType': predicate_type, 'subject': "
        "[{'name': path.name, 'digest': {'sha256': digest}}], "
        "'predicate': sbom if predicate_type.endswith('/bom') else {}}\n"
        "print(json.dumps([{'verificationResult': {'statement': statement}}]))\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    fake_git = bin_dir / "git"
    fake_git.write_text("#!/bin/sh\nprintf '%040d\\n' 0 | tr 0 a\n", encoding="utf-8")
    fake_git.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "GITHUB_REPOSITORY": "owner/repo",
            "RELEASE_TAG": "v1.2.3",
            "FAKE_CALLS": str(tmp_path / "calls.jsonl"),
        }
    )
    cases = (
        ("", "", "", True),
        (SLSA, "wheel.whl", "missing", False),
        (SLSA, "source.tar.gz", "digest", False),
        (SLSA, "SBOM.cdx.json", "missing", False),
        (CYCLONEDX, "wheel.whl", "missing", False),
        (CYCLONEDX, "source.tar.gz", "digest", False),
        (CYCLONEDX, "wheel.whl", "content", False),
    )
    for broken_type, broken_name, broken_kind, expected_success in cases:
        env["FAKE_BROKEN_TYPE"] = broken_type
        env["FAKE_BROKEN_NAME"] = broken_name
        env["FAKE_BROKEN_KIND"] = broken_kind
        Path(env["FAKE_CALLS"]).write_text("", encoding="utf-8")
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", script],
            cwd=tmp_path,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert (result.returncode == 0) == expected_success, (
            broken_type,
            broken_name,
            broken_kind,
            result.stdout,
            result.stderr,
        )
        if expected_success:
            calls = [
                json.loads(line)
                for line in Path(env["FAKE_CALLS"]).read_text().splitlines()
            ]
            assert {tuple(call) for call in calls} == {
                ("wheel.whl", SLSA),
                ("wheel.whl", CYCLONEDX),
                ("source.tar.gz", SLSA),
                ("source.tar.gz", CYCLONEDX),
                ("SBOM.cdx.json", SLSA),
            }
            assert len(calls) == 5


def test_dependabot_and_dependency_ranges_are_lock_free() -> None:
    policy = _yaml(ROOT / ".github/dependabot.yml")
    assert policy["version"] == "2"
    updates = policy["updates"]
    assert {item["package-ecosystem"] for item in updates} == {"github-actions", "pip"}
    assert all(
        item["directory"] == "/"
        and item["schedule"]["interval"] == "weekly"
        and item["groups"]
        for item in updates
    )
    pip = next(item for item in updates if item["package-ecosystem"] == "pip")
    actions = next(
        item for item in updates if item["package-ecosystem"] == "github-actions"
    )
    assert pip["versioning-strategy"] == "increase"
    assert "versioning-strategy" not in actions
    assert all(
        group["patterns"] == ["*"]
        for item in updates
        for group in item["groups"].values()
    )
    assert not any(
        (ROOT / name).exists()
        for name in ("uv.lock", "poetry.lock", "Pipfile.lock", "requirements.txt")
    )
    with (ROOT / "pyproject.toml").open("rb") as source:
        project = tomllib.load(source)
    requirements = [
        *project["build-system"]["requires"],
        *project["project"]["dependencies"],
    ]
    for group in project["project"].get("optional-dependencies", {}).values():
        requirements.extend(group)
    for group in project.get("dependency-groups", {}).values():
        requirements.extend(group)
    assert all(
        {str(spec)[:2] for spec in Requirement(item).specifier} == {">="}
        for item in requirements
    )


def test_workflows_keep_major_tags_credentials_off_and_cache_off() -> None:
    for name in ("ci.yml", "release.yml"):
        workflow = _yaml(WORKFLOWS / name)
        for job in workflow["jobs"].values():
            for step in job["steps"]:
                action = step.get("uses")
                if action:
                    assert action.rsplit("@", 1)[-1].startswith("v")
                    assert action.rsplit("@", 1)[-1][1:].isdigit()
                    assert "/cache@" not in action
                    if action.startswith("actions/checkout@"):
                        assert step["with"]["persist-credentials"] == "false"
                    if action.startswith("astral-sh/setup-uv@"):
                        assert step["with"]["enable-cache"] == "false"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    release_section = readme.split("## Release boundary", 1)[1]
    assert "gh attestation verify" in release_section
    assert "--source-digest" in release_section
    assert SLSA in release_section and CYCLONEDX in release_section
    assert "scientific validity" in release_section
    assert "human authorship" in release_section
