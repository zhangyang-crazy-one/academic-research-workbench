"""Session adapter applies declared exact-span edits; generation is explicit."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.ports.writing import CAPABILITIES

from .diagnostics import CONTROL_METRICS, diagnose, effects
from .preservation import verify


class Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class Edit(Strict):
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    before: str
    replacement: str


class Generation(Strict):
    provider: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=128)
    prompt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    parameters: dict[str, str | int | float | bool] = Field(max_length=32)


class Proposal(Strict):
    schema_version: Literal["arw.writing-proposal.v1"]
    capability: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    author_target: str = Field(min_length=1, max_length=4096)
    language: Literal["en", "zh", "en-zh"]
    protected_terms: list[str] = Field(max_length=100)
    protected_spans: list[str] = Field(max_length=100)
    controls: dict[str, Literal["change", "increase", "decrease"]] = Field(
        min_length=1, max_length=6
    )
    generation: Generation
    edits: list[Edit] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def supported(self):
        if self.capability not in CAPABILITIES or set(self.controls) - set(
            CONTROL_METRICS
        ):
            raise ValueError("unsupported capability or control")
        if self.controls.get("paragraph_cadence", "change") != "change":
            raise ValueError("paragraph cadence supports change only")
        if any(not s for s in self.protected_terms + self.protected_spans):
            raise ValueError("empty protected content")
        return self


class SessionWritingTransformer:
    def verify_preservation(
        self, source, candidate, *, protected_terms, protected_spans
    ):
        return verify(source, candidate, protected_terms, protected_spans)

    def transform(self, source, proposal):
        p = Proposal.model_validate(proposal)
        if (
            len(source.encode()) > 65536
            or sha256_hex(source.encode()) != p.source_sha256
        ):
            raise ValueError("source size or digest mismatch")
        pieces, cursor = [], 0
        for edit in p.edits:
            if (
                edit.start < cursor
                or edit.end < edit.start
                or edit.end > len(source)
                or source[edit.start : edit.end] != edit.before
            ):
                raise ValueError("overlapping, unordered or mismatched exact-span edit")
            pieces.extend((source[cursor : edit.start], edit.replacement))
            cursor = edit.end
        candidate = "".join(pieces) + source[cursor:]
        if len(candidate.encode()) > 65536 or candidate == source:
            raise ValueError("unchanged or oversized candidate")
        before, after = diagnose(source), diagnose(candidate)
        effect = effects(before, after, p.controls)
        verification = self.verify_preservation(
            source,
            candidate,
            protected_terms=p.protected_terms,
            protected_spans=p.protected_spans,
        )
        return {
            "schema_version": "arw.writing-candidate.v1",
            "transformer": "session-exact-span",
            "transformer_version": "1",
            "proposal": p.model_dump(mode="json"),
            "proposal_sha256": sha256_hex(
                canonical_json_bytes(p.model_dump(mode="json"))
            ),
            "source": source,
            "source_sha256": p.source_sha256,
            "candidate": candidate,
            "candidate_sha256": sha256_hex(candidate.encode()),
            "diagnostics": {"before": before, "after": after, "controls": effect},
            "controls_effective": all(
                v["status"] == "effective" for v in effect.values()
            ),
            "watermark": {
                "status": "unsupported",
                "detector": None,
                "model_key_assumptions": None,
                "verified_absence": False,
                "reason": "No qualified statistical detector configured; surface metrics do not establish watermark removal",
            },
            "verification": verification,
            "verification_sha256": sha256_hex(canonical_json_bytes(verification)),
            "disposition": verification["disposition"],
            "accepted": False,
        }
