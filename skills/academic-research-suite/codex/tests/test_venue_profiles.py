from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

CODEX_ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = CODEX_ROOT / "references" / "annual_venue_profiles.json"
VALIDATOR_PATH = CODEX_ROOT / "scripts" / "validate_venue_profiles.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "validate_venue_profiles", VALIDATOR_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _document() -> dict:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def _profiles(document: dict) -> dict[str, dict]:
    return {
        profile["id"]: profile
        for collection in ("review_systems", "venues")
        for profile in document[collection]
    }


def test_registry_passes_validator() -> None:
    validator = _load_validator()
    assert validator.validate_path(PROFILE_PATH) == []


def test_arr_venues_compose_review_system_and_venue_year_rules() -> None:
    profiles = _profiles(_document())
    arr = profiles["arr-2026-october"]
    coling = profiles["coling-2027"]
    naacl = profiles["naacl-2027"]

    assert arr["format_contract"]["paper_types"]["long"]["content_pages"] == 8
    assert coling["format_contract"] == {
        "mode": "inherit",
        "review_system_id": "arr-2026-october",
    }
    assert naacl["format_contract"] == coling["format_contract"]


def test_venue_specific_commitment_is_not_arr_cycle_end() -> None:
    profiles = _profiles(_document())
    cycle_end = profiles["arr-2026-october"]["milestones"]["cycle_end"]
    commitment = profiles["coling-2027"]["milestones"]["commitment"]

    assert cycle_end["date"] == "2026-12-20"
    assert commitment["date"] == "2026-12-23"
    assert commitment["source_id"] == "coling-2027-home"


def test_unannounced_naacl_dates_are_not_invented() -> None:
    commitment = _profiles(_document())["naacl-2027"]["milestones"]["commitment"]
    assert commitment == {
        "date": None,
        "time": None,
        "timezone": None,
        "status": "not_announced",
        "source_id": "naacl-2027-home",
    }


def test_current_paper_route_is_explicitly_tiered() -> None:
    routing = _document()["project_routing"]
    assert routing["primary"]["venue_id"] == "coling-2027"
    assert routing["same_cycle_alternative"]["venue_id"] == "naacl-2027"
    assert routing["conditional_backup"]["venue_id"] == "ecir-2027-full"
    assert routing["conditional_backup"]["fit"] == "conditional_reframe_only"


def test_style_learning_is_sourced_and_non_normative() -> None:
    document = _document()
    style = document["style_learning"]
    source_ids = {item["source_id"] for item in style["exemplars"]}

    assert style["status"] == "non_normative_editorial_inference"
    assert source_ids == {
        "coling-2025-zero-shot-ontology",
        "coling-2025-b2nerd",
        "coling-2025-gaef",
        "coling-2025-cycleoie",
        "coling-2025-kgpcl",
        "coling-2025-kg-trick",
        "coling-2025-ood-control",
        "naacl-2025-track-sql",
        "naacl-2025-soft-syntax-ee",
    }
    assert all(
        document["sources"][source_id]["authority"] == "official_published_paper"
        for source_id in source_ids
    )
    assert any(
        "prompt rephrasings" in slot for slot in style["consensus_argument_slots"]
    )


def test_topic_matched_coling_audit_overrides_generic_editorial_heuristics() -> None:
    style = _document()["style_learning"]
    boundary = style["direct_vs_adjacent"]
    artifact = style["artifact_contract"]

    assert style["editorial_precedence"] == [
        "official_target_venue_requirements",
        "topic_matched_full_text_accepted_paper_audit",
        "generic_cross_venue_heuristic",
    ]
    assert boundary["direct_exemplars"] == [
        "coling-2025-zero-shot-ontology",
        "coling-2025-b2nerd",
        "coling-2025-gaef",
    ]
    assert boundary["adjacent_not_direct_baselines"] == [
        "coling-2025-kgpcl",
        "coling-2025-kg-trick",
    ]
    assert artifact["default_figure_sequence"][0].startswith(
        "Figure 1: a realistic task"
    )
    assert artifact["default_figure_sequence"][1].startswith(
        "Figure 2: a functional method"
    )
    assert "not a hard cap" in artifact["table_density_rule"]
    assert artifact["main_result_settings"] == [
        "fully_unseen_labels",
        "partially_seen_labels",
        "cross_domain",
    ]
    assert "report_local_metric_for_each_module" in artifact["ablation_requirements"]
    assert (
        "no_evidence_rejection_accuracy_and_hallucination_rate"
        in artifact["robustness_and_error_requirements"]
    )


def test_validator_rejects_reversed_editorial_precedence() -> None:
    validator = _load_validator()
    document = copy.deepcopy(_document())
    document["style_learning"]["editorial_precedence"].reverse()

    errors = validator.validate_document(document)
    assert any("editorial_precedence" in error for error in errors)


def test_validator_rejects_unknown_exemplar_role() -> None:
    validator = _load_validator()
    document = copy.deepcopy(_document())
    document["style_learning"]["exemplars"][0]["role"] = "direct_baseline"

    errors = validator.validate_document(document)
    assert any("invalid role" in error for error in errors)


def test_validator_rejects_nonofficial_deadline_source() -> None:
    validator = _load_validator()
    document = copy.deepcopy(_document())
    document["venues"][0]["milestones"]["commitment"]["source_id"] = "ucas-ccf-2026-pdf"

    errors = validator.validate_document(document)
    assert any("dated facts require an official source" in error for error in errors)


def test_validator_rejects_silent_naacl_date_invention() -> None:
    validator = _load_validator()
    document = copy.deepcopy(_document())
    commitment = document["venues"][1]["milestones"]["commitment"]
    commitment["date"] = "2026-12-20"
    commitment["status"] = "confirmed"

    errors = validator.validate_document(document)
    assert any(
        "unannounced commitment date must remain explicit" in error for error in errors
    )


def test_validator_cli_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(VALIDATOR_PATH), str(PROFILE_PATH), "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["errors"] == []
