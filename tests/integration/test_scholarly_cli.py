from __future__ import annotations

import json
from pathlib import Path

from arw.cli import main
from arw.files import FilesAdminService
from arw.kernel.policy.citations import ReferenceRecord, ReferenceUse
from tests.unit.test_pdf_extraction import _pdf


def test_fixture_citation_gate_and_pdf_registration(tmp_path, capsys):
    store = tmp_path / "store"
    store.mkdir()
    reference = ReferenceRecord(reference_id="ref.alpha", citation_key="Smith2024", title="Evidence for Alpha",
                                authors=("Smith",), year=2024, doi="10.1234/alpha")
    ref_file = tmp_path / "reference.json"
    ref_file.write_text(reference.model_dump_json(), encoding="utf-8")
    use = ReferenceUse(use_id="use.support", reference_id="ref.alpha", claim_id="claim.alpha", role="supporting")
    use_file = tmp_path / "use.json"
    use_file.write_text(use.model_dump_json(), encoding="utf-8")
    response = tmp_path / "crossref.json"
    response.write_text(json.dumps({"message": {"items": [{"DOI": "10.1234/alpha", "title": ["Evidence for Alpha"],
                              "published": {"date-parts": [[2024]]}, "author": [{"family": "Smith"}],
                              "updated-by": [{"type": "retraction", "source": "retraction-watch"}]}]}}), encoding="utf-8")
    assert main(["citation", "check", "--reference", str(ref_file), "--provider", "crossref",
                 "--store", str(store), "--response", str(response), "--observed-at", "2026-09-25T00:00:00Z"]) == 0
    check = json.loads(capsys.readouterr().out)
    assert check["receipt"]["status"] == "retracted"
    assert main(["citation", "gate", "--reference", str(ref_file), "--use", str(use_file),
                 "--store", str(store), "--provider", "crossref"]) == 0
    gate = json.loads(capsys.readouterr().out)
    assert gate["gate_proposal"]["verdict"] == "BLOCK"

    source = tmp_path / "source"
    source.mkdir()
    (source / "paper.pdf").write_bytes(_pdf())
    control = tmp_path / "control"
    FilesAdminService(control).register_root(root_id="root.paper", root_path=source, policy_id="policy.paper")
    assert main(["pdf", "--root", str(source), "--path", "paper.pdf", "--output-root", str(store),
                 "--control-root", str(control), "--root-id", "root.paper", "--file-id", "file.paper",
                 "--registration-id", "extraction.paper", "--extracted-at", "2026-09-25T00:00:00Z"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["extraction"]["quality_state"] == "complete"
    assert result["registration"]["source_file_id"] == "file.paper"
    assert (control / "roots/root.paper/extractions/extraction.paper/text.txt").read_bytes()


def test_image_only_pdf_creates_review_without_registration(tmp_path, capsys):
    source = tmp_path / "source"
    source.mkdir()
    (source / "scan.pdf").write_bytes(_pdf(blank=True))
    output = tmp_path / "output"
    output.mkdir()
    assert main(["pdf", "--root", str(source), "--path", "scan.pdf", "--output-root", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["extraction"]["quality_state"] == "needs_review"
    assert result["human_review"]["reasons"] == ["no_extractable_text"]
    assert "registration" not in result
    assert Path(result["human_review_path"]).is_file()


def test_pdf_manifest_identity_changes_without_text_collision(tmp_path, capsys, monkeypatch):
    from arw.kernel.core.canonical import sha256_hex
    from arw.pdf_extraction import extract_pdf_bytes
    source = tmp_path / "source"
    source.mkdir()
    raw = _pdf()
    (source / "paper.pdf").write_bytes(raw)
    output = tmp_path / "output"
    output.mkdir()
    extraction, text = extract_pdf_bytes(raw)
    args = ["pdf", "--root", str(source), "--path", "paper.pdf", "--output-root", str(output)]
    historical = output / "pdf" / extraction.source_sha256 / f"{extraction.extracted_text_sha256}.json"
    historical.parent.mkdir(parents=True)
    historical.write_bytes(b"historical-v1-manifest-kept-byte-for-byte")
    paths = []
    for index in range(3):
        updated = extraction.model_copy(update={
            "configuration_sha256": sha256_hex(str(min(index, 1)).encode()),
            "model_manifest_sha256": sha256_hex(str(max(index - 1, 0)).encode())})
        monkeypatch.setattr("arw.cli_scholarly.extract_pdf_isolated", lambda *a, updated=updated, **kw: (updated, text))
        assert main(args) == 0
        result = json.loads(capsys.readouterr().out)
        manifest = Path(result["manifest_path"])
        assert manifest.stem == sha256_hex(manifest.read_bytes())
        paths.append(manifest)
    assert len(set(paths)) == 3
    assert all(path.is_file() for path in paths)
    assert historical.read_bytes() == b"historical-v1-manifest-kept-byte-for-byte"
    assert main(args) == 0  # Same identity is idempotent.
    assert json.loads(capsys.readouterr().out)["manifest_path"] == str(paths[2])


def test_docling_shaped_sdk_in_real_cli_child(tmp_path, monkeypatch, capsys):
    """A fake SDK exercises the real child/CLI, never real Docling qualification."""
    from tests.unit.test_pdf_structure_boundary import assets_manifest

    package = tmp_path / "fake-sdk"
    files = {
        "docling/__init__.py": "",
        "docling/datamodel/__init__.py": "",
        "docling/datamodel/base_models.py": '''
from types import SimpleNamespace
InputFormat = SimpleNamespace(PDF="pdf")
def DocumentStream(**kw):
    return kw
''',
        "docling/datamodel/pipeline_options.py": '''
class PdfPipelineOptions:
    def __init__(self, **kw):
        self.kw = kw
    def model_dump(self, **kw):
        return {**self.kw, "artifacts_path": str(self.kw["artifacts_path"])}
''',
        "docling/document_converter.py": '''
from types import SimpleNamespace
from tests.unit.test_pdf_structure_boundary import document_fixture
ConversionStatus = SimpleNamespace(SUCCESS="success")
def PdfFormatOption(**kw):
    return kw
class DocumentConverter:
    def __init__(self, **kw):
        pass
    def convert(self, *args, **kw):
        return SimpleNamespace(document=document_fixture(), status="success")
''',
        "docling-2.60.0.dist-info/METADATA": "Metadata-Version: 2.1\nName: docling\nVersion: 2.60.0\n",
    }
    for name, data in files.items():
        path = package / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)
    models = tmp_path / "authorized-models"
    assets_manifest(models)
    source = tmp_path / "source"
    source.mkdir()
    (source / "paper.pdf").write_bytes(_pdf())
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setenv("PYTHONPATH", f"{package}:{Path(__file__).resolve().parents[2]}")
    assert main(["pdf", "--root", str(source), "--path", "paper.pdf", "--output-root", str(output),
                 "--provider", "docling", "--docling-artifacts-path", str(models)]) == 0
    result = json.loads(capsys.readouterr().out)
    receipt = result["extraction"]
    assert receipt["quality_state"] == "complete"
    assert receipt["extractor_version"] == "2.60.0"
    assert {"section", "region", "table", "reference"} <= {x["kind"] for x in receipt["locators"]}
    assert receipt["model_manifest_sha256"]
    published = Path(result["manifest_path"]).read_text()
    assert str(models) not in published
    assert "model.bin" not in published
