"""Pinned offline model identity and refusal cases without downloading weights."""

import hashlib
from pathlib import Path

from arw_writing import gpt2_preset
from arw_writing.detection import detect
from arw_writing.service import WritingAuditService


def test_preset_requires_explicit_local_model():
    result = detect(
        "A public English example.",
        {"detectors": [{"backend": "openai_gpt2_detector_local"}]},
    )[0]
    assert result["kind"] == "classification"
    assert result["status"] == "not_run" and result["score"] is None
    assert result["version"] == gpt2_preset.REVISION
    assert (
        result["parameters"]["model_file_sha256"]["model.safetensors"]
        == gpt2_preset.FILES["model.safetensors"]
    )


def test_preset_rejects_changed_and_extra_model_files(tmp_path, monkeypatch):
    payload = b"public model fixture"
    monkeypatch.setattr(
        gpt2_preset, "FILES", {"model.safetensors": hashlib.sha256(payload).hexdigest()}
    )
    weight = tmp_path / "model.safetensors"
    weight.write_bytes(payload)
    assert gpt2_preset.verify_files(tmp_path) is None
    (tmp_path / "special_tokens_map.json").write_text("{}")
    assert gpt2_preset.verify_files(tmp_path) == "unexpected_or_missing_model_files"
    (tmp_path / "special_tokens_map.json").unlink()
    weight.write_bytes(b"changed")
    assert gpt2_preset.verify_files(tmp_path) == "model_file_digest_mismatch"
    result = detect(
        "English text",
        {
            "detectors": [
                {"backend": "openai_gpt2_detector_local", "model_path": str(tmp_path)}
            ]
        },
    )[0]
    assert result["status"] == "error" and result["score"] is None


def test_preset_directory_read_error_keeps_other_results(tmp_path, monkeypatch):
    root = tmp_path / "model"
    root.mkdir()
    original_iterdir = Path.iterdir

    def unreadable(path):
        if path == root:
            raise OSError("directory cannot be read")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", unreadable)
    assert gpt2_preset.verify_files(root) == "model_directory_unreadable"
    result = detect(
        "English text",
        {
            "detectors": [
                {"backend": "openai_gpt2_detector_local", "model_path": str(root)},
                {"backend": "hmac_green"},
            ]
        },
    )
    assert result[0]["status"] == "error"
    assert result[0]["reason"] == "model_directory_unreadable"
    assert result[1]["status"] == "not_run"
    audit = WritingAuditService().audit_texts(
        "The result was 5%.",
        "The result was 5%.",
        detector_config={
            "detectors": [
                {"backend": "openai_gpt2_detector_local", "model_path": str(root)},
                {"backend": "hmac_green"},
            ]
        },
    )
    assert audit["detection"]["pairs"][0]["after"]["status"] == "error"
    assert audit["detection"]["pairs"][1]["after"]["status"] == "not_run"
    assert audit["fact_lock"]["status"] == "available"
