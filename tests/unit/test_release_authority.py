"""Independent authority rejects substitutions and unsigned historical records."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import runpy
import subprocess
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from arw.kernel.policy.release_authority import (
    PREDICATE_TYPE,
    ReleaseAuthorityError,
    validate_candidate_run,
    validate_dispatch,
    validate_verified_authority,
    verify_signature,
)


def run(*, authority: bool = False) -> dict:
    return {
        "id": 90 if authority else 80,
        "run_attempt": 1,
        "event": "workflow_dispatch" if authority else "push",
        "head_branch": "main", "head_sha": "a" * 40,
        "repository": {"full_name": "owner/repo"},
        "head_repository": {"full_name": "owner/repo"},
        "path": ".github/workflows/release-authority.yml" if authority else ".github/workflows/ci.yml",
        "status": "completed", "conclusion": "success",
        "actor": {"login": "owner", "id": 7},
        "triggering_actor": {"login": "owner", "id": 7},
    }


def predicate() -> dict:
    return {
        "schema_version": "1.0.0", "repository": "owner/repo",
        "source_commit": "a" * 40, "source_ref": "refs/heads/main",
        "release_tag": "v0.2.0", "release_version": "0.2.0",
        "candidate_run_id": 80, "candidate_artifact_id": 81,
        "candidate_artifact_name": "candidate-a", "candidate_artifact_digest": "sha256:" + "b" * 64,
        "qualification_release_id": 92, "qualification_asset_id": 93,
        "qualification_asset_name": "arw-qualified-candidate-v0.2.0.tar.gz",
        "qualification_asset_digest": "sha256:" + "2" * 64,
        "bundle_manifest_sha256": "c" * 64,
        "wheel_sha256": "d" * 64, "sdist_sha256": "e" * 64, "sbom_sha256": "f" * 64,
        "source_manifest_sha256": "1" * 64,
        "permission_basis": "pinned-existing-component-licenses",
        "intended_use": "noncommercial-academic-research", "distribution_class": "public",
        "actor": "owner", "actor_id": 7, "authority_run_id": 90, "authority_run_attempt": 1,
    }


def rows(value: dict) -> list:
    return [{"verificationResult": {"statement": {
        "predicateType": PREDICATE_TYPE,
        "subject": [{"name": "bundle-manifest.json", "digest": {"sha256": "c" * 64}}],
        "predicate": value,
    }}}]


def expected() -> dict:
    return {k: v for k, v in predicate().items() if k not in {
        "actor", "actor_id", "authority_run_id", "authority_run_attempt",
        "intended_use", "distribution_class", "permission_basis",
    }}


def test_exact_verified_authority() -> None:
    assert validate_verified_authority(rows(predicate()), expected(), run(authority=True)).actor == "owner"


@pytest.mark.parametrize("key,value", [
    ("repository", "attacker/repo"), ("source_commit", "b" * 40),
    ("source_ref", "refs/tags/v0.2.0"), ("release_tag", "v0.2.1"),
    ("release_version", "0.2.1"), ("candidate_run_id", 82),
    ("candidate_artifact_id", 82), ("candidate_artifact_name", "other"),
    ("candidate_artifact_digest", "sha256:" + "0" * 64),
    ("qualification_release_id", 94), ("qualification_asset_id", 94),
    ("qualification_asset_name", "arw-qualified-candidate-v0.2.1.tar.gz"),
    ("qualification_asset_digest", "sha256:" + "0" * 64),
    ("wheel_sha256", "0" * 64), ("sdist_sha256", "0" * 64),
    ("sbom_sha256", "0" * 64), ("bundle_manifest_sha256", "0" * 64),
    ("source_manifest_sha256", "0" * 64), ("actor", "attacker"),
    ("actor_id", 8), ("authority_run_id", 91), ("authority_run_attempt", 2),
    ("intended_use", "commercial"), ("permission_basis", "owner-said-PASS"),
    ("distribution_class", "unknown"),
])
def test_substitution_and_replay_fail(key: str, value: object) -> None:
    changed = {**predicate(), key: value}
    with pytest.raises(ReleaseAuthorityError):
        validate_verified_authority(rows(changed), expected(), run(authority=True))


@pytest.mark.parametrize("change", [[], rows({"accountable_approval": {"status": "approved"}})])
def test_missing_or_historical_authority_fails(change: list) -> None:
    with pytest.raises(ReleaseAuthorityError):
        validate_verified_authority(change, expected(), run(authority=True))


def test_wrong_subject_and_predicate_fail() -> None:
    for key in ("predicateType", "subject"):
        changed = rows(predicate())
        changed[0]["verificationResult"]["statement"][key] = "wrong"
        with pytest.raises(ReleaseAuthorityError):
            validate_verified_authority(changed, expected(), run(authority=True))


@pytest.mark.parametrize("key,value", [("event", "pull_request"), ("head_branch", "topic"),
    ("head_sha", "b" * 40), ("conclusion", "failure"), ("path", ".github/workflows/other.yml"),
    ("repository", {"full_name": "other/repo"}), ("head_repository", {"full_name": "other/repo"})])
def test_candidate_github_provenance_rejected(key: str, value: object) -> None:
    with pytest.raises(ReleaseAuthorityError):
        validate_candidate_run({**run(), key: value}, "owner/repo", "a" * 40, 80)


def test_actual_dispatch_actor_checked_and_rerun_rejected() -> None:
    for changed in ({"actor": {"login": "other", "id": 8}},
                    {"triggering_actor": {"login": "other", "id": 8}},
                    {"run_attempt": 2}, {"event": "push"}):
        with pytest.raises(ReleaseAuthorityError):
            validate_dispatch({**run(authority=True), **changed}, "owner/repo", "a" * 40)


@pytest.mark.parametrize("key", ["permission_basis", "intended_use", "distribution_class", "actor_id"])
def test_absent_accountable_declaration_fails(key: str) -> None:
    value = predicate()
    del value[key]
    with pytest.raises(ReleaseAuthorityError):
        validate_verified_authority(rows(value), expected(), run(authority=True))


def test_schema_drift_unknown_fields_and_strict_identity() -> None:
    import jsonschema

    from arw.kernel.policy.release_authority import release_authority_schema_document
    root = Path(__file__).resolve().parents[2]
    schema = json.loads((root / "schemas/v1/release-authority.schema.json").read_text())
    assert schema == release_authority_schema_document()
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(predicate())
    from arw.kernel.policy.schema_registry import (
        QUALIFICATION_SCHEMA_NAMES,
        SchemaRegistryError,
        validate_schema_document,
    )
    assert "release-authority.schema.json" in QUALIFICATION_SCHEMA_NAMES
    validate_schema_document("release-authority.schema.json", schema)
    changed = copy.deepcopy(schema)
    changed["properties"]["intended_use"]["const"] = "commercial"
    with pytest.raises(SchemaRegistryError, match="model projection"):
        validate_schema_document("release-authority.schema.json", changed)
    for changed in ({"authority_run_attempt": True}, {"actor_id": "7"}, {"PASS": True}):
        with pytest.raises(ReleaseAuthorityError):
            validate_verified_authority(rows({**predicate(), **changed}), expected(), run(authority=True))


def test_signature_command_is_executed_with_exact_trust_constraints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    def verifier(command: list, **kwargs: object) -> subprocess.CompletedProcess:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, json.dumps(rows(predicate())), "")
    monkeypatch.setattr(subprocess, "run", verifier)
    subject = tmp_path / "bundle-manifest.json"
    verify_signature(subject, "owner/repo", "a" * 40)
    command = calls[0]
    for flag, value in {"--repo": "owner/repo", "--source-ref": "refs/heads/main",
            "--source-digest": "a" * 40, "--signer-digest": "a" * 40,
            "--cert-identity": "https://github.com/owner/repo/.github/workflows/release-authority.yml@refs/heads/main",
            "--predicate-type": PREDICATE_TYPE}.items():
        assert command[command.index(flag) + 1] == value
    def missing(command: list, **kwargs: object) -> subprocess.CompletedProcess:
        raise subprocess.CalledProcessError(1, command, stderr="no signature")
    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(ReleaseAuthorityError, match="signature"):
        verify_signature(subject, "owner/repo", "a" * 40)


@pytest.fixture
def transfer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict, argparse.Namespace, dict]:
    root = Path(__file__).resolve().parents[2]
    module = runpy.run_path(str(root / "scripts/release-authority"))
    namespace = module["candidate_identity"].__globals__
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    args = argparse.Namespace(repository="owner/repo", source_commit="a" * 40,
        candidate_run_id=80, candidate_artifact_name="candidate-a", release_tag=f"v{version}",
        bundle_root=tmp_path / "qualified", ci_bundle_root=tmp_path / "ci",
        qualification_archive=tmp_path / "qualified.tar.gz")
    args.qualification_archive.write_bytes(b"exact qualified archive")
    checksum = lambda value: hashlib.sha256(value).hexdigest()
    for bundle in (args.bundle_root, args.ci_bundle_root):
        (bundle / "dist").mkdir(parents=True)
        (bundle / "evidence").mkdir()
        items = []
        for kind, name in (("wheel", "wheel.whl"), ("sdist", "source.tar.gz")):
            value = kind.encode()
            (bundle / "dist" / name).write_bytes(value)
            items.append({"kind": kind, "path": f"dist/{name}", "sha256": checksum(value)})
        (bundle / "build-evidence.json").write_text(json.dumps({
            "source_identity": {"git_commit": "a" * 40, "git_status": ""}, "artifacts": items}))
        (bundle / "evidence/SBOM.cdx.json").write_text('{}')
        (bundle / "bundle-manifest.json").write_text('{}')
    artifact = {"id": 81, "name": "candidate-a", "expired": False,
        "digest": "sha256:" + "b" * 64, "workflow_run": {
            "id": 80, "head_sha": "a" * 40, "head_branch": "main"}}
    release = {"id": 92, "draft": True, "tag_name": args.release_tag,
        "target_commitish": "a" * 40, "assets": [{"id": 93, "state": "uploaded",
            "name": f"arw-qualified-candidate-{args.release_tag}.tar.gz",
            "digest": "sha256:" + checksum(args.qualification_archive.read_bytes())}]}
    def github(endpoint: str, **kwargs: object) -> object:
        if "/releases/" in endpoint:
            return copy.deepcopy(release)
        if "/artifacts?" in endpoint:
            return [{"artifacts": [artifact]}]
        return run()
    monkeypatch.setitem(namespace, "api", github)
    monkeypatch.setitem(namespace, "validate_permission_basis", lambda bundle: None)
    return module, args, {"artifact": artifact, "release": release}


def test_transfer_binds_actual_github_ids_and_exact_subjects(transfer: tuple) -> None:
    module, args, api = transfer
    expected = module["candidate_identity"](args)
    assert expected["candidate_artifact_id"] == api["artifact"]["id"]
    assert expected["qualification_release_id"] == api["release"]["id"]
    assert expected["qualification_asset_id"] == api["release"]["assets"][0]["id"]


@pytest.mark.parametrize("mutation", ["published", "source", "asset-digest", "expired-ci",
    "wrong-ci-run", "ci-sbom", "ci-wheel", "build-evidence"])
def test_live_transfer_substitutions_fail(transfer: tuple, mutation: str) -> None:
    module, args, api = transfer
    if mutation == "published":
        api["release"]["draft"] = False
    elif mutation == "source":
        api["release"]["target_commitish"] = "main"
    elif mutation == "asset-digest":
        api["release"]["assets"][0]["digest"] = "sha256:" + "0" * 64
    elif mutation == "expired-ci":
        api["artifact"]["expired"] = True
    elif mutation == "wrong-ci-run":
        api["artifact"]["workflow_run"]["id"] = 82
    elif mutation == "ci-sbom":
        (args.ci_bundle_root / "evidence/SBOM.cdx.json").write_text('{"substituted":true}')
    elif mutation == "ci-wheel":
        (args.ci_bundle_root / "dist/wheel.whl").write_bytes(b"other wheel")
    else:
        build = args.bundle_root / "build-evidence.json"
        build.write_text(build.read_text() + "\n")
    with pytest.raises(ReleaseAuthorityError):
        module["candidate_identity"](args)


@pytest.mark.parametrize("mutation", ["none", "missing-license", "wrong-license", "unsupported-basis"])
def test_permission_basis_verifies_pinned_license_bytes(tmp_path: Path, mutation: str) -> None:
    root = Path(__file__).resolve().parents[2]
    module = runpy.run_path(str(root / "scripts/release-authority"))
    manifest = json.loads((root / "vendor/source-manifest.json").read_text())
    rows = []
    evidence = tmp_path / "evidence"
    (evidence / "supply-chain").mkdir(parents=True)
    (evidence / "LICENSES").mkdir()
    for component in manifest["components"]:
        license = component["licenses"][0]
        relative = f"LICENSES/{component['id']}.txt"
        (evidence / relative).write_bytes((root / license["path"]).read_bytes())
        rows.append({"component_id": component["id"], "license": license["spdx"],
            "source_path": license["path"], "source_sha256": license["sha256"],
            "staged_path": relative, "staged_sha256": license["sha256"]})
    if mutation == "missing-license":
        (evidence / rows[0]["staged_path"]).unlink()
    elif mutation == "wrong-license":
        (evidence / rows[0]["staged_path"]).write_text("permission granted by a local PASS")
    elif mutation == "unsupported-basis":
        rows[0]["license"] = "MIT"
    (evidence / "supply-chain/license-verdict.json").write_text(json.dumps({"components": rows}))
    if mutation == "none":
        module["validate_permission_basis"](tmp_path)
    else:
        with pytest.raises(ReleaseAuthorityError):
            module["validate_permission_basis"](tmp_path)


@pytest.mark.parametrize("mutation", ["none", "identical-retry", "unrelated", "conflicting", "live-identity"])
def test_publish_existing_draft_uses_verified_bytes_and_exact_ids(transfer: tuple,
        monkeypatch: pytest.MonkeyPatch, mutation: str) -> None:
    authority, args, api = transfer
    root = Path(__file__).resolve().parents[2]
    publisher = runpy.run_path(str(root / "scripts/publish-verified-draft"))
    namespace = publisher["main"].__globals__
    monkeypatch.setitem(namespace, "runpy", SimpleNamespace(run_path=lambda path: authority))
    paths = [args.bundle_root / "dist/wheel.whl", args.bundle_root / "dist/source.tar.gz"]
    files = args.bundle_root / "publish-files.txt"
    files.write_text("\n".join(str(path) for path in paths) + "\n")
    monkeypatch.setattr("sys.argv", ["publish-verified-draft", "--repository", args.repository,
        "--release-tag", args.release_tag, "--source-commit", args.source_commit,
        "--qualification-archive", str(args.qualification_archive), "--files-list", str(files)])
    if mutation in ("identical-retry", "conflicting", "unrelated"):
        api["release"]["assets"].append({"id": 100, "state": "uploaded",
            "name": "unexpected.bin" if mutation == "unrelated" else paths[0].name,
            "digest": "sha256:" + ("0" * 64 if mutation == "conflicting"
                else hashlib.sha256(paths[0].read_bytes()).hexdigest())})
    calls = []
    def github(command: list, **kwargs: object) -> subprocess.CompletedProcess:
        calls.append(command)
        method = command[command.index("--method") + 1]
        if method == "POST":
            assert "/releases/92/assets?" in command[command.index("-H") + 2]
            path = Path(command[command.index("--input") + 1])
            row = {"id": len(calls) + 100, "name": path.name, "state": "uploaded",
                   "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()}
            api["release"]["assets"].append(row)
            if mutation == "live-identity":
                api["release"]["assets"][0]["id"] = 94
        elif method == "DELETE":
            assert command[-1] == "repos/owner/repo/releases/assets/93"
            api["release"]["assets"] = [row for row in api["release"]["assets"] if row["id"] != 93]
            row = {}
        else:
            assert method == "PATCH" and "repos/owner/repo/releases/92" in command
            assert command[-2:] == ["-F", "draft=false"]
            api["release"].update({"draft": False, "html_url": "https://github.com/owner/repo/releases/tag/" + args.release_tag})
            row = api["release"]
        return subprocess.CompletedProcess(command, 0, json.dumps(row), "")
    monkeypatch.setattr(subprocess, "run", github)
    if mutation in ("unrelated", "conflicting", "live-identity"):
        with pytest.raises(ValueError):
            publisher["main"]()
        assert api["release"]["draft"] is True
        assert not any(command[command.index("--method") + 1] in ("DELETE", "PATCH") for command in calls)
    else:
        publisher["main"]()
        assert api["release"]["draft"] is False
        assert {row["name"] for row in api["release"]["assets"]} == {path.name for path in paths}
        assert len([command for command in calls if "POST" in command]) == (1 if mutation == "identical-retry" else 2)
