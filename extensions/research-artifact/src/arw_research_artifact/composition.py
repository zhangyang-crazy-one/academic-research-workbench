"""First-party inert SVG composition over canonical scientific sources."""

from __future__ import annotations

import copy
import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.ledger.accepted_refs import (
    ResolutionContext,
    ResolutionCache,
    to_accepted_ref,
)
from arw.kernel.ledger.research_records import commit_artifact_pipeline
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.state.figure_composition import (
    SCIENTIFIC_OBJECT,
    EntityGraphObject,
    FigureCompositionReceipt,
    PanelTypography,
    SequenceObject,
)
from arw.kernel.state.research_artifact import (
    OutputDigest,
    RendererIdentity,
    ValidationResults,
    VisualReviewer,
)
from .renderer import _text, _wrap
from .validation import IRValidationFault, accepted_content

NS = "{http://www.w3.org/2000/svg}"
ET.register_namespace("", NS[1:-1])


def safe_tree(raw):
    """Closed geometry/text subset; only local marker/clip URL references."""
    if len(raw) > 2_097_152 or b"<!" in raw or b"<?" in raw:
        raise IRValidationFault("composition_unsafe_svg_declaration")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise IRValidationFault("composition_invalid_svg") from exc
    if root.tag != NS + "svg":
        raise IRValidationFault("composition_invalid_svg_root")
    tags = {
        "svg",
        "g",
        "defs",
        "marker",
        "clipPath",
        "title",
        "desc",
        "text",
        "tspan",
        "line",
        "rect",
        "circle",
        "ellipse",
        "path",
        "polygon",
        "polyline",
    }
    attrs = {
        "role",
        "aria-labelledby",
        "aria-label",
        "id",
        "xmlns",
        "width",
        "height",
        "viewBox",
        "x",
        "y",
        "x1",
        "y1",
        "x2",
        "y2",
        "cx",
        "cy",
        "r",
        "rx",
        "ry",
        "d",
        "points",
        "fill",
        "stroke",
        "stroke-width",
        "stroke-dasharray",
        "font-family",
        "font-size",
        "font-weight",
        "text-anchor",
        "dominant-baseline",
        "dy",
        "dx",
        "marker-end",
        "marker-start",
        "markerWidth",
        "markerHeight",
        "refX",
        "refY",
        "orient",
        "markerUnits",
        "clip-path",
    }
    ids, references = [], []
    for el in root.iter():
        if not el.tag.startswith(NS) or el.tag[len(NS) :] not in tags:
            raise IRValidationFault("composition_unsafe_svg_element")
        for key, value in el.attrib.items():
            if key not in attrs or re.search(
                r"@import|javascript:|expression\s*\(", value, re.I
            ):
                raise IRValidationFault("composition_unsafe_svg_attribute")
            if re.search(r"url\s*\(", value, re.I):
                match = re.fullmatch(r"url\(#([A-Za-z0-9_.-]+)\)", value)
                if key not in {"marker-start", "marker-end", "clip-path"} or not match:
                    raise IRValidationFault("composition_external_svg_reference")
                references.append(match[1])
        if "id" in el.attrib:
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", el.attrib["id"]):
                raise IRValidationFault("composition_invalid_svg_id")
            ids.append(el.attrib["id"])
    if len(set(ids)) != len(ids):
        raise IRValidationFault("composition_duplicate_svg_id")
    if not set(references) <= set(ids):
        raise IRValidationFault("composition_dangling_svg_reference")
    return root


def namespace_tree(root, prefix):
    child = copy.deepcopy(root)
    for el in child.iter():
        if "id" in el.attrib:
            el.attrib["id"] = prefix + el.attrib["id"]
        for key, value in list(el.attrib.items()):
            if value.startswith("url(#"):
                el.attrib[key] = "url(#" + prefix + value[5:]
    return child


def number(value):
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


class CompositionRenderer:
    @property
    def identity(self):
        return RendererIdentity(
            name="arw.composition-svg",
            version="1.0.0",
            identity_digest=sha256_hex(Path(__file__).read_bytes()),
            normalization_policy="utf8-svg-bounded-cells-uniform6.v1",
        )

    def _object(self, obj, encodings):
        parts = []

        def symbol(identity, x, y):
            if identity not in encodings:
                raise IRValidationFault("composition_missing_shared_encoding")
            e = encodings[identity]
            common = f'fill="{e.color}" stroke="#222222" stroke-width="1"'
            if e.shape == "circle":
                parts.append(f'<circle cx="{x}" cy="{y}" r="8" {common}/>')
            elif e.shape == "square":
                parts.append(
                    f'<rect x="{x - 8}" y="{y - 8}" width="16" height="16" {common}/>'
                )
            else:
                parts.append(
                    f'<polygon points="{x},{y - 9} {x + 9},{y} {x},{y + 9} {x - 9},{y}" {common}/>'
                )
            dash = {"solid": "", "dashed": "8 4", "dotted": "2 3"}[e.line_style]
            parts.append(
                f'<line x1="{x + 14}" y1="{y}" x2="{x + 38}" y2="{y}" stroke="{e.color}" stroke-width="2" stroke-dasharray="{dash}"/>'
            )

        if isinstance(obj, SequenceObject):
            symbol(obj.object_id, 20, 20)
            parts.append(_text(f"{obj.object_id} / {obj.state_id}", 68, 25, 44, 16))
            for i, segment in enumerate(obj.segments):
                y = 70 + i * 84
                parts.append(f'<g id="{segment.segment_id}">')
                if segment.highlighted:
                    parts.append(
                        f'<rect x="8" y="{y - 22}" width="420" height="76" fill="#ffffff" stroke="{encodings[obj.object_id].color}" stroke-width="2"/>'
                    )
                parts.append(_text(segment.text, 20, y, 40, 16))
                parts.append("</g>")
            width, height = 450, 85 * len(obj.segments) + 55
        else:
            assert isinstance(obj, EntityGraphObject)
            width, height = (
                900,
                max(240, 140 * len(obj.entities) + 80, 120 * len(obj.relations) + 60),
            )
            if obj.expanded_group:
                parts.append(
                    _text(
                        obj.expanded_group.label
                        + ": "
                        + ", ".join(obj.expanded_group.members),
                        10,
                        20,
                        70,
                        14,
                    )
                )
            entity_start = len(parts)
            positions = {}
            for i, e in enumerate(obj.entities):
                y = 80 + i * 140
                positions[e.object_id] = y
                parts.append(f'<g id="{e.object_id}">')
                symbol(e.object_id, 20, y)
                parts.append(_text(e.label, 68, y - 10, 30, 18))
                parts.append(
                    _text(
                        f"{e.object_id} [{e.entity_type}; {e.state_id}]",
                        68,
                        y + 25,
                        38,
                        14,
                    )
                )
                parts.append("</g>")
            entity_parts = parts[entity_start:]
            parts = parts[:entity_start]
            for i, r in enumerate(obj.relations):
                sy, ty = positions[r.source], positions[r.target]
                rail = 430 + i * 10
                # A per-relation marker and labeled path preserve source direction.
                parts.append(
                    f'<defs><marker id="arrow.{r.relation_id}" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#333333"/></marker></defs>'
                )
                via = ty if sy != ty else ty - 35
                path = f"M28,{sy} L{rail},{sy} L{rail},{via} L28,{via} L28,{ty}"
                arrow = (
                    f' marker-end="url(#arrow.{r.relation_id})"' if r.directed else ""
                )
                dash = {"control": "", "data": "8 4", "support": "2 3"}[r.relation_type]
                parts.append(
                    f'<g id="{r.relation_id}"><path d="{path}" fill="none" stroke="#333333" stroke-width="2" stroke-dasharray="{dash}"{arrow}/>'
                )
                parts.append(
                    _text(f"({i + 1})", rail + 5, (sy + ty) / 2 + 18 * (i % 3), 6, 14)
                )
                parts.append(
                    _text(
                        f"({i + 1}) {r.relation_type}: {r.label}",
                        580,
                        80 + i * 120,
                        30,
                        14,
                    )
                )
                parts.append("</g>")
            parts.extend(entity_parts)
        return safe_tree(
            (
                f'<svg xmlns="{NS[1:-1]}" viewBox="0 0 {width} {height}"><g font-family="Noto Sans CJK SC, sans-serif">'
                + "".join(parts)
                + "</g></svg>"
            ).encode()
        )

    def render(self, ir, *, run_root, service, context, events):
        if ir.renderer_hints != self.identity:
            raise IRValidationFault("pinned_composition_renderer_unavailable")
        cache = ResolutionCache()
        encodings = {e.semantic_id: e for e in ir.encodings}
        children = []
        total = 0
        for panel in sorted(ir.panels, key=lambda p: p.reading_order):
            resolved = to_accepted_ref(panel.content_ref, context, cache=cache)
            if resolved.status != "resolved":
                raise IRValidationFault(
                    "composition_source_unresolved:" + str(resolved.reason)
                )
            value = resolved.selected_value
            total += len(resolved.raw_bytes or b"")
            if total > 8_388_608:
                raise IRValidationFault("composition_source_budget_exceeded")
            if sha256_hex(canonical_json_bytes(value)) != panel.content_sha256:
                raise IRValidationFault("composition_selected_digest_mismatch")
            for claim in panel.claims:
                result = to_accepted_ref(claim, context, cache=cache)
                if result.status != "resolved":
                    raise IRValidationFault("composition_claim_unresolved")
            if panel.content_kind == "accepted_v1":
                if panel.content_ref.json_pointer != "":
                    raise IRValidationFault("composition_child_requires_whole_receipt")
                inspected = service.inspect(
                    panel.content_ref.artifact_id, run_root=run_root, _events=events
                )
                receipt = inspected["receipt"]
                if (
                    receipt != value
                    or receipt["qualification"] != "PASS"
                    or receipt["artifact_kind"]
                    not in {"result_plot", "methodology_figure", "evidence_graph_view"}
                    or receipt["renderer"] != panel.renderer.model_dump(mode="json")
                    or not inspected["renderer_available"]
                ):
                    raise IRValidationFault("composition_child_identity_mismatch")
                raw = read_retained_bytes(
                    run_root,
                    f".arw/artifacts/accepted/{panel.content_ref.artifact_id}/figure.svg",
                )
                child = safe_tree(raw)
                # Re-encoding is not an in-place mutation of an accepted SVG.
                if receipt["artifact_kind"] == "result_plot":
                    self._child_encodings(panel, encodings, run_root)
            else:
                if panel.renderer != self.identity:
                    raise IRValidationFault("composition_object_renderer_mismatch")
                obj = SCIENTIFIC_OBJECT.validate_json(canonical_json_bytes(value))
                if obj.kind != panel.content_kind or panel.role == "quantitative":
                    raise IRValidationFault("composition_object_kind_mismatch")
                child = self._object(obj, encodings)
            children.append(
                (panel, namespace_tree(child, f"arw_panel_{panel.reading_order}__"))
            )
        return self._assemble(ir, children, encodings)

    def _child_encodings(self, panel, encodings, root):
        from .plot_renderer import OKABE_ITO

        payload = json.loads(
            read_retained_bytes(
                root, f".arw/artifacts/accepted/{panel.content_ref.artifact_id}/ir.json"
            )
        )
        series = sorted(
            {d.get("series", "") for layer in payload["layers"] for d in layer["data"]}
        )
        palette = (
            OKABE_ITO
            if payload["presentation"]["palette"] == "okabe_ito"
            else ("#222222",)
        )
        for i, name in enumerate(series):
            if name in encodings:
                e = encodings[name]
                if (
                    e.color.lower() != palette[i % len(palette)].lower()
                    or e.shape != "circle"
                    or e.line_style != "solid"
                ):
                    raise IRValidationFault(
                        "composition_child_encoding_requires_new_candidate"
                    )

    def _assemble(self, ir, children, encodings):
        width, height = ir.width_mm * 72 / 25.4, ir.height_mm * 72 / 25.4
        gap, margin = ir.layout.gap_pt, 10
        legend_height = 20 * len(ir.legend_ids)

        def divisions(ratios, available):
            if available <= 0:
                raise IRValidationFault("composition_canvas_too_small")
            return [available * v / sum(ratios) for v in ratios]

        columns = divisions(
            ir.layout.column_ratios,
            width - 2 * margin - gap * (len(ir.layout.column_ratios) - 1),
        )
        rows = divisions(
            ir.layout.row_ratios,
            height - 2 * margin - legend_height - gap * (len(ir.layout.row_ratios) - 1),
        )
        out = ET.Element(
            NS + "svg",
            {
                "width": number(ir.width_mm) + "mm",
                "height": number(ir.height_mm) + "mm",
                "viewBox": f"0 0 {number(width)} {number(height)}",
            },
        )
        desc = ET.SubElement(out, NS + "desc")
        desc.text = ir.visual_argument
        typography = []
        for panel, child in children:
            p = panel.position
            x, y = (
                margin + sum(columns[: p.column]) + gap * p.column,
                margin + sum(rows[: p.row]) + gap * p.row,
            )
            cw = sum(columns[p.column : p.column + p.column_span]) + gap * (
                p.column_span - 1
            )
            title_lines = _wrap(f"({panel.label}) {panel.title}", max(4, int(cw / 6)))
            header = max(32, len(title_lines) * 17 + 8)
            ch = sum(rows[p.row : p.row + p.row_span]) + gap * (p.row_span - 1) - header
            try:
                vx, vy, sw, sh = map(float, child.attrib["viewBox"].split())
                if (
                    not all(math.isfinite(n) for n in (vx, vy, sw, sh))
                    or vx != 0
                    or vy != 0
                    or sw <= 0
                    or sh <= 0
                    or ch <= 0
                ):
                    raise ValueError
            except (KeyError, ValueError) as exc:
                raise IRValidationFault("composition_invalid_child_viewbox") from exc
            scale = min(cw / sw, ch / sh)
            factor = {"start": 0, "center": 0.5, "end": 1}[p.align]
            tx, ty = (
                x + (cw - sw * scale) * factor,
                y + header + (ch - sh * scale) * factor,
            )
            label = ET.SubElement(
                out,
                NS + "text",
                {
                    "x": number(x),
                    "y": number(y + 14),
                    "font-size": "11",
                    "font-family": "Noto Sans CJK SC, sans-serif",
                },
            )
            for i, line in enumerate(title_lines):
                span = ET.SubElement(
                    label, NS + "tspan", {"x": number(x), "dy": "0" if i == 0 else "17"}
                )
                span.text = line
            group = ET.SubElement(
                out,
                NS + "g",
                {
                    "id": f"arw_panel_{panel.reading_order}",
                    "transform": f"translate({number(tx)} {number(ty)}) scale({number(scale)})",
                },
            )
            # Root presentation is retained; never replace with a clipping viewport.
            inner = ET.SubElement(
                group,
                NS + "g",
                {
                    k: v
                    for k, v in child.attrib.items()
                    if k not in {"width", "height", "viewBox"}
                },
            )
            inner.extend(list(child))
            fonts = [
                float(e.attrib["font-size"])
                for e in child.iter()
                if "font-size" in e.attrib
            ]
            if not fonts or min(fonts) <= 0:
                raise IRValidationFault("composition_child_typography_unsupported")
            typography.append(
                PanelTypography(
                    panel_id=panel.panel_id,
                    min_font_pt=min(11.0, min(fonts) * float(number(scale))),
                    uniform_scale=scale,
                )
            )
        for i, identifier in enumerate(ir.legend_ids):
            e = encodings[identifier]
            # Render the same shape + line style used by objects, not a separate palette.
            marker = self._object(
                SequenceObject(
                    kind="sequence",
                    object_id=identifier,
                    state_id="legend",
                    segments=({"segment_id": "legend.segment", "text": e.label},),
                ),
                encodings,
            )
            # Only the identity symbol and the stable label belong in the legend.
            group = ET.SubElement(
                out,
                NS + "g",
                {
                    "transform": f"translate(10 {number(height - legend_height + i * 20)}) scale(0.6)"
                },
            )
            source_group = list(marker)[0]
            group.extend(list(source_group)[:2])
            text = ET.SubElement(
                group,
                NS + "text",
                {
                    "x": "68",
                    "y": "25",
                    "font-size": "16",
                    "font-family": "Noto Sans CJK SC, sans-serif",
                },
            )
            text.text = e.label
        ids = [e.attrib["id"] for e in out.iter() if "id" in e.attrib]
        if len(ids) != len(set(ids)):
            raise IRValidationFault("composition_duplicate_final_svg_id")
        output = ET.tostring(out, encoding="utf-8") + b"\n"
        if len(output) > 2_097_152:
            raise IRValidationFault("composition_output_budget_exceeded")
        return output, tuple(typography)


def render_composition(service, ir, *, run_root, resolution_context=None, events=None):
    context = resolution_context or ResolutionContext(
        "composition.local", (Path(run_root),)
    )
    if tuple(Path(p).absolute() for p in context.run_roots) != (
        Path(run_root).absolute(),
    ):
        raise IRValidationFault("composition_cross_run_children_unsupported")
    replay = service._plot_replay(run_root, context)
    if events is not None and replay.events != tuple(events):
        raise IRValidationFault("composition_prefix_differs_from_parent_history")
    output, typography = CompositionRenderer().render(
        ir, run_root=run_root, service=service, context=context, events=replay.events
    )
    return canonical_json_bytes(ir.model_dump(mode="json")), output, typography


def qualify_composition(
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
                old["artifact_kind"] != "figure_composition"
                or ir.revision != old["revision"] + 1
            ):
                raise IRValidationFault("composition_supersession_revision_mismatch")
        raw, output, typography = render_composition(
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
        receipt = FigureCompositionReceipt(
            artifact_id=ir.artifact_id,
            revision=ir.revision,
            ir_sha256=digest,
            renderer=CompositionRenderer().identity,
            inputs=ir.research_bindings,
            outputs=(
                OutputDigest(path=prefix + "/ir.json", sha256=digest),
                OutputDigest(path=prefix + "/figure.svg", sha256=sha256_hex(output)),
            ),
            typography=typography,
            min_font_pt=min(
                [p.min_font_pt for p in typography] + ([9.6] if ir.legend_ids else [])
            ),
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
