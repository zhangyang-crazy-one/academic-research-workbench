"""Read-only review suggestions and target replay through original validators."""

from __future__ import annotations

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.core.privacy import reject_secret_shapes
from arw.kernel.ledger.claim_graph import (
    _check_occurrence,
    _closure,
    _read_inputs,
    _registrations,
    graph,
)
from arw.kernel.state.claim_graph import Occurrence, SnapshotManifest
from arw.kernel.state.review_concern import (
    ClaimRevisionTarget,
    OccurrenceTarget,
    ReviewConcern,
    ReviewConcernReport,
)


def validate_concern(concern: ReviewConcern, project_root, run_roots, *, inputs=None):
    concern = ReviewConcern.model_validate_json(
        canonical_json_bytes(concern.model_dump(mode="json"))
    )
    if inputs is None:
        inputs = _read_inputs(project_root, run_roots, concern.snapshot_manifest)
        _closure(inputs)
    if inputs.manifest != concern.snapshot_manifest:
        raise ValueError("review concern snapshot mismatch")
    target = concern.target
    if isinstance(target, ClaimRevisionTarget):
        registration = _registrations(inputs.journal).get(target.claim_id)
        if registration is None or (
            registration.claim.revision,
            registration.claim.sha256,
        ) != (target.revision, target.claim_sha256):
            raise ValueError(
                "review concern claim revision differs from canonical journal"
            )
    else:
        _check_occurrence(target.occurrence, inputs)
    reject_secret_shapes(canonical_json_bytes(concern.model_dump(mode="json")))
    return concern


def diagnose(project_root, run_roots):
    view = graph(project_root, run_roots=run_roots)
    snapshot = SnapshotManifest.model_validate(view["snapshot_manifest"])
    concerns = []
    for node in view["nodes"]:
        target = None
        if node["node_kind"] == "Claim" and not node["integrity"]:
            target = ClaimRevisionTarget(
                claim_id=node["claim_id"],
                revision=node["revision"],
                claim_sha256=node["claim_sha256"],
            )
            message = "Consider adding explicit supporting evidence and clarifying the scope of this registered claim."
        elif node["node_kind"] == "Occurrence" and (
            node["registration"] == "unknown"
            or node.get("numeric_verification", {}).get("status") == "not_checked"
        ):
            occurrence = Occurrence.model_validate(
                {k: node[k] for k in Occurrence.model_fields if k in node}
            )
            target = OccurrenceTarget(occurrence=occurrence)
            message = "Consider explicitly registering this source occurrence and documenting its intended evidential role."
        if target is not None:
            digest = sha256_hex(
                canonical_json_bytes(
                    {
                        "target": target.model_dump(mode="json"),
                        "snapshot": snapshot.sha256,
                        "message": message,
                    }
                )
            )
            concerns.append(
                ReviewConcern(
                    concern_id="concern." + digest[:32],
                    snapshot_manifest=snapshot,
                    target=target,
                    message=message,
                    source="rule",
                )
            )
    report = ReviewConcernReport(
        snapshot_manifest=snapshot,
        concerns=tuple(sorted(concerns, key=lambda c: c.concern_id)),
    )
    replay_report(report, project_root, run_roots)
    return report


def replay_report(report: ReviewConcernReport, project_root, run_roots):
    raw = canonical_json_bytes(report.model_dump(mode="json"))
    if len(raw) > 2_097_152:
        raise ValueError("review report byte budget exceeded")
    report = ReviewConcernReport.model_validate_json(raw)
    inputs = _read_inputs(project_root, run_roots, report.snapshot_manifest)
    _closure(inputs)
    for concern in report.concerns:
        validate_concern(concern, project_root, run_roots, inputs=inputs)
    return report


def export_prov(report: ReviewConcernReport, project_root, run_roots):
    replay_report(report, project_root, run_roots)
    snapshot_id = "#snapshot." + report.snapshot_manifest.sha256
    activity_id = "#annotation." + report.sha256
    root_id = "#concern-set." + report.sha256
    nodes = [
        {
            "@id": root_id,
            "@type": ["CreativeWork", "prov:Entity"],
            "name": "Advisory manuscript concerns",
            "prov:wasDerivedFrom": {"@id": snapshot_id},
            "prov:wasGeneratedBy": {"@id": activity_id},
            "arw:reportSha256": report.sha256,
            "arw:scope": "advisory_only",
        },
        {
            "@id": snapshot_id,
            "@type": "prov:Entity",
            "arw:sha256": report.snapshot_manifest.sha256,
            "arw:snapshotJson": canonical_json_bytes(
                report.snapshot_manifest.model_dump(mode="json")
            ).decode(),
        },
        {
            "@id": activity_id,
            "@type": ["CreateAction", "prov:Activity"],
            "name": "Source-bound review annotation/diagnosis",
            "prov:used": {"@id": snapshot_id},
            "arw:generator": report.generator_version,
        },
    ]
    for concern in report.concerns:
        target_id = "#target." + sha256_hex(
            canonical_json_bytes(concern.target.model_dump(mode="json"))
        )
        if not any(n["@id"] == target_id for n in nodes):
            nodes.append(
                {
                    "@id": target_id,
                    "@type": "prov:Entity",
                    "prov:wasDerivedFrom": {"@id": snapshot_id},
                    "arw:targetJson": canonical_json_bytes(
                        concern.target.model_dump(mode="json")
                    ).decode(),
                }
            )
        node = {
            "@id": "#" + concern.concern_id,
            "@type": ["Comment", "prov:Entity"],
            "text": concern.message,
            "about": {"@id": target_id},
            "isPartOf": {"@id": root_id},
            "prov:wasDerivedFrom": {"@id": target_id},
            "prov:wasGeneratedBy": {"@id": activity_id},
            "arw:propositionType": concern.proposition_type,
            "arw:annotationSource": concern.source,
            "arw:advisory": True,
        }
        if concern.argumentative_zone:
            node["arw:argumentativeZone"] = concern.argumentative_zone
        nodes.append(node)
    document = {
        "@context": [
            "https://w3id.org/ro/crate/1.1/context",
            {
                "prov": "http://www.w3.org/ns/prov#",
                "arw": "https://academic-research-workbench.local/terms/",
            },
        ],
        "@graph": sorted(nodes, key=lambda n: n["@id"]),
    }
    validate_prov(document)
    if len(canonical_json_bytes(document)) > 2_097_152:
        raise ValueError("review PROV output budget exceeded")
    reject_secret_shapes(canonical_json_bytes(document))
    return document


def validate_prov(document):
    """Validate emitted identities/types/links without remote context fetching."""
    nodes = document.get("@graph")
    if not isinstance(nodes, list) or any(
        not isinstance(n, dict) or not isinstance(n.get("@id"), str) for n in nodes
    ):
        raise ValueError("invalid PROV graph")
    ids = {n["@id"] for n in nodes}
    if len(ids) != len(nodes):
        raise ValueError("duplicate PROV graph identity")
    for node in nodes:
        for key in (
            "prov:used",
            "prov:wasGeneratedBy",
            "prov:wasDerivedFrom",
            "about",
            "isPartOf",
        ):
            if key in node and (
                set(node[key]) != {"@id"} or node[key]["@id"] not in ids
            ):
                raise ValueError("dangling PROV entity/activity link")
    return True
