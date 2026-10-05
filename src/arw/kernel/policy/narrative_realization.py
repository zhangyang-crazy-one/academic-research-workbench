"""Deterministic paper-realization checks over retained source bytes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, NoReturn

from arw.kernel.core.canonical import sha256_hex, strict_json_loads
from arw.kernel.ledger.manifests import load_artifact_manifest
from arw.kernel.ledger.narrative_content import (
    NarrativeRealizationError,
    verify_realization_source,
)
from arw.kernel.ledger.narrative_content import (
    paragraph_bounds as _paragraph_bounds,
)
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.state.narrative import NarrativeSnapshot
from arw.kernel.state.narrative_realization import (
    HypothesisHistory,
    NarrativeRealization,
)

STAGE_KINDS = {
    "narrative-outline": "outline",
    "paper-outline": "outline",
    "outline": "outline",
    "evidence-map": "outline",
    "narrative-blueprint": "blueprint",
    "argument-blueprint": "blueprint",
    "blueprint": "blueprint",
    "narrative-draft": "draft",
    "paper-draft": "draft",
    "draft": "draft",
    "manuscript": "draft",
    "paper-manuscript": "draft",
    "writing-derived": "draft",
}


def _fail(code: str, message: str) -> NoReturn:
    raise NarrativeRealizationError(code, message)


def _heading_only(raw: bytes) -> bool:
    """Recognize adjacent ATX/Setext blocks, including multiline Setext titles."""
    lines = raw.decode("utf-8").splitlines()
    atx = re.compile(r" {0,3}#{1,6}(?:[ \t]+.*|[ \t]*)")
    underline = re.compile(r" {0,3}(?:=+|-+)[ \t]*")
    block_start = re.compile(r"(?:\t| {4}| {0,3}(?:>|(?:[-+*]|\d+[.)])[ \t]+|`{3,}|~{3,}|<))")
    thematic_break = re.compile(r" {0,3}(?:(?:\*[ \t]*){3,}|(?:_[ \t]*){3,}|(?:-[ \t]*){3,})")
    index = 0
    while index < len(lines):
        if atx.fullmatch(lines[index]):
            index += 1
            continue
        start = index
        while (index < len(lines) and lines[index].strip()
               and not atx.fullmatch(lines[index])
               and not underline.fullmatch(lines[index])):
            if block_start.match(lines[index]) or thematic_break.fullmatch(lines[index]):
                return False
            index += 1
        # Ordinary paragraph lines become a Setext title only when followed
        # immediately by its underline. An ATX boundary does not absorb prose.
        if index == start or index == len(lines) or not underline.fullmatch(lines[index]):
            return False
        index += 1
    return bool(lines)


def _accepted_predecessor(root: Path, value: NarrativeRealization, events) -> NarrativeRealization | None:
    if value.stage == "outline":
        return None
    matches = [
        event for event in events
        if event.event_type == "artifact.accepted"
        and event.payload.artifact_id == value.predecessor_artifact_id
    ]
    if len(matches) != 1:
        _fail("narrative_predecessor_missing", "predecessor is not uniquely accepted")
    manifest = load_artifact_manifest(root, matches[0].payload.manifest_sha256)
    expected = "outline" if value.stage == "blueprint" else "blueprint"
    if STAGE_KINDS.get(manifest.artifact_kind) != expected:
        _fail("narrative_predecessor_invalid", "predecessor has the wrong stage")
    raw = read_retained_bytes(root, manifest.content_path, max_bytes=1_048_576)
    if sha256_hex(raw) != manifest.content_sha256:
        _fail("narrative_predecessor_invalid", "predecessor content changed")
    try:
        prior = NarrativeRealization.model_validate(strict_json_loads(raw))
    except ValueError as error:
        raise NarrativeRealizationError("narrative_predecessor_invalid", "predecessor contract is invalid") from error
    if prior.narrative_sha256 != value.narrative_sha256 or prior.stage != expected:
        _fail("stale_narrative", "predecessor has another narrative version")
    return prior


def validate_realization(
    root: Path,
    value: NarrativeRealization,
    snapshot: NarrativeSnapshot,
    *,
    events=(),
    source_bytes: bytes | None = None,
    validation_policy: Literal["structural-v1", "admission-v2"] = "admission-v2",
) -> dict[str, object]:
    """Check structure; advisory replay can retain historical admission policy."""
    if validation_policy not in {"structural-v1", "admission-v2"}:
        _fail("narrative_validation_policy_invalid", "unknown realization validation policy")
    if value.narrative_sha256 != snapshot.sha256 or any(
        node.narrative_sha256 != snapshot.sha256 for node in value.nodes
    ):
        _fail("stale_narrative", "realization carries an obsolete narrative digest")
    raw = verify_realization_source(root, value, source_bytes=source_bytes)
    # Syntax-only admission check: titles do not realize argument functions.
    # Keep historical replay's byte/span checks independent of this new policy.
    if validation_policy == "admission-v2":
        for node in value.nodes:
            if _heading_only(raw[node.span.start:node.span.end]):
                _fail("narrative_heading_only", "argument function binds only a Markdown heading; annotate body prose")
    required = set(snapshot.plan.function_order)
    if {node.function_id for node in value.nodes} != required:
        _fail("narrative_function_missing", "not all six argument functions are annotated")
    contributions = {n.node_id for n in value.nodes if n.function_id == "contribution"}
    evidence = {n.evidence_ref for n in value.nodes if n.function_id == "evidence" and n.evidence_ref}
    boundaries = {n.node_id for n in value.nodes if n.function_id == "knowledge_boundary"}
    if snapshot.plan.schema_version == "arw.narrative-plan.v2":
        anchors = {anchor.transition: anchor for anchor in snapshot.plan.transition_anchors or ()}
        if (anchors["problem_to_contribution"].object_ref not in contributions
                or anchors["evidence_to_conclusion"].object_ref not in boundaries
                or anchors["contribution_to_evidence"].object_ref not in {
                    n.evidence_form for n in value.nodes if n.function_id == "evidence"
                }):
            _fail("narrative_plan_anchor_unresolved", "realization does not resolve the selected plan's concrete transition objects")
    claims = [n for n in value.nodes if n.claim_id is not None]
    if not claims or len({n.claim_id for n in claims}) != len(claims):
        _fail("narrative_claim_invalid", "claim IDs must exist and be unique")
    if len(evidence) != len([n for n in value.nodes if n.function_id == "evidence"]):
        _fail("narrative_evidence_missing", "each evidence node needs a distinct evidence reference")
    for n in value.nodes:
        if n.function_id == "evidence" and (
            n.contribution_id not in contributions or n.knowledge_boundary_id not in boundaries
        ):
            _fail("narrative_graph_disconnected", "evidence lacks a contribution or boundary")
        if n.claim_id is not None and (
            n.contribution_id not in contributions
            or n.evidence_ref not in evidence
            or n.knowledge_boundary_id not in boundaries
        ):
            _fail("narrative_orphan_claim", "claim lacks contribution, evidence or boundary")
        if n.conclusion and n.within_scope_boundary is not True:
            _fail("narrative_scope_unresolved", "conclusion has no declared in-scope boundary")
    if any(
        not any(n.function_id == "evidence" and n.contribution_id == contribution for n in value.nodes)
        for contribution in contributions
    ):
        _fail("narrative_graph_disconnected", "contribution lacks evidence")
    evidence_by_ref = {
        n.evidence_ref: n for n in value.nodes
        if n.function_id == "evidence" and n.evidence_ref is not None
    }
    for claim in claims:
        assert claim.evidence_ref is not None  # Established by the orphan-claim check.
        supporting = evidence_by_ref[claim.evidence_ref]
        if (claim.contribution_id != supporting.contribution_id
                or claim.knowledge_boundary_id != supporting.knowledge_boundary_id):
            _fail("narrative_graph_disconnected", "claim and evidence follow different contribution or boundary paths")
    prior = _accepted_predecessor(root, value, events)
    prior_claims: set[str] = set()
    if prior is not None and value.stage == "draft":
        current_claims = {n.claim_id for n in claims}
        prior_claims = {n.claim_id for n in prior.nodes if n.claim_id is not None}
        if not prior_claims <= current_claims:
            _fail("narrative_blueprint_claim_missing", "draft omits an accepted blueprint claim")
        for node in claims:
            if node.claim_id not in prior_claims and not (node.new_claim_reason and node.new_claim_reason.strip()):
                _fail("narrative_new_claim_unexplained", "new draft claim needs a revision reason")
    ordered = sorted(value.nodes, key=lambda item: (item.span.start, item.span.end))
    order = {function: index for index, function in enumerate(snapshot.plan.function_order)}
    seen: set[str] = set()
    last = -1
    review: set[str] = {"semantic_support_unknown", "scope_support_needs_human_review"}
    if snapshot.plan.schema_version == "arw.narrative-plan.v1":
        review.add("legacy_plan_transition_anchors_unknown")
    if prior is not None and value.stage == "draft" and any(n.claim_id not in prior_claims for n in claims):
        review.add("new_claim_review")
    accepted_sources = {}
    for event in events:
        if event.event_type == "artifact.accepted":
            accepted_sources[event.payload.artifact_id] = event
    for node in value.nodes:
        if node.function_id == "evidence":
            if node.evidence_source_artifact_id is None:
                review.add("evidence_source_unknown")
            else:
                source_event = accepted_sources.get(node.evidence_source_artifact_id)
                if source_event is None:
                    _fail("narrative_evidence_source_invalid", "evidence source is not accepted")
                source_manifest = load_artifact_manifest(root, source_event.payload.manifest_sha256)
                if source_manifest.content_sha256 != node.evidence_source_sha256:
                    _fail("narrative_evidence_source_invalid", "evidence source digest differs")
                source_raw = read_retained_bytes(root, source_manifest.content_path, max_bytes=8_388_608)
                if sha256_hex(source_raw) != node.evidence_source_sha256:
                    _fail("narrative_evidence_source_invalid", "evidence source bytes changed")
        if node.hypothesis_history_ref is not None:
            historical = accepted_sources.get(node.hypothesis_history_ref)
            if historical is None:
                _fail("narrative_hypothesis_history_invalid", "hypothesis history reference is not accepted")
            historical_manifest = load_artifact_manifest(root, historical.payload.manifest_sha256)
            if historical_manifest.artifact_kind != "hypothesis-history":
                _fail("narrative_hypothesis_history_invalid", "history reference has the wrong artifact kind")
            history_raw = read_retained_bytes(root, historical_manifest.content_path, max_bytes=65_536)
            if sha256_hex(history_raw) != historical_manifest.content_sha256:
                _fail("narrative_hypothesis_history_invalid", "history contract changed")
            try:
                history = HypothesisHistory.model_validate(strict_json_loads(history_raw))
                history_source = read_retained_bytes(root, history.source_path, max_bytes=65_536)
            except (ValueError, OSError) as error:
                raise NarrativeRealizationError("narrative_hypothesis_history_invalid", "history source is unsafe") from error
            if (history.claim_id != node.claim_id
                    or history.narrative_sha256 != value.narrative_sha256
                    or sha256_hex(history_source) != history.source_sha256
                    or (history.span.start, history.span.end) not in _paragraph_bounds(history_source)
                    or sha256_hex(history_source[history.span.start:history.span.end]) != history.span.sha256):
                _fail("narrative_hypothesis_history_invalid", "history does not bind this claim and source span")
            if history.designation == "unknown":
                review.add("hypothesis_history_unknown")
            elif node.post_hoc != (history.designation == "post_hoc"):
                _fail("narrative_posthoc_mismatch", "claim origin differs from accepted history annotation")
    groups: dict[tuple[int, int], list] = {}
    for node in ordered:
        groups.setdefault((node.span.start, node.span.end), []).append(node)
    for group in groups.values():
        group_positions = sorted({order[node.function_id] for node in group})
        if len(group_positions) > 1:
            review.add("co_located_functions_review")
        for position in group_positions:
            nodes_here = [node for node in group if order[node.function_id] == position]
            if position < last or (nodes_here[0].function_id not in seen and position != len(seen)):
                if not any(node.interleave_reason and node.interleave_reason.strip() for node in nodes_here):
                    _fail("narrative_order_unexplained", "order deviation needs an interleave reason")
                review.add("narrative_interleave_review")
            seen.add(nodes_here[0].function_id)
        last = max(last, *group_positions)
    for node in value.nodes:
        if node.claim_id is not None and not node.post_hoc and node.hypothesis_history_ref is None:
            review.add("hypothesis_history_unknown")
    return {
        "mechanical_status": "PASS",
        "semantic_status": "UNKNOWN",
        "human_review_reason_codes": sorted(review),
        "source_sha256": value.source_sha256,
        "narrative_sha256": value.narrative_sha256,
        "claim_ids": sorted(n.claim_id for n in claims if n.claim_id is not None),
    }
