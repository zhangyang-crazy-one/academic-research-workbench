"""Optional deterministic PGFPlots source; never invokes or qualifies TeX."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.state.research_artifact import RendererIdentity

from .plot_policy import PlotFault
from .plot_renderer import OKABE_ITO

ESCAPES = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "%": r"\%",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "_": r"\_",
    "^": r"\textasciicircum{}",
    "~": r"\textasciitilde{}",
}


def tex_text(value: str) -> str:
    """Escape once, per character; no user fragment becomes TeX syntax."""
    if any(ord(c) < 32 and c not in "\t\r\n" for c in value) or "\x7f" in value:
        raise PlotFault("tex_control_character")
    return "".join(" " if c in "\t\r\n" else ESCAPES.get(c, c) for c in value)


def rational(value: Fraction) -> str:
    # Avoid TeX division for finite decimals while preserving exact values.
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        return f"{{{value.numerator}/{value.denominator}}}"
    places = max(twos, fives)
    scaled = value.numerator * 2 ** (places - twos) * 5 ** (places - fives)
    if places == 0:
        return str(scaled)
    digits = str(abs(scaled)).zfill(places + 1)
    return ("-" if scaled < 0 else "") + digits[:-places] + "." + digits[-places:]


class PGFPlotsExporter:
    @property
    def identity(self):
        own = Path(__file__).read_bytes()
        palette_source = Path(__file__).with_name("plot_renderer.py").read_bytes()
        return RendererIdentity(
            name="arw.result-pgfplots",
            version="1.0.1",
            identity_digest=sha256_hex(own + b"\0" + palette_source),
            normalization_policy="utf8-lf-inert-text-exact-decimal-or-rational.v1",
        )

    def export(self, compiled):
        ir = compiled.ir
        rows = [d for _, group in compiled.layers for d in group]
        categories = ir.scales.x.categories or tuple(sorted({d.category for d in rows}))
        series = tuple(sorted({d.series for d in rows}))
        named = tuple(s for s in series if s)
        if len(series) > 8:
            raise PlotFault("series_budget_exceeded")
        palette = OKABE_ITO if ir.presentation.palette == "okabe_ito" else ("#222222",)
        colors = {s: palette[i % len(palette)] for i, s in enumerate(series)}
        options = [
            f"title={{{tex_text(ir.title)}}}",
            f"xlabel={{{tex_text(ir.scales.x.unit)}}}",
            f"ylabel={{{tex_text(ir.scales.y.unit)}}}",
            "unbounded coords=jump",
        ]
        for axis, scale in (("x", ir.scales.x), ("y", ir.scales.y)):
            if scale.type == "log":
                options.append(f"{axis}mode=log")
            if scale.domain:
                lo, hi = scale.domain
                options.extend(
                    (
                        f"{axis}min={rational(lo.as_fraction())}",
                        f"{axis}max={rational(hi.as_fraction())}",
                    )
                )
        if ir.scales.x.type == "band":
            options += [
                "xtick={" + ",".join(str(i) for i in range(len(categories))) + "}",
                "xticklabels={"
                + ",".join("{" + tex_text(c) + "}" for c in categories)
                + "}",
            ]

        def x_coordinate(datum, layer):
            if ir.scales.x.type != "band":
                return datum.x.exact.as_fraction()
            if datum.category not in categories:
                raise PlotFault("category_outside_explicit_domain")
            x = Fraction(categories.index(datum.category))
            if datum.series and len(named) > 1:
                x += (
                    Fraction(named.index(datum.series)) - Fraction(len(named) - 1, 2)
                ) * Fraction(1, len(named) + 2)
            if layer.jitter_axis:
                if not datum.stable_row_id:
                    raise PlotFault("jitter_requires_stable_row_id")
                digest = int(sha256_hex(datum.stable_row_id.encode())[:16], 16)
                x += (Fraction(digest, 2**64 - 1) - Fraction(1, 2)) * Fraction(
                    2, 5 * (len(named) + 2)
                )
            return x

        parts = [
            "% source plot_value_id: " + v.plot_value_id for v in compiled.plot_values
        ]
        parts += [r"\begin{tikzpicture}", r"\begin{axis}[" + ",\n".join(options) + "]"]
        for layer, data in compiled.layers:
            groups = sorted(
                {(d.series, d.pair_id if layer.paired else None) for d in data},
                key=lambda k: (k[0], k[1] or ""),
            )
            for group in groups:
                selected = [
                    d
                    for d in data
                    if (d.series, d.pair_id if layer.paired else None) == group
                ]
                if layer.mark == "line":
                    selected.sort(key=lambda d: d.order)
                rgb = colors[group[0]].lstrip("#")
                color = (
                    "{rgb,255:red,"
                    + str(int(rgb[:2], 16))
                    + ";green,"
                    + str(int(rgb[2:4], 16))
                    + ";blue,"
                    + str(int(rgb[4:], 16))
                    + "}"
                )
                style = (
                    "mark=*"
                    if layer.mark == "line"
                    else "ybar,bar width=8pt"
                    if layer.mark == "bar"
                    else "only marks,mark=*"
                )
                if layer.role == "interval":
                    for d in selected:
                        parts.append(
                            r"\addplot+[mark=none,color=" + color + "] coordinates {"
                        )
                        x = rational(x_coordinate(d, layer))
                        for endpoint in (d.lower, d.upper):
                            parts.append("% plot_value_id: " + endpoint.plot_value_id)
                            parts.append(
                                "("
                                + x
                                + ","
                                + rational(endpoint.exact.as_fraction())
                                + ")"
                            )
                        parts.append("};")
                else:
                    parts.append(
                        r"\addplot+[" + style + ",color=" + color + "] coordinates {"
                    )
                    for d in selected:
                        # IDs are compiler-generated StableRuntimeIds; comments
                        # encode all provenance IDs separately in the manifest.
                        parts.append("% plot_value_id: " + d.y.plot_value_id)
                        parts.append(
                            "("
                            + rational(x_coordinate(d, layer))
                            + ","
                            + rational(d.y.exact.as_fraction())
                            + ")"
                        )
                    parts.append("};")
                if group[0]:
                    parts.append(r"\addlegendentry{" + tex_text(group[0]) + "}")
        parts += [
            r"\end{axis}",
            r"\end{tikzpicture}",
            r"\par " + tex_text(ir.caption),
            r"\par " + tex_text(ir.manuscript_reference),
        ]
        source = ("\n".join(parts) + "\n").encode("utf-8")
        if len(source) > 2_097_152:
            raise PlotFault("render_output_budget_exceeded")
        metadata = {
            "schema_version": "arw.pgfplots-source-export.v1",
            "artifact_id": ir.artifact_id,
            "revision": ir.revision,
            "ir_sha256": sha256_hex(canonical_json_bytes(ir.model_dump(mode="json"))),
            "exporter": self.identity.model_dump(mode="json"),
            "source_sha256": sha256_hex(source),
            "plot_values": [v.model_dump(mode="json") for v in compiled.plot_values],
            "source_determinism": "byte_deterministic",
            "fixed_environment_render": "not_verified",
            "publication_quality": "not_verified",
            "tex_invoked": False,
            "requires": "Caller-provided pgfplots with compat=1.18; CJK labels require a Unicode-capable engine and configured CJK fonts/packages (e.g. XeLaTeX with xeCJK/ctex); engine/package/font qualification not performed",
        }
        return source, metadata
