from __future__ import annotations


def test_status_json_and_text_render_the_same_runtime_state() -> None:
    from arw.kernel.ledger.reducer import RuntimeState
    from arw.kernel.state.status import build_status_report, render_status_text

    state = RuntimeState.empty(
        run_id="run-00000000-0000-4000-8000-000000000001",
        workflow_definition_id="core-research.v1",
    )
    report = build_status_report(state)
    payload = report.model_dump(mode="json")
    assert set(payload) >= {
        "schema_version",
        "reducer_version",
        "run_id",
        "current_stage",
        "accepted_revision",
        "ledger_head_sha256",
        "current_passport_sha256",
        "recovery_health",
        "blockers",
        "pending_human_decisions",
        "active_attempts",
        "legal_next_transitions",
    }
    text = render_status_text(report)
    assert report.run_id in text
    assert report.current_stage in text
    assert str(report.accepted_revision) in text
