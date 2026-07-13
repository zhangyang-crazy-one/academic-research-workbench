from __future__ import annotations

import pytest


pytestmark = pytest.mark.skip(
    reason="Plan 03-02 owns create/modify/rename/delete/ignore/extractor-version synchronization"
)


def test_generation_change_matrix_preserves_only_unambiguous_identity() -> None:
    pytest.fail("Plan 03-02 must replace this Wave 0 RED placeholder")


def test_generation_removes_deleted_ignored_and_old_extraction_body() -> None:
    pytest.fail("Plan 03-02 must replace this Wave 0 RED placeholder")

