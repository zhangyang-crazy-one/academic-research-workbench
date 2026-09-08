"""Real exact-span transformations, scoped gate failures and canonical review admission."""

import json
import subprocess
import sys

import pytest
from arw_writing.diagnostics import diagnose
from arw_writing.service import WritingService
from arw_writing.transformer import SessionWritingTransformer

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.ledger.journal import replay_run
from arw.ports.writing import CAPABILITIES, WritingTransformer

from .test_precise_source_locators import accept, seed
from .test_research_artifacts import request

SOURCE = "Moreover, ModelX may improve accuracy by 5% in our experiments [@lee]. Moreover, ModelX may improve recall.\n\n在本实验中，ModelX可能提高准确率。 $x=2$ remains unchanged."
CANDIDATE = "ModelX may improve accuracy by 5% in our experiments [@lee]. ModelX may improve recall.\n\n在本实验中，ModelX可能提高准确率。 $x=2$ remains unchanged."


def proposal(source=SOURCE, candidate=CANDIDATE, capability=CAPABILITIES[0]):
    return {
        "schema_version": "arw.writing-proposal.v1",
        "capability": capability,
        "source_sha256": sha256_hex(source.encode()),
        "author_target": "Improve manuscript rhythm while preserving study limitations and evidence / 保留实验限定",
        "language": "en-zh",
        "protected_terms": ["ModelX"] if "ModelX" in source else [],
        "protected_spans": [],
        "controls": {"connectors": "decrease"},
        "generation": {
            "provider": "fixture-author",
            "model": "manual-exact-edit-fixture",
            "version": "1",
            "prompt_sha256": "1" * 64,
            "parameters": {"temperature": 0},
        },
        "edits": [
            {"start": 0, "end": len(source), "before": source, "replacement": candidate}
        ],
    }


def prepared(tmp_path):
    root, _ = seed(tmp_path)
    (root / "manuscript.txt").write_text(SOURCE)
    assert accept(
        root, "artifact.manuscript", "manuscript.txt", 40, kind="manuscript"
    ).accepted
    return root, WritingService(root)


def approve(root, candidate, number=60, **overrides):
    review = {
        "schema_version": "arw.writing-review.v1",
        "source_sha256": candidate["source_sha256"],
        "candidate_sha256": candidate["candidate_sha256"],
        "proposal_sha256": candidate["proposal_sha256"],
        "verification_sha256": candidate["verification_sha256"],
        "decision": "APPROVED",
        "reviewed_dimensions": candidate["verification"]["unresolved_dimensions"],
        "reviewer": "synthetic-fixture-reviewer",
        "rationale": "TEST FIXTURE ONLY: removal of repeated connectors retains the cited study limitation",
        **overrides,
    }
    (root / f"review{number}.json").write_bytes(canonical_json_bytes(review))
    artifact_id = f"artifact.review{number}"
    assert accept(
        root, artifact_id, f"review{number}.json", number, kind="writing-human-review"
    ).accepted
    return artifact_id


@pytest.mark.parametrize("capability", CAPABILITIES)
def test_five_operations_require_review_then_accept_and_retry(tmp_path, capability):
    root, service = prepared(tmp_path)
    variants = {
        CAPABILITIES[0]: CANDIDATE.replace("remains unchanged", "is retained"),
        CAPABILITIES[1]: CANDIDATE.replace("remains unchanged", "stays the same"),
        CAPABILITIES[2]: CANDIDATE.replace(" recall.\n\n", " recall. "),
        CAPABILITIES[3]: CANDIDATE.replace(
            "may improve recall", "may yield improved recall"
        ),
        CAPABILITIES[4]: CANDIDATE.replace(
            "may improve accuracy", "may yield improved accuracy"
        ),
    }
    expected_candidate = variants[capability]
    p = proposal(candidate=expected_candidate, capability=capability)
    candidate = service.prepare("artifact.manuscript", p)
    assert isinstance(service, WritingTransformer)
    assert (
        candidate["candidate"] == expected_candidate and candidate["controls_effective"]
    )
    assert candidate["disposition"] == "human_review" and not candidate["accepted"]
    pending = service.record("artifact.manuscript", p, request=request(root, 50))
    assert pending["candidate_accepted"] is False
    assert replay_run(root).events[-1].event_type == "artifact.accepted"
    review = approve(root, candidate)
    req = request(root, 70)
    done = service.record(
        "artifact.manuscript", p, request=req, review_artifact_id=review
    )
    assert (
        done["candidate_accepted"]
        and done["disposition"] == "accepted_after_human_review"
    )
    assert (
        service.record(
            "artifact.manuscript", p, request=req, review_artifact_id=review
        )["status"]
        == "already_recorded"
    )
    bundle = json.loads((root / done["bundle_path"]).read_text())
    assert bundle["source"] == SOURCE and bundle["candidate"] == expected_candidate
    assert bundle["review_binding"]["artifact_id"] == review
    assert (root / "manuscript.txt").read_text() == SOURCE
    with pytest.raises(ValueError, match="identity conflict"):
        service.record("artifact.manuscript", p, request=req)


@pytest.mark.parametrize(
    "before,after,dimension",
    [
        ("may improve", "improves", "hedging"),
        ("in our experiments", "generally", "experimental_conditions"),
        ("5%", "6%", "numbers_units"),
        ("$x=2$", "$x=3$", "equations"),
        ("ModelX", "ModelY", "method_dataset_terms"),
        ("[@lee]", "[@kim]", "citations"),
    ],
)
def test_known_drift_rejected(tmp_path, before, after, dimension):
    root, service = prepared(tmp_path)
    p = proposal(candidate=CANDIDATE.replace(before, after))
    candidate = service.prepare("artifact.manuscript", p)
    assert candidate["disposition"] == "reject"
    assert any(
        f["dimension"] == dimension and f["status"] == "reject"
        for f in candidate["verification"]["findings"]
    )
    receipt = service.record("artifact.manuscript", p, request=request(root, 50))
    assert receipt["candidate_accepted"] is False and receipt["disposition"] == "reject"
    review = approve(root, candidate)
    with pytest.raises(ValueError, match="hard preservation"):
        service.record(
            "artifact.manuscript",
            p,
            request=request(root, 70),
            review_artifact_id=review,
        )


@pytest.mark.parametrize(
    "candidate",
    [
        CANDIDATE.replace("experiments [@lee]", "experiments").replace(
            "recall.", "recall [@lee]."
        ),
        CANDIDATE.replace("improve recall", "harm recall"),
    ],
)
def test_no_lexical_semantic_pass(candidate):
    result = SessionWritingTransformer().transform(
        SOURCE, proposal(candidate=candidate)
    )
    assert result["disposition"] == "human_review"
    assert result["verification"]["semantic_equivalence_proven"] is False
    assert (
        result["verification"]["citation_bindings"]["source"]
        != result["verification"]["citation_bindings"]["candidate"]
        or "harm" in candidate
    )


def test_stale_or_incomplete_review_blocked(tmp_path):
    root, service = prepared(tmp_path)
    p = proposal()
    candidate = service.prepare("artifact.manuscript", p)
    for number, override in enumerate(
        (
            {"candidate_sha256": "0" * 64},
            {"reviewed_dimensions": []},
            {"decision": "REJECTED"},
            {"reviewer": ""},
        ),
        60,
    ):
        review = approve(root, candidate, number, **override)
        with pytest.raises(ValueError, match="stale or incomplete"):
            service.record(
                "artifact.manuscript",
                p,
                request=request(root, 100 + number),
                review_artifact_id=review,
            )


def test_changed_source_invalid(tmp_path):
    root, service = prepared(tmp_path)
    (root / "manuscript.txt").write_text("changed")
    with pytest.raises(ValueError):
        service.prepare("artifact.manuscript", proposal())


def test_metrics_pinned_and_controls_measured():
    d = diagnose("Moreover, cats run. Moreover, cats sleep.\n\n猫跑。猫睡。")
    assert {
        k: d[k]
        for k in (
            "token_count",
            "sentence_count",
            "sentence_lengths",
            "sentence_length_variance",
            "connector_count",
            "lexical_repetition",
            "syntactic_template_proxy_repetition",
            "paragraph_lengths",
        )
    } == {
        "token_count": 10,
        "sentence_count": 4,
        "sentence_lengths": [3, 3, 2, 2],
        "sentence_length_variance": 0.25,
        "connector_count": 2,
        "lexical_repetition": 3,
        "syntactic_template_proxy_repetition": 1,
        "paragraph_lengths": [6, 4],
    }
    source = "Moreover, cats run. Moreover, cats run. Moreover, cats run."
    candidate = "Cats run, sleep and play together in the garden.\n\nBirds fly."
    p = proposal(source, candidate)
    p["controls"] = {
        "sentence_structure": "change",
        "length_rhythm": "increase",
        "connectors": "decrease",
        "lexical_repetition": "decrease",
        "syntactic_repetition": "decrease",
        "paragraph_cadence": "change",
    }
    result = SessionWritingTransformer().transform(source, p)
    assert result["controls_effective"]
    assert (
        result["watermark"]["status"] == "unsupported"
        and not result["watermark"]["verified_absence"]
    )
    assert "not authorship proof" in result["diagnostics"]["before"]["label"]


def test_unicode_cleanup_is_not_statistical_humanization():
    source = "Moreover, cats\u200brun."
    result = SessionWritingTransformer().transform(
        source, proposal(source, source.replace("\u200b", " "))
    )
    assert not result["controls_effective"]
    with pytest.raises(ValueError, match="unchanged"):
        SessionWritingTransformer().transform(SOURCE, proposal(candidate=SOURCE))


def test_optional_routing_and_cli(tmp_path, monkeypatch):
    from arw import composition
    from arw.kernel.capabilities import CapabilityUnavailable

    root, _ = prepared(tmp_path)
    original = composition.import_module

    def absent(name):
        if name.startswith("arw_writing"):
            raise ImportError("fixture absent extension")
        return original(name)

    monkeypatch.setattr(composition, "import_module", absent)
    with pytest.raises(CapabilityUnavailable):
        composition.default_router(writing_run_root=root).resolve(CAPABILITIES[0])
    monkeypatch.setattr(composition, "import_module", original)
    path = tmp_path / "proposal.json"
    path.write_bytes(canonical_json_bytes(proposal()))
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
        str(path),
    ]
    outcome = subprocess.run(command, capture_output=True, text=True, check=False)
    assert outcome.returncode == 0, outcome.stdout + outcome.stderr
    assert json.loads(outcome.stdout)["candidate"] == CANDIDATE
