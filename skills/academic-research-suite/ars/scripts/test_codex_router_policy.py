"""Codex router policy regression tests.

These tests guard adapter-only routing rules in
`skills/academic-research-suite/SKILL.md`. They are intentionally static:
runtime skill routing is performed by the Codex model, so the repository needs a
small text-level contract that prevents future syncs from dropping Codex-specific
instructions.
"""

from __future__ import annotations

from pathlib import Path


ARS_ROOT = Path(__file__).resolve().parents[1]
SUITE_ROOT = ARS_ROOT.parent
ROUTER = SUITE_ROOT / "SKILL.md"


def _router_text() -> str:
    return ROUTER.read_text(encoding="utf-8")


def test_vague_paper_topic_routes_to_socratic_before_paper_or_pipeline() -> None:
    text = _router_text()
    assert "Paper Topic Scoping Override" in text
    assert "broad topic" in text
    assert "tentative title" in text
    assert "research question is not yet precise" in text
    assert "ars/deep-research/WORKFLOW.md" in text
    assert "`socratic` mode" in text


def test_router_contains_chinese_paper_topic_triggers() -> None:
    text = _router_text()
    for trigger in ("我想做一篇論文", "題目", "研究方向", "收斂研究問題"):
        assert trigger in text


def test_router_blocks_outline_before_rq_convergence() -> None:
    text = _router_text()
    assert "Do not produce an outline" in text
    assert "until the user has converged" in text


def test_alias_router_is_not_redirected_by_socratic_override() -> None:
    # ARW: ARS v3.22.2 reversed the alias policy (explicit aliases select their
    # mode and are never redirected to Socratic scoping) but kept the stale
    # pre-3.22 assertions. These assert the v3.22.2 contract instead.
    text = _router_text()
    assert "An `ars-*` alias is never redirected by this override." in text
    assert "An alias selects its mode even when the request contains only a vague topic" in text


def test_bibliographic_clients_are_not_inferred_from_ars_full() -> None:
    text = _router_text()
    assert "Bibliographic Network Routing" in text
    assert "Do not infer this from an `ars-full` request alone" in text
    assert "explicit request to run `verify_passport.py`" in text
    assert "Manual references skip all four" in text


def test_claim_standing_is_a_separate_consent_bound_path() -> None:
    text = _router_text()
    assert "A separate user request plus affirmative, plan-bound consent" in text
    assert "not the four single-reference resolver clients" in text
    assert "absent, cancelled, invalidated, or stale consent means no call" in text
