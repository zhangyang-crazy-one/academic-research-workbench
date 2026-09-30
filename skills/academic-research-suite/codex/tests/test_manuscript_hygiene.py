from __future__ import annotations

import builtins
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

CODEX_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = CODEX_ROOT / "scripts" / "check_manuscript_hygiene.py"
FIXTURES = CODEX_ROOT / "tests" / "fixtures" / "manuscript_hygiene"


def _load():
    spec = importlib.util.spec_from_file_location("check_manuscript_hygiene", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _checks(report: dict) -> list[tuple[str, str]]:
    return sorted((item["check"], item["severity"]) for item in report["findings"])


def _pdf_with_image(width_px: int, height_px: int, *, text: bool) -> bytes:
    """Hand-built single-page PDF drawing one gray image across the page."""
    pixels = bytes([128]) * (width_px * height_px)
    content = b"q 612 0 0 792 0 0 cm /Im0 Do Q"
    if text:
        content += b" BT /F1 12 Tf 72 72 Td (vector label) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /XObject << /Im0 5 0 R >> /Font << /F1 6 0 R >> >> "
            b"/Contents 4 0 R >>"
        ),
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
        b"/ColorSpace /DeviceGray /BitsPerComponent 8 /Length %d >>\nstream\n"
        % (width_px, height_px, len(pixels))
        + pixels
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def test_dirty_fixture_reports_every_real_use_defect() -> None:
    report = _load().audit_package(FIXTURES / "dirty")
    assert _checks(report) == [
        ("H1", "fail"),
        ("H2", "warn"),
        ("H2", "warn"),
        ("H3", "warn"),
        ("H4", "warn"),
        ("H5", "warn"),
        ("H6", "fail"),
    ]
    assert report["counts"] == {"fail": 2, "warn": 5, "not_checked": 0}


def test_clean_fixture_has_no_findings() -> None:
    report = _load().audit_package(FIXTURES / "clean")
    assert report["findings"] == []


def test_local_path_is_redacted_in_report() -> None:
    report = _load().audit_package(FIXTURES / "dirty")
    h1 = [item for item in report["findings"] if item["check"] == "H1"]
    assert h1 and "example-user" not in json.dumps(h1)
    assert "/home/<redacted>" in h1[0]["detail"]


def test_comments_bibliography_and_cite_optional_args_are_ignored(
    tmp_path: Path,
) -> None:
    (tmp_path / "paper.tex").write_text(
        "\\documentclass{IEEEtran}\\begin{document}\n"
        "See \\cite[Sec.~3, Fig.~1]{r1}. % Section 4.1 in a comment\n"
        "The interval is {[}0.094, 1.056{]}.\n"
        "\\begin{thebibliography}{9}\\bibitem{r1} X. [1] Table 2.\\end{thebibliography}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    assert _load().audit_package(tmp_path)["findings"] == []


def test_hard_coded_citation_requires_cite_usage(tmp_path: Path) -> None:
    (tmp_path / "notes.tex").write_text("Brackets [3] without any cite command.\n")
    assert _load().audit_package(tmp_path)["findings"] == []


def test_svg_raster_above_threshold_passes(tmp_path: Path) -> None:
    source = (FIXTURES / "dirty" / "figures" / "method.svg").read_text(encoding="utf-8")
    (tmp_path / "fig.svg").write_text(source, encoding="utf-8")
    module = _load()
    assert [
        f["check"] for f in module.audit_package(tmp_path, min_dpi=90)["findings"]
    ] == []
    assert [
        f["check"] for f in module.audit_package(tmp_path, min_dpi=300)["findings"]
    ] == ["H6"]


def test_pdf_full_page_raster_and_low_dpi(tmp_path: Path) -> None:
    pytest.importorskip("pypdf")
    (tmp_path / "figure.pdf").write_bytes(_pdf_with_image(100, 80, text=False))
    report = _load().audit_package(tmp_path)
    assert _checks(report) == [("H7", "fail"), ("H7", "warn")]


def test_pdf_with_vector_text_is_not_a_full_page_raster(tmp_path: Path) -> None:
    pytest.importorskip("pypdf")
    (tmp_path / "figure.pdf").write_bytes(_pdf_with_image(4000, 5200, text=True))
    assert _load().audit_package(tmp_path)["findings"] == []


def test_pdf_checks_report_not_checked_without_pypdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "figure.pdf").write_bytes(b"%PDF-1.4\n")
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pypdf" or name.startswith("pypdf."):
            raise ImportError("pypdf unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    report = _load().audit_package(tmp_path)
    assert _checks(report) == [("H7", "not_checked")]


def test_cli_strict_exit_codes(tmp_path: Path) -> None:
    dirty = subprocess.run(
        [sys.executable, str(SCRIPT), str(FIXTURES / "dirty"), "--strict", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert dirty.returncode == 1
    assert json.loads(dirty.stdout)["schema"] == "arw.manuscript-hygiene-report.v1"
    advisory = subprocess.run(
        [sys.executable, str(SCRIPT), str(FIXTURES / "dirty")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert advisory.returncode == 0
    clean_copy = tmp_path / "clean"
    shutil.copytree(FIXTURES / "clean", clean_copy)
    clean = subprocess.run(
        [sys.executable, str(SCRIPT), str(clean_copy), "--strict"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert clean.returncode == 0
    missing = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / "absent")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing.returncode == 2


def test_dpi_within_tolerance_of_threshold_passes(tmp_path: Path) -> None:
    source = (FIXTURES / "dirty" / "figures" / "method.svg").read_text(encoding="utf-8")
    (tmp_path / "fig.svg").write_text(source, encoding="utf-8")
    module = _load()
    # The fixture raster prints at exactly 100 dpi: a 100.9 threshold is within
    # the 1% tolerance and passes; a 102 threshold fails.
    assert module.audit_package(tmp_path, min_dpi=100.9)["findings"] == []
    assert [
        f["check"] for f in module.audit_package(tmp_path, min_dpi=102)["findings"]
    ] == ["H6"]


@pytest.mark.parametrize(
    "reference", [r"\ref{fig:included}", r"\cref{fig:included,tab:included}"]
)
def test_float_references_are_package_wide(tmp_path: Path, reference: str) -> None:
    (tmp_path / "main.tex").write_text(reference + r"\input{sections/results}")
    (tmp_path / "sections").mkdir()
    (tmp_path / "sections/results.tex").write_text(
        "\\begin{figure}\n\\label{fig:included}\n\\end{figure}\n"
        "\\begin{table}\\label{tab:unused}\\end{table}\n"
    )
    findings = _load().audit_package(tmp_path)["findings"]
    assert len(findings) == 1
    assert findings[0]["check"] == "H5"
    assert "tab:unused" in findings[0]["detail"]
    assert findings[0]["path"] == "sections/results.tex"
    assert findings[0]["line"] == 4


@pytest.mark.parametrize(
    "citation",
    [
        r"\cite{key}",
        r"\bibliography{refs}",
        r"\addbibresource{refs.bib}",
        r"\printbibliography",
        r"\begin{thebibliography}{9}\bibitem{key} Title [2].\end{thebibliography}",
    ],
)
def test_citation_state_is_package_wide(tmp_path: Path, citation: str) -> None:
    (tmp_path / "main.tex").write_text(citation)
    (tmp_path / "chapter.tex").write_text("Introduction.\nPrior work [3].\n")
    findings = _load().audit_package(tmp_path)["findings"]
    assert [(f["check"], f["path"], f["line"]) for f in findings] == [
        ("H3", "chapter.tex", 2)
    ]


def test_commented_package_state_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text(
        "% \\cite{key} \\bibliography{refs} \\ref{fig:unused}\n"
    )
    (tmp_path / "chapter.tex").write_text(
        "Prior work [3].\n\\begin{figure}\\label{fig:unused}\\end{figure}\n"
    )
    assert _checks(_load().audit_package(tmp_path)) == [("H5", "warn")]


def _png_header() -> bytes:
    import struct

    return b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR" + struct.pack(">II", 100, 100)


def _svg_with_href(path: Path, href: str) -> None:
    from xml.sax.saxutils import quoteattr

    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1in" viewBox="0 0 100 100">'
        f'<image width="100" height="100" href={quoteattr(href)}/></svg>'
    )


def test_svg_relative_raster_inside_package_is_checked(tmp_path: Path) -> None:
    (tmp_path / "figures").mkdir()
    (tmp_path / "raster.png").write_bytes(_png_header())
    _svg_with_href(tmp_path / "figures/fig.svg", "../raster.png")
    assert _checks(_load().audit_package(tmp_path)) == [("H6", "fail")]


@pytest.mark.parametrize(
    "source",
    ["traversal", "absolute", "file_symlink", "directory_symlink", "internal_symlink"],
)
def test_svg_does_not_read_unsafe_raster_sources(
    tmp_path: Path, monkeypatch, source: str
) -> None:
    module = _load()
    package = tmp_path / "package"
    package.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    raster = outside / "raster.png"
    raster.write_bytes(_png_header())
    if source == "traversal":
        href = "../outside/raster.png"
    elif source == "absolute":
        href = str(raster)
    elif source == "file_symlink":
        (package / "link.png").symlink_to(raster)
        href = "link.png"
    elif source == "directory_symlink":
        (package / "link").symlink_to(outside, target_is_directory=True)
        href = "link/raster.png"
    else:
        (package / "raster.png").write_bytes(_png_header())
        (package / "link.png").symlink_to(package / "raster.png")
        href = "link.png"
    _svg_with_href(package / "fig.svg", href)

    # Any successfully read raster would reach this function.
    def unexpected_raster_read(data):
        pytest.fail("unsafe raster data was read")

    monkeypatch.setattr(module, "_raster_size", unexpected_raster_read)
    assert _checks(module.audit_package(package)) == [("H6", "not_checked")]


def test_svg_oversized_raster_is_not_read(tmp_path: Path, monkeypatch) -> None:
    module = _load()
    monkeypatch.setattr(module, "MAX_RASTER_BYTES", 24)
    (tmp_path / "raster.png").write_bytes(_png_header() + b"x")
    _svg_with_href(tmp_path / "fig.svg", "raster.png")
    assert _checks(module.audit_package(tmp_path)) == [("H6", "not_checked")]


@pytest.mark.parametrize("payload", ["A" * 40, "!invalid!", "%89PNG"])
def test_svg_data_uri_rejects_oversized_or_malformed_payload(
    tmp_path: Path, monkeypatch, payload: str
) -> None:
    module = _load()
    monkeypatch.setattr(module, "MAX_RASTER_BYTES", 24)
    _svg_with_href(tmp_path / "fig.svg", "data:image/png;base64," + payload)
    assert _checks(module.audit_package(tmp_path)) == [("H6", "not_checked")]


def test_svg_non_base64_data_uri_is_not_checked(tmp_path: Path) -> None:
    _svg_with_href(tmp_path / "fig.svg", "data:image/png,not-base64")
    assert _checks(_load().audit_package(tmp_path)) == [("H6", "not_checked")]


def test_svg_document_read_is_bounded(tmp_path: Path, monkeypatch) -> None:
    module = _load()
    monkeypatch.setattr(module, "MAX_TEXT_BYTES", 24)
    _svg_with_href(tmp_path / "fig.svg", "raster.png")
    assert _checks(module.audit_package(tmp_path)) == [("H6", "not_checked")]


def test_svg_data_uri_size_boundary(tmp_path: Path, monkeypatch) -> None:
    import base64

    module = _load()
    monkeypatch.setattr(module, "MAX_RASTER_BYTES", 24)
    _svg_with_href(
        tmp_path / "fig.svg",
        "data:image/png;base64," + base64.b64encode(_png_header()).decode(),
    )
    assert _checks(module.audit_package(tmp_path)) == [("H6", "fail")]
    # 25 bytes and 27 bytes have the same encoded length. Check decoded size too.
    monkeypatch.setattr(module, "MAX_RASTER_BYTES", 25)
    _svg_with_href(
        tmp_path / "fig.svg",
        "data:image/png;base64," + base64.b64encode(_png_header() + b"xx").decode(),
    )
    assert _checks(module.audit_package(tmp_path)) == [("H6", "not_checked")]


def test_oversized_data_uri_is_rejected_before_decoding(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load()
    monkeypatch.setattr(module, "MAX_RASTER_BYTES", 24)

    def unexpected_decode(*args, **kwargs):
        pytest.fail("oversized data URI was decoded")

    monkeypatch.setattr(module.base64, "b64decode", unexpected_decode)
    assert (
        module._svg_raster_data(
            tmp_path, tmp_path / "fig.svg", "data:image/png;base64," + "A" * 40
        )
        is None
    )


def test_svg_nonregular_raster_is_not_checked(tmp_path: Path) -> None:
    import os

    os.mkfifo(tmp_path / "raster.png")
    _svg_with_href(tmp_path / "fig.svg", "raster.png")
    assert _checks(_load().audit_package(tmp_path)) == [("H6", "not_checked")]


def test_package_reader_uses_bounded_read_even_if_file_grows(
    tmp_path: Path, monkeypatch
) -> None:
    import io

    module = _load()
    raster = tmp_path / "raster.png"
    raster.write_bytes(_png_header())
    original_fdopen = module.os.fdopen

    class GrowingFile(io.BytesIO):
        def read(self, size=-1):
            assert size == 25
            return super().read(size)

    def growing_fdopen(fd, mode):
        original_fdopen(fd, mode).close()
        return GrowingFile(_png_header() + b"extra data after stat")

    monkeypatch.setattr(module.os, "fdopen", growing_fdopen)
    assert module._read_package_bytes(tmp_path, raster, 24) is None
