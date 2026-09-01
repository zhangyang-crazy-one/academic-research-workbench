from __future__ import annotations

from itertools import permutations

from arw.audit_dossier import assemble_audit_dossier, render_audit_dossier_json
from arw.kernel.ledger.journal import ReplayState


def test_reference_permutation_has_one_canonical_order() -> None:
    for permutation in permutations(["a" * 64, "b" * 64, "c" * 64]):
        _assert_permutation(permutation)


def _assert_permutation(permutation: tuple[str, ...]) -> None:
    state = ReplayState(run_id="run-00000000-0000-4000-8000-000000000031", revision=0, last_event_sha256="a" * 64, event_count=0, event_ids=frozenset(), command_ids=frozenset(), events=(), validated=True)
    dossier = assemble_audit_dossier(
        replay_state=state,
        run_manifest_sha256="d" * 64,
        generated_at="2026-07-16T00:00:00Z",
        evidence={"passports": permutation},
    )
    assert dossier.passport_sha256 == tuple(sorted(set(permutation)))
    assert render_audit_dossier_json(dossier).endswith(b"\n")
