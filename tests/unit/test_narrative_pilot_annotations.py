"""Owner answers must survive transcription without becoming historical truth."""

import csv
import runpy
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "examples/pilots/narrative-public-decisions"
check = runpy.run_path(str(ROOT / "scripts/check-narrative-pilot-annotations"))["check"]


def rewrite_rows(directory, transform):
    path = directory / "annotations.csv"
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        rows = list(reader)
    transform(rows)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_actual_answers_and_optional_dimension_choice_are_retained():
    result = check(KIT)
    assert result["owner_annotation_count"] == 10
    assert result["status"] == "owner_annotations_recorded"
    assert result["source_history_comparison_ready"] is False
    assert result["agreement"] == "not_evaluated"
    with (KIT / "annotations.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[2]["selected_option"] == "B"
    assert rows[2]["human_annotation"] == "B 应该选择允许缺省。"
    assert "而不进行审批" in rows[3]["human_annotation"]
    assert "如果只是加快了实验的处理过程直接做就行" in rows[4]["human_annotation"]
    assert all(not row["human_status"] for row in rows)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("human_status", "kept", "must not be encoded as source history"),
        ("human_reason", "guessed reason", "must not be encoded as source history"),
        ("human_annotation", "", "actual annotation text"),
        ("annotation_basis", "guessed", "invalid annotation basis"),
        ("source_sha256", "0" * 64, "source identity differs"),
    ],
)
def test_invalid_transcription_is_rejected(tmp_path, field, value, message):
    directory = shutil.copytree(KIT, tmp_path / "kit")
    rewrite_rows(directory, lambda rows: rows[0].update({field: value}))
    with pytest.raises(ValueError, match=message):
        check(directory)


def test_legacy_source_history_sheet_remains_readable(tmp_path):
    directory = shutil.copytree(KIT, tmp_path / "kit")
    path = directory / "annotations.csv"
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames[:8]
        rows = [{key: row[key] for key in fields} for row in reader]
    for row in rows:
        row.update(
            human_status="unknown",
            reason_status="unknown",
            human_reason="",
            evidence_locator="test-fixture:unresolved-history",
            annotator_id="test-annotator",
            annotated_at_utc="2026-10-12T00:00:00Z",
        )
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    result = check(directory)
    assert result["owner_annotation_count"] == 0
    assert result["annotation_counts"]["unknown"] == 10
    assert result["source_history_comparison_ready"] is True
    assert result["agreement"] == "not_evaluated"
