"""Canonical binding and representation checks, separate from visual review."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

from arw.kernel.core.canonical import sha256_hex, strict_json_loads
from arw.kernel.ledger.manifests import load_artifact_manifest
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.state.models import ArtifactAcceptedPayload
from arw.kernel.state.research_artifact import ValidationResults, VisualReviewer


class IRValidationFault(ValueError):
    code = "ir_validation_fault"


def accepted_content(root, events, artifact_id, event_id=None, expected_digest=None):
    matches = [
        e
        for e in events
        if e.event_type in {"artifact.accepted", "research_artifact_accepted"}
        and isinstance(e.payload, ArtifactAcceptedPayload)
        and e.payload.artifact_id == artifact_id
        and (event_id is None or e.event_id == event_id)
    ]
    if len(matches) != 1:
        raise IRValidationFault("binding does not select one accepted artifact")
    event = matches[0]
    if expected_digest is not None and event.payload.artifact_sha256 != expected_digest:
        raise IRValidationFault("binding digest differs from accepted artifact")
    manifest = load_artifact_manifest(root, event.payload.manifest_sha256)
    raw = read_retained_bytes(root, manifest.content_path)
    if sha256_hex(raw) != event.payload.artifact_sha256:
        raise IRValidationFault("retained evidence digest mismatch")
    return strict_json_loads(raw), event, raw


def resolve_pointer(value, pointer):
    if not pointer:
        return value
    for component in pointer[1:].split("/"):
        if re.search(r"~(?![01])", component):
            raise IRValidationFault("invalid JSON pointer escape")
        key = component.replace("~1", "/").replace("~0", "~")
        try:
            if isinstance(value, list):
                if not re.fullmatch(r"0|[1-9][0-9]*", key):
                    raise IRValidationFault("invalid array pointer")
                value = value[int(key)]
            elif isinstance(value, dict):
                value = value[key]
            else:
                raise IRValidationFault("pointer traverses scalar evidence")
        except (IndexError, KeyError) as error:
            raise IRValidationFault("binding location does not exist") from error
    return value


def resolve_bindings(ir, root, events):
    sources, resolved, total = {}, {}, 0
    for binding in ir.research_bindings:
        key = (binding.artifact_id, binding.ledger_event_id, binding.sha256)
        if key not in sources:
            value, event, raw = accepted_content(
                root, events, *key[:2], expected_digest=binding.sha256
            )
            total += len(raw)
            if total > 8_388_608:
                raise IRValidationFault("aggregate evidence budget exceeded")
            sources[key] = (value, event)
        value, event = sources[key]
        if event.event_sha256 != binding.ledger_event_sha256:
            raise IRValidationFault("binding event digest mismatch")
        resolved[binding.binding_id] = resolve_pointer(value, binding.json_pointer)
    return resolved


class EvidenceValidator:
    def validate(self, ir, output: bytes, *, run_root, events, visual_review_id=None):
        statuses = {
            "schema": "PASS",
            "provenance": "PASS",
            "semantic": "PASS",
            "render": "PASS",
            "visual": "UNAVAILABLE",
        }
        reasons = []
        reviewer = None
        try:
            bindings = resolve_bindings(ir, run_root, events)
        except (ValueError, RuntimeError, OSError):
            bindings = {}
            statuses["provenance"] = "FAIL"
            statuses["semantic"] = "UNAVAILABLE"
            reasons.append("unresolved_evidence_binding")
        if bindings:
            for node in ir.nodes:
                source = bindings[node.binding_id]
                if (
                    not isinstance(source, dict)
                    or source.get("label") != node.label
                    or source.get("kind") != node.kind
                    or type(source.get("confidence")) is not int
                    or node.confidence > source["confidence"]
                ):
                    statuses["semantic"] = "FAIL"
                    reasons.append("node_exceeds_accepted_semantics")
            for edge in ir.edges:
                source = bindings[edge.binding_id]
                if not isinstance(source, dict) or any(
                    source.get(k) != getattr(edge, k)
                    for k in ("source", "target", "relation", "label")
                ):
                    statuses["semantic"] = "FAIL"
                    reasons.append("edge_differs_from_accepted_relation")
            for annotation in ir.annotations:
                source = bindings[annotation.binding_id]
                text = source.get("text") if isinstance(source, dict) else source
                if annotation.text != text:
                    statuses["semantic"] = "FAIL"
                    reasons.append("caption_or_manuscript_differs_from_evidence")
        try:
            element = ET.fromstring(output)
            ids = [e.attrib["id"] for e in element.iter() if "id" in e.attrib]
            expected = {
                e.id for e in (*ir.nodes, *ir.edges, *ir.groups, *ir.annotations)
            }
            if (
                element.tag != "{http://www.w3.org/2000/svg}svg"
                or not expected <= set(ids)
                or len(ids) != len(set(ids))
            ):
                raise ValueError("render structure invalid")
        except (ET.ParseError, ValueError):
            statuses["render"] = "FAIL"
            reasons.append("invalid_svg_structure")
        if visual_review_id:
            try:
                from arw.kernel.core.canonical import canonical_json_bytes

                value, event, _ = accepted_content(run_root, events, visual_review_id)
                if (
                    value.get("schema_version") != "arw.visual-review.v1"
                    or value.get("ir_sha256")
                    != sha256_hex(canonical_json_bytes(ir.model_dump(mode="json")))
                    or value.get("output_sha256") != sha256_hex(output)
                    or value.get("status") not in {"PASS", "FAIL"}
                ):
                    raise ValueError("review does not bind output")
                reviewer = VisualReviewer.model_validate_json(
                    json.dumps(
                        {
                            **value["reviewer"],
                            "evidence_artifact_id": visual_review_id,
                            "evidence_event_id": event.event_id,
                            "evidence_event_sha256": event.event_sha256,
                        }
                    )
                )
                statuses["visual"] = value["status"]
            except (ValueError, RuntimeError, KeyError, TypeError):
                statuses["visual"] = "FAIL"
                reasons.append("invalid_visual_review_binding")
        for level, applicability in ir.validation_policy.model_dump(
            mode="json"
        ).items():
            if applicability == "NOT_APPLICABLE":
                statuses[level] = "NOT_APPLICABLE"
            elif applicability == "OPTIONAL" and statuses[level] == "UNAVAILABLE":
                statuses[level] = "OPTIONAL_SKIPPED"
        # Even optional semantic/render/provenance failures cannot be silently accepted.
        passed = (
            all(
                statuses[level] == "PASS"
                for level, required in ir.validation_policy.model_dump(
                    mode="json"
                ).items()
                if required == "REQUIRED"
            )
            and "FAIL" not in statuses.values()
        )
        return (
            ValidationResults.model_validate_json(json.dumps(statuses)),
            tuple(sorted(set(reasons))),
            reviewer,
            passed,
        )
