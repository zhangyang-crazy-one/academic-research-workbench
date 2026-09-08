"""Public parser/dispatch and capability activation for artifact commands."""

import json

import pytest

from arw.cli import main
from arw.composition import default_router
from arw.kernel.capabilities import CapabilityUnavailable
from tests.integration.test_artifact_sanitize import setup_run


def test_inspection_is_public_versioned_json(tmp_path, capsys):
    source = tmp_path / "paper.md"
    source.write_text("中文\u200b x=3 [@key]", encoding="utf-8")
    before = source.read_bytes()
    assert (
        main(["artifact", "inspect", "--root", str(tmp_path), "--path", source.name])
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["schema_version"] == "arw.artifact-inspection.v1"
    assert result["total_findings"] == 1 and source.read_bytes() == before


def test_clean_and_binary_and_unknown_detector(tmp_path, capsys):
    source = tmp_path / "paper"
    for content, exit_code, status in [
        (b"plain", 0, "inspected"),
        (b"%PDF-1.7", 65, "unsupported"),
    ]:
        source.write_bytes(content)
        assert (
            main(
                [
                    "artifact",
                    "inspect",
                    "--root",
                    str(tmp_path),
                    "--path",
                    source.name,
                    "--detector",
                    "unqualified",
                ]
            )
            == exit_code
        )
        result = json.loads(capsys.readouterr().out)
        assert result["status"] == status
        assert result["detectors"]["unqualified"]["status"] == "unsupported"


def test_public_sanitize_and_missing_authorization(tmp_path, capsys):
    root, _source, request = setup_run(tmp_path)
    request_path = tmp_path / "request.json"
    request_path.write_text(request.model_dump_json())
    args = [
        "artifact",
        "sanitize",
        "--root",
        str(root),
        "--path",
        "source.txt",
        "--run-root",
        str(root),
        "--request",
        str(request_path),
        "--remove-codepoint",
        "U+200B",
    ]
    assert main(args) == 65
    assert (
        json.loads(capsys.readouterr().out)["reason_code"]
        == "privacy_authorization_required"
    )
    assert main(args + ["--privacy"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["accepted"] and (root / result["export_path"]).is_file()
    assert main(args + ["--privacy", "--strip-provenance"]) == 65
    assert json.loads(capsys.readouterr().out)["reason_code"] == "unsupported_treatment"


def test_manifest_gates_both_capabilities(tmp_path, monkeypatch, capsys):
    manifest = tmp_path / "plugin.json"
    manifest.write_text('{"interface":{"capabilities":[]}}')
    monkeypatch.setenv("ARW_PLUGIN_MANIFEST", str(manifest))
    for capability in ("artifact.inspect", "artifact.sanitize"):
        with pytest.raises(CapabilityUnavailable):
            default_router(plugin_manifest=manifest).resolve(capability)
    assert (
        main(["artifact", "inspect", "--root", str(tmp_path), "--path", "absent"]) == 65
    )
    assert json.loads(capsys.readouterr().out)["status"] == "unavailable"


def test_installed_missing_manifest_fails_closed(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ARW_PLUGIN_MANIFEST", raising=False)
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(tmp_path))
    assert (
        main(["artifact", "inspect", "--root", str(tmp_path), "--path", "absent"]) == 65
    )
    assert (
        json.loads(capsys.readouterr().out)["reason_code"] == "plugin_manifest_missing"
    )


def test_invalid_request_and_confined_path_return_json(tmp_path, capsys):
    assert (
        main(["artifact", "inspect", "--root", str(tmp_path), "--path", "../outside"])
        == 65
    )
    assert json.loads(capsys.readouterr().out)["reason_code"] == "invalid_relative_path"


def test_legacy_evaluate_surface_is_preserved():
    from arw.adapters.artifacts import ArtifactIntegrityAdapter

    provider = default_router().resolve("artifact.inspect")
    assert isinstance(provider, ArtifactIntegrityAdapter)
    assert callable(provider.evaluate)
