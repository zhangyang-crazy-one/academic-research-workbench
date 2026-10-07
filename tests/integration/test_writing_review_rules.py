"""Rule-review tasks and reviewer findings remain bound to real candidate bytes."""

import json
import os
import subprocess
import sys

import pytest
from arw_writing.review_rules import CATEGORIES, validate_report
from arw_writing.transformer import SessionWritingTransformer

from arw.kernel.core.canonical import sha256_hex

from .test_research_artifacts import request
from .test_writing import CANDIDATE, SOURCE, approve, prepared, proposal


def report(candidate):
    plan = candidate["verification"]["rule_review"]["plan"]
    quote = "ModelX"
    start = candidate["candidate"].index(quote)
    return {
        "schema_version": "arw.writing-rule-review.v1",
        "source_sha256": candidate["source_sha256"],
        "candidate_sha256": candidate["candidate_sha256"],
        "plan_sha256": plan["plan_sha256"],
        "provider": "manual",
        "reviewer": "synthetic-fixture-reviewer",
        "coverage": [
            {
                "category": category,
                "status": "reviewed",
                "reason": "Inspected the fixed test passage",
            }
            for category in CATEGORIES
        ],
        "findings": [
            {
                "category": "claim_strength",
                "severity": "suggestion",
                "confidence": "low",
                "review_status": "accepted_risk",
                "candidate_span": {
                    "start": start,
                    "end": start + len(quote),
                    "quote": quote,
                },
                "source_span": None,
                "evidence": "Fixture reviewer inspected the claim in context; no external evidence asserted",
                "reason": "Synthetic fixture note, not an automatic semantic finding",
                "minimal_change": "If needed, clarify the scope around this named model",
                "resolution_reason": "Fixture reviewer accepts the existing named-model scope",
            }
        ],
    }


def test_plan_is_actionable_and_covered_by_verification_digest():
    candidate = SessionWritingTransformer().transform(SOURCE, proposal())
    plan = candidate["verification"]["rule_review"]["plan"]
    assert [task["category"] for task in plan["tasks"]] == list(CATEGORIES)
    assert candidate["rule_review"] == {"status": "not_run", "report": None}
    assert candidate["verification"]["semantic_equivalence_proven"] is False
    assert plan["source_sha256"] == sha256_hex(SOURCE.encode())
    assert plan["candidate_sha256"] == sha256_hex(CANDIDATE.encode())
    assert "interval crossing zero" in plan["tasks"][1]["instruction"]
    assert "protocol name does not establish novelty" in plan["tasks"][2]["instruction"]


def test_review_report_rejects_stale_hash_and_unlocated_evidence():
    candidate = SessionWritingTransformer().transform(SOURCE, proposal())
    plan = candidate["verification"]["rule_review"]["plan"]
    base = report(candidate)
    assert validate_report(base, plan, SOURCE, CANDIDATE)["findings"]
    bad = {**base, "plan_sha256": "0" * 64}
    with pytest.raises(ValueError, match="stale"):
        validate_report(bad, plan, SOURCE, CANDIDATE)
    bad = {
        **base,
        "findings": [
            {
                **base["findings"][0],
                "candidate_span": {"start": 1, "end": 7, "quote": "ModelX"},
            }
        ],
    }
    with pytest.raises(ValueError, match="unlocated"):
        validate_report(bad, plan, SOURCE, CANDIDATE)
    bad = {**base, "findings": [{**base["findings"][0], "severity": "blocker"}]}
    with pytest.raises(ValueError):
        validate_report(bad, plan, SOURCE, CANDIDATE)
    tail = CANDIDATE[-8:]
    bad = {
        **base,
        "findings": [
            {
                **base["findings"][0],
                "candidate_span": {
                    "start": len(CANDIDATE) - 8,
                    "end": len(CANDIDATE) + 10,
                    "quote": tail,
                },
            }
        ],
    }
    with pytest.raises(ValueError, match="unlocated"):
        validate_report(bad, plan, SOURCE, CANDIDATE)
    bad["findings"][0]["candidate_span"] = {
        "start": len(CANDIDATE) + 1,
        "end": len(CANDIDATE) + 7,
        "quote": "ModelX",
    }
    with pytest.raises(ValueError, match="unlocated"):
        validate_report(bad, plan, SOURCE, CANDIDATE)


def test_record_retains_real_rule_report_and_legacy_is_not_run(tmp_path):
    root, service = prepared(tmp_path)
    candidate = service.prepare("artifact.manuscript", proposal())
    legacy = approve(root, candidate, 60)
    old = service.record(
        "artifact.manuscript",
        proposal(),
        request=request(root, 70),
        review_artifact_id=legacy,
    )
    assert (
        json.loads((root / old["bundle_path"]).read_text())["rule_review"]["status"]
        == "not_run"
    )
    current = approve(root, candidate, 80, rule_review=report(candidate))
    done = service.record(
        "artifact.manuscript",
        proposal(),
        request=request(root, 90),
        review_artifact_id=current,
    )
    body = json.loads((root / done["bundle_path"]).read_text())
    assert done["candidate_accepted"]
    assert body["rule_review"]["status"] == "reviewed"
    assert body["rule_review"]["report"]["findings"][0]["confidence"] == "low"
    assert body["review_binding"]["artifact_id"] == current
    assert body["verification"]["semantic_equivalence_proven"] is False


@pytest.mark.parametrize(
    "change",
    [
        lambda r: {**r, "candidate_sha256": "0" * 64},
        lambda r: {
            **r,
            "coverage": [
                {**r["coverage"][0], "status": "not_reviewed"},
                *r["coverage"][1:],
            ],
        },
        lambda r: {**r, "findings": [{**r["findings"][0], "review_status": "open"}]},
        lambda r: {
            **r,
            "findings": [
                {
                    **r["findings"][0],
                    "candidate_span": {"start": 1, "end": 7, "quote": "ModelX"},
                }
            ],
        },
        lambda r: {**r, "findings": [{**r["findings"][0], "evidence": ""}]},
        lambda r: {**r, "provider": "   "},
        lambda r: {**r, "reviewer": "   "},
        lambda r: {
            **r,
            "coverage": [{**r["coverage"][0], "reason": " \t "}, *r["coverage"][1:]],
        },
        lambda r: {**r, "findings": [{**r["findings"][0], "minimal_change": "  "}]},
    ],
)
def test_incomplete_or_stale_rule_review_cannot_approve(tmp_path, change):
    root, service = prepared(tmp_path)
    candidate = service.prepare("artifact.manuscript", proposal())
    review = approve(root, candidate, 60, rule_review=change(report(candidate)))
    with pytest.raises(ValueError, match="rule review"):
        service.record(
            "artifact.manuscript",
            proposal(),
            request=request(root, 70),
            review_artifact_id=review,
        )


def test_cli_prepare_emits_five_tasks_through_manifest_gate(tmp_path):
    root, _ = prepared(tmp_path)
    input_path = root / "proposal.json"
    input_path.write_text(json.dumps(proposal()))
    repo = __import__("pathlib").Path(__file__).resolve().parents[2]
    command = [
        sys.executable,
        "-m",
        "arw.cli",
        "writing",
        "prepare",
        "--run-root",
        str(root),
        "--source-id",
        "artifact.manuscript",
        "--proposal",
        str(input_path),
    ]
    env = {
        **os.environ,
        "PYTHONPATH": f"{repo / 'src'}:{repo / 'extensions/academic-humanization/src'}",
    }
    run = subprocess.run(command, text=True, capture_output=True, check=False, env=env)
    assert run.returncode == 0, run.stderr + run.stdout
    output = json.loads(run.stdout)
    assert len(output["verification"]["rule_review"]["plan"]["tasks"]) == 5
    assert output["rule_review"]["status"] == "not_run"
