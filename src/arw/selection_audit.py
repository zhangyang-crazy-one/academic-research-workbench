"""Read-only bridge from retained ARS candidates to explicit reading evidence."""

from __future__ import annotations

import importlib.util
import os
import stat
from pathlib import Path
from typing import Annotated, Literal

from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import Field, model_validator

from arw.kernel.capabilities import CapabilityUnavailable
from arw.kernel.core.canonical import (
    canonical_json_bytes,
    sha256_hex,
    strict_json_loads,
)
from arw.kernel.ledger.journal import locked_replay
from arw.kernel.ledger.manifests import load_artifact_manifest
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.state.models import (
    ArtifactAcceptedPayload,
    EventId,
    RunId,
    Sha256,
    StableRuntimeId,
    StrictModel,
)

MAX_INPUT = 1_048_576
MAX_FAMILIES = 240
ShortId = Annotated[str, Field(min_length=1, max_length=96)]


class SelectionAuditError(ValueError):
    code = "selection_audit_invalid"


class AcceptedRef(StrictModel):
    artifact_id: StableRuntimeId
    event_id: EventId
    event_sha256: Sha256
    manifest_sha256: Sha256
    content_sha256: Sha256


class Reading(StrictModel):
    round: Annotated[int, Field(ge=1, le=240)]
    order: Annotated[int, Field(ge=1, le=240)]
    work_family_id: ShortId
    raw_hit_id: ShortId
    stance: Literal["support", "oppose", "neutral", "unknown"] = "unknown"
    stance_basis: Literal["human_assertion", "synthetic_fixture", "unknown"] = "unknown"
    @model_validator(mode="after")
    def basis_matches(self):
        if (self.stance == "unknown") != (self.stance_basis == "unknown"):
            raise ValueError("stance and basis must both be known or unknown")
        return self


class ReadingTrace(StrictModel):
    schema_version: Literal["arw.selection-reading-trace.v1"]
    query_plan_sha256: Sha256
    candidate_ledger_sha256: Sha256
    readings: Annotated[list[Reading], Field(max_length=240)]
    reached_rounds: Annotated[int, Field(ge=0, le=240)] | None = None
    stop_reason: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    complete_log: bool = False
    @model_validator(mode="after")
    def coherent(self):
        positions = [(r.round, r.order) for r in self.readings]
        if positions != sorted(set(positions)):
            raise ValueError("reading positions must be unique and ordered")
        if self.reached_rounds is not None and any(r.round > self.reached_rounds for r in self.readings):
            raise ValueError("reading exceeds reached round")
        if self.complete_log and (self.reached_rounds is None or self.stop_reason is None):
            raise ValueError("complete log requires round reach and stop reason")
        return self


class RawRankRow(StrictModel):
    raw_hit_id: ShortId
    query_id: ShortId
    index_id: ShortId
    provider_rank: Annotated[int, Field(ge=1, le=240)]
    work_family_id: ShortId | None
    terminal_state: ShortId
    retained_raw_hit_id: ShortId | None


class SelectionReceipt(StrictModel):
    schema_version: Literal["arw.selection-audit-receipt.v1"] = "arw.selection-audit-receipt.v1"
    run_id: RunId
    run_head_sha256: Sha256
    query_plan: AcceptedRef
    retrieval_input: AcceptedRef
    candidate_ledger: AcceptedRef
    reading_trace: AcceptedRef | None
    query_plan_sha256: Sha256
    retrieval_input_sha256: Sha256
    candidate_ledger_sha256: Sha256
    pool_digest: Sha256
    raw_hit_count: Annotated[int, Field(ge=0, le=240)]
    family_count: Annotated[int, Field(ge=0, le=240)]
    selected_family_ids: Annotated[list[str], Field(max_length=40)]
    raw_rank_and_dedup: Annotated[list[RawRankRow], Field(max_length=240)]
    reading_status: Literal["recorded", "unknown"]
    readings: Annotated[list[Reading], Field(max_length=240)]
    rounds_reached: Annotated[int, Field(ge=0, le=240)] | None
    stop_reason: Annotated[str, Field(min_length=1, max_length=200)] | None
    coverage_status: Literal["known", "unknown", "zero"]
    read_family_count: Annotated[int, Field(ge=0, le=240)]
    correction_status: Literal["descriptive_only", "srs_estimate"]
    estimated_support_minus_oppose: float | None
    receipt_sha256: Sha256


def _ars_builder():
    configured = os.environ.get("ARW_PLUGIN_ROOT")
    root = Path(configured) if configured else Path(__file__).resolve().parents[2]
    if (not root.is_absolute() or not root.is_dir()
            or any(part.is_symlink() for part in (root, *root.parents))):
        raise CapabilityUnavailable("research.literature (bundled ARS root unavailable)")
    relative = Path("skills/academic-research-suite/ars/scripts/build_claim_standing_candidate_ledger.py")
    path = root / relative
    if any(part.is_symlink() for part in (path, *path.parents) if part.is_relative_to(root)):
        raise CapabilityUnavailable("research.literature (bundled ARS script unsafe)")
    try:
        if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size > MAX_INPUT:
            raise OSError("bundled ARS script is not bounded regular file")
    except OSError as error:
        raise CapabilityUnavailable("research.literature (bundled ARS script unavailable)") from error
    spec = importlib.util.spec_from_file_location("_arw_ars_candidate_builder", path)
    if spec is None or spec.loader is None:
        raise CapabilityUnavailable("research.literature (bundled ARS script cannot load)")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except (OSError, ImportError, SyntaxError) as error:
        raise CapabilityUnavailable("research.literature (bundled ARS script cannot execute)") from error
    return module


def _accepted(root: Path, state, artifact_id: str) -> tuple[AcceptedRef, dict]:
    matches = [e for e in state.events if e.event_type in {"artifact.accepted", "research_artifact_accepted"}
               and isinstance(e.payload, ArtifactAcceptedPayload) and e.payload.artifact_id == artifact_id]
    if len(matches) != 1:
        raise SelectionAuditError("artifact is not uniquely parent accepted in this run")
    event = matches[0]
    manifest = load_artifact_manifest(root, event.payload.manifest_sha256)
    if (manifest.run_id != state.run_id or manifest.artifact_id != artifact_id
            or manifest.content_sha256 != event.payload.artifact_sha256
            or manifest.media_type != "application/json"):
        raise SelectionAuditError("accepted artifact binding is inconsistent")
    raw = read_retained_bytes(root, manifest.content_path, max_bytes=MAX_INPUT)
    if sha256_hex(raw) != manifest.content_sha256:
        raise SelectionAuditError("accepted artifact bytes changed")
    data = strict_json_loads(raw)
    if not isinstance(data, dict):
        raise SelectionAuditError("accepted JSON must be an object")
    return AcceptedRef(artifact_id=artifact_id, event_id=event.event_id,
                       event_sha256=event.event_sha256, manifest_sha256=event.payload.manifest_sha256,
                       content_sha256=manifest.content_sha256), data


def _seal(receipt: dict) -> dict:
    receipt["receipt_sha256"] = sha256_hex(canonical_json_bytes(receipt))
    return SelectionReceipt.model_validate(receipt).model_dump(mode="json")


def export(root: Path, *, expected_head: str, plan_id: str, retrieval_id: str,
           ledger_id: str, trace_id: str | None = None) -> dict:
    """Return a bounded receipt while holding the canonical read-side lock."""
    with locked_replay(root, read_only=True) as (_, state):
        return _export_locked(root, state, expected_head=expected_head,
                              plan_id=plan_id, retrieval_id=retrieval_id,
                              ledger_id=ledger_id, trace_id=trace_id)


def _export_locked(root: Path, state, *, expected_head: str, plan_id: str,
                   retrieval_id: str, ledger_id: str, trace_id: str | None) -> dict:
    if state.recovery_health != "healthy" or state.last_event_sha256 != expected_head:
        raise SelectionAuditError("run history is stale or unhealthy")
    plan_ref, plan = _accepted(root, state, plan_id)
    retrieval_ref, retained = _accepted(root, state, retrieval_id)
    ledger_ref, ledger = _accepted(root, state, ledger_id)
    builder = _ars_builder()
    try:
        builder.validate_ledger(plan, retained, ledger)
        persistence = plan["consent"]["local_persistence"]
    except (KeyError, TypeError, ValueError, AttributeError, SchemaError, JsonSchemaValidationError) as error:
        raise SelectionAuditError("ARS plan, retrieval input, or ledger failed normative replay") from error
    if persistence != "explicit_local_export":
        raise SelectionAuditError("ARS consent forbids local export")
    families = ledger["work_families"]
    family_by_id = {f["work_family_id"]: f for f in families}
    selected = sorted(f["work_family_id"] for f in families if f["selection_state"] == "selected")
    trace_ref = None
    trace = None
    if trace_id is not None:
        trace_ref, trace_data = _accepted(root, state, trace_id)
        trace = ReadingTrace.model_validate(trace_data)
        if trace.query_plan_sha256 != plan["plan_sha256"] or trace.candidate_ledger_sha256 != ledger["candidate_ledger_sha256"]:
            raise SelectionAuditError("reading trace is stale")
        seen = set()
        for read in trace.readings:
            family = family_by_id.get(read.work_family_id)
            if (family is None or family["selection_state"] != "selected"
                    or read.raw_hit_id not in family["member_raw_hit_ids"]
                    or read.work_family_id in seen):
                raise SelectionAuditError("reading is outside a unique selected family")
            if read.stance_basis == "synthetic_fixture":
                raise SelectionAuditError("retained reading cannot use a synthetic fixture label")
            seen.add(read.work_family_id)
    rows = [{"raw_hit_id": r["raw_hit_id"], "query_id": r["query_id"], "index_id": r["index_id"],
             "provider_rank": r["provider_rank"], "work_family_id": r["work_family_id"],
             "terminal_state": r["terminal_state"], "retained_raw_hit_id": r["retained_raw_hit_id"]}
            for r in ledger["raw_hits"]]
    rows.sort(key=lambda row: (row["query_id"], row["index_id"], row["provider_rank"], row["raw_hit_id"]))
    reads = trace.readings if trace else []
    return _seal({"schema_version": "arw.selection-audit-receipt.v1", "run_id": state.run_id,
                  "run_head_sha256": state.last_event_sha256, "query_plan": plan_ref.model_dump(mode="json"),
                  "retrieval_input": retrieval_ref.model_dump(mode="json"), "candidate_ledger": ledger_ref.model_dump(mode="json"),
                  "reading_trace": trace_ref.model_dump(mode="json") if trace_ref else None,
                  "query_plan_sha256": plan["plan_sha256"], "retrieval_input_sha256": retained["retrieval_input_sha256"],
                  "candidate_ledger_sha256": ledger["candidate_ledger_sha256"],
                  "pool_digest": sha256_hex(canonical_json_bytes({"raw_hits": ledger["raw_hits"], "work_families": families})),
                  "raw_hit_count": len(rows), "family_count": len(families), "selected_family_ids": selected,
                  "raw_rank_and_dedup": rows, "reading_status": "recorded" if trace and trace.complete_log else "unknown",
                  "readings": [r.model_dump(mode="json") for r in reads],
                  "rounds_reached": trace.reached_rounds if trace else None,
                  "stop_reason": trace.stop_reason if trace else None,
                  "coverage_status": ("unknown" if trace is None or not trace.complete_log else
                                      "zero" if not reads else "known"),
                  "read_family_count": len(reads), "correction_status": "descriptive_only",
                  "estimated_support_minus_oppose": None})


class FixtureFamily(StrictModel):
    work_family_id: ShortId
    raw_hit_ids: Annotated[list[ShortId], Field(min_length=1, max_length=8)]
    label: Literal["support", "oppose", "neutral", "unknown"]
    label_basis: Literal["synthetic_fixture"] = "synthetic_fixture"


class FixtureCitation(StrictModel):
    work_family_id: ShortId
    raw_hit_id: ShortId
    source_text: Annotated[str, Field(min_length=1, max_length=1000)]
    byte_start: Annotated[int, Field(ge=0, le=1000)]
    byte_end: Annotated[int, Field(ge=1, le=1000)]
    quote_sha256: Sha256

    @model_validator(mode="after")
    def valid_locator(self):
        raw = self.source_text.encode("utf-8")
        if self.byte_end > len(raw) or self.byte_end <= self.byte_start or sha256_hex(raw[self.byte_start:self.byte_end]) != self.quote_sha256:
            raise ValueError("fixture citation quote does not match exact source bytes")
        return self


class PoolFixture(StrictModel):
    schema_version: Literal["arw.selection-pool-fixture.v1"]
    origin: Literal["self_authored_synthetic"]
    claim: Annotated[str, Field(min_length=1, max_length=300)]
    families: Annotated[list[FixtureFamily], Field(min_length=1, max_length=40)]
    original_order: Annotated[list[ShortId], Field(min_length=1, max_length=40)]
    original_citations: Annotated[list[FixtureCitation], Field(min_length=1, max_length=8)]
    budget: Annotated[int, Field(ge=1, le=40)]
    original_stop_reason: Annotated[str, Field(min_length=1, max_length=200)]
    @model_validator(mode="after")
    def consistent(self):
        ids = [f.work_family_id for f in self.families]
        raw = [r for f in self.families for r in f.raw_hit_ids]
        if len(ids) != len(set(ids)) or len(raw) != len(set(raw)):
            raise ValueError("fixture IDs must be unique")
        if set(self.original_order) != set(ids) or len(self.original_order) != len(ids):
            raise ValueError("original order must contain each family exactly once")
        if len(raw) > MAX_FAMILIES:
            raise ValueError("fixture raw-hit pool exceeds ARS cap")
        read_ids = set(self.original_order[:self.budget])
        by_id = {f.work_family_id: f for f in self.families}
        if any(c.work_family_id not in read_ids or
               c.raw_hit_id not in by_id[c.work_family_id].raw_hit_ids
               for c in self.original_citations):
            raise ValueError("fixture citation must locate an originally read raw hit")
        if self.budget > len(ids):
            raise ValueError("budget exceeds pool")
        return self


def _direction(labels: list[str]) -> str:
    score = sum({"support": 1, "oppose": -1, "neutral": 0, "unknown": 0}[x] for x in labels)
    if "unknown" in labels:
        return "unknown"
    return "support_tilt" if score > 0 else "oppose_tilt" if score < 0 else "balanced"


def replay_fixture(fixture: PoolFixture) -> dict:
    """Replay a declared synthetic pool; labels are never inferred from papers."""
    by_id = {f.work_family_id: f for f in fixture.families}
    pool_digest = sha256_hex(canonical_json_bytes(fixture.model_dump(mode="json")))
    def run(order: list[str]) -> dict:
        reads = order[:fixture.budget]
        labels = [by_id[x].label for x in reads]
        score = sum({"support": 1, "oppose": -1, "neutral": 0, "unknown": 0}[x] for x in labels)
        unknown = labels.count("unknown")
        return {"read_family_ids": reads, "labels": labels, "direction": _direction(labels),
                "support_minus_oppose": score if not unknown else None,
                "score_bounds": [score - unknown, score + unknown],
                "unread_family_ids": order[fixture.budget:],
                "reached_rounds": 1, "stop_reason": fixture.original_stop_reason}
    stable = list(fixture.original_order)
    positions = {value: i for i, value in enumerate(stable)}
    support = sorted(stable, key=lambda x: (0 if by_id[x].label == "support" else 1, positions[x]))
    oppose = sorted(stable, key=lambda x: (0 if by_id[x].label == "oppose" else 1, positions[x]))
    scenarios = {"original": run(stable), "support_first": run(support), "oppose_first": run(oppose)}
    receipt = {"schema_version": "arw.selection-paired-replay.v1", "mode": "synthetic_fixture",
               "pool_digest": pool_digest, "claim": fixture.claim, "budget": fixture.budget,
               "family_count": len(stable), "raw_hit_count": sum(len(f.raw_hit_ids) for f in fixture.families),
               "duplicate_version_count": sum(len(f.raw_hit_ids) - 1 for f in fixture.families),
               "original_citation_locator_valid": True,
               "original_citation_raw_hit_ids": [c.raw_hit_id for c in fixture.original_citations],
               "unread_opposing_family_ids": [x for x in stable[fixture.budget:] if by_id[x].label == "oppose"],
               "scenarios": scenarios, "conclusion_direction_changed":
               scenarios["support_first"]["direction"] != scenarios["oppose_first"]["direction"],
               "reading_set_changed": set(scenarios["support_first"]["read_family_ids"]) != set(scenarios["oppose_first"]["read_family_ids"]),
               "correction_status": "descriptive_only", "scientific_assertion": False,
               "srs_example": srs_synthetic_example(["support", "support", "oppose", "neutral"], [0, 2])}
    receipt["receipt_sha256"] = sha256_hex(canonical_json_bytes(receipt))
    return receipt


def srs_synthetic_example(labels: list[str], selected_indexes: list[int]) -> dict:
    """Recompute finite SRS example with known inclusion, no production estimator claim."""
    from itertools import combinations
    if not 1 <= len(selected_indexes) <= len(labels) <= 12 or len(set(selected_indexes)) != len(selected_indexes):
        raise SelectionAuditError("invalid synthetic SRS sample")
    if any(i < 0 or i >= len(labels) for i in selected_indexes):
        raise SelectionAuditError("synthetic SRS index outside population")
    if any(x not in {"support", "oppose", "neutral", "unknown"} for x in labels):
        raise SelectionAuditError("invalid synthetic SRS label")
    n, k = len(labels), len(selected_indexes)
    outcomes = list(combinations(range(n), k))
    pi = sum(0 in draw for draw in outcomes) / len(outcomes)
    if any(labels[i] == "unknown" for i in selected_indexes) or not selected_indexes:
        estimate = None
    else:
        estimate = sum({"support": 1, "oppose": -1, "neutral": 0}[labels[i]] / pi for i in selected_indexes)
    return {"population_size": n, "draw_size": k, "possible_draws": len(outcomes),
            "inclusion_probability": pi, "selected_indexes": selected_indexes,
            "reached_rounds": 1, "estimator": "horvitz_thompson" if estimate is not None else "unknown",
            "estimated_support_minus_oppose": estimate, "basis": "synthetic_enumerated_srs"}
