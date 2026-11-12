"""Retained public-source replay, canonical continuation and forgery controls."""

import csv
import json
import runpy
import shutil
from pathlib import Path

import pytest

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "examples/pilots/narrative-public-decisions/evidence"
PILOT = runpy.run_path(str(ROOT / "scripts/run-public-narrative-pilot"))


def reseal(directory, relative):
    path = directory / "inventory.json"
    inventory = json.loads(path.read_bytes())
    inventory[relative] = sha256_hex((directory / relative).read_bytes())
    path.write_bytes(canonical_json_bytes(inventory))


def test_actual_exports_and_two_round_continuations_replay():
    report = PILOT["verify"](EVIDENCE)
    assert report["status_counts"] == {
        "agreement": 8,
        "disagreement": 1,
        "explicit_unknown": 1,
    }
    assert report["rows"][-1]["human_status"] == "kept"
    assert report["rows"][-1]["machine_status"] == "superseded"
    assert report["historical_reason_assessed_count"] == 0
    assert {(r["sample_id"], r["round"]) for r in report["handoff_resume"]} == {
        ("nep-0016", 1),
        ("nep-0016", 2),
        ("nep-0017", 1),
        ("nep-0017", 2),
    }
    assert all(r["abandoned_notice_present"] for r in report["handoff_resume"])


def test_self_consistent_report_hash_cannot_replace_canonical_result(tmp_path):
    directory = shutil.copytree(EVIDENCE, tmp_path / "evidence")
    path = directory / "report.json"
    value = json.loads(path.read_bytes())
    value["status_counts"]["agreement"] = 10
    path.write_bytes(canonical_json_bytes(value))
    reseal(directory, "report.json")
    with pytest.raises(ValueError, match="canonical evidence recomputation"):
        PILOT["verify"](directory)


def test_relabeling_disagreement_does_not_rewrite_retained_comparison(tmp_path):
    directory = shutil.copytree(EVIDENCE, tmp_path / "evidence")
    path = directory / "inputs/annotations.csv"
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)
    rows[-1]["human_status"] = "superseded"
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    reseal(directory, "inputs/annotations.csv")
    with pytest.raises(ValueError, match="canonical evidence recomputation"):
        PILOT["verify"](directory)


def test_resealed_but_invalid_narrative_chain_is_rejected(tmp_path):
    directory = shutil.copytree(EVIDENCE, tmp_path / "evidence")
    relative = "nep-0016/.arw/narrative/events.jsonl"
    path = directory / relative
    path.write_bytes(
        path.read_bytes().replace(b'"route":"custom"', b'"route":"theory"')
    )
    reseal(directory, relative)
    with pytest.raises(ValueError):
        PILOT["verify"](directory)


def test_resealed_handoff_body_cannot_revive_abandoned_next_action(tmp_path):
    directory = shutil.copytree(EVIDENCE, tmp_path / "evidence")
    body = next((directory / "nep-0016/.arw/memory/bodies").rglob("*.json"))
    value = json.loads(body.read_bytes())
    value["handoff"]["next_concrete_action"] = "Reintroduce the withdrawn proposal"
    body.write_bytes(canonical_json_bytes(value))
    reseal(directory, body.relative_to(directory).as_posix())
    with pytest.raises(ValueError):
        PILOT["verify"](directory)
