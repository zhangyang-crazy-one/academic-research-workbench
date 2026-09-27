"""A failed candidate promotion must leave previously accepted bytes in place."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

STAGE_SCRIPT = Path(__file__).resolve().parents[2] / "scripts/stage-plugin"
PROMOTION_PREFIX = '"$PYTHON" - "$TEMP_STAGE" "$STAGE_ROOT" "$TEMP_EVIDENCE" "$EVIDENCE_ROOT" <<\'PY\'\n'


@pytest.mark.parametrize("failed_move", ("accepted-stage", "new-evidence", "new-stage-interrupt", "new-evidence-interrupt"))
def test_failed_promotion_preserves_accepted_stage_and_evidence(tmp_path: Path, failed_move: str) -> None:
    script = STAGE_SCRIPT.read_text(encoding="utf-8")
    promotion = script.split(PROMOTION_PREFIX, 1)[1].split("\nPY\n", 1)[0]
    accepted_stage = tmp_path / "accepted-stage"
    accepted_evidence = tmp_path / "accepted-evidence"
    new_stage = tmp_path / "new-stage"
    new_evidence = tmp_path / "new-evidence"
    for root, text in ((accepted_stage, "accepted stage"), (accepted_evidence, "accepted evidence"),
                       (new_stage, "new stage"), (new_evidence, "new evidence")):
        root.mkdir()
        (root / "marker.txt").write_text(text, encoding="utf-8")

    # Patch only the single move under test in the child process. The tested
    # promotion block itself is read verbatim from the executable script.
    (tmp_path / "sitecustomize.py").write_text(
        "import os\nfrom pathlib import Path\n"
        "_rename = Path.rename\n"
        "def fail_selected_move(self, target):\n"
        "    if str(self) == os.environ.get('ARW_FAIL_MOVE_SOURCE'):\n"
        "        if os.environ.get('ARW_INTERRUPT_MOVE') == '1':\n"
        "            raise KeyboardInterrupt('injected candidate promotion interruption')\n"
        "        raise OSError('injected candidate promotion failure')\n"
        "    return _rename(self, target)\n"
        "Path.rename = fail_selected_move\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(tmp_path)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    source = {"accepted-stage": accepted_stage, "new-evidence": new_evidence,
              "new-stage-interrupt": new_stage, "new-evidence-interrupt": new_evidence}[failed_move]
    env["ARW_FAIL_MOVE_SOURCE"] = str(source)
    env["ARW_INTERRUPT_MOVE"] = "1" if failed_move.endswith("interrupt") else "0"
    result = subprocess.run(
        [sys.executable, "-c", promotion, str(new_stage), str(accepted_stage),
         str(new_evidence), str(accepted_evidence)],
        env=env, text=True, capture_output=True, check=False,
    )
    assert result.returncode != 0
    assert "injected candidate promotion" in result.stderr
    assert (accepted_stage / "marker.txt").read_text(encoding="utf-8") == "accepted stage"
    assert (accepted_evidence / "marker.txt").read_text(encoding="utf-8") == "accepted evidence"


@pytest.mark.parametrize("nested", ("equal", "stage-inside-evidence", "evidence-inside-stage"))
def test_promotion_rejects_overlapping_accepted_roots_before_moves(tmp_path: Path, nested: str) -> None:
    script = STAGE_SCRIPT.read_text(encoding="utf-8")
    promotion = script.split(PROMOTION_PREFIX, 1)[1].split("\nPY\n", 1)[0]
    stage = tmp_path / "accepted"
    evidence = {"equal": stage, "stage-inside-evidence": tmp_path,
                "evidence-inside-stage": stage / "evidence"}[nested]
    stage.mkdir(parents=True)
    evidence.mkdir(parents=True, exist_ok=True)
    marker = stage / "marker.txt"
    marker.write_text("accepted", encoding="utf-8")
    new_stage = tmp_path / "new-stage"
    new_evidence = tmp_path / "new-evidence"
    new_stage.mkdir()
    new_evidence.mkdir()
    result = subprocess.run(
        [sys.executable, "-c", promotion, str(new_stage), str(stage), str(new_evidence), str(evidence)],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode != 0
    assert "must be disjoint" in result.stderr
    assert marker.read_text(encoding="utf-8") == "accepted"
