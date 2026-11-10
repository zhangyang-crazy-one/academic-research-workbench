"""Deterministic report-outcome pilot, not a production semantic validator.

Consumes the caller's freshly replayed ClaimGraph and experiment receipt. The
runtime currently has no qualified execution evidence that could authorize a
``verified_success`` label. Do not infer it from numeric conformance alone.
"""

import json

from arw.kernel.artifacts.experiment_acceptance import ExperimentAcceptanceResult
from arw.kernel.artifacts.experiment_provenance import ControlledExecutionDecision
from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex


def render_outcome(
    *,
    result: ExperimentAcceptanceResult,
    graph: dict,
    claim_id: str,
    execution: ControlledExecutionDecision | None = None,
) -> dict:
    claim = next(
        n
        for n in graph["nodes"]
        if n["node_kind"] == "Claim" and n["claim_id"] == claim_id
    )
    evidence = next(
        n
        for n in graph["nodes"]
        if n.get("artifact_kind") == "experiment-acceptance-result"
        and n["source"]["content_sha256"] == sha256_hex(result.canonical_bytes())
    )
    # Check outputs are not identities: distinct receipts can produce identical
    # result dictionaries. Resolve this claim revision's registered evidence node
    # and require its exact accepted reference to name the selected receipt.
    binding = next(
        (
            node
            for group in claim["checks"]
            for node in graph["nodes"]
            if node["id"]
            == f"evidence:{claim_id}@{claim['revision']}:{group['evidence_id']}"
            and node["node_kind"] == "ExperimentResult"
            and node.get("adapter_status") == "resolved"
            and node.get("original") == evidence["source"]
            and node.get("accepted_ref") == evidence["source"]
            and group["results"] == node["checks"]
        ),
        None,
    )
    if binding is None or not binding["checks"]:
        raise ValueError("experiment receipt is not bound to the report claim")
    checks = binding["checks"]
    statuses = [c["status"] for c in checks]
    if execution is not None and not execution.subprocess_allowed:
        outcome = "blocked"
        reasons = list(execution.reason_codes)
    elif any(s in {"not_checked", "unsupported"} for s in statuses):
        outcome = "unverified"
        reasons = ["experiment_evidence_not_verified"]
    elif any(
        (c.kind == "baseline_comparison" and c.status not in {"passed", "failed"})
        or (c.kind != "baseline_comparison" and c.status != "passed")
        for c in result.checks
    ):
        outcome = "blocked"
        reasons = ["contract_check_invalid_or_non_comparison_failed"]
    elif any(
        c.kind == "baseline_comparison" and c.status == "failed" for c in result.checks
    ):
        outcome = "negative_result"
        reasons = ["improvement_criterion_failed"]
    else:
        outcome = "unverified"
        reasons = ["contract_conformance_is_not_verified_execution"]
    structured = {
        "schema_version": "arw.pilot-report-outcome.v1",
        "outcome": outcome,
        "reason_codes": reasons,
        "experiment_result_sha256": result.result_sha256,
        "experiment_accepted_ref": evidence["source"],
        "claim_id": claim_id,
        "claim_evidence_id": binding["evidence_id"],
        "claim_graph_sha256": graph["snapshot_sha256"],
        "scope": result.scope,
        "checks": checks,
    }
    # Detach all nested graph data before hashing the retained report.
    structured = json.loads(canonical_json_bytes(structured))
    section = "## Experiment outcome\n\n" + outcome + "\n\n"
    section += "No verified success is established.\n\n"
    section += "\n".join(f"- {reason}" for reason in reasons) + "\n\n"
    section += (
        "\n".join(f"- {c['check_id']}: {c['status']} ({c['method']})" for c in checks)
        + "\n"
    )
    return {
        "outcome": structured,
        "outcome_sha256": sha256_hex(canonical_json_bytes(structured)),
        "outcome_section": section,
        "outcome_section_sha256": sha256_hex(section.encode()),
    }
