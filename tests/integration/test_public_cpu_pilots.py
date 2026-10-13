"""Cold replay of retained real numerical executions, including failed v1."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from arw.kernel.artifacts.experiment_acceptance import (
    load_experiment_acceptance,
    load_experiment_contract,
    replay_experiment_acceptance,
    timing_from_run,
)
from arw.kernel.artifacts.experiment_provenance import load_experiment_provenance
from arw.kernel.core.canonical import sha256_hex
from arw.kernel.ledger.journal import replay_run

EVIDENCE = (
    Path(__file__).resolve().parents[2] / "examples/pilots/cpu-experiments/evidence"
)


def cold(root, digest):
    receipt = load_experiment_acceptance(root, digest)
    contract = load_experiment_contract(root, receipt.contract_sha256)
    provenance = load_experiment_provenance(root, receipt.provenance_sha256)
    return replay_experiment_acceptance(
        receipt,
        contract,
        provenance,
        root,
        timing=timing_from_run(
            root, receipt.contract_sha256, receipt.provenance_sha256
        ),
    )


def test_retained_inventory_and_four_original_results():
    inventory = json.loads((EVIDENCE / "inventory.json").read_text())
    for name, digest in inventory.items():
        assert sha256_hex((EVIDENCE / name).read_bytes()) == digest, name
    report = json.loads((EVIDENCE / "report.json").read_text())
    assert len(report["pilots"]) == 3
    assert report["model_calls"] == 0
    assert report["controlled_execution_qualified"] is False
    for pilot in report["pilots"]:
        root = EVIDENCE / pilot["experiment"]
        assert replay_run(root).recovery_health == "healthy"
        assert pilot["costs"]["monetary_cost"] == "unknown"
        assert pilot["costs"]["measurements"]["wall_seconds"] >= 0
        for version in pilot["results"]:
            result = cold(root, version["result_sha256"])
            assert result.overall_status == version["overall_status"]
            assert result.predeclaration == version["predeclaration"]
            assert (version["freeze_sequence"] < pilot["provenance_sequence"]) == (
                version["version"] == 1
            )
    first = report["pilots"][0]["results"]
    assert [(r["overall_status"], r["predeclaration"]) for r in first] == [
        ("failed", "verified_predeclared"),
        ("passed", "predeclaration_contradicted"),
    ]


def test_changed_observations_cannot_replay_original_pass(tmp_path):
    report = json.loads((EVIDENCE / "report.json").read_text())
    pilot = report["pilots"][1]
    root = shutil.copytree(EVIDENCE / pilot["experiment"], tmp_path / "changed")
    (root / "results/raw.csv").write_text("trial,value\nchanged,42\n")
    with pytest.raises(ValueError):
        cold(root, pilot["results"][0]["result_sha256"])
