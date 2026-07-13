from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def _ids():
    counters: dict[str, int] = {}

    def make(kind: str) -> str:
        counters[kind] = counters.get(kind, 0) + 1
        return f"{kind}_test_{counters[kind]:03d}"

    return make


def _service(control_root: Path):
    from arw.files import FilesAdminService

    return FilesAdminService(
        control_root,
        id_factory=_ids(),
        clock=lambda: "2026-07-14T00:00:00Z",
    )


def _manifest(service, root_id: str, generation_id: str) -> dict[str, object]:
    path = service.generation_path(root_id, generation_id) / "identity-manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _database_rows(service, root_id: str, generation_id: str) -> list[tuple[str, str, str | None]]:
    database = service.generation_path(root_id, generation_id) / "files.sqlite3"
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        return connection.execute(
            "SELECT relative_path, index_state, body FROM files ORDER BY relative_path"
        ).fetchall()
    finally:
        connection.close()


def test_generation_change_matrix_preserves_only_unambiguous_identity(tmp_path: Path) -> None:
    root = tmp_path / "root"
    for directory in ("same", "rename", "ambiguous", "delete", "ignore"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / "same/modified.txt").write_text("version one", encoding="utf-8")
    (root / "rename/old.txt").write_text("unique rename bytes", encoding="utf-8")
    (root / "ambiguous/old-a.txt").write_text("duplicate bytes", encoding="utf-8")
    (root / "ambiguous/old-b.txt").write_text("duplicate bytes", encoding="utf-8")
    (root / "delete/remove.txt").write_text("delete canary", encoding="utf-8")
    (root / "ignore/later.txt").write_text("ignore canary", encoding="utf-8")
    service = _service(tmp_path / "control")
    service.register_root(root_id="research-root", root_path=root, policy_id="research-files-v1")
    first = service.sync("research-root", extractor_version="1.0.0")
    initial = {
        item["relative_path"]: item["file_id"]
        for item in _manifest(service, "research-root", first.selected_generation_id)["records"]
    }

    (root / "same/modified.txt").write_text("version two", encoding="utf-8")
    (root / "rename/old.txt").rename(root / "rename/new.txt")
    # Copy then delete both duplicates so neither inode nor digest establishes a
    # unique old-to-new mapping.
    duplicate = (root / "ambiguous/old-a.txt").read_bytes()
    (root / "ambiguous/new-a.txt").write_bytes(duplicate)
    (root / "ambiguous/new-b.txt").write_bytes(duplicate)
    (root / "ambiguous/old-a.txt").unlink()
    (root / "ambiguous/old-b.txt").unlink()
    (root / "delete/remove.txt").unlink()
    (root / ".arwignore").write_text("ignore/\n", encoding="utf-8")
    second = service.sync("research-root", extractor_version="1.0.0")
    changed_manifest = _manifest(service, "research-root", second.selected_generation_id)
    changed = {item["relative_path"]: item for item in changed_manifest["records"]}

    assert changed["same/modified.txt"]["file_id"] == initial["same/modified.txt"]
    assert changed["rename/new.txt"]["file_id"] == initial["rename/old.txt"]
    assert changed["rename/new.txt"]["identity_evidence"] in {"os_identity", "unique_digest"}
    assert changed["ambiguous/new-a.txt"]["file_id"] not in {
        initial["ambiguous/old-a.txt"], initial["ambiguous/old-b.txt"]
    }
    assert changed["ambiguous/new-b.txt"]["file_id"] not in {
        initial["ambiguous/old-a.txt"], initial["ambiguous/old-b.txt"]
    }
    assert initial["delete/remove.txt"] in changed_manifest["deleted_file_ids"]
    assert initial["ignore/later.txt"] in changed_manifest["deleted_file_ids"]
    assert "delete/remove.txt" not in changed
    assert "ignore/later.txt" not in changed


def test_generation_removes_deleted_ignored_and_old_extraction_body(tmp_path: Path) -> None:
    from arw.file_models import ExtractionRegistration

    root = tmp_path / "root"
    (root / "pdf").mkdir(parents=True)
    (root / "plain").mkdir()
    source = root / "pdf/paper.pdf"
    source.write_bytes(b"%PDF-1.4\nsynthetic no parser\n%%EOF\n")
    stale = root / "plain/stale.txt"
    stale.write_text("ARW-TEST-STALE-BODY", encoding="utf-8")
    service = _service(tmp_path / "control")
    service.register_root(root_id="research-root", root_path=root, policy_id="research-files-v1")
    first = service.sync("research-root", extractor_version="1.0.0")
    first_manifest = _manifest(service, "research-root", first.selected_generation_id)
    pdf_id = next(item["file_id"] for item in first_manifest["records"] if item["relative_path"] == "pdf/paper.pdf")
    source_digest = next(item["digest"] for item in first_manifest["records"] if item["file_id"] == pdf_id)
    extraction_text = tmp_path / "paper.txt"
    extraction_text.write_text("registered paper evidence", encoding="utf-8")
    import hashlib

    registration = ExtractionRegistration.model_validate(
        {
            "schema_version": "1.0.0",
            "registration_id": "extraction_test_001",
            "source_file_id": pdf_id,
            "source_digest": source_digest,
            "extracted_text_digest": hashlib.sha256(extraction_text.read_bytes()).hexdigest(),
            "extractor_name": "fixture-extractor",
            "extractor_version": "1.0.0",
            "extracted_at": "2026-07-14T00:00:00Z",
            "quality_state": "complete",
            "access_state": "accessible",
        }
    )
    service.register_extraction("research-root", registration, extraction_text)
    second = service.sync("research-root", extractor_version="1.0.0")
    rows = _database_rows(service, "research-root", second.selected_generation_id)
    assert ("pdf/paper.pdf", "indexed", "registered paper evidence") in rows

    stale.unlink()
    third = service.sync("research-root", extractor_version="2.0.0")
    rows = _database_rows(service, "research-root", third.selected_generation_id)
    assert all("ARW-TEST-STALE-BODY" not in (body or "") for _, _, body in rows)
    pdf_row = next(row for row in rows if row[0] == "pdf/paper.pdf")
    assert pdf_row[1:] == ("degraded", None)

    rebuilt = service.rebuild("research-root", extractor_version="2.0.0")
    assert _database_rows(service, "research-root", rebuilt.selected_generation_id) == rows
