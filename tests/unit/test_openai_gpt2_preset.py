"""Pinned offline model identity and refusal cases without downloading weights."""

import hashlib

from arw_writing import gpt2_preset
from arw_writing.detection import detect


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
