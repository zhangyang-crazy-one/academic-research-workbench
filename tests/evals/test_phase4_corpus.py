from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any

from arw.canonical import canonical_json_bytes


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CORPUS_ROOT = REPOSITORY_ROOT / "tests/evals/phase4/corpus/v1"
FIXTURE_PATH = REPOSITORY_ROOT / "tests/fixtures/orchestration/v1/phase4-fixtures.json"
FAMILY_COUNTS = {
    "assignment_immutability_echo_validation": 6,
    "proposal_path_byte_defenses": 6,
    "frozen_order_concurrency": 6,
    "retry_cancel_orphan_recovery": 6,
    "stale_superseded_results": 6,
    "blind_panel_identity_isolation": 6,
    "dissent_finding_matrix_synthesis": 5,
    "hook_parity_continuation_abuse": 4,
    "human_gate_freshness_append_only": 3,
}


def _load_canonical(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    assert raw.endswith(b"\n"), f"{path} must be newline terminated"
    value = json.loads(raw)
    assert raw == canonical_json_bytes(value), f"{path} must use canonical JSON bytes"
    return value


def _case_digest(case: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(case)).hexdigest()


def _walk_strings(value: object) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return set().union(*(_walk_strings(item) for item in value)) if value else set()
    if isinstance(value, dict):
        return set().union(*(_walk_strings(item) for item in value.values())) if value else set()
    return set()


def _worker_visible_projection(case: dict[str, Any], allowed_fields: tuple[str, ...]) -> dict[str, Any]:
    """The corpus's deliberate allowlist prevents parent-only labels reaching workers."""

    return {field: case[field] for field in allowed_fields}


def test_phase4_corpus_is_canonical_digest_bound_and_has_the_locked_distribution() -> None:
    manifest = _load_canonical(CORPUS_ROOT / "manifest.json")
    development = _load_canonical(CORPUS_ROOT / "development/cases.json")
    sealed = _load_canonical(CORPUS_ROOT / "sealed-parent-only/cases.json")

    assert manifest["schema_version"] == "phase4-corpus-manifest.v1"
    assert manifest["synthetic_only"] is True
    assert manifest["case_counts"] == {"development": 32, "sealed_parent_only": 16, "total": 48}
    assert manifest["family_counts"] == FAMILY_COUNTS
    assert development["visibility"] == "development"
    assert sealed["visibility"] == "sealed-parent-only"
    assert len(development["cases"]) == 32
    assert len(sealed["cases"]) == 16

    files = manifest["files"]
    for relative in ("development/cases.json", "sealed-parent-only/cases.json"):
        raw = (CORPUS_ROOT / relative).read_bytes()
        assert files[relative]["sha256"] == hashlib.sha256(raw).hexdigest()

    all_cases = [*development["cases"], *sealed["cases"]]
    assert len(all_cases) == 48
    assert len({case["case_id"] for case in all_cases}) == 48
    assert Counter(case["family"] for case in all_cases) == FAMILY_COUNTS
    assert {case["case_id"] for case in development["cases"]} == {
        entry["case_id"] for entry in manifest["cases"] if entry["visibility"] == "development"
    }
    assert {case["case_id"] for case in sealed["cases"]} == {
        entry["case_id"]
        for entry in manifest["cases"]
        if entry["visibility"] == "sealed-parent-only"
    }
    expected_digests = {entry["case_id"]: entry["sha256"] for entry in manifest["cases"]}
    assert {_case_digest(case) for case in all_cases} == set(expected_digests.values())
    assert all(_case_digest(case) == expected_digests[case["case_id"]] for case in all_cases)


def test_sealed_labels_are_parent_only_and_worker_projections_use_an_allowlist() -> None:
    fixture = _load_canonical(FIXTURE_PATH)
    development = _load_canonical(CORPUS_ROOT / "development/cases.json")
    sealed = _load_canonical(CORPUS_ROOT / "sealed-parent-only/cases.json")
    allowed_fields = tuple(fixture["worker_visible_case_fields"])
    assert allowed_fields == ("case_id", "family", "protocol_version", "input", "role_policy")

    sealed_labels = {
        case["expected"]["label_id"] for case in sealed["cases"]
    } | {case["adjudication"]["key"] for case in sealed["cases"]}
    assert len(sealed_labels) == 32
    assert all("expected" in case and "adjudication" in case for case in sealed["cases"])
    assert all("label_id" not in case for case in development["cases"])
    assert all("adjudication" not in case for case in development["cases"])

    worker_visible_payloads = [
        fixture,
        development,
        *(_worker_visible_projection(case, allowed_fields) for case in development["cases"]),
        *(_worker_visible_projection(case, allowed_fields) for case in sealed["cases"]),
    ]
    for payload in worker_visible_payloads:
        rendered = canonical_json_bytes(payload).decode("utf-8")
        assert not (sealed_labels & _walk_strings(payload))
        assert "adjudication" not in rendered
        assert "label_id" not in rendered


def test_corpus_cases_cover_direct_path_symlink_malformed_late_and_stale_evidence() -> None:
    development = _load_canonical(CORPUS_ROOT / "development/cases.json")
    sealed = _load_canonical(CORPUS_ROOT / "sealed-parent-only/cases.json")
    evidence_kinds = {
        case["input"]["evidence_kind"] for case in [*development["cases"], *sealed["cases"]]
    }
    assert {"direct_path", "symlink", "malformed", "late", "stale"} <= evidence_kinds
    assert all(
        {"mode", "status", "verdict"} <= set(case["expected"])
        for case in [*development["cases"], *sealed["cases"]]
    )
