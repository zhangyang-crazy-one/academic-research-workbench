"""Source-answer comparison, independent of the mechanism drawing implementation.

Checks visible SVG structure. This is neither pixel comprehension nor authorization.
"""

from __future__ import annotations

import re

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.state.mechanism_figure import MechanismReviewBinding

from .composition import safe_tree
from .validation import IRValidationFault

NS = "{http://www.w3.org/2000/svg}"


def advisory_binding(*, source, ir, svg, png, raster):
    """Bind actual source/output/font/environment bytes; never approve them."""
    return MechanismReviewBinding(
        source_sha256=sha256_hex(canonical_json_bytes(source)),
        ir_sha256=sha256_hex(ir),
        svg_sha256=sha256_hex(svg),
        png_sha256=sha256_hex(png),
        font_sha256=sha256_hex(canonical_json_bytes(raster["fonts"])),
        environment_sha256=sha256_hex(canonical_json_bytes(raster["rasterizer"])),
    )


def advisory_status(review, binding):
    return review.status if review.binding == binding else "stale"


def inspect_mechanism(facts, ir, svg):
    findings = []

    def fail(code, identity, expected, observed):
        findings.append(
            {
                "finding_id": f"{code}:{identity}",
                "type": "necessary_content_or_scientific_difference",
                "severity": "error",
                "semantic_id": identity,
                "expected": expected,
                "observed": observed,
                "pass_condition": "Restore the frozen source requirement and rerun this comparison.",
                "uncertainty": "Structural SVG comparison only; final pixels require a separate reviewer.",
            }
        )

    try:
        root = safe_tree(svg)
    except IRValidationFault as exc:
        return {
            "status": "changes_required",
            "findings": [{"finding_id": "unsafe_svg", "observed": str(exc)}],
        }
    indexed = {e.get("id"): e for e in root.iter() if e.get("id")}
    # No inherited concealment/transforms are part of this renderer contract.
    if any(
        "transform" in e.attrib
        or any(k in e.attrib for k in ("opacity", "display", "visibility", "style"))
        for e in root.iter()
    ):
        fail(
            "unsupported_visibility",
            "svg",
            "plain visible vectors",
            "concealment or transform",
        )
    expected_ids = {c.semantic_id for c in facts.components}
    actual_ids = {
        k.removeprefix("component.") for k in indexed if k.startswith("component.")
    }
    if expected_ids != actual_ids:
        fail("component_inventory", "svg", sorted(expected_ids), sorted(actual_ids))
    cells = {c.semantic_id: c for c in ir.cells}
    components = {c.semantic_id: c for c in facts.components}

    def normalized(value):
        return re.sub(r"\s+", "", value)

    def visible(identity):
        e = indexed.get(identity)
        return "" if e is None else "".join(e.itertext())

    for c in facts.components:
        observed = visible("content." + c.semantic_id)
        requirements = [
            c.label,
            f"{c.status} | {c.phase} | parameters: {c.parameters}",
            *c.steps,
        ]
        requirements += [
            f"{t.token_id}: {t.text} -> {t.representation_id}"
            + (" [MASK]" if t.masked else "")
            for t in c.tokens
        ]
        if c.axes:
            requirements.append("axes: " + "; ".join(c.axes))
        if c.condition:
            requirements.append("continue: " + c.condition)
        if c.stop_condition:
            requirements.append("stop: " + c.stop_condition)
        if c.before:
            requirements.append("before: " + c.before)
        if c.after:
            requirements.append("after: " + c.after)
        if c.semantic_id == facts.innovation_id:
            requirements.append("INNOVATION")
        for requirement in requirements:
            if normalized(requirement) not in normalized(observed):
                fail("component_content", c.semantic_id, requirement, observed)
        for p in c.ports:
            requirement = f"{p.direction} {p.port_id}: {p.value_type} / {p.object_id}@{p.state_id}"
            if normalized(requirement) not in normalized(observed):
                fail(
                    "port_identity",
                    c.semantic_id + "." + p.port_id,
                    requirement,
                    observed,
                )
            node = indexed.get(f"port.{c.semantic_id}.{p.port_id}")
            if node is None or node.tag != NS + "circle":
                fail(
                    "port_missing",
                    c.semantic_id + "." + p.port_id,
                    "visible port",
                    None,
                )
    for r in facts.relations:
        edge = indexed.get("edge." + r.semantic_id)
        if edge is None or edge.tag != NS + "polyline":
            fail("edge_missing", r.semantic_id, "directed path", None)
            continue
        try:
            points = [
                tuple(map(float, p.split(","))) for p in edge.get("points", "").split()
            ]
            ends = []
            for cid, pid in (
                (r.source_component, r.source_port),
                (r.target_component, r.target_port),
            ):
                c, cell = components[cid], cells[cid]
                p = next(p for p in c.ports if p.port_id == pid)
                siblings = [p2 for p2 in c.ports if p2.direction == p.direction]
                ends.append(
                    (
                        cell.x if p.direction == "input" else cell.x + cell.width,
                        cell.y
                        + cell.height * (siblings.index(p) + 1) / (len(siblings) + 1),
                    )
                )
            if len(points) < 2 or points[0] != ends[0] or points[-1] != ends[1]:
                fail("edge_direction_or_endpoint", r.semantic_id, ends, points)
        except (ValueError, KeyError, StopIteration):
            fail(
                "edge_geometry_invalid",
                r.semantic_id,
                "typed port endpoints",
                edge.attrib,
            )
        marker = indexed.get("arrow." + r.relation_type)
        arrow_path = None if marker is None else marker.find(NS + "path")
        if (
            edge.get("marker-start")
            or edge.get("marker-end") != "url(#arrow." + r.relation_type + ")"
            or marker is None
            or marker.get("orient") != "auto"
            or arrow_path is None
            or arrow_path.get("d") != "M 0 0 L 7 3.5 L 0 7 Z"
        ):
            fail("edge_arrow", r.semantic_id, "forward typed arrow", edge.attrib)
        expected_label = (
            f"{r.semantic_id} [{r.relation_type}]: {r.payload}; when {r.trigger}"
            + ("; feedback" if r.feedback else "")
        )
        if normalized(expected_label) != normalized(
            visible("relation." + r.semantic_id)
        ):
            fail(
                "relation_meaning",
                r.semantic_id,
                expected_label,
                visible("relation." + r.semantic_id),
            )
    expected_edge_ids = {r.semantic_id for r in facts.relations}
    if {
        k.removeprefix("edge.") for k in indexed if k.startswith("edge.")
    } != expected_edge_ids:
        fail(
            "edge_inventory",
            "svg",
            sorted(expected_edge_ids),
            "different edge inventory",
        )
    for e in root.iter(NS + "text"):
        try:
            if float(e.get("font-size", "0")) < ir.min_font_pt:
                fail("minimum_font", e.get("id"), ir.min_font_pt, e.get("font-size"))
        except ValueError:
            fail("invalid_font", e.get("id"), "finite point size", e.get("font-size"))
    return {
        "status": "changes_required" if findings else "reviewed",
        "scope": "source-answer SVG structure only",
        "human_status": "human_pending",
        "publication_visual_pass": False,
        "findings": findings,
    }
