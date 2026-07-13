from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_NAME = "academic-research-workbench"


def test_installed_version_reports_only_packaged_build_identity(tmp_path: Path) -> None:
    smoke_script = REPOSITORY_ROOT / "scripts/smoke-staged-plugin"
    stage_root = tmp_path / "stage" / PLUGIN_NAME
    evidence_root = tmp_path / "evidence"
    environment = {
        "HOME": str(tmp_path / "caller-home"),
        "CODEX_HOME": str(tmp_path / "caller-codex-home"),
        "PATH": os.environ["PATH"],
        "PIP_NO_INDEX": "1",
        "PYTHONNOUSERSITE": "1",
        "UV_OFFLINE": "1",
    }
    result = subprocess.run(
        [
            str(smoke_script),
            "--version",
            "--fresh-home",
            str(tmp_path / "installed-home"),
            "--evidence-root",
            str(evidence_root),
            str(stage_root),
        ],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    identity_path = stage_root / "share/arw/build-identity.json"
    identity_bytes = identity_path.read_bytes()
    identity = json.loads(identity_bytes)
    report = json.loads(
        (evidence_root / "plugin/version/report.json").read_text(encoding="utf-8")
    )
    version_schema = json.loads(
        (stage_root / "share/arw/schemas/version-report.schema.json").read_text(
            encoding="utf-8"
        )
    )
    build_schema = json.loads(
        (stage_root / "share/arw/schemas/build-identity.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.Draft202012Validator.check_schema(version_schema)
    jsonschema.Draft202012Validator(build_schema).validate(identity)
    schema_registry = Registry().with_resources(
        [
            (version_schema["$id"], Resource.from_contents(version_schema)),
            (build_schema["$id"], Resource.from_contents(build_schema)),
        ]
    )
    jsonschema.Draft202012Validator(version_schema, registry=schema_registry).validate(
        report
    )

    assert report["command"] == "version"
    assert report["identity"] == identity
    assert report["build_identity_sha256"] == hashlib.sha256(identity_bytes).hexdigest()
    assert report["identity"]["platform_claim"] == "linux"
    assert {item["id"] for item in identity["components"]} == {
        "academic-research-skills",
        "experiment-agent",
        "file-base",
    }
    assert set(identity["evidence"]) == {
        "pre_vendor",
        "legal",
        "upstream",
        "asan_ubsan",
        "tsan",
    }
    assert len(identity["schemas"]["files"]) == 12
    assert identity["staged_payloads"]

    inventory = json.loads(
        (stage_root / "supply-chain/stage-inventory.json").read_text(encoding="utf-8")
    )
    assert "share/arw/build-identity.json" in inventory["files"]
    assert all(
        entry["path"] != "share/arw/build-identity.json"
        for entry in identity["staged_payloads"]
    )


def test_identity_loader_rejects_tampered_packaged_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    smoke_script = REPOSITORY_ROOT / "scripts/smoke-staged-plugin"
    stage_root = tmp_path / "stage" / PLUGIN_NAME
    result = subprocess.run(
        [
            str(smoke_script),
            "--version",
            "--fresh-home",
            str(tmp_path / "installed-home"),
            "--evidence-root",
            str(tmp_path / "evidence"),
            str(stage_root),
        ],
        cwd=tmp_path,
        env={
            "HOME": str(tmp_path / "caller-home"),
            "CODEX_HOME": str(tmp_path / "caller-codex-home"),
            "PATH": os.environ["PATH"],
            "PIP_NO_INDEX": "1",
            "PYTHONNOUSERSITE": "1",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    from arw.build_identity import BuildIdentityError, load_packaged_build_identity

    schema = stage_root / "share/arw/schemas/build-identity.schema.json"
    schema.write_text(schema.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(stage_root))
    monkeypatch.setenv("ARW_BUILD_IDENTITY", str(stage_root / "share/arw/build-identity.json"))
    monkeypatch.setenv("ARW_SCHEMA_ROOT", str(stage_root / "share/arw/schemas"))
    with pytest.raises(BuildIdentityError, match="packaged schema digest mismatch"):
        load_packaged_build_identity()
