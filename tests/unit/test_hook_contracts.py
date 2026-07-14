"""Owner-mapped red tests for observational hook contracts."""

import pytest


@pytest.mark.xfail(strict=True, reason="P04-03-T03: hook contract implementation pending")
def test_p04_03_t03_hook_status_cannot_be_authority_input() -> None:
    assert False


@pytest.mark.xfail(strict=True, reason="P04-03-T03: continuation budget implementation pending")
def test_p04_03_t03_continuation_is_at_most_once_per_key() -> None:
    assert False
