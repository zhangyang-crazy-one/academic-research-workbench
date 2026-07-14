"""Owner-mapped red tests for the sole-writer lifecycle."""

import pytest


@pytest.mark.xfail(strict=True, reason="P04-04-T01: parent preparation lifecycle pending")
def test_p04_04_t01_parent_freezes_assignment_before_dispatch() -> None:
    assert False


@pytest.mark.xfail(strict=True, reason="P04-04-T02: proposal admission pending")
def test_p04_04_t02_worker_cannot_append_canonical_state() -> None:
    assert False


@pytest.mark.xfail(strict=True, reason="P04-04-T03: recovery lifecycle pending")
def test_p04_04_t03_late_proposal_is_rejected_stale() -> None:
    assert False
