from __future__ import annotations

import pytest


pytestmark = pytest.mark.skip(
    reason="Plan 03-03 owns the exact five-tool native files profile and live list/read"
)


def test_files_profile_advertises_exact_read_only_tool_set() -> None:
    pytest.fail("Plan 03-03 must replace this Wave 0 RED placeholder")


def test_list_and_read_are_bounded_restart_safe_and_query_side_effect_free() -> None:
    pytest.fail("Plan 03-03 must replace this Wave 0 RED placeholder")


def test_read_replacement_conflict_returns_no_body() -> None:
    pytest.fail("Plan 03-03 must replace this Wave 0 RED placeholder")

