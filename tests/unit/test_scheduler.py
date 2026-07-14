"""Owner-mapped red tests for the deterministic Phase 4 scheduler."""

import pytest


@pytest.mark.xfail(strict=True, reason="P04-03-T01: scheduler implementation pending")
def test_p04_03_t01_frozen_cursor_is_permutation_invariant() -> None:
    assert False


@pytest.mark.xfail(strict=True, reason="P04-03-T01: retry/cancel policy implementation pending")
def test_p04_03_t01_retry_taxonomy_is_bounded() -> None:
    assert False
