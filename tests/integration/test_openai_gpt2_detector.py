"""Opt-in real offline model smoke test; CI never fetches model weights."""

import json
import os
import subprocess
from pathlib import Path

import pytest
from arw_writing.gpt2_preset import REVISION

ROOT = Path(__file__).resolve().parents[2]


def test_official_gpt2_detector_real_offline_cli(tmp_path):
    python = os.environ.get("ARW_GPT2_PYTHON")
    model_dir = os.environ.get("ARW_GPT2_MODEL_DIR")
    if not python or not model_dir:
        pytest.skip(
            "set ARW_GPT2_PYTHON and ARW_GPT2_MODEL_DIR for the public offline model"
        )
    result = subprocess.run(
        [
            python,
            str(ROOT / "examples/openai_gpt2_detector_demo.py"),
            "--model-path",
            model_dir,
            "--output-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        env={**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(result.stdout)
    pair = report["detection"]["pairs"][0]
    assert pair["before"]["status"] == pair["after"]["status"] == "available"
    assert pair["before"]["version"] == REVISION
    assert (
        pair["before"]["parameters"]["model_id"]
        == "openai-community/roberta-base-openai-detector"
    )
    assert pair["comparable"] and isinstance(pair["delta"], float)
    assert report["fact_lock"]["semantic_status"] == "human_review_required"
