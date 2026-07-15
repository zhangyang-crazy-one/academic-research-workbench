from __future__ import annotations

from arw.audit_dossier import assemble_audit_dossier, replay_audit_dossier, render_audit_dossier_json, render_audit_dossier_markdown
from arw.journal import ReplayState


def test_projection_loss_keeps_canonical_dossier_authority_boundary() -> None:
    state = ReplayState(run_id="run-00000000-0000-4000-8000-000000000031", revision=0, last_event_sha256="a" * 64, event_count=0, event_ids=frozenset(), command_ids=frozenset(), events=(), validated=True)
    dossier = assemble_audit_dossier(replay_state=state, run_manifest_sha256="b" * 64, generated_at="2026-07-16T00:00:00Z")
    cold = replay_audit_dossier(dossier, projection_available=False)
    assert cold.blockers[-1].code == "projection_unavailable"
    assert cold.technical_qualification.verdict == dossier.technical_qualification.verdict
    assert cold.release_qualification.verdict == "BLOCKED"
    assert "SQLite" not in render_audit_dossier_json(cold).decode()
    assert "non-authoritative" in render_audit_dossier_markdown(cold).decode()


def test_frozen_replay_rerenders_exact_bytes() -> None:
    state = ReplayState(run_id="run-00000000-0000-4000-8000-000000000031", revision=0, last_event_sha256="a" * 64, event_count=0, event_ids=frozenset(), command_ids=frozenset(), events=(), validated=True)
    one = assemble_audit_dossier(replay_state=state, run_manifest_sha256="b" * 64, generated_at="2026-07-16T00:00:00Z")
    two = replay_audit_dossier(one)
    assert one.canonical_bytes() == two.canonical_bytes()
    assert render_audit_dossier_markdown(one) == render_audit_dossier_markdown(two)
