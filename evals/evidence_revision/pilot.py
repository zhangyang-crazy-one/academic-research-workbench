"""Execute the public read-only, two-round impact pilot without model calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from arw.evidence_revision import EvidenceUpdate, impact_checklist
from arw.graph_projection import project_canonical_records
from arw.graph_store import GraphStore
from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex

DEFAULT_FIXTURE = Path(__file__).with_name("public.json")


def score(checklist: dict, labels: dict) -> dict:
    """Labels are consumed only by this scorer, never by impact traversal."""
    required = set(labels["required_revisions"])
    candidates = {row["record_id"]: row for row in checklist["candidates"]}
    actual = set(candidates)
    return {
        "required_revisions": len(required),
        "missed_required_revisions": len(required - actual),
        "false_revisions": len(actual - required),
        "stale_candidate_errors": sum(
            identity not in candidates or candidates[identity]["proposed_text"] != text
            for identity, text in labels["expected_candidate_text"].items()
        ),
        # Correct candidate routing is not an accepted manuscript correction.
        "accepted_stale_items_pending_review": len(required),
    }


def run_pilot(fixture: dict, cache: Path) -> dict:
    records = [
        dict(record, source_digest=sha256_hex(canonical_json_bytes(record)))
        for record in fixture["records"]
    ]
    before = canonical_json_bytes(records)
    projection = project_canonical_records(
        records, ledger_watermark=1, ledger_head_sha256=sha256_hex(before)
    )
    store = GraphStore(cache, "revision-pilot")
    store.build(projection)
    rounds = []
    previous_candidates: dict = {}
    for round_ in fixture["rounds"]:
        checks = []
        for case in round_["updates"]:
            result = impact_checklist(
                store,
                EvidenceUpdate.model_validate(case["update"]),
                expected_watermark=1,
                proposed_text=case["proposed_text"],
            )
            labels = case["labels"]
            checks.append(
                {
                    "checklist": result,
                    "metrics": score(result, labels),
                    "previous_round_stale_candidate_errors": score(
                        {"candidates": list(previous_candidates.values())}, labels
                    )["stale_candidate_errors"],
                }
            )
        for check in checks:
            previous_candidates.update(
                {c["record_id"]: c for c in check["checklist"]["candidates"]}
            )
        rounds.append({"round": round_["round"], "checks": checks})
    totals: dict[str, int] = {}
    costs: dict[str, int] = {}
    for round_ in rounds:
        for check in round_["checks"]:
            for key, value in check["metrics"].items():
                totals[key] = totals.get(key, 0) + value
            for key, value in check["checklist"]["costs"].items():
                costs[key] = costs.get(key, 0) + value
    unchanged = before == canonical_json_bytes(records)
    passed = unchanged and all(
        c["checklist"]["status"] == "review_required"
        and not any(
            c["metrics"][key]
            for key in (
                "missed_required_revisions",
                "false_revisions",
                "stale_candidate_errors",
            )
        )
        for r in rounds
        for c in r["checks"]
    )
    return {
        "schema_version": "arw.evidence-revision-pilot.v1",
        "status": "passed" if passed else "failed",
        "scope": "synthetic_dependency_routing_and_scripted_candidates_only",
        "fixture_sha256": sha256_hex(canonical_json_bytes(fixture)),
        "accepted_records_unchanged": unchanged,
        "accepted_records_sha256": sha256_hex(before),
        "rounds": rounds,
        "totals": totals,
        "costs": costs,
        "limitations": [
            "Public labels and scripted candidate text are not independent semantic evaluation.",
            "No model, source retrieval, live literature reading, or accepted-output revision occurred.",
            "Counts sum update-record pairs, including records revisited in round two.",
            "Accepted stale items remain pending review; no automatic revocation or admission.",
            "Missing dependency links may cause misses; declared irrelevant updates are still traced.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text())
    with TemporaryDirectory(prefix="arw-evidence-revision-") as temporary:
        result = run_pilot(fixture, Path(temporary))
    # Retained reports are append-only by filename; never clobber previous runs.
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
