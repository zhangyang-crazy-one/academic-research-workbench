#!/usr/bin/env python3
"""Deterministic manuscript-package hygiene audit (real-use review findings).

Scans a manuscript package directory for mechanical defects that a
narrative review can miss but that reviewers, editors, or anonymity checks
catch immediately:

  H1  absolute local paths (``/home/<user>/``, ``/Users/<user>/``,
      ``C:\\Users\\``, ``file://``) in text-bearing files — a privacy and
      anonymity leak;
  H2  relative references (Markdown links, JSON path strings or keys) that
      do not resolve inside the package — workspace paths that readers
      cannot follow;
  H3  hard-coded numeric citations in LaTeX sources that otherwise use
      ``\\cite`` — they silently drift when the bibliography is reordered;
  H4  hard-coded cross-reference numbers in LaTeX (``Section 4.1``,
      ``Table 3``) instead of ``\\ref`` — typically Markdown numbering that
      disagrees with the class's own numbering (IEEEtran uses IV-A);
  H5  figure/table labels never referenced in the text;
  H6  embedded raster images in SVG figures whose effective print
      resolution is below ``--min-dpi``;
  H7  PDF figures that are a single full-page raster image (no vector
      text), and embedded PDF images below ``--min-dpi`` (requires pypdf;
      reported ``not_checked`` when it is unavailable).

Contract boundaries:

  - **Advisory by default.** Every finding is reported with a severity
    (``fail`` / ``warn`` / ``not_checked``); the default exit code is 0.
    ``--strict`` exits 1 when any ``fail`` finding is present.
  - **Detection only.** The checker never edits, moves, or redacts files.
    Local-path findings redact the user-name segment in their own output so
    the report does not re-leak what it detects.
  - **Heuristic classes are labelled.** H2–H5 are pattern heuristics and can
    false-positive on legitimate prose; H6/H7 ignore SVG transforms and
    report the resolution implied by the declared display size.
  - A clean report is not a camera-ready verdict. It says only that these
    specific mechanical patterns were not found.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

TEXT_SUFFIXES = {
    ".md",
    ".tex",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".bib",
    ".csv",
    ".py",
    ".html",
    ".svg",
}
SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".pytest_cache"}
DEFAULT_MIN_DPI = 300.0
# Placement sizes are stored rounded; allow 1% below the threshold before failing
# so an image built for exactly 300 dpi does not report "~300 dpi (< 300)".
DPI_TOLERANCE = 0.01
MAX_TEXT_BYTES = 8 * 1024 * 1024

LOCAL_PATH_RE = re.compile(
    r"(?P<prefix>/home/|/Users/|[A-Za-z]:\\\\?Users\\\\?)(?P<user>[^/\\\s\"'`<>|]+)"
    r"|(?P<fileurl>file://)"
)
MD_LINK_RE = re.compile(r"(?<!!)\[[^\]\n]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
PATHLIKE_RE = re.compile(r"^(?:\.{1,2}/)?[\w.\-]+(?:/[\w.\-]+)+\.[A-Za-z0-9]{1,6}$")
LATEX_COMMENT_RE = re.compile(r"(?<!\\)%.*")
HARD_CITE_RE = re.compile(
    r"\{\[\}\s*\d+(?:\s*[,\u2013-]\s*\d+)*\s*\{\]\}"
    r"|(?<![\\\w\]])\[\s*\d+(?:\s*[,\u2013-]\s*\d+)*\s*\](?![\w{])"
)
HARD_XREF_RE = re.compile(
    r"\b(?P<kind>Section|Sections|Sec\.|Table|Tables|Tab\.|Figure|Figures|Fig\.)"
    r"(?:~|\s)+(?P<num>\d+(?:\.\d+)*)\b"
)
CITE_OPT_RE = re.compile(r"\\cite[a-zA-Z]*\*?(?:\[[^\]]*\]){1,2}\{")
LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
REF_RE = re.compile(
    r"\\(?:ref|cref|Cref|autoref|pageref|eqref|nameref|vref)\*?\{([^}]+)\}"
)
FLOAT_ENV_RE = re.compile(r"\\begin\{(figure|table)\*?\}(.*?)\\end\{\1\*?\}", re.DOTALL)
LENGTH_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([a-z%]*)\s*$")
UNIT_TO_INCH = {
    "": 1 / 96,
    "px": 1 / 96,
    "pt": 1 / 72,
    "pc": 1 / 6,
    "mm": 1 / 25.4,
    "cm": 1 / 2.54,
    "in": 1.0,
}
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"


def _finding(
    check: str,
    severity: str,
    path: str,
    detail: str,
    *,
    line: int | None = None,
    signal_class: str = "deterministic",
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "check": check,
        "severity": severity,
        "path": path,
        "detail": detail,
        "signal_class": signal_class,
    }
    if line is not None:
        item["line"] = line
    return item


def _iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_file() and not path.is_symlink():
            files.append(path)
    return files


def _read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_TEXT_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def check_local_paths(root: Path, texts: dict[Path, str]) -> list[dict[str, Any]]:
    findings = []
    for path, text in texts.items():
        rel = path.relative_to(root).as_posix()
        for match in LOCAL_PATH_RE.finditer(text):
            if match.group("fileurl"):
                shown = "file://"
            else:
                shown = f"{match.group('prefix')}<redacted>"
            findings.append(
                _finding(
                    "H1",
                    "fail",
                    rel,
                    f"absolute local path {shown!s} exposes the author workspace",
                    line=_line_of(text, match.start()),
                )
            )
    return findings


def _resolves(root: Path, base: Path, target: str) -> bool:
    target = target.split("#", 1)[0].split("?", 1)[0]
    if not target:
        return True
    candidates = [(base / target), (root / target)]
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.exists() and (
            resolved == root.resolve() or root.resolve() in resolved.parents
        ):
            return True
    return False


def _json_strings(node: Any) -> list[str]:
    out: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            out.append(str(key))
            out.extend(_json_strings(value))
    elif isinstance(node, list):
        for value in node:
            out.extend(_json_strings(value))
    elif isinstance(node, str):
        out.append(node)
    return out


def check_dangling_references(
    root: Path, texts: dict[Path, str]
) -> list[dict[str, Any]]:
    findings = []
    for path, text in texts.items():
        rel = path.relative_to(root).as_posix()
        if path.suffix == ".md":
            for match in MD_LINK_RE.finditer(text):
                target = match.group(1)
                if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith(
                    "#"
                ):
                    continue
                if not _resolves(root, path.parent, target):
                    findings.append(
                        _finding(
                            "H2",
                            "warn",
                            rel,
                            f"relative link does not resolve inside the package: {target}",
                            line=_line_of(text, match.start()),
                            signal_class="heuristic",
                        )
                    )
        elif path.suffix == ".json":
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            seen: set[str] = set()
            for value in _json_strings(payload):
                if value in seen or not PATHLIKE_RE.match(value):
                    continue
                seen.add(value)
                if not _resolves(root, path.parent, value):
                    findings.append(
                        _finding(
                            "H2",
                            "warn",
                            rel,
                            f"path string does not resolve inside the package: {value}",
                            signal_class="heuristic",
                        )
                    )
    return findings


def _latex_body(text: str) -> str:
    lines = [LATEX_COMMENT_RE.sub("", line) for line in text.splitlines()]
    body = "\n".join(lines)
    return re.sub(
        r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}",
        lambda m: "\n" * m.group(0).count("\n"),
        body,
        flags=re.DOTALL,
    )


def check_latex(root: Path, texts: dict[Path, str]) -> list[dict[str, Any]]:
    findings = []
    for path, text in texts.items():
        if path.suffix != ".tex":
            continue
        rel = path.relative_to(root).as_posix()
        body = _latex_body(text)
        uses_cite = bool(re.search(r"\\cite[a-zA-Z]*\*?[\[{]|\\bibitem", text))
        masked = CITE_OPT_RE.sub(lambda m: " " * len(m.group(0)), body)
        if uses_cite:
            for match in HARD_CITE_RE.finditer(masked):
                findings.append(
                    _finding(
                        "H3",
                        "warn",
                        rel,
                        f"hard-coded citation number {match.group(0)!r}; use \\cite so "
                        "numbering follows the bibliography",
                        line=_line_of(body, match.start()),
                        signal_class="heuristic",
                    )
                )
        for match in HARD_XREF_RE.finditer(masked):
            findings.append(
                _finding(
                    "H4",
                    "warn",
                    rel,
                    f"hard-coded cross-reference {match.group(0)!r}; use \\ref so the "
                    "number follows the document class",
                    line=_line_of(body, match.start()),
                    signal_class="heuristic",
                )
            )
        referenced = {
            key.strip() for group in REF_RE.findall(body) for key in group.split(",")
        }
        for env in FLOAT_ENV_RE.finditer(body):
            for label in LABEL_RE.findall(env.group(2)):
                if label not in referenced:
                    findings.append(
                        _finding(
                            "H5",
                            "warn",
                            rel,
                            f"{env.group(1)} label {label!r} is never referenced in the text",
                            line=_line_of(body, env.start()),
                            signal_class="heuristic",
                        )
                    )
    return findings


def _raster_size(data: bytes) -> tuple[int, int] | None:
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24 and data[12:16] == b"IHDR":
        width, height = struct.unpack(">II", data[16:24])
        return int(width), int(height)
    if data[:2] == b"\xff\xd8":
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                index += 2
                continue
            (seg_len,) = struct.unpack(">H", data[index + 2 : index + 4])
            if marker in (
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            ):
                height, width = struct.unpack(">HH", data[index + 5 : index + 9])
                return int(width), int(height)
            index += 2 + seg_len
    return None


def _length_in_inches(raw: str | None) -> float | None:
    if raw is None:
        return None
    match = LENGTH_RE.match(raw)
    if not match or match.group(2) not in UNIT_TO_INCH:
        return None
    return float(match.group(1)) * UNIT_TO_INCH[match.group(2)]


def _svg_user_unit_inches(svg: ET.Element) -> float:
    width_in = _length_in_inches(svg.get("width"))
    view_box = (svg.get("viewBox") or "").replace(",", " ").split()
    if width_in and len(view_box) == 4:
        try:
            vb_width = float(view_box[2])
        except ValueError:
            vb_width = 0.0
        if vb_width > 0:
            return width_in / vb_width
    return UNIT_TO_INCH["px"]


def check_svg_rasters(root: Path, min_dpi: float) -> list[dict[str, Any]]:
    findings = []
    for path in _iter_files(root):
        if path.suffix.lower() != ".svg":
            continue
        rel = path.relative_to(root).as_posix()
        try:
            svg = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            continue
        unit_in = _svg_user_unit_inches(svg)
        for image in svg.iter("{http://www.w3.org/2000/svg}image"):
            href = image.get(XLINK_HREF) or image.get("href") or ""
            data: bytes | None = None
            if href.startswith("data:image/"):
                try:
                    data = base64.b64decode(re.sub(r"\s", "", href.split(",", 1)[1]))
                except (IndexError, ValueError):
                    data = None
            elif href and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", href):
                target = path.parent / href
                if target.is_file():
                    data = target.read_bytes()
            size = _raster_size(data) if data else None
            try:
                shown_width = float(image.get("width", "0"))
            except ValueError:
                shown_width = 0.0
            if not size or shown_width <= 0:
                continue
            inches = shown_width * unit_in
            dpi = size[0] / inches if inches else 0.0
            if dpi < min_dpi * (1 - DPI_TOLERANCE):
                findings.append(
                    _finding(
                        "H6",
                        "fail",
                        rel,
                        f"embedded raster {size[0]}x{size[1]} px displayed at "
                        f"{inches * 25.4:.1f} mm prints at ~{dpi:.1f} dpi "
                        f"(< {min_dpi:.0f}); supply a higher-resolution or vector source",
                    )
                )
    return findings


def _matrix_mul(a: list[float], b: list[float]) -> list[float]:
    return [
        a[0] * b[0] + a[1] * b[2],
        a[0] * b[1] + a[1] * b[3],
        a[2] * b[0] + a[3] * b[2],
        a[2] * b[1] + a[3] * b[3],
        a[4] * b[0] + a[5] * b[2] + b[4],
        a[4] * b[1] + a[5] * b[3] + b[5],
    ]


def _pdf_placements(pypdf: Any, page: Any) -> list[tuple[int, int, float, float]]:
    """Return (px_w, px_h, placed_w_pt, placed_h_pt) for every image draw."""
    from pypdf.generic import ContentStream  # type: ignore[import-not-found]

    placements: list[tuple[int, int, float, float]] = []

    def walk(contents: Any, resources: Any, ctm: list[float], depth: int) -> None:
        if depth > 8 or contents is None:
            return
        stack: list[list[float]] = []
        current = list(ctm)
        xobjects = resources.get("/XObject") if resources else None
        xobjects = xobjects.get_object() if xobjects is not None else {}
        for operands, operator in ContentStream(contents, page.pdf).operations:
            if operator == b"q":
                stack.append(list(current))
            elif operator == b"Q" and stack:
                current = stack.pop()
            elif operator == b"cm" and len(operands) == 6:
                current = _matrix_mul([float(x) for x in operands], current)
            elif operator == b"Do" and operands:
                name = operands[0]
                if name not in xobjects:
                    continue
                xobj = xobjects[name].get_object()
                subtype = xobj.get("/Subtype")
                if subtype == "/Image":
                    width_pt = (current[0] ** 2 + current[1] ** 2) ** 0.5
                    height_pt = (current[2] ** 2 + current[3] ** 2) ** 0.5
                    placements.append(
                        (
                            int(xobj.get("/Width", 0)),
                            int(xobj.get("/Height", 0)),
                            width_pt,
                            height_pt,
                        )
                    )
                elif subtype == "/Form":
                    matrix = [float(x) for x in xobj.get("/Matrix", [1, 0, 0, 1, 0, 0])]
                    walk(
                        xobj,
                        xobj.get("/Resources"),
                        _matrix_mul(matrix, current),
                        depth + 1,
                    )

    walk(page.get_contents(), page.get("/Resources"), [1, 0, 0, 1, 0, 0], 0)
    return placements


def check_pdf_rasters(root: Path, min_dpi: float) -> list[dict[str, Any]]:
    pdfs = [p for p in _iter_files(root) if p.suffix.lower() == ".pdf"]
    if not pdfs:
        return []
    try:
        import pypdf  # type: ignore[import-not-found]
    except ImportError:
        return [
            _finding(
                "H7",
                "not_checked",
                ".",
                f"{len(pdfs)} PDF file(s) present but pypdf is unavailable; "
                "raster-resolution and full-page-raster checks were not run",
            )
        ]
    findings = []
    for path in pdfs:
        rel = path.relative_to(root).as_posix()
        try:
            reader = pypdf.PdfReader(str(path))
            pages = list(reader.pages)
        except Exception as exc:  # noqa: BLE001 - report unreadable PDFs honestly
            findings.append(
                _finding(
                    "H7",
                    "not_checked",
                    rel,
                    f"PDF could not be parsed: {type(exc).__name__}",
                )
            )
            continue
        for number, page in enumerate(pages, start=1):
            try:
                placements = _pdf_placements(pypdf, page)
                text = (page.extract_text() or "").strip()
            except Exception as exc:  # noqa: BLE001
                findings.append(
                    _finding(
                        "H7",
                        "not_checked",
                        rel,
                        f"page {number} content could not be analysed: {type(exc).__name__}",
                    )
                )
                continue
            box = page.mediabox
            page_area = float(box.width) * float(box.height)
            for px_w, px_h, w_pt, h_pt in placements:
                if w_pt <= 0 or px_w <= 0:
                    continue
                dpi = px_w / (w_pt / 72)
                covers_page = page_area > 0 and (w_pt * h_pt) / page_area >= 0.9
                if covers_page and not text and len(placements) == 1:
                    findings.append(
                        _finding(
                            "H7",
                            "warn",
                            rel,
                            f"page {number} is a single full-page raster image "
                            f"({px_w}x{px_h} px, ~{dpi:.0f} dpi) with no vector text; "
                            "labels cannot be searched or edited — export the vector source",
                        )
                    )
                if dpi < min_dpi * (1 - DPI_TOLERANCE):
                    findings.append(
                        _finding(
                            "H7",
                            "fail",
                            rel,
                            f"page {number}: embedded image {px_w}x{px_h} px placed at "
                            f"{w_pt / 72 * 25.4:.1f} mm prints at ~{dpi:.1f} dpi (< {min_dpi:.0f})",
                        )
                    )
    return findings


def audit_package(root: Path, *, min_dpi: float = DEFAULT_MIN_DPI) -> dict[str, Any]:
    root = root.resolve()
    texts: dict[Path, str] = {}
    for path in _iter_files(root):
        if path.suffix.lower() in TEXT_SUFFIXES:
            text = _read_text(path)
            if text is not None:
                texts[path] = text
    findings: list[dict[str, Any]] = []
    findings += check_local_paths(root, texts)
    findings += check_dangling_references(root, texts)
    findings += check_latex(root, texts)
    findings += check_svg_rasters(root, min_dpi)
    findings += check_pdf_rasters(root, min_dpi)
    counts = {level: 0 for level in ("fail", "warn", "not_checked")}
    for item in findings:
        counts[item["severity"]] += 1
    return {
        "schema": "arw.manuscript-hygiene-report.v1",
        "min_dpi": min_dpi,
        "text_files_scanned": len(texts),
        "counts": counts,
        "findings": findings,
        "limitations": [
            "Pattern checks H2-H5 are heuristics and can flag legitimate prose.",
            "Raster resolution ignores SVG transforms and uses declared display size.",
            "A clean report is not a camera-ready or anonymity verdict.",
        ],
    }


def _render(report: dict[str, Any]) -> str:
    counts = report["counts"]
    lines = [
        (
            f"manuscript hygiene: {counts['fail']} fail, {counts['warn']} warn, "
            f"{counts['not_checked']} not_checked "
            f"({report['text_files_scanned']} text files scanned)"
        )
    ]
    for item in report["findings"]:
        where = item["path"] + (f":{item['line']}" if "line" in item else "")
        lines.append(
            f"  [{item['severity']}] {item['check']} {where} — {item['detail']}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").strip().splitlines()[0]
    )
    parser.add_argument("package", type=Path, help="manuscript package directory")
    parser.add_argument("--min-dpi", type=float, default=DEFAULT_MIN_DPI)
    parser.add_argument("--json", action="store_true", help="emit the JSON report")
    parser.add_argument(
        "--strict", action="store_true", help="exit 1 when any fail finding is present"
    )
    args = parser.parse_args(argv)
    if not args.package.is_dir():
        print(f"not a directory: {args.package}", file=sys.stderr)
        return 2
    report = audit_package(args.package, min_dpi=args.min_dpi)
    print(
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.json
        else _render(report)
    )
    return 1 if (args.strict and report["counts"]["fail"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
