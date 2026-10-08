"""Versioned claims and fixed multi-log snapshot contracts.

Semantic claims are explicitly registered. Byte occurrences never imply a
scientific proposition, verification, support or authorship.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BeforeValidator, Field, field_validator, model_validator

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.state.models import Sha256, StableRuntimeId, StrictModel


def _array(value: object) -> tuple:
    if isinstance(value, (list, tuple)):
        return tuple(value)
    raise ValueError("expected a JSON array")


class JournalPrefix(StrictModel):
    sequence: Annotated[int, Field(ge=1)]
    head_sha256: Sha256


class RunPrefix(StrictModel):
    run_id: StableRuntimeId
    run_manifest_sha256: Sha256
    revision: Annotated[int, Field(ge=1)]
    head_sha256: Sha256


class SnapshotManifest(StrictModel):
    schema_version: Literal["arw.claim-graph-snapshot.v1"] = (
        "arw.claim-graph-snapshot.v1"
    )
    project_id: StableRuntimeId
    journal: JournalPrefix
    runs: Annotated[tuple[RunPrefix, ...], BeforeValidator(_array)] = Field(
        max_length=32
    )
    projection_version: Literal["arw.claim-graph.v1"] = "arw.claim-graph.v1"
    adapter_matrix_version: Literal["arw.accepted-ref-adapters.v1"] = (
        "arw.accepted-ref-adapters.v1"
    )
    canonicalization_version: Literal["arw.canonical-json.v1"] = "arw.canonical-json.v1"

    @model_validator(mode="after")
    def sorted_runs(self) -> Self:
        ids = [r.run_id for r in self.runs]
        if ids != sorted(set(ids)):
            raise ValueError("snapshot run IDs must be sorted and unique")
        return self

    @property
    def sha256(self) -> str:
        return sha256_hex(canonical_json_bytes(self.model_dump(mode="json")))


class SemanticClaim(StrictModel):
    claim_id: StableRuntimeId
    revision: Annotated[int, Field(ge=1)]
    statement: Annotated[str, Field(min_length=1, max_length=8192)]
    claim_kind: Literal[
        "result", "literature", "method", "interpretation", "novelty", "other"
    ]
    supersedes: Sha256 | None = None

    @field_validator("statement")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("claim statement must not be blank")
        return value

    @model_validator(mode="after")
    def predecessor(self) -> Self:
        if (self.revision == 1) != (self.supersedes is None):
            raise ValueError("claim revisions after one require predecessor digest")
        return self

    @property
    def sha256(self) -> str:
        return sha256_hex(canonical_json_bytes(self.model_dump(mode="json")))


class Occurrence(StrictModel):
    kind: Literal["numeric_token", "figure_caption", "citation_sentence"]
    manuscript_ref: dict
    manuscript_sha256: Sha256
    offset: Annotated[int, Field(ge=0)]
    length: Annotated[int, Field(gt=0, le=1_048_576)]
    selected_sha256: Sha256
    locator_version: Literal[
        "arw.utf8-byte-span.v1", "arw.writing-citation-bindings.v2"
    ] = "arw.utf8-byte-span.v1"
    numeric_class: (
        Literal[
            "own_result",
            "literature_reported",
            "method_parameter",
            "count",
            "sample_size",
            "identifier",
            "year",
            "figure_number",
            "confidence_level",
            "unknown",
        ]
        | None
    ) = None
    derivation_id: Sha256 | None = None
    plot_value_id: StableRuntimeId | None = None
    plot_revision: Annotated[int, Field(ge=1)] | None = None

    @field_validator("manuscript_ref")
    @classmethod
    def accepted_manuscript_ref(cls, value: dict) -> dict:
        from arw.kernel.state.accepted_ref import ParentArtifactRef

        return ParentArtifactRef.model_validate(value).model_dump(mode="json")

    @model_validator(mode="after")
    def classified_number(self) -> Self:
        if self.kind != "numeric_token" and self.numeric_class is not None:
            raise ValueError("numeric classification applies only to numeric tokens")
        if (self.plot_value_id is None) != (self.plot_revision is None):
            raise ValueError("plot value binding requires identity and revision")
        if self.manuscript_ref.get("scope") != "parent-artifact":
            raise ValueError(
                "manuscript occurrence requires an accepted parent artifact"
            )
        return self

    @property
    def occurrence_id(self) -> str:
        # Classification and semantic claim bindings do not alter byte identity.
        return sha256_hex(
            canonical_json_bytes(
                {
                    "kind": self.kind,
                    "manuscript_ref": self.manuscript_ref,
                    "manuscript_sha256": self.manuscript_sha256,
                    "offset": self.offset,
                    "length": self.length,
                    "selected_sha256": self.selected_sha256,
                }
            )
        )


class SpecifiedCheck(StrictModel):
    method: StableRuntimeId
    version: Annotated[str, Field(min_length=1, max_length=128)]
    status: Literal["passed", "failed", "unsupported", "not_checked"]
    basis: dict


class EvidenceBinding(StrictModel):
    evidence_id: StableRuntimeId
    node_kind: Literal[
        "LiteratureEvidence",
        "ReferenceCheck",
        "ExperimentResult",
        "Figure",
        "Decision",
        "SelectionContext",
        "Evidence",
    ]
    adapter: Literal[
        "accepted_ref",
        "source_locator",
        "evidence_span",
        "research_binding",
        "submission_reference",
        "memory_link",
        "venue_capsule",
    ] = "accepted_ref"
    original: dict
    checks: Annotated[tuple[SpecifiedCheck, ...], BeforeValidator(_array)] = Field(
        default=(), max_length=32
    )


class ArgumentRelation(StrictModel):
    evidence_id: StableRuntimeId
    relation: Literal["supports", "contradicts", "contextualizes"]
    asserted_by: StableRuntimeId
    basis: Annotated[str, Field(min_length=1, max_length=4096)]


class AdvisoryAssessment(StrictModel):
    evidence_id: StableRuntimeId
    direction: Literal["supports", "contradicts", "contextualizes", "unknown"]
    source: Annotated[str, Field(min_length=1, max_length=2048)]
    confidence: Annotated[float, Field(ge=0, le=1)]
    provenance: dict


class ClaimRegistration(StrictModel):
    schema_version: Literal["arw.claim-registration.v1"] = "arw.claim-registration.v1"
    claim: SemanticClaim
    occurrences: Annotated[tuple[Occurrence, ...], BeforeValidator(_array)] = Field(
        min_length=1, max_length=128
    )
    evidence: Annotated[tuple[EvidenceBinding, ...], BeforeValidator(_array)] = Field(
        default=(), max_length=128
    )
    relations: Annotated[tuple[ArgumentRelation, ...], BeforeValidator(_array)] = Field(
        default=(), max_length=128
    )
    assessments: Annotated[tuple[AdvisoryAssessment, ...], BeforeValidator(_array)] = (
        Field(default=(), max_length=128)
    )
    author_id: Annotated[str, Field(min_length=1, max_length=128)]

    @field_validator("author_id")
    @classmethod
    def nonblank_author(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("author ID must not be blank")
        return value

    @model_validator(mode="after")
    def bounded_dependencies(self) -> Self:
        ids = {item.evidence_id for item in self.evidence}
        if len(ids) != len(self.evidence):
            raise ValueError("evidence IDs must be unique")
        if len({o.occurrence_id for o in self.occurrences}) != len(self.occurrences):
            raise ValueError("occurrences must be unique within a claim revision")
        if any(r.evidence_id not in ids for r in (*self.relations, *self.assessments)):
            raise ValueError(
                "relations and assessments must target registered evidence"
            )
        if len(canonical_json_bytes(self.model_dump(mode="json"))) > 131072:
            raise ValueError("claim registration exceeds byte budget")
        return self


class DeclaredAuthority(StrictModel):
    kind: Literal["declared"] = "declared"
    author_id: Annotated[str, Field(min_length=1, max_length=128)]

    @field_validator("author_id")
    @classmethod
    def nonblank_author(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("author ID must not be blank")
        return value


class DeclaredAttestation(StrictModel):
    schema_version: Literal["arw.claim-attestation.v1"] = "arw.claim-attestation.v1"
    claim_id: StableRuntimeId
    claim_revision: Annotated[int, Field(ge=1)]
    claim_sha256: Sha256
    evidence_dependency_sha256: Sha256
    statement: Annotated[str, Field(min_length=1, max_length=4096)]
    scope: Annotated[str, Field(min_length=1, max_length=2048)]
    policy_version: Annotated[str, Field(min_length=1, max_length=128)]
    graph_snapshot_sha256: Sha256
    snapshot_manifest: SnapshotManifest
    authority: DeclaredAuthority

    @model_validator(mode="after")
    def exact_snapshot(self) -> Self:
        if self.graph_snapshot_sha256 != self.snapshot_manifest.sha256:
            raise ValueError("attestation snapshot digest mismatch")
        if not all(
            getattr(self, k).strip() for k in ("statement", "scope", "policy_version")
        ):
            raise ValueError(
                "attestation statement, scope and policy must not be blank"
            )
        return self


def claim_graph_schema_documents() -> dict[str, dict]:
    documents = {
        "claim-graph-snapshot.schema.json": SnapshotManifest.model_json_schema(),
        "claim-registration.schema.json": ClaimRegistration.model_json_schema(),
        "claim-attestation.schema.json": DeclaredAttestation.model_json_schema(),
    }
    for name, value in documents.items():
        value["$id"] = f"https://academic-research-workbench.local/schemas/v1/{name}"
    from arw.kernel.state.claim_authentication import authentication_schema_documents
    documents.update(authentication_schema_documents())
    return documents
