"""Producer and CLI reader share a whole-envelope byte budget."""

import pytest

from arw.cli_disclosure import read
from arw.kernel.core.canonical import canonical_json_bytes
from arw.kernel.ledger import ai_disclosure
from arw.kernel.ledger.ai_disclosure import make_draft, replay_draft
from arw.kernel.state.ai_disclosure import AIActivityReceipt
from tests.integration.test_ai_disclosure import accept, policy
from tests.unit.test_accepted_refs import accepted_fixture


def test_whole_draft_budget_and_cli_roundtrip(tmp_path, monkeypatch):
    run, ctx, ref, _ = accepted_fixture(tmp_path, b"Synthetic manuscript")
    record = AIActivityReceipt(
        activity_id="activity.one",
        target=ref,
        usage="ai_drafted",
        system="synthetic",
        harness="synthetic",
        model="synthetic",
        detail="x" * 2048,
    )
    accept(
        run, ref, record.model_dump(mode="json"), "ai-activity-receipt", "receipt.one"
    )
    draft = make_draft(ctx, policy())
    raw = canonical_json_bytes(draft)
    summary_bytes = len(canonical_json_bytes(draft["summary"]))
    assert summary_bytes < len(raw)
    path = run / "draft.json"
    path.write_bytes(raw)
    monkeypatch.setattr(ai_disclosure, "MAX_BYTES", len(raw))
    assert read(path) == draft and replay_draft(read(path), ctx) == draft
    assert make_draft(ctx, policy()) == draft
    monkeypatch.setattr(ai_disclosure, "MAX_BYTES", len(raw) - 1)
    with pytest.raises(ValueError, match="draft output budget"):
        make_draft(ctx, policy())
    with pytest.raises(ValueError, match="input budget"):
        read(path)
    assert summary_bytes < ai_disclosure.MAX_BYTES
