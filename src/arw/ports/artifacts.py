"""ArtifactInspector port: non-mutating artifact integrity inspection.

Derived from the v1 integrity evaluation surface
(`arw.kernel.artifacts.integrity`). Inspection never mutates the artifact;
privacy sanitation is a separate, explicit, ledger-recorded operation.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from arw.kernel.artifacts.integrity import IntegrityEvaluation, IntegrityReceipt


class ArtifactInspector(Protocol):
    """Evaluate artifact integrity receipts against freshness policy."""

    def evaluate(
        self,
        receipt: IntegrityReceipt,
        subject_sha256: str | None,
        input_sha256: Sequence[str] | None,
        now: datetime | str | None = None,
    ) -> IntegrityEvaluation: ...
