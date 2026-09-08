"""ArtifactInspector port: non-mutating artifact integrity inspection.

Derived from the v1 integrity evaluation surface
(`arw.kernel.artifacts.integrity`). Inspection never mutates the artifact;
privacy sanitation is a separate, explicit, ledger-recorded operation.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from arw.kernel.artifacts.integrity import IntegrityEvaluation, IntegrityReceipt
from arw.kernel.state.models import CanonicalEvent
from arw.kernel.state.research_artifact import (
    RendererIdentity,
    ResearchArtifactIR,
    ValidationResults,
    VisualReviewer,
)


class ArtifactDiagnosticModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class DetectorResult(ArtifactDiagnosticModel):
    status: Literal[
        "detected", "not_detected", "unsupported", "unknown", "not_applicable"
    ]
    reason_code: str


class UnicodeFinding(ArtifactDiagnosticModel):
    codepoint: str
    category: Literal["invisible", "bidi", "tag", "exotic_space"]
    character_offset: int = Field(ge=0)
    byte_offset: int = Field(ge=0)


class ArtifactInspection(ArtifactDiagnosticModel):
    schema_version: Literal["arw.artifact-inspection.v1"] = "arw.artifact-inspection.v1"
    inspector_version: Literal["unicode-explicit.v1"] = "unicode-explicit.v1"
    status: Literal["inspected", "unsupported"]
    reason_code: str
    content_sha256: str | None
    input_bytes: int = Field(ge=0)
    detectors: dict[str, DetectorResult]
    findings: list[UnicodeFinding] = Field(default_factory=list, max_length=256)
    category_counts: dict[str, int] = Field(default_factory=dict)
    total_findings: int = Field(default=0, ge=0)
    truncated: bool = False
    interpretation: str = (
        "Potential explicit signals only; not watermark absence or authorship proof."
    )


class UnicodeSanitization(ArtifactDiagnosticModel):
    schema_version: Literal["arw.unicode-sanitization.v1"] = (
        "arw.unicode-sanitization.v1"
    )
    policy_version: Literal["selected-codepoint-removal.v1"] = (
        "selected-codepoint-removal.v1"
    )
    selected_codepoints: list[str]
    derived_text: str
    removed_counts: dict[str, int]
    only_selected_changed: bool
    before: ArtifactInspection
    after: ArtifactInspection


class ArtifactInspector(Protocol):
    """Evaluate artifact integrity receipts against freshness policy."""

    def evaluate(
        self,
        receipt: IntegrityReceipt,
        subject_sha256: str | None,
        input_sha256: Sequence[str] | None,
        now: datetime | str | None = None,
    ) -> IntegrityEvaluation: ...

    def inspect_bytes(
        self, content: bytes, *, detectors: Sequence[str] | None = None
    ) -> ArtifactInspection: ...


class ArtifactIRBuilder(Protocol):
    """Build an IR using bounded projection lookups and canonical evidence."""

    def build(
        self,
        specification: dict[str, object],
        *,
        run_root: Path,
        store_path: Path | None = None,
    ) -> ResearchArtifactIR: ...


class ArtifactRenderer(Protocol):
    """Render with a pinned identity and deterministic normalization policy."""

    @property
    def identity(self) -> RendererIdentity: ...

    def render(self, ir: ResearchArtifactIR) -> bytes: ...


class ArtifactValidator(Protocol):
    """Return distinct schema, provenance, semantic, render and visual outcomes."""

    def validate(
        self,
        ir: ResearchArtifactIR,
        output: bytes,
        *,
        run_root: Path,
        events: Sequence[CanonicalEvent],
        visual_review_id: str | None = None,
    ) -> tuple[ValidationResults, tuple[str, ...], VisualReviewer | None, bool]: ...
