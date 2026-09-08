"""Deterministic SVG source rendering; raster typography remains host-dependent."""

from __future__ import annotations

import html
from pathlib import Path

from arw.kernel.core.canonical import sha256_hex
from arw.kernel.state.research_artifact import RendererIdentity


def _wrap(text: str, width: int) -> list[str]:
    lines, line, size = [], "", 0
    for character in text:
        codepoint = ord(character)
        # Fixed approximate width ranges keep SVG bytes independent of the
        # host Python Unicode database. Visual review still owns typography.
        units = (
            2
            if any(
                start <= codepoint <= end
                for start, end in (
                    (0x1100, 0x11FF),
                    (0x2E80, 0xA4CF),
                    (0xAC00, 0xD7AF),
                    (0xF900, 0xFAFF),
                    (0xFE10, 0xFE6F),
                    (0xFF01, 0xFF60),
                    (0xFFE0, 0xFFE6),
                    (0x1F300, 0x1FAFF),
                    (0x20000, 0x3FFFF),
                )
            )
            else 1
        )
        if character == "\n" or size + units > width:
            lines.append(line)
            line, size = "", 0
        if character != "\n":
            line += character
            size += units
    lines.append(line)
    return lines


def _text(text, x, y, width=48, size=15):
    lines = _wrap(text, width)
    spans = "".join(
        f'<tspan x="{x}" dy="{0 if i == 0 else size + 6}">{html.escape(line)}</tspan>'
        for i, line in enumerate(lines)
    )
    return f'<text x="{x}" y="{y}" font-size="{size}">{spans}</text>'


class SvgRenderer:
    @property
    def identity(self):
        return RendererIdentity(
            name="arw.svg",
            version="1.0.0",
            identity_digest=sha256_hex(Path(__file__).read_bytes()),
            normalization_policy="utf8-lf-sorted-elements-integer-layout.v1",
        )

    def render(self, ir) -> bytes:
        nodes = {n.id: n for n in ir.nodes}
        pending = set(nodes)
        ordered = []
        while pending:
            ready = sorted(
                identifier
                for identifier in pending
                if not any(
                    edge.target == identifier
                    and edge.source in pending
                    and edge.source != identifier
                    for edge in ir.edges
                )
            )
            if not ready:
                ready = [min(pending)]
            ordered.extend(ready)
            pending.difference_update(ready)
        rank = {identifier: index for index, identifier in enumerate(ordered)}
        grouped = {member for group in ir.groups for member in group.members}
        order = [(None, sorted(set(nodes) - grouped, key=rank.get))]
        order += [
            (group, sorted(group.members, key=rank.get))
            for group in sorted(ir.groups, key=lambda g: g.id)
        ]
        positions, groups, y = {}, [], 135
        for group, members in order:
            top = y
            if group:
                y += 48
            for identifier in members:
                height = max(88, 40 + len(_wrap(nodes[identifier].label, 48)) * 21)
                positions[identifier] = (80, y, 440, height)
                y += height + 55
            if group:
                groups.append((group, top, y - top - 15))
                y += 20
        width = max(920, 700 + len(ir.edges) * 20)
        annotations_height = sum(
            40 + len(_wrap(a.text, 90)) * 20 for a in ir.annotations
        )
        height = y + annotations_height + 75
        ink, fill = (
            ("#243b53", "#eef5fc")
            if ir.presentation.theme == "blue"
            else ("#222222", "#f5f5f5")
        )
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">',
            f"<title>{html.escape(ir.title)}</title>",
            '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 Z" fill="#526777"/></marker></defs>',
            f'<g font-family="{ir.presentation.font_family}" fill="{ink}">',
            _text(ir.title, 45, 40, 88, 21),
            _text(
                "Publication-critical"
                if ir.publication_critical
                else "Exploratory research projection",
                45,
                95,
                88,
                12,
            ),
        ]
        for group, top, group_height in groups:
            parts += [
                f'<g id="{group.id}"><rect x="55" y="{top}" width="490" height="{group_height}" rx="8" fill="none" stroke="#9fb3c8" stroke-dasharray="6 4"/>',
                _text(group.label, 70, top + 25, 58, 13),
                "</g>",
            ]
        for index, edge in enumerate(sorted(ir.edges, key=lambda e: e.id)):
            x, sy, w, sh = positions[edge.source]
            _, ty, _, th = positions[edge.target]
            sy += sh // 2
            ty += th // 2
            rail = 590 + index * 20
            parts += [
                f'<g id="{edge.id}"><path d="M {x + w} {sy} H {rail} V {ty} H {x + w + 5}" fill="none" stroke="#526777" marker-end="url(#arrow)"/>',
                f"<title>{html.escape(edge.label)}</title>",
                _text(edge.label, rail + 4, (sy + ty) // 2, 24, 11),
                "</g>",
            ]
        for identifier in sorted(positions):
            node = nodes[identifier]
            x, ny, w, h = positions[identifier]
            parts += [
                f'<g id="{identifier}"><rect x="{x}" y="{ny}" width="{w}" height="{h}" rx="7" fill="{fill}" stroke="#526777"/>',
                _text(node.label, x + 18, ny + 29),
                _text(
                    f"{node.kind} · confidence {node.confidence}/100",
                    x + 18,
                    ny + h - 14,
                    48,
                    10,
                ),
                "</g>",
            ]
        for annotation in sorted(ir.annotations, key=lambda a: a.id):
            parts += [
                f'<g id="{annotation.id}">',
                _text(annotation.text, 45, y + 15, 90, 14),
                "</g>",
            ]
            y += 40 + len(_wrap(annotation.text, 90)) * 20
        parts += ["</g>", "</svg>"]
        return ("\n".join(parts) + "\n").encode("utf-8")
