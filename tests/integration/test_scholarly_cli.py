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
                              "update-to": [{"type": "retraction"}]}]}}), encoding="utf-8")
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
