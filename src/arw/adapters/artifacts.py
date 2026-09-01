"""ArtifactInspector adapter for the v1 integrity evaluation surface."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from arw.kernel.artifacts.integrity import (
    IntegrityEvaluation,
    IntegrityReceipt,
    evaluate_integrity_receipt,
)


class ArtifactIntegrityAdapter:
    """ArtifactInspector over the v1 receipt evaluation."""

    def evaluate(
        self,
        receipt: IntegrityReceipt,
        subject_sha256: str | None,
        input_sha256: Sequence[str] | None,
        now: datetime | str | None = None,
    ) -> IntegrityEvaluation:
        return evaluate_integrity_receipt(
            receipt, subject_sha256, input_sha256, now=now
        )
