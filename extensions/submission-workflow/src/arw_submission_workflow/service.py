"""Non-authoritative submission preparation provider.

All canonical writes remain in the ARW parent control plane.  This adapter only
normalizes strict domain values and returns observations that the parent must
bind to accepted artifacts before using them in a gate.
"""

from __future__ import annotations

from collections.abc import Mapping

from arw.kernel.state.submission import (
    ReviewResponse,
    ReviewRound,
    SubmissionCheck,
    SubmissionPacket,
    SubmissionVerifierObservation,
)


class SubmissionWorkflowService:
    """Optional provider resolved only from ``arw.composition``."""

    provider_schema_version = "arw.submission-provider.v1"

    @staticmethod
    def _mapping(value: Mapping[str, object] | dict[str, object]) -> dict[str, object]:
        if not isinstance(value, Mapping):
            raise TypeError("submission provider input must be a JSON object")
        return dict(value)

    def prepare(self, value: dict[str, object]) -> SubmissionPacket:
        return SubmissionPacket.model_validate(self._mapping(value))

    def normalize_review(self, value: dict[str, object]) -> ReviewRound:
        return ReviewRound.model_validate(self._mapping(value))

    def normalize_response(self, value: dict[str, object]) -> ReviewResponse:
        return ReviewResponse.model_validate(self._mapping(value))

    def observe_checks(self, value: dict[str, object]) -> tuple[SubmissionCheck, ...]:
        raw_checks = self._mapping(value).get("checks")
        if not isinstance(raw_checks, list) or len(raw_checks) > 256:
            raise TypeError("submission check observation requires a checks array")
        return tuple(SubmissionCheck.model_validate(item) for item in raw_checks)

    def observe_verifier(self, value: dict[str, object]) -> SubmissionVerifierObservation:
        """Normalize a bounded verifier receipt without executing the verifier."""

        payload = self._mapping(value)
        checks = payload.get("checks")
        if not isinstance(checks, list) or len(checks) > 256:
            raise TypeError("submission verifier observation requires a checks array")
        payload["checks"] = tuple(checks)
        return SubmissionVerifierObservation.model_validate(payload)
