"""Read parent-owned participation evidence, independently of ClaimGraph."""

from __future__ import annotations

from dataclasses import replace

from arw.kernel.core.canonical import (
    canonical_json_bytes,
    sha256_hex,
)
from arw.kernel.core.privacy import reject_secret_shapes
from arw.kernel.ledger.accepted_refs import (
    ResolutionCache,
    ResolutionContext,
    RunPrefix,
    _runs,
    resolve_ref,
)
from arw.kernel.ledger.manifests import load_artifact_manifest
from arw.kernel.state.accepted_ref import ParentArtifactRef
from arw.kernel.state.ai_disclosure import (
    AIActivityReceipt,
    AIDisclosurePolicy,
    AIParticipationDeclaration,
)

MAX_ITEMS = 5000
MAX_BYTES = 2_097_152
RECORDS = {
    "ai-activity-receipt": (AIActivityReceipt, "observed"),
    "ai-participation-declaration": (AIParticipationDeclaration, "human-declared"),
}


def ref_key(ref):
    return (ref.run_id, ref.accepting_event_id, ref.content_sha256)


def capture(context: ResolutionContext):
    runs = _runs(context)  # Original canonical readers/locks; no graph/cache input.
    prefixes = tuple(
        RunPrefix(manifest.run_id, replay.revision, replay.last_event_sha256, digest)
        for _, manifest, digest, replay in sorted(runs, key=lambda r: r[1].run_id)
    )
    fixed = replace(context, run_prefixes=prefixes)
    entries, records = {}, []
    memo = ResolutionCache()
    for root, manifest, digest, replay in runs:
        for event in replay.events:
            if event.event_type not in {
                "artifact.accepted",
                "research_artifact_accepted",
            }:
                continue
            artifact = load_artifact_manifest(root, event.payload.manifest_sha256)
            ref = ParentArtifactRef(
                project_id=context.project_id,
                run_id=manifest.run_id,
                run_manifest_sha256=digest,
                artifact_id=artifact.artifact_id,
                accepting_event_id=event.event_id,
                accepting_event_sha256=event.event_sha256,
                content_sha256=artifact.content_sha256,
            )
            resolved = resolve_ref(ref, fixed, memo)
            if resolved.status != "resolved" or resolved.proven_scope not in {
                "bytes",
                "structural_capsule",
                "metadata_only",
            }:
                raise ValueError("AI disclosure source is unavailable or changed")
            if artifact.artifact_kind in RECORDS:
                model, status = RECORDS[artifact.artifact_kind]
                record = model.model_validate_json(resolved.raw_bytes)
                if record.target.selector or record.target.selected_sha256:
                    raise ValueError(
                        "participation target must bind whole artifact bytes"
                    )
                target = resolve_ref(record.target, fixed, memo)
                if target.status != "resolved" or target.proven_scope not in {
                    "bytes",
                    "structural_capsule",
                    "metadata_only",
                }:
                    raise ValueError(
                        "participation target is unavailable or outside prefix"
                    )
                records.append((record, status, ref, event.sequence))
            elif artifact.artifact_kind not in {
                "ai-disclosure-draft",
                "ai-disclosure-policy",
            }:
                material_type = (
                    "figure"
                    if artifact.artifact_kind == "research-artifact"
                    or artifact.media_type.startswith("image/")
                    else "code"
                    if artifact.content_path.endswith(
                        (".py", ".r", ".R", ".js", ".ts", ".c", ".cpp", ".jl", ".ipynb")
                    )
                    else "text"
                    if artifact.media_type.startswith("text/")
                    else "other"
                )
                entries[ref_key(ref)] = {
                    "target": ref.model_dump(mode="json"),
                    "artifact_kind": artifact.artifact_kind,
                    "material_type": material_type,
                    "content_path": artifact.content_path,
                    "ai_involvement": "unknown",
                    "histories": [],
                }
                if resolved.proven_scope != "bytes":
                    entries[ref_key(ref)]["content_proof_scope"] = resolved.proven_scope
            if len(entries) + len(records) > MAX_ITEMS:
                raise ValueError("AI disclosure item budget exceeded")
    for record, status, source, sequence in records:
        entry = entries.get(ref_key(record.target))
        if entry is None:
            raise ValueError("participation target is not an included material")
        if record.target.run_id == source.run_id:
            target_sequence = next(
                e.sequence
                for _, m, _, replay in runs
                if m.run_id == source.run_id
                for e in replay.events
                if e.event_id == record.target.accepting_event_id
            )
            if target_sequence >= sequence:
                raise ValueError("participation target must precede receipt acceptance")
        entry["histories"].append(
            {
                "status": status,
                "usage": record.usage,
                "record": record.model_dump(mode="json"),
                "evidence": source.model_dump(mode="json"),
                "proof_scope": "accepted_receipt_contents_only"
                if status == "observed"
                else "human_declaration_only",
            }
        )
    materials = []
    for key in sorted(entries):
        entry = entries[key]
        entry["histories"].sort(key=lambda h: canonical_json_bytes(h))
        states = {h["status"] for h in entry["histories"]}
        entry["ai_involvement"] = (
            "observed"
            if "observed" in states
            else "human-declared"
            if states
            else "unknown"
        )
        entry["history_complete"] = (
            False  # No claim that imported/external edits were completely observed.
        )
        materials.append(entry)
    summary = {
        "schema_version": "arw.ai-participation-summary.v1",
        "project_id": context.project_id,
        "run_prefixes": [
            {
                "run_id": p.run_id,
                "revision": p.revision,
                "head_sha256": p.head_sha256,
                "run_manifest_sha256": p.run_manifest_sha256,
            }
            for p in prefixes
        ],
        "materials": materials,
        "coverage": "all included parent-accepted artifacts, irrespective of claim anchors; unaccepted external files are not observed",
        "interpretation": "Receipt integrity and human declarations are distinct; absence is unknown, not human authorship proof.",
    }
    reject_secret_shapes(canonical_json_bytes(summary))
    if len(canonical_json_bytes(summary)) > MAX_BYTES:
        raise ValueError("AI disclosure output budget exceeded")
    return summary


def make_draft(
    context: ResolutionContext, policy: AIDisclosurePolicy, *, generator_version="1.1.0"
):
    if generator_version not in {"1.0.0", "1.1.0"}:
        raise ValueError("unsupported disclosure generator")
    summary = capture(context)
    lines = [
        f"{policy.venue} AI involvement disclosure draft ({policy.template})",
        f"Policy {policy.policy_version}; verified {policy.verified_on}; human final review required.",
    ]
    if policy.template == "checklist":
        lines.append(
            "Checklist response: author must supply the actual yes/no answer and section locators; unknown history is not a No answer."
        )
    else:
        lines.append(
            "Acknowledgments draft: author must identify each AI system, affected sections and extent; grammar-only editing remains separately reported."
        )
    lines.extend("Policy guidance: " + rule for rule in policy.requirements)
    for entry in summary["materials"]:
        lines.append(
            f"{entry['target']['run_id']}/{entry['target']['artifact_id']}: {entry['ai_involvement']}."
        )
        for history in entry["histories"]:
            record = history["record"]
            system = record.get("system") or "system identity unknown"
            if generator_version == "1.1.0" and history["usage"] == "imported":
                lines.append(
                    f"  {history['status']}: imported material receipt/declaration; "
                    f"does not establish AI drafting; {system}; {record['detail']}"
                )
            else:
                lines.append(
                    f"  {history['status']}: {history['usage']}; {system}; {record['detail']}"
                )
    unknown = sum(m["ai_involvement"] == "unknown" for m in summary["materials"])
    lines.append(
        f"Unknown material histories: {unknown}; no assertion of exclusively human creation. Add manuscript section locators and review every external/imported edit before submission."
    )
    body = {
        "schema_version": "arw.ai-disclosure-draft.v1",
        "generator_version": generator_version,
        "policy": policy.model_dump(mode="json"),
        "policy_sha256": policy.sha256,
        "summary": summary,
        "text": "\n".join(lines) + "\n",
        "human_final_review": "pending",
        "submission": "not_performed",
    }
    draft = {**body, "draft_sha256": sha256_hex(canonical_json_bytes(body))}
    if len(canonical_json_bytes(draft)) > MAX_BYTES:
        raise ValueError("AI disclosure draft output budget exceeded")
    return draft


def replay_draft(value: dict, context: ResolutionContext):
    fields = {
        "schema_version",
        "generator_version",
        "policy",
        "policy_sha256",
        "summary",
        "text",
        "human_final_review",
        "submission",
        "draft_sha256",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("invalid disclosure draft envelope")
    policy = AIDisclosurePolicy.model_validate_json(
        canonical_json_bytes(value["policy"])
    )
    fixed = replace(
        context,
        run_prefixes=tuple(RunPrefix(**p) for p in value["summary"]["run_prefixes"]),
    )
    expected = make_draft(fixed, policy, generator_version=value["generator_version"])
    if canonical_json_bytes(expected) != canonical_json_bytes(value):
        raise ValueError("disclosure draft replay mismatch")
    return expected
