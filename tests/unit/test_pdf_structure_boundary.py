"""Behavior tests use Docling-shaped doubles, never real model evidence."""
import json
import types

import pytest

from arw.kernel.core.canonical import sha256_hex
from arw.pdf_extraction import PdfExtraction, extract_docling_local, verify_pdf_locator
from tests.unit.test_pdf_extraction import _pdf


def assets_manifest(path):
    path.mkdir(exist_ok=True)
    (path / "model.bin").write_bytes(b"fixture")
    manifest = {"schema_version": "arw.docling-assets.v1", "files": [
        {"path": "model.bin", "sha256": sha256_hex(b"fixture"), "size_bytes": 7}]}
    (path / "arw-docling-assets.json").write_text(json.dumps(manifest))


def document_fixture():
    ns = types.SimpleNamespace
    bbox = ns(l=10, t=90, r=80, b=50, coord_origin="BOTTOMLEFT")
    def item(label, text, index, page=1):
        return ns(label=label, text=text, self_ref=f"#/texts/{index}",
                  prov=[ns(page_no=page, bbox=bbox, charspan=(0, len(text)))])
    items = [item("section_header", "Methods 方法", 0),
             item("text", "A retained paragraph with sufficient text for complete quality.", 1),
             ns(label="table", self_ref="#/tables/0", prov=[ns(page_no=1, bbox=bbox)],
                data=ns(table_cells=[ns(text="Arm A"), ns(text="42")])),
             item("reference", "Smith (2024). A reference whose metadata is not parsed.", 2),
             item("text", "Repeated paragraph on the second page preserves UTF-8 offsets.", 3, page=2)]
    return ns(pages={1: ns(size=ns(width=100, height=100)), 2: ns(size=ns(width=100,height=100))},
              iterate_items=lambda: iter((item, 0) for item in items),
              export_to_markdown=lambda **kw: pytest.fail("Markdown must not establish structure"))


def install_docling(monkeypatch, document, *, on_convert=None):
    import sys
    for name in ("docling", "docling.datamodel", "docling.datamodel.base_models",
                 "docling.datamodel.pipeline_options", "docling.document_converter"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    base = sys.modules["docling.datamodel.base_models"]
    base.InputFormat = types.SimpleNamespace(PDF="pdf")
    base.DocumentStream = lambda **kw: kw
    options = sys.modules["docling.datamodel.pipeline_options"]
    options.PdfPipelineOptions = lambda **kw: types.SimpleNamespace(
        model_dump=lambda **unused: {**kw, "artifacts_path": str(kw["artifacts_path"]), "default_option": True})
    converter = sys.modules["docling.document_converter"]
    converter.ConversionStatus = types.SimpleNamespace(SUCCESS="success")
    converter.PdfFormatOption = lambda **kw: kw
    class Converter:
        def __init__(self, **kw):
            pass
        def convert(self, *args, **kw):
            if on_convert:
                on_convert()
            return types.SimpleNamespace(document=document, status="success")
    converter.DocumentConverter = Converter
    monkeypatch.setattr("importlib.metadata.version", lambda name: "2.60.0")


def test_docling_structures_are_source_backed(tmp_path, monkeypatch):
    assets_manifest(tmp_path)
    install_docling(monkeypatch, document_fixture())
    extraction, text = extract_docling_local(_pdf(), artifacts_path=tmp_path)
    assert extraction.quality_state == "complete"
    assert {"section", "table", "reference", "region"} <= {x.kind for x in extraction.locators}
    assert b"Arm A\t42" in text
    assert "方法" in text.decode()
    assert extraction.references == ()
    assert "reference_metadata" in extraction.unsupported_structures
    assert extraction.configuration_sha256
    assert extraction.model_manifest_sha256
    assert all(x.bbox == (0.1, 0.1, 0.8, 0.5) for x in extraction.locators if x.kind == "region")
    assert any(x.page == 2 for x in extraction.locators)
    for locator in extraction.locators:
        assert verify_pdf_locator(extraction, text, locator)


def test_docling_assets_must_be_verified_before_converter(tmp_path, monkeypatch):
    assets_manifest(tmp_path)
    install_docling(monkeypatch, document_fixture(), on_convert=lambda: pytest.fail("unverified assets used"))
    (tmp_path / "model.bin").write_bytes(b"changed")
    with pytest.raises(ValueError, match="asset"):
        extract_docling_local(_pdf(), artifacts_path=tmp_path)


def test_docling_model_change_changes_identity(tmp_path, monkeypatch):
    assets_manifest(tmp_path)
    install_docling(monkeypatch, document_fixture())
    first, _ = extract_docling_local(_pdf(), artifacts_path=tmp_path)
    (tmp_path / "model.bin").write_bytes(b"another")
    manifest = json.loads((tmp_path / "arw-docling-assets.json").read_text())
    manifest["files"][0]["sha256"] = sha256_hex(b"another")
    (tmp_path / "arw-docling-assets.json").write_text(json.dumps(manifest))
    second, _ = extract_docling_local(_pdf(), artifacts_path=tmp_path)
    assert first.model_manifest_sha256 != second.model_manifest_sha256
    assert first.extracted_text_sha256 == second.extracted_text_sha256


def test_old_pdf_receipt_still_decodes():
    from arw.pdf_extraction import extract_pdf_bytes
    extraction, _ = extract_pdf_bytes(_pdf())
    old = extraction.model_dump(mode="json")
    old["schema_version"] = "arw.pdf-extraction.v1"
    for key in ("configuration_sha256", "model_manifest_sha256", "unsupported_structures"):
        old.pop(key, None)
    loaded = PdfExtraction.model_validate_json(json.dumps(old))
    assert loaded.configuration_sha256 is None
    assert loaded.model_manifest_sha256 is None


def test_docling_configuration_defaults_change_identity(tmp_path, monkeypatch):
    import sys
    assets_manifest(tmp_path)
    install_docling(monkeypatch, document_fixture())
    first, _ = extract_docling_local(_pdf(), artifacts_path=tmp_path)
    options = sys.modules["docling.datamodel.pipeline_options"]
    original = options.PdfPipelineOptions
    def changed(**kw):
        option = original(**kw)
        dump = option.model_dump
        option.model_dump = lambda **opts: {**dump(**opts), "default_option": False}
        return option
    options.PdfPipelineOptions = changed
    second, _ = extract_docling_local(_pdf(), artifacts_path=tmp_path)
    assert first.configuration_sha256 != second.configuration_sha256
    assert first.extracted_text_sha256 == second.extracted_text_sha256


@pytest.mark.parametrize("fault", ["missing", "extra", "symlink", "parent", "mutated"])
def test_docling_assets_reject_unverified_inputs(tmp_path, monkeypatch, fault):
    assets_manifest(tmp_path)
    if fault == "missing":
        (tmp_path / "arw-docling-assets.json").unlink()
    elif fault == "extra":
        (tmp_path / "unlisted.bin").write_bytes(b"extra")
    elif fault == "symlink":
        (tmp_path / "model.bin").unlink()
        (tmp_path / "model.bin").symlink_to("/etc/hosts")
    elif fault == "parent":
        manifest = json.loads((tmp_path / "arw-docling-assets.json").read_text())
        manifest["files"][0]["path"] = "../model.bin"
        (tmp_path / "arw-docling-assets.json").write_text(json.dumps(manifest))
    install_docling(monkeypatch, document_fixture(), on_convert=(
        lambda: (tmp_path / "model.bin").write_bytes(b"changed")) if fault == "mutated" else None)
    with pytest.raises(ValueError):
        extract_docling_local(_pdf(), artifacts_path=tmp_path)


def test_docling_unknown_page_and_multipage_are_not_invented(tmp_path, monkeypatch):
    assets_manifest(tmp_path)
    document = document_fixture()
    items = list(document.iterate_items())
    items[1][0].prov.append(items[-1][0].prov[0])
    install_docling(monkeypatch, document)
    document.iterate_items = lambda: iter(items)
    extraction, text = extract_docling_local(_pdf(), artifacts_path=tmp_path)
    assert extraction.quality_state == "needs_review"
    assert "docling_item_page_mapping_unknown" in extraction.review_reasons
    assert b"A retained paragraph" not in text
    items[0][0].prov[0].page_no = 99
    with pytest.raises(ValueError, match="outside"):
        extract_docling_local(_pdf(), artifacts_path=tmp_path)


def test_isolated_pdf_worker_roundtrip_and_timeout():
    from arw.pdf_extraction import extract_pdf_isolated
    extraction, text = extract_pdf_isolated(_pdf())
    assert extraction.quality_state == "complete"
    assert verify_pdf_locator(extraction, text, extraction.locators[0]) == text
    with pytest.raises(RuntimeError, match="timeout"):
        extract_pdf_isolated(_pdf(), timeout_seconds=0.001)


def test_isolated_pdf_worker_is_a_limited_process(monkeypatch):
    import subprocess

    from arw.pdf_extraction import extract_pdf_isolated
    actual = subprocess.Popen
    children = []
    def launch(*args, **kwargs):
        child = actual(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(subprocess, "Popen", launch)
    extraction, _ = extract_pdf_isolated(_pdf())
    assert children and children[0].pid != __import__("os").getpid()
    assert children[0].returncode == 0
    assert extraction.configuration_sha256


def test_child_enforces_limits_and_offline_flags(tmp_path, monkeypatch):
    from arw.pdf_extraction import PDF_WORKER_LIMITS, extract_pdf_isolated
    marker = tmp_path / "child.json"
    # This module substitutes the parser inside the real child, not Popen or the worker.
    (tmp_path / "pypdf.py").write_text(f'''
import json, os, resource, socket
__version__ = "6.14.2"
class PdfReader:
    def __init__(self, *args, **kwargs):
        assert os.environ["HF_HUB_OFFLINE"] == "1"
        assert os.environ["TRANSFORMERS_OFFLINE"] == "1"
        assert "ARW_TEST_SECRET" not in os.environ
        denied = False
        try:
            socket.create_connection(("127.0.0.1", 9), timeout=0.1)
        except PermissionError:
            denied = True
        open({str(marker)!r}, "w").write(json.dumps({{
            "pid": os.getpid(), "network_denied": denied,
            "memory": resource.getrlimit(resource.RLIMIT_AS),
            "cpu": resource.getrlimit(resource.RLIMIT_CPU),
            "output": resource.getrlimit(resource.RLIMIT_FSIZE),
            "files": resource.getrlimit(resource.RLIMIT_NOFILE)}}))
        self.is_encrypted = False
        self.pages = [type("Page", (), {{"extract_text": lambda self: "A child parser page with enough text for complete extraction."}})()]
''')
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setenv("ARW_TEST_SECRET", "not-forwarded")
    extraction, _ = extract_pdf_isolated(b"%PDF-fixture")
    observed = json.loads(marker.read_text())
    assert observed["pid"] != __import__("os").getpid()
    assert observed["network_denied"] is True
    for key, field in (("memory", "address_space_bytes"), ("cpu", "cpu_seconds"),
                       ("output", "file_bytes"), ("files", "open_files")):
        assert observed[key] == [PDF_WORKER_LIMITS[field]] * 2
    assert extraction.quality_state == "complete"


def test_worker_timeout_kills_running_parser(tmp_path, monkeypatch):
    import os

    from arw.pdf_extraction import extract_pdf_isolated
    marker = tmp_path / "pid"
    (tmp_path / "pypdf.py").write_text(f'''
import os, time
__version__ = "6.14.2"
class PdfReader:
    def __init__(self, *a, **kw):
        open({str(marker)!r}, "w").write(str(os.getpid()))
        time.sleep(30)
''')
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    with pytest.raises(RuntimeError, match="pdf_worker_timeout"):
        extract_pdf_isolated(b"%PDF-fixture", timeout_seconds=1)
    assert marker.is_file()
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)


def test_worker_resource_and_output_failures_are_explicit(tmp_path, monkeypatch):
    from arw.pdf_extraction import extract_pdf_isolated
    (tmp_path / "pypdf.py").write_text('''
import os, sys
__version__ = "6.14.2"
class PdfReader:
    def __init__(self, *a, **kw):
        while True:
            os.write(sys.stdout.fileno(), b"x" * 65536)
''')
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    with pytest.raises(RuntimeError, match="pdf_worker_resource_limit_or_failure"):
        extract_pdf_isolated(b"%PDF-fixture")


def test_docling_charspan_is_not_expanded_to_whole_item(tmp_path, monkeypatch):
    assets_manifest(tmp_path)
    document = document_fixture()
    items = list(document.iterate_items())
    items[1][0].prov[0].charspan = (0, 4)
    document.iterate_items = lambda: iter(items)
    install_docling(monkeypatch, document)
    extraction, text = extract_docling_local(_pdf(), artifacts_path=tmp_path)
    assert extraction.quality_state == "needs_review"
    assert "docling_item_charspan_mapping_unknown" in extraction.review_reasons
    assert b"A retained paragraph" not in text


def test_worker_unsupported_platform_is_explicit(monkeypatch):
    import arw.pdf_extraction as pdf
    monkeypatch.setattr(pdf.os, "name", "unsupported")
    with pytest.raises(pdf.PdfWorkerError, match="pdf_resource_limits_unsupported"):
        pdf.extract_pdf_isolated(b"%PDF-fixture")


def test_complete_docling_v2_requires_model_identity(tmp_path, monkeypatch):
    assets_manifest(tmp_path)
    install_docling(monkeypatch, document_fixture())
    extraction, _ = extract_docling_local(_pdf(), artifacts_path=tmp_path)
    receipt = extraction.model_dump(mode="json")
    receipt["model_manifest_sha256"] = None
    with pytest.raises(ValueError, match="model identity"):
        PdfExtraction.model_validate_json(json.dumps(receipt))


def test_unavailable_grobid_retains_requested_configuration(monkeypatch):
    import urllib.request

    from arw.pdf_extraction import extract_grobid

    class Unavailable:
        def open(self, *a, **kw):
            raise OSError("fixture unavailable")
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a: Unavailable())
    first, _ = extract_grobid(b"%PDF-fixture", endpoint="http://127.0.0.1:8070/api/processFulltextDocument",
                             allow_local_service=True)
    second, _ = extract_grobid(b"%PDF-fixture", endpoint="http://127.0.0.1:8071/api/processFulltextDocument",
                              allow_local_service=True)
    assert "service_unavailable" in first.review_reasons
    assert first.configuration_sha256 != second.configuration_sha256
