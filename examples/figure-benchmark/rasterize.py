"""Optional system-Python GI renderer. No dependency on the ARW runtime."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def render(source, output, width_mm, height_mm, dpi):
    import cairo
    import gi

    gi.require_version("Rsvg", "2.0")
    gi.require_version("Pango", "1.0")
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import Rsvg, Pango, PangoCairo

    raw = source.read_bytes()
    if len(raw) > 2_097_152 or b"<!" in raw or b"<?" in raw:
        raise ValueError("untrusted_svg")
    root = ET.fromstring(raw)
    if any(
        e.tag.rsplit("}", 1)[-1] in {"script", "image", "foreignObject", "use"}
        for e in root.iter()
    ):
        raise ValueError("unsupported_svg_element")
    for element in root.iter():
        for key, value in element.attrib.items():
            if (
                key.lower().startswith("on")
                or key.rsplit("}", 1)[-1] in {"href", "src", "style"}
                or ("url(" in value.lower() and not value.startswith("url(#"))
            ):
                raise ValueError("external_svg_reference")
    width, height = (math.ceil(n / 25.4 * dpi) for n in (width_mm, height_mm))
    if not (1 <= width <= 5000 and 1 <= height <= 5000):
        raise ValueError("raster_dimensions_out_of_bounds")
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    cr.set_source_rgb(1, 1, 1)
    cr.paint()
    handle = Rsvg.Handle.new_from_data(raw)

    def viewport(w, h):
        box = Rsvg.Rectangle()
        box.x, box.y, box.width, box.height = 0, 0, w, h
        return box

    handle.render_document(cr, viewport(width, height))
    surface.write_to_png(str(output))
    # Preserve vector PDF as an additional delivery format, without claiming
    # a particular editor's text round-trip behavior.
    pdf = output.with_suffix(".pdf")
    ps = cairo.PDFSurface(str(pdf), width_mm / 25.4 * 72, height_mm / 25.4 * 72)
    handle.render_document(
        cairo.Context(ps),
        viewport(width_mm / 25.4 * 72, height_mm / 25.4 * 72),
    )
    ps.finish()
    # Pango probes the same configured text family and records actual fallback
    # font runs. It is a coverage probe, not an independent visual judgment.
    texts = ["".join(e.itertext()) for e in root.iter() if e.tag.endswith("}text")]
    configured_family = subprocess.run(
        ["fc-match", "-f", "%{family}", "Noto Sans CJK SC"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    font_available = "Noto Sans CJK SC" in configured_family.split(",")
    layout = PangoCairo.create_layout(cr)
    layout.set_font_description(Pango.FontDescription("Noto Sans CJK SC 12"))
    layout.set_text("\n".join(texts), -1)
    unknown = layout.get_unknown_glyphs_count()
    iterator, fonts = layout.get_iter(), set()
    while True:
        run = iterator.get_run_readonly()
        if run is not None:
            fonts.add(
                (
                    run.item.analysis.font.describe().to_string(),
                    run.item.analysis.font.describe().get_family(),
                )
            )
        if not iterator.next_run():
            break
    records = []
    for font, family in sorted(fonts):
        match = subprocess.run(
            ["fc-match", "-f", "%{family}\n%{file}\n", family],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        path = Path(match[1])
        license_query = subprocess.run(
            ["rpm", "-qf", "--qf", "%{NAME} %{VERSION} | %{LICENSE}\n", str(path)],
            capture_output=True,
            text=True,
        )
        records.append(
            {
                "description": font,
                "family": match[0],
                "file": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "license_metadata": license_query.stdout.strip()
                if license_query.returncode == 0
                else "unavailable",
            }
        )
    surface.flush()
    data, stride = bytes(surface.get_data()), surface.get_stride()
    minx, miny, maxx, maxy, count = width, height, -1, -1, 0
    border = False
    # Cumulative ink bounds from actual rendered pixels; no source-only claim.
    for y in range(height):
        for x in range(width):
            if min(data[y * stride + x * 4 : y * stride + x * 4 + 3]) < 245:
                count += 1
                minx = min(minx, x)
                miny = min(miny, y)
                maxx = max(maxx, x)
                maxy = max(maxy, y)
                if x in {0, width - 1} or y in {0, height - 1}:
                    border = True
    # Actual grayscale pixels are retained for independent discrimination checks.
    gray_data = bytearray(data)
    for y in range(height):
        for x in range(width):
            i = y * stride + x * 4
            b, g, r = data[i : i + 3]
            luminance = round(0.2126 * r + 0.7152 * g + 0.0722 * b)
            gray_data[i : i + 3] = bytes((luminance,) * 3)
    gray_path = output.with_name(output.stem + "-gray.png")
    gray_surface = cairo.ImageSurface.create_for_data(
        gray_data, cairo.FORMAT_ARGB32, width, height, stride
    )
    gray_surface.write_to_png(str(gray_path))
    return {
        "status": "passed" if font_available else "unavailable",
        "requested_font_available": font_available,
        "grayscale_sha256": hashlib.sha256(gray_path.read_bytes()).hexdigest(),
        "rasterizer": {
            "name": "librsvg",
            "version": f"{Rsvg.MAJOR_VERSION}.{Rsvg.MINOR_VERSION}.{Rsvg.MICRO_VERSION}",
            "pango": Pango.version_string(),
            "cairo": cairo.cairo_version_string(),
            "python": sys.version.split()[0],
        },
        "fonts": records,
        "font_probe_unknown_glyphs": unknown,
        "width_px": width,
        "height_px": height,
        "width_mm": width_mm,
        "height_mm": height_mm,
        "dpi": dpi,
        "ink_pixels": count,
        "ink_bounds": [minx, miny, maxx, maxy],
        "border_ink": border,
        "png_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
        "limitations": [
            "Pango coverage probe does not prove readable pixel glyphs.",
            "Border screening does not certify absence of all clipping or occlusion.",
            "Color/grayscale perception requires human review.",
        ],
    }


if __name__ == "__main__":
    try:
        result = render(
            Path(sys.argv[1]),
            Path(sys.argv[2]),
            float(sys.argv[3]),
            float(sys.argv[4]),
            float(sys.argv[5]),
        )
    except (ImportError, ValueError, OSError, RuntimeError) as exc:
        result = {
            "status": "unavailable",
            "reason": str(exc),
            "type": type(exc).__name__,
        }
    print(json.dumps(result, ensure_ascii=False))
