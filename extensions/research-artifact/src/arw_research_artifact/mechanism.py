"""Explicit mechanism components; sourced facts, manual geometry, inert SVG."""

from __future__ import annotations

import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import replace
from itertools import pairwise
from pathlib import Path

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.ledger.accepted_refs import (
    ResolutionCache,
    ResolutionContext,
    to_accepted_ref,
)
from arw.kernel.ledger.research_records import commit_artifact_pipeline
from arw.kernel.state.mechanism_figure import MechanismFacts, MechanismFigureReceipt
from arw.kernel.state.research_artifact import (
    OutputDigest,
    RendererIdentity,
    ValidationResults,
    VisualReviewer,
)

from .validation import IRValidationFault, accepted_content

NS = "{http://www.w3.org/2000/svg}"
ET.register_namespace("", NS[1:-1])
FONT = "Noto Sans CJK SC, sans-serif"
# First-party component convention, not a purported industry icon standard.
RELATIONS = {
    "data": ("#0072b2", ""),
    "condition": ("#7a5195", "3 3"),
    "control": ("#333333", "6 3"),
    "retrieval": ("#00796b", "2 2"),
    "action": ("#a85100", ""),
    "observation": ("#005f73", "5 2"),
    "supervision": ("#8c2d5d", "8 2 2 2"),
    "parameter_update": ("#8b0000", "1 2"),
}


def component_lines(c):
    """Complete visible content; reviewer compares it with the frozen answer."""
    lines = [c.label, f"{c.status} | {c.phase} | parameters: {c.parameters}"]
    lines.extend(f"{i + 1}. {step}" for i, step in enumerate(c.steps))
    lines.extend(
        f"{t.token_id}: {t.text} -> {t.representation_id}"
        + (" [MASK]" if t.masked else "")
        for t in c.tokens
    )
    if c.axes:
        lines.append("axes: " + "; ".join(c.axes))
    if c.condition:
        lines.append("continue: " + c.condition)
    if c.stop_condition:
        lines.append("stop: " + c.stop_condition)
    if c.before:
        lines.append("before: " + c.before)
    if c.after:
        lines.append("after: " + c.after)
    for p in c.ports:
        lines.append(
            f"{p.direction} {p.port_id}: {p.value_type} / {p.object_id}@{p.state_id}"
        )
    return lines


def wrap(text, width, size):
    # Preserve whole words where possible, with bounded fallback for long IDs/CJK.
    def measure(value):
        return sum(
            size * (1.0 if unicodedata.east_asian_width(c) in {"W", "F"} else 0.65)
            for c in value
        )

    out, row = [], ""
    for word in re.findall(r"\S+\s*", text):
        if row and measure(row + word.rstrip()) > width:
            out.append(row.rstrip())
            row = ""
        for ch in word:
            if row and measure(row + ch) > width:
                out.append(row.rstrip())
                row = ""
            row += ch
    return (*out, row.rstrip())


def port_position(component, cell, port_id):
    port = next(p for p in component.ports if p.port_id == port_id)
    ports = [p for p in component.ports if p.direction == port.direction]
    i = ports.index(port)
    return (
        cell.x if port.direction == "input" else cell.x + cell.width,
        cell.y + cell.height * (i + 1) / (len(ports) + 1),
    )


def route_points(facts, ir, relation):
    cs = {c.semantic_id: c for c in facts.components}
    cells = {c.semantic_id: c for c in ir.cells}
    route = next(r for r in ir.routes if r.semantic_id == relation.semantic_id)
    return (
        port_position(
            cs[relation.source_component],
            cells[relation.source_component],
            relation.source_port,
        ),
        *route.via,
        port_position(
            cs[relation.target_component],
            cells[relation.target_component],
            relation.target_port,
        ),
    )


def text_element(parent, identity, lines, x, y, size):
    e = ET.SubElement(
        parent,
        NS + "text",
        {
            "id": identity,
            "font-size": str(size),
            "font-family": FONT,
            "fill": "#222222",
        },
    )
    for i, line in enumerate(lines):
        t = ET.SubElement(e, NS + "tspan", {"x": str(x), "y": str(y + i * size * 1.45)})
        t.text = line
    return e


def load_facts(service, ir, run_root, context, events=None):
    replay = service._plot_replay(run_root, context)
    if events is not None and replay.events != tuple(events):
        raise IRValidationFault("mechanism_prefix_differs_from_parent_history")
    result = to_accepted_ref(ir.source, context, cache=ResolutionCache())
    if result.status != "resolved":
        raise IRValidationFault("mechanism_source_unresolved:" + str(result.reason))
    raw = canonical_json_bytes(result.selected_value)
    if len(raw) > 65_536:
        raise IRValidationFault("mechanism_source_budget_exceeded")
    if sha256_hex(raw) != ir.source_sha256:
        raise IRValidationFault("mechanism_source_digest_mismatch")
    return MechanismFacts.model_validate_json(raw)


class MechanismRenderer:
    @property
    def identity(self):
        return RendererIdentity(
            name="arw.mechanism-svg",
            version="1.1.0",
            identity_digest=sha256_hex(Path(__file__).read_bytes()),
            normalization_policy="utf8-svg-explicit-ports-pt.v1",
        )

    def render(self, facts, ir):
        if ir.renderer_hints != self.identity:
            raise IRValidationFault("mechanism_renderer_identity_mismatch")
        if {c.semantic_id for c in facts.components} != {
            c.semantic_id for c in ir.cells
        } or {r.semantic_id for r in facts.relations} != {
            r.semantic_id for r in ir.routes
        }:
            raise IRValidationFault("mechanism_layout_inventory_mismatch")
        width, height = ir.width_mm * 72 / 25.4, ir.height_mm * 72 / 25.4
        root = ET.Element(
            NS + "svg",
            {
                "width": f"{ir.width_mm}mm",
                "height": f"{ir.height_mm}mm",
                "viewBox": f"0 0 {width} {height}",
            },
        )
        ET.SubElement(root, NS + "desc").text = json.dumps(
            {
                "source_sha256": ir.source_sha256,
                "profile": ir.profile,
                "candidate_exception": facts.candidate_exception,
            },
            ensure_ascii=False,
        )
        text_element(
            root,
            "mechanism.claim",
            wrap(
                f"[{facts.data_nature}] {facts.claim}", width - 24, ir.min_font_pt + 1
            ),
            12,
            18,
            ir.min_font_pt + 1,
        )
        text_element(
            root,
            "mechanism.question",
            wrap(facts.question, width - 24, ir.min_font_pt),
            12,
            43,
            ir.min_font_pt,
        )
        defs = ET.SubElement(root, NS + "defs")
        for key, (color, _) in RELATIONS.items():
            marker = ET.SubElement(
                defs,
                NS + "marker",
                {
                    "id": "arrow." + key,
                    "markerWidth": "7",
                    "markerHeight": "7",
                    "refX": "7",
                    "refY": "3.5",
                    "orient": "auto",
                    "markerUnits": "userSpaceOnUse",
                },
            )
            ET.SubElement(
                marker, NS + "path", {"d": "M 0 0 L 7 3.5 L 0 7 Z", "fill": color}
            )
        cells = {c.semantic_id: c for c in ir.cells}
        # Edges first: never paint lines over component text.
        for relation in facts.relations:
            route = next(r for r in ir.routes if r.semantic_id == relation.semantic_id)
            points = route_points(facts, ir, relation)
            if any(a == b for a, b in zip(points, points[1:])):
                raise IRValidationFault("mechanism_zero_length_edge_segment")
            color, dash = RELATIONS[relation.relation_type]
            ET.SubElement(
                root,
                NS + "polyline",
                {
                    "id": "edge." + relation.semantic_id,
                    "points": " ".join(f"{x},{y}" for x, y in points),
                    "fill": "none",
                    "stroke": color,
                    "stroke-width": "1.2",
                    "stroke-dasharray": dash,
                    "marker-end": "url(#arrow." + relation.relation_type + ")",
                },
            )
            # Reserve the long horizontal routing gap for an intact local name.
            # A narrow source-exit gutter cannot hold words like counterexample.
            spans = [(a, b) for a, b in pairwise(points) if a[1] == b[1]]
            label_width = len(relation.semantic_id) * ir.min_font_pt * 0.65
            spans = [(a, b) for a, b in spans if abs(b[0] - a[0]) >= label_width + 12]
            if not spans:
                raise IRValidationFault(
                    "mechanism_local_label_gap_required:" + relation.semantic_id
                )
            a, b = max(spans, key=lambda pair: abs(pair[1][0] - pair[0][0]))
            text_element(
                root,
                "edge-label." + relation.semantic_id,
                (relation.semantic_id,),
                (a[0] + b[0] - label_width) / 2,
                a[1] - 7,
                ir.min_font_pt,
            )
            label = (
                f"{relation.semantic_id} [{relation.relation_type}]: {relation.payload}; when {relation.trigger}"
                + ("; feedback" if relation.feedback else "")
            )
            lines = wrap(label, width - route.label_x - 12, ir.min_font_pt)
            if route.label_y + len(lines) * ir.min_font_pt * 1.45 > height - 8:
                raise IRValidationFault("mechanism_relation_label_out_of_bounds")
            text_element(
                root,
                "relation." + relation.semantic_id,
                lines,
                route.label_x,
                route.label_y,
                ir.min_font_pt,
            )
        for component in facts.components:
            cell = cells[component.semantic_id]
            group = ET.SubElement(
                root, NS + "g", {"id": "component." + component.semantic_id}
            )
            innovation = component.semantic_id == facts.innovation_id
            # Distinct semantic motifs remain simple editable primitives.
            fill = "#eff7fb" if innovation else "#ffffff"
            ET.SubElement(
                group,
                NS + "rect",
                {
                    "id": "body." + component.semantic_id,
                    "x": str(cell.x),
                    "y": str(cell.y),
                    "width": str(cell.width),
                    "height": str(cell.height),
                    "rx": "0" if component.family == "port_operation" else "8",
                    "fill": fill,
                    "stroke": "#0072b2" if innovation else "#555555",
                    "stroke-width": "2" if innovation else "1",
                },
            )
            self._component(
                group,
                component,
                cell,
                ir.min_font_pt,
                innovation,
                [
                    r
                    for r in facts.relations
                    if r.source_component == component.semantic_id
                ],
            )
            for port in component.ports:
                x, y = port_position(component, cell, port.port_id)
                ET.SubElement(
                    group,
                    NS + "circle",
                    {
                        "id": f"port.{component.semantic_id}.{port.port_id}",
                        "cx": str(x),
                        "cy": str(y),
                        "r": "3",
                        "fill": "#ffffff",
                        "stroke": "#222222",
                        "stroke-width": "1",
                    },
                )
        raw = ET.tostring(root, encoding="utf-8") + b"\n"
        if len(raw) > 262_144:
            raise IRValidationFault("mechanism_output_budget_exceeded")
        return raw

    def _component(self, group, c, cell, size, innovation, relations):
        content = ET.SubElement(group, NS + "g", {"id": "content." + c.semantic_id})
        x, y, w = cell.x + 12, cell.y + 10, cell.width - 24
        row = size * 1.45
        counter = 0

        def text(value, xx=x, yy=None, ww=w):
            nonlocal y, counter
            lines = wrap(value, ww, size)
            baseline = y + size if yy is None else yy + size
            text_element(
                content, f"label.{c.semantic_id}.{counter}", lines, xx, baseline, size
            )
            counter += 1
            if yy is None:
                y += len(lines) * row
            return len(lines) * row

        text(("INNOVATION: " if innovation else "") + c.label)
        text(f"{c.status} | {c.phase} | parameters: {c.parameters}")
        y += 5
        if c.family == "port_operation":
            for i, step in enumerate(c.steps):
                lines = wrap(f"{i + 1}. {step}", w - 20, size)
                table = (
                    c.coordinate_sum
                    if c.coordinate_sum and c.coordinate_sum.step_index == i
                    else None
                )
                h = len(lines) * row + 8
                table_height = (len(table.operands) + 2) * row + 14 if table else 0
                ET.SubElement(
                    content,
                    NS + "rect",
                    {
                        "x": str(x),
                        "y": str(y),
                        "width": str(w),
                        "height": str(h + table_height),
                        "fill": "#ffffff",
                        "stroke": "#0072b2",
                        "stroke-width": "0.7",
                    },
                )
                text(f"{i + 1}. {step}", x + 10, y + 3, w - 20)
                y += h
                if table:
                    self._coordinates(
                        content, c.semantic_id, table, x + 10, y, w - 20, size
                    )
                    y += table_height
                if i != len(c.steps) - 1:
                    ET.SubElement(
                        content,
                        NS + "line",
                        {
                            "x1": str(x + w / 2),
                            "x2": str(x + w / 2),
                            "y1": str(y),
                            "y2": str(y + 8),
                            "stroke": "#0072b2",
                            "stroke-width": "1",
                            "marker-end": "url(#arrow.data)",
                        },
                    )
                    y += 9
        else:
            for step in c.steps:
                text(step)
            if c.tokens:
                for t in c.tokens:
                    h = row + 8
                    half = (w - 35) / 2
                    for xx in (x, x + half + 35):
                        ET.SubElement(
                            content,
                            NS + "rect",
                            {
                                "x": str(xx),
                                "y": str(y),
                                "width": str(half),
                                "height": str(h),
                                "fill": "#eef6fa" if not t.masked else "#eeeeee",
                                "stroke": "#0072b2",
                                "stroke-width": "0.8",
                            },
                        )
                    text(f"{t.token_id}: {t.text}", x + 6, y + 3, half - 12)
                    text(" -> ", x + half + 6, y + 3, 30)
                    text(
                        t.representation_id + (" [MASK]" if t.masked else ""),
                        x + half + 41,
                        y + 3,
                        half - 12,
                    )
                    y += h + 4
            if c.axes:
                text("axes: " + "; ".join(c.axes))
            pair = None
            if c.condition:
                # Bind each predicate to its actual output circle, not left/right
                # boxes whose position has no relationship to top/bottom exits.
                outputs = [p for p in c.ports if p.direction == "output"]
                if len(outputs) != 2:
                    raise IRValidationFault("mechanism_two_branch_ports_required")
                branches = {r.source_port: r for r in relations}
                if len(relations) != 2 or set(branches) != {p.port_id for p in outputs}:
                    raise IRValidationFault("mechanism_branch_port_binding_required")
                for p in outputs:
                    relation = branches[p.port_id]
                    role, predicate = (
                        ("continue", c.condition)
                        if relation.feedback
                        else ("stop", c.stop_condition)
                    )
                    if relation.trigger != predicate:
                        raise IRValidationFault("mechanism_branch_predicate_mismatch")
                    value = role + ": " + predicate
                    px, py = port_position(c, cell, p.port_id)
                    lines = wrap(value, w - 42, size)
                    h = len(lines) * row + 10
                    top = py - h / 2
                    if top < y:
                        raise IRValidationFault(
                            "mechanism_predicate_space_required:" + c.semantic_id
                        )
                    ET.SubElement(
                        content,
                        NS + "rect",
                        {
                            "x": str(x),
                            "y": str(top),
                            "width": str(w - 30),
                            "height": str(h),
                            "fill": "#ffffff",
                            "stroke": "#333333",
                        },
                    )
                    text_element(
                        content,
                        f"predicate.{c.semantic_id}.{p.port_id}",
                        lines,
                        x + 6,
                        top + 5 + size,
                        size,
                    )
                    ET.SubElement(
                        content,
                        NS + "line",
                        {
                            "id": f"predicate-link.{c.semantic_id}.{p.port_id}",
                            "x1": str(x + w - 30),
                            "y1": str(py),
                            "x2": str(px),
                            "y2": str(py),
                            "stroke": "#333333",
                        },
                    )
                    y = top + h + 5
            elif c.before:
                pair = ("before: " + c.before, "after: " + c.after)
            if pair:
                half = (w - 20) / 2
                heights = [
                    len(wrap(value, half - 12, size)) * row + 10 for value in pair
                ]
                h = max(heights)
                for j, value in enumerate(pair):
                    xx = x + j * (half + 20)
                    ET.SubElement(
                        content,
                        NS + "rect",
                        {
                            "x": str(xx),
                            "y": str(y),
                            "width": str(half),
                            "height": str(h),
                            "fill": "#ffffff",
                            "stroke": "#555555",
                            "stroke-width": "0.8",
                        },
                    )
                    text(value, xx + 6, y + 4, half - 12)
                if c.before:
                    text(" -> ", x + half, y + 4, 20)
                y += h + 5
            if c.rule_change:
                self._rule_change(content, c.semantic_id, c.rule_change, x, y, w, size)
                y += row * 5 + 8
        y += 5
        for p in c.ports:
            text(
                f"{p.direction} {p.port_id}: {p.value_type} / {p.object_id}@{p.state_id}"
            )
        if y > cell.y + cell.height - 5:
            raise IRValidationFault(
                "mechanism_component_text_does_not_fit:" + c.semantic_id
            )

    def _coordinates(self, parent, identity, table, x, y, width, size):
        row = size * 1.45
        col = width / (len(table.axis_labels) + 1)
        text_element(
            parent,
            f"coordinate.{identity}.axis-label",
            ("coordinate",),
            x,
            y + size,
            size,
        )
        for j, name in enumerate(table.axis_labels):
            text_element(
                parent,
                f"coordinate.{identity}.axis.{j}",
                (name,),
                x + (j + 1) * col,
                y + size,
                size,
            )
        for i, operand in enumerate(table.operands):
            yy = y + (i + 1) * row + size
            text_element(
                parent,
                f"coordinate.{identity}.operand.{i}",
                (operand.label,),
                x,
                yy,
                size,
            )
            for j, value in enumerate(operand.values):
                text_element(
                    parent,
                    f"coordinate.{identity}.{i}.{j}",
                    (str(value),),
                    x + (j + 1) * col,
                    yy,
                    size,
                )
        yy = y + (len(table.operands) + 1) * row + 3
        ET.SubElement(
            parent,
            NS + "line",
            {
                "id": f"coordinate.{identity}.sum-bar",
                "x1": str(x),
                "x2": str(x + width),
                "y1": str(yy),
                "y2": str(yy),
                "stroke": "#333333",
            },
        )
        text_element(
            parent,
            f"coordinate.{identity}.result",
            (table.result_label,),
            x,
            yy + size + 3,
            size,
        )
        for j, value in enumerate(table.result):
            expression = (
                " + ".join(str(o.values[j]) for o in table.operands)
                + " = "
                + str(value)
            )
            if len(wrap(expression, col - 8, size)) != 1:
                raise IRValidationFault("mechanism_coordinate_column_too_narrow")
            text_element(
                parent,
                f"coordinate.{identity}.sum.{j}",
                (expression,),
                x + (j + 1) * col,
                yy + size + 3,
                size,
            )

    def _rule_change(self, parent, identity, change, x, y, width, size):
        row = size * 1.45
        prefix = f"rule.{identity}."
        # Stable columns expose unchanged antecedent/conclusion and isolate the
        # exact added source clause, including a non-color border/weight cue.
        left = x + 45
        added_x = left + (len(change.retained_clause) + 2) * size * 0.65
        added_width = (len(change.added_clause) + 2) * size * 0.65
        conclusion_x = added_x + added_width + 8
        if conclusion_x + len(change.conclusion) * size * 0.65 > x + width:
            raise IRValidationFault("mechanism_rule_columns_too_narrow")
        text_element(
            parent, prefix + "added-label", ("ADDED GUARD",), added_x, y + size, size
        )
        for i, role in enumerate(("before", "after")):
            yy = y + (i * 2 + 2) * row
            text_element(parent, prefix + role, (role + ":",), x, yy, size)
            text_element(
                parent,
                prefix + role + ".retained",
                (change.retained_clause,),
                left,
                yy,
                size,
            )
            text_element(
                parent,
                prefix + role + ".conclusion",
                (change.conclusion,),
                conclusion_x,
                yy,
                size,
            )
            if role == "after":
                ET.SubElement(
                    parent,
                    NS + "rect",
                    {
                        "id": prefix + "guard-box",
                        "x": str(added_x - 3),
                        "y": str(yy - size - 3),
                        "width": str(added_width),
                        "height": str(row + 6),
                        "fill": "#fff3d6",
                        "stroke": "#333333",
                        "stroke-width": "2",
                    },
                )
                text_element(
                    parent, prefix + "added", (change.added_clause,), added_x, yy, size
                ).set("font-weight", "bold")


def render_mechanism(service, ir, *, run_root, resolution_context=None, events=None):
    context = resolution_context or ResolutionContext(
        "mechanism.local", (Path(run_root),)
    )
    if tuple(Path(p).absolute() for p in context.run_roots) != (
        Path(run_root).absolute(),
    ):
        raise IRValidationFault("mechanism_cross_run_sources_unsupported")
    facts = load_facts(service, ir, run_root, context, events)
    return canonical_json_bytes(ir.model_dump(mode="json")), MechanismRenderer().render(
        facts, ir
    )


def qualify_mechanism(
    service, ir, *, run_root, request, visual_review_id=None, resolution_context=None
):
    def prepare(events):
        context = resolution_context or ResolutionContext(
            "composition.local", (Path(run_root),)
        )
        context = replace(context, held_lock_roots=(Path(run_root).absolute(),))
        if ir.supersedes:
            old = service.inspect(ir.supersedes, run_root=run_root, _events=events)[
                "receipt"
            ]
            if (
                old["artifact_kind"] != "mechanism_figure"
                or ir.revision != old["revision"] + 1
            ):
                raise IRValidationFault("mechanism_supersession_revision_mismatch")
        raw, output = render_mechanism(
            service, ir, run_root=run_root, resolution_context=context, events=events
        )
        statuses = {
            "schema": "PASS",
            "provenance": "PASS",
            "semantic": "PASS",
            "render": "PASS",
            "visual": "UNAVAILABLE",
        }
        reviewer, reasons = None, []
        if visual_review_id:
            try:
                review, event, _ = accepted_content(run_root, events, visual_review_id)
                if (
                    review.get("schema_version") != "arw.visual-review.v1"
                    or review.get("ir_sha256") != sha256_hex(raw)
                    or review.get("output_sha256") != sha256_hex(output)
                    or review.get("status") not in {"PASS", "FAIL"}
                ):
                    raise ValueError("composition review binding mismatch")
                reviewer = VisualReviewer.model_validate_json(
                    json.dumps(
                        {
                            **review["reviewer"],
                            "evidence_artifact_id": visual_review_id,
                            "evidence_event_id": event.event_id,
                            "evidence_event_sha256": event.event_sha256,
                        }
                    )
                )
                statuses["visual"] = review["status"]
            except (ValueError, KeyError, TypeError):
                statuses["visual"] = "FAIL"
                reasons.append("invalid_visual_review_binding")
        elif ir.validation_policy.visual == "OPTIONAL":
            statuses["visual"] = "OPTIONAL_SKIPPED"
        elif ir.validation_policy.visual == "NOT_APPLICABLE":
            statuses["visual"] = "NOT_APPLICABLE"
        passed = "FAIL" not in statuses.values() and all(
            statuses[k] == "PASS"
            for k, v in ir.validation_policy.model_dump(mode="json").items()
            if v == "REQUIRED"
        )
        digest = sha256_hex(raw)
        candidate = f".arw/artifacts/candidates/{ir.artifact_id}/{digest}"
        accepted = f".arw/artifacts/accepted/{ir.artifact_id}"
        prefix = accepted if passed else candidate
        receipt = MechanismFigureReceipt(
            artifact_id=ir.artifact_id,
            revision=ir.revision,
            ir_sha256=digest,
            renderer=MechanismRenderer().identity,
            inputs=ir.research_bindings,
            outputs=(
                OutputDigest(path=prefix + "/ir.json", sha256=digest),
                OutputDigest(path=prefix + "/figure.svg", sha256=sha256_hex(output)),
            ),
            min_font_pt=ir.min_font_pt,
            validation_policy=ir.validation_policy,
            validation=ValidationResults.model_validate_json(json.dumps(statuses)),
            qualification="PASS" if passed else "FAIL",
            purpose="publication-critical"
            if ir.publication_critical
            else "exploratory",
            visual_reviewer=reviewer,
            reason_codes=tuple(reasons),
        )
        files = {
            candidate + "/ir.json": raw,
            candidate + "/figure.svg": output,
            candidate + "/receipt.json": canonical_json_bytes(
                receipt.model_dump(mode="json")
            ),
        }
        if passed:
            files.update(
                {
                    k.replace(candidate + "/", accepted + "/", 1): v
                    for k, v in list(files.items())
                }
            )
        return ir, receipt, files

    return commit_artifact_pipeline(
        run_root, request, prepare, boundary=service.boundary
    )
