"""Optional submission workflow provider boundary.

The provider prepares and normalizes domain values; it never owns canonical
artifact admission, gates, provenance, retries, or journal transitions.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from arw.kernel.state.submission import (
    ReviewResponse,
    ReviewRound,
    SubmissionCheck,
    SubmissionPacket,
    SubmissionVerifierObservation,
)

CAPABILITIES = (
    "submission.prepare",
    "submission.review_normalize",
    "submission.check_observe",
)
PROVIDER_SCHEMA_VERSION: Literal["arw.submission-provider.v1"] = (
    "arw.submission-provider.v1"
)


@runtime_checkable
class SubmissionWorkflowProvider(Protocol):
    """Non-authoritative preparation and observation operations."""

    provider_schema_version: Literal["arw.submission-provider.v1"]

    def prepare(self, value: dict[str, object]) -> SubmissionPacket: ...

    def normalize_review(self, value: dict[str, object]) -> ReviewRound: ...

    def observe_checks(self, value: dict[str, object]) -> tuple[SubmissionCheck, ...]: ...

    def observe_verifier(self, value: dict[str, object]) -> SubmissionVerifierObservation: ...

    def normalize_response(self, value: dict[str, object]) -> ReviewResponse: ...


__all__ = ["CAPABILITIES", "PROVIDER_SCHEMA_VERSION", "SubmissionWorkflowProvider"]
