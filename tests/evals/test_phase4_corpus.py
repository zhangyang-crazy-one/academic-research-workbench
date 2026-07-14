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
FIXTURE_RELATIVE = "tests/fixtures/orchestration/v1/phase4-fixtures.json"
CORPUS_FILES = ("development/cases.json", "sealed-parent-only/cases.json")
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


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _worker_visible_projection(case: dict[str, Any], allowed_fields: tuple[str, ...]) -> dict[str, Any]:
    """Construct the only case shape that a worker-facing assignment may receive."""

    return {field: case[field] for field in allowed_fields}


def _walk_strings(value: object) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return set().union(*(_walk_strings(item) for item in value)) if value else set()
    if isinstance(value, dict):
        return set().union(*(_walk_strings(item) for item in value.values())) if value else set()
    return set()


def _walk_keys(value: object) -> set[str]:
    if isinstance(value, list):
        return set().union(*(_walk_keys(item) for item in value)) if value else set()
    if isinstance(value, dict):
        return set(value) | (set().union(*(_walk_keys(item) for item in value.values())) if value else set())
    return set()


def test_phase4_corpus_is_canonical_digest_bound_and_has_the_locked_distribution() -> None:
    manifest = _load_canonical(CORPUS_ROOT / "manifest.json")
    development = _load_canonical(CORPUS_ROOT / "development/cases.json")
    sealed = _load_canonical(CORPUS_ROOT / "sealed-parent-only/cases.json")
    fixture = _load_canonical(FIXTURE_PATH)

    assert manifest["schema_version"] == "phase4-corpus-manifest.v1"
    assert manifest["synthetic_only"] is True
    assert manifest["case_counts"] == {"development": 32, "sealed_parent_only": 16, "total": 48}
    assert manifest["family_counts"] == FAMILY_COUNTS
    assert development["visibility"] == "development"
    assert sealed["visibility"] == "sealed-parent-only"
    assert len(development["cases"]) == 32
    assert len(sealed["cases"]) == 16

    fixture_digest = hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest()
    assert manifest["fixture"] == {"path": FIXTURE_RELATIVE, "sha256": fixture_digest}
    assert fixture["schema_version"] == "phase4-orchestration-fixtures.v1"

    files = manifest["files"]
    assert set(files) == set(CORPUS_FILES)
    for relative in CORPUS_FILES:
        raw = (CORPUS_ROOT / relative).read_bytes()
        assert files[relative]["sha256"] == hashlib.sha256(raw).hexdigest()

    all_cases = [*development["cases"], *sealed["cases"]]
    assert len(all_cases) == 48
    assert len({case["case_id"] for case in all_cases}) == 48
    assert Counter(case["family"] for case in all_cases) == FAMILY_COUNTS

    entries = {entry["case_id"]: entry for entry in manifest["cases"]}
    assert len(entries) == 48
    for case in all_cases:
        entry = entries[case["case_id"]]
        assert entry["family"] == case["family"]
        assert entry["visibility"] in {"development", "sealed-parent-only"}
        assert entry["sha256"] == _digest(case)
        assert entry["input_sha256"] == _digest(case["input"])
        assert entry["expected_sha256"] == _digest(case["expected"])
        assert entry["fixture_sha256"] == fixture_digest

    assert {case["case_id"] for case in development["cases"]} == {
        entry["case_id"] for entry in manifest["cases"] if entry["visibility"] == "development"
    }
    assert {case["case_id"] for case in sealed["cases"]} == {
        entry["case_id"]
        for entry in manifest["cases"]
        if entry["visibility"] == "sealed-parent-only"
    }


def test_sealed_labels_are_parent_only_and_worker_projections_use_an_allowlist() -> None:
    manifest = _load_canonical(CORPUS_ROOT / "manifest.json")
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
    assert all("label_id" not in case["expected"] for case in development["cases"])
    assert all("adjudication" not in case for case in development["cases"])
    assert not (sealed_labels & _walk_strings(manifest))

    worker_visible_payloads = [
        fixture,
        *(_worker_visible_projection(case, allowed_fields) for case in development["cases"]),
        *(_worker_visible_projection(case, allowed_fields) for case in sealed["cases"]),
    ]
    for payload in worker_visible_payloads:
        rendered = canonical_json_bytes(payload).decode("utf-8")
        assert not (sealed_labels & _walk_strings(payload))
        assert not ({"expected", "adjudication", "label_id"} & _walk_keys(payload))
        assert "adjudication" not in rendered
        assert "label_id" not in rendered


def test_corpus_cases_cover_phase4_lifecycle_and_evidence_boundaries() -> None:
    development = _load_canonical(CORPUS_ROOT / "development/cases.json")
    sealed = _load_canonical(CORPUS_ROOT / "sealed-parent-only/cases.json")
    cases = [*development["cases"], *sealed["cases"]]
    evidence_kinds = {case["input"]["evidence_kind"] for case in cases}
    assert {"direct_path", "symlink", "malformed", "late", "stale"} <= evidence_kinds
    assert all({"mode", "status", "verdict"} <= set(case["expected"]) for case in cases)
    assert all(case["input"]["synthetic"] is True for case in cases)
    assert all(len(case["input"]["input_sha256"]) == 64 for case in cases)

    scenarios = {case["input"]["scenario"] for case in cases}
    assert {
        "assignment-supersession-required",
        "frozen-order-buffered-later-result",
        "retry-timeout-once",
        "cancel-cooperative-then-force",
        "orphan-interrupted-requeue",
        "formal-panel-four-distinct-workers",
        "finding-matrix-da-critical-unresolved",
        "hook-duplicate-stop-continuation",
        "human-gate-scoped-waiver",
    } <= scenarios
