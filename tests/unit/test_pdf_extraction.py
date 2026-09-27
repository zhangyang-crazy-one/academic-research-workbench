from __future__ import annotations

import io
import sys
import types
import urllib.request
from pathlib import Path

import pytest

from arw.kernel.ledger.source_locations import SourceLocatorError
from arw.pdf_extraction import (
    PdfLocator,
    extract_docling,
    extract_docling_local,
    extract_grobid,
    extract_grobid_tei,
    extract_pdf_bytes,
    extract_pdf_from_root,
    pdf_human_review_item,
    verify_pdf_locator,
)


def _pdf(*, blank=False):
    pypdf = pytest.importorskip("pypdf")
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    if not blank:
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 50 250 Td (A verified paragraph with enough text for complete extraction.) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def test_image_only_pdf_routes_to_review():
    extraction, text = extract_pdf_bytes(_pdf(blank=True))
    assert extraction.quality_state == "needs_review"
    assert "no_extractable_text" in extraction.review_reasons
    assert text == b""
    assert pdf_human_review_item(extraction).requested_action == "inspect_pdf_or_supply_reviewed_ocr"


def test_default_pypdf_text_locator():
    extraction, text = extract_pdf_bytes(_pdf())
    assert extraction.quality_state == "complete"
    assert extraction.page_count == 1
    assert any(item.kind == "paragraph" for item in extraction.locators)
    assert not any(item.kind == "region" for item in extraction.locators)
    assert verify_pdf_locator(extraction, text, extraction.locators[0]).startswith(b"A verified")
    with pytest.raises(ValueError, match="structural coordinates"):
        PdfLocator.model_validate({**extraction.locators[0].model_dump(mode="json"),
                                   "kind": "region", "bbox": (0.0, 0.0, 20.0, 20.0)})


def test_malformed_and_unsafe_pdf_input(tmp_path):
    extraction, _ = extract_pdf_bytes(b"not a PDF")
    assert extraction.quality_state == "malformed"
    (tmp_path / "unsafe.pdf").symlink_to("/etc/hosts")
    with pytest.raises(SourceLocatorError):
        extract_pdf_from_root(tmp_path, "unsafe.pdf")
    with pytest.raises(SourceLocatorError):
        extract_pdf_from_root(tmp_path, "../unsafe.pdf")


def test_grobid_fixture_and_exact_offsets():
    raw = _pdf()
    tei = b'<TEI><text><body><p><pb n="1"/>A verified paragraph with enough text for the complete quality threshold.</p></body></text></TEI>'
    extraction, text = extract_grobid_tei(raw, tei, version="0.8.0")
    assert extraction.quality_state == "complete"
    assert extraction.locators[0].page == 1
    assert verify_pdf_locator(extraction, text, extraction.locators[0]) == text
    with pytest.raises(ValueError, match="digest"):
        verify_pdf_locator(extraction, b"altered", extraction.locators[0])


def test_grobid_structures_and_shared_reference_record():
    tei = b'''<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><pb n="1"/><head>Methods</head><p>A paragraph with enough text to preserve an exact first page locator.</p><table>Result table</table><figure>Figure caption</figure><listBibl><biblStruct xml:id="smith2024"><analytic><title>Evidence for Alpha</title><author><persName><surname>Smith</surname></persName></author></analytic><monogr><imprint><date when="2024"/></imprint></monogr><idno type="DOI">10.1234/alpha</idno></biblStruct></listBibl></body></text></TEI>'''
    extraction, text = extract_grobid_tei(_pdf(), tei, version="0.8.0")
    assert extraction.quality_state == "complete"
    assert {"section", "table", "figure", "reference"}.issubset({locator.kind for locator in extraction.locators})
    assert extraction.references[0].doi == "10.1234/alpha"
    assert any(locator.kind == "reference" and locator.label == extraction.references[0].reference_id for locator in extraction.locators)
    for locator in extraction.locators:
        assert verify_pdf_locator(extraction, text, locator)


def test_grobid_transport_uses_loopback_multipart_mock(monkeypatch):
    raw = _pdf()
    tei = b'<TEI><text><body><pb n="1"/><p>A verified paragraph with enough text to pass extraction quality.</p></body></text></TEI>'
    class Response:
        def __init__(self):
            self.headers = {"X-GROBID-Version": "0.8.0"}
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def geturl(self):
            return "http://127.0.0.1:8070/api/processFulltextDocument"
        def read(self, _limit):
            return tei
    class Opener:
        def open(self, request, timeout):
            assert timeout == 15
            assert request.data.find(raw) >= 0
            assert request.headers["Content-type"].startswith("multipart/form-data;")
            return Response()
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args: Opener())
    extraction, text = extract_grobid(raw, endpoint="http://127.0.0.1:8070/api/processFulltextDocument", allow_local_service=True)
    assert extraction.quality_state == "complete"
    assert text.startswith(b"A verified")


def test_optional_providers_require_explicit_local_assets():
    raw = _pdf()
    with pytest.raises(PermissionError):
        extract_grobid(raw, endpoint="http://127.0.0.1:8070/api/processFulltextDocument")
    with pytest.raises(ValueError, match="loopback"):
        extract_grobid(raw, endpoint="https://example.org/api", allow_local_service=True)
    with pytest.raises(RuntimeError, match="offline converter"):
        extract_docling(raw)
    with pytest.raises(ValueError, match="nonempty local model"):
        extract_docling_local(raw, artifacts_path=Path("/nonexistent/arw-docling-models"))
    class LocalConverter:
        offline_assets_verified = True
        def extract_pages(self, _raw):
            return ["A retained local paragraph with enough characters to pass quality."]
    extraction, text = extract_docling(raw, converter=LocalConverter(), version="2.0.0")
    assert extraction.quality_state == "complete"
    assert verify_pdf_locator(extraction, text, extraction.locators[1]).startswith(b"A retained")


def test_grobid_pins_localhost_and_rejects_redirected_response(monkeypatch):
    raw = _pdf()
    class Response:
        def __init__(self):
            self.headers = {"X-GROBID-Version": "0.8.0"}
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def geturl(self):
            return "http://example.org/api/processFulltextDocument"
    class Opener:
        def open(self, request, timeout):
            assert request.full_url == "http://127.0.0.1:8070/api/processFulltextDocument"
            return Response()
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args: Opener())
    with pytest.raises(ValueError, match="redirect"):
        extract_grobid(raw, endpoint="http://localhost:8070/api/processFulltextDocument", allow_local_service=True)


def test_docling_local_adapter_uses_offline_options(tmp_path, monkeypatch):
    artifacts = tmp_path / "models"
    artifacts.mkdir()
    (artifacts / "model.bin").write_bytes(b"fixture")
    captured = {}
    for name in ("docling", "docling.datamodel", "docling.datamodel.base_models",
                 "docling.datamodel.pipeline_options", "docling.document_converter"):
        module = types.ModuleType(name)
        if name in {"docling", "docling.datamodel"}:
            module.__path__ = []
        monkeypatch.setitem(sys.modules, name, module)
    base = sys.modules["docling.datamodel.base_models"]
    base.InputFormat = types.SimpleNamespace(PDF="pdf")
    base.DocumentStream = lambda **kwargs: kwargs
    options = sys.modules["docling.datamodel.pipeline_options"]
    options.PdfPipelineOptions = lambda **kwargs: captured.update(kwargs) or kwargs
    converter_module = sys.modules["docling.document_converter"]
    converter_module.ConversionStatus = types.SimpleNamespace(SUCCESS="success")
    converter_module.PdfFormatOption = lambda **kwargs: kwargs
    class Converter:
        def __init__(self, **kwargs):
            captured["converter"] = kwargs
        def convert(self, source, **kwargs):
            captured["limits"] = kwargs
            document = types.SimpleNamespace(pages={1: object()}, export_to_markdown=lambda page_no: "A complete local page with enough text for an exact locator.")
            return types.SimpleNamespace(document=document, status="success")
    converter_module.DocumentConverter = Converter
    monkeypatch.setattr("importlib.metadata.version", lambda name: "2.70.0")
    extraction, text = extract_docling_local(_pdf(), artifacts_path=artifacts)
    assert extraction.quality_state == "complete"
    assert extraction.extractor_version == "2.70.0"
    assert captured["enable_remote_services"] is False
    assert captured["allow_external_plugins"] is False
    assert captured["artifacts_path"] == artifacts
    assert captured["limits"]["max_num_pages"] == 500
    assert text.startswith(b"A complete local page")
