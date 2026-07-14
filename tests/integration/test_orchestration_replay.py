"""Owner-mapped red tests for canonical replay and recovery."""

import pytest


@pytest.mark.xfail(strict=True, reason="P04-04-T03: cold replay implementation pending")
def test_p04_04_t03_cold_replay_does_not_read_projection_state() -> None:
    assert False


@pytest.mark.xfail(strict=True, reason="P04-04-T03: orphan recovery implementation pending")
def test_p04_04_t03_orphan_attempt_is_interrupted_and_requeued_once() -> None:
    assert False
