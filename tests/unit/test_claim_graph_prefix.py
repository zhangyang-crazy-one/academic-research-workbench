"""Historical run views validate the same canonical prefix, never a later tail."""
from pathlib import Path

import pytest

from arw.kernel.ledger.journal import (
    JournalError, append_probe, initialize_run, replay_run, replay_run_prefix,
)
from arw.kernel.state.models import AppendProbeRequest
from tests.unit.test_narrative import project, run_request


def test_prefix_survives_append_and_torn_tail(tmp_path: Path):
    root = project(tmp_path)
    request = run_request(root)
    run = root / 'runs/one'
    initial = initialize_run(run, request)
    manifest_sha = initial.events[0].payload.manifest_sha256
    append_probe(run, AppendProbeRequest.model_validate({
        'schema_version':'1.0.0', 'event_type':'baseline.probe_recorded', 'run_id': request.run_id,
        'event_id':'evt-00000000-0000-4000-8000-000000000002',
        'command_id':'cmd-00000000-0000-4000-8000-000000000002',
        'occurred_at':'2026-07-13T00:01:00Z', 'actor_id':'parent.runtime',
        'expected_revision':1, 'payload':{'probe_id':'probe.test', 'status':'pass', 'summary':'test'},
    }))
    assert replay_run(run).revision == 2
    (run/'events.jsonl').open('ab').write(b'{bad tail')
    prefix = replay_run_prefix(run, revision=1, expected_head_sha256=initial.last_event_sha256,
                               expected_manifest_sha256=manifest_sha)
    assert prefix.events == initial.events
    assert prefix.recovery_health == 'healthy'
    with pytest.raises(JournalError, match='head digest'):
        replay_run_prefix(run, revision=1, expected_head_sha256='0'*64)
    with pytest.raises(JournalError, match='manifest digest'):
        replay_run_prefix(run, revision=1, expected_head_sha256=initial.last_event_sha256,
                          expected_manifest_sha256='0'*64)


def test_prefix_rejects_modified_chain(tmp_path: Path):
    root = project(tmp_path)
    request = run_request(root)
    run = root/'runs/one'
    initial = initialize_run(run, request)
    raw = (run/'events.jsonl').read_bytes()
    (run/'events.jsonl').write_bytes(raw.replace(b'parent.runtime', b'parent.tampered'))
    with pytest.raises(JournalError, match='trustworthy prefix'):
        replay_run_prefix(run, revision=1, expected_head_sha256=initial.last_event_sha256)
