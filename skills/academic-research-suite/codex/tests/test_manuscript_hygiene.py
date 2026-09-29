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
