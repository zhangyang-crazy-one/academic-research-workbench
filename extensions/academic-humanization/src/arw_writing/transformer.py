"""Session adapter applies declared exact-span edits; generation is explicit."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.state.narrative_realization import NarrativeRealization
from arw.ports.writing import CAPABILITIES

from .detection import compare
from .diagnostics import CONTROL_METRICS, diagnose, effects
from .fact_audit import audit as fact_audit
from .preservation import verify
from .review_rules import plan as review_plan

# One manuscript (source or candidate) per writing proposal. Receipts embed the
# source and candidate once, so they stay well inside the retained-file budget.
MAX_TEXT_BYTES = 1_048_576


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
    narrative_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    narrative_realization: NarrativeRealization | None = None
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

    def transform(self, source, proposal, *, detector_config=None, allow_network=False):
        p = Proposal.model_validate(proposal)
        if (
            len(source.encode()) > MAX_TEXT_BYTES
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
        if len(candidate.encode()) > MAX_TEXT_BYTES or candidate == source:
            raise ValueError("unchanged or oversized candidate")
        before, after = diagnose(source), diagnose(candidate)
        effect = effects(before, after, p.controls)
        verification = self.verify_preservation(
            source,
            candidate,
            protected_terms=p.protected_terms,
            protected_spans=p.protected_spans,
        )
        detection = compare(
            source,
            candidate,
            detector_config or {"detectors": []},
            allow_network=allow_network,
        )
        facts = fact_audit(source, candidate)
        verification["fact_lock"] = {
            "status": facts["status"],
            "mechanical_status": facts["mechanical_status"],
            "semantic_status": facts["semantic_status"],
        }
        if facts["mechanical_status"] == "failed":
            verification["disposition"] = "reject"
        rules = review_plan(source, candidate)
        verification["rule_review"] = {
            "semantic_status": "human_review_required",
            "plan": rules,
        }
        return {
            "schema_version": "arw.writing-candidate.v1",
            "transformer": "session-exact-span",
            "transformer_version": "1",
            "proposal": p.model_dump(mode="json", exclude_none=True),
            "proposal_sha256": sha256_hex(
                canonical_json_bytes(p.model_dump(mode="json", exclude_none=True))
            ),
            "source": source,
            "source_sha256": p.source_sha256,
            "candidate": candidate,
            "candidate_sha256": sha256_hex(candidate.encode()),
            "diagnostics": {"before": before, "after": after, "controls": effect},
            "detection": detection,
            "fact_lock": facts,
            "rule_review": {"status": "not_run", "report": None},
            "controls_effective": all(
                v["status"] == "effective" for v in effect.values()
            ),
            "watermark": {
                "status": "not_run"
                if detector_config is None
                else next(
                    (
                        p["after"]["status"]
                        for p in detection["pairs"]
                        if p["after"]["kind"] == "watermark"
                    ),
                    "not_run",
                ),
                "detector": None,
                "model_key_assumptions": None,
                "verified_absence": False,
                "reason": "See detection pairs; no score verifies watermark absence",
            },
            "verification": verification,
            "verification_sha256": sha256_hex(canonical_json_bytes(verification)),
            "disposition": verification["disposition"],
            "accepted": False,
        }
