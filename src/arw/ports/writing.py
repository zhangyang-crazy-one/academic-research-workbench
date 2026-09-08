"""Optional writing boundary; proposals never confer evidence authority."""

from typing import Protocol, runtime_checkable

CAPABILITIES = tuple(
    "writing." + name
    for name in (
        "academic_rewrite",
        "naturalize",
        "statistical_humanize",
        "claim_preserving_rewrite",
        "citation_aware_rewrite",
    )
)


@runtime_checkable
class WritingTransformer(Protocol):
    def transform(self, source: str, proposal: dict) -> dict: ...
    def verify_preservation(
        self,
        source: str,
        candidate: str,
        *,
        protected_terms: list[str],
        protected_spans: list[str],
    ) -> dict: ...
