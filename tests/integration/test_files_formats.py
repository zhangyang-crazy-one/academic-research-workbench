from __future__ import annotations

import pytest


pytestmark = pytest.mark.skip(
    reason="Plan 03-04 owns deterministic search, outlines, context, CJK, and PDF registration"
)


def test_exact_and_full_text_search_cover_cjk_without_raw_fts_syntax() -> None:
    pytest.fail("Plan 03-04 must replace this Wave 0 RED placeholder")


def test_declared_research_formats_have_deterministic_outline_behavior() -> None:
    pytest.fail("Plan 03-04 must replace this Wave 0 RED placeholder")


def test_only_complete_accessible_registered_pdf_text_is_searchable() -> None:
    pytest.fail("Plan 03-04 must replace this Wave 0 RED placeholder")

