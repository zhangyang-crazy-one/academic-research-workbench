# Issue #39 / F05 PDF structure and parser boundary

Status: **已验证** for local behavior below; **未验证** for real offline Docling/GROBID and the original multilingual/two-column/scanned-paper acceptance matrix.

Authority: the saved issue #39 body in `build/verification/upstream-audit-20261023/issues.json` has zero comments. F05 in `closed-coverage.md` identified the Markdown-only local Docling path, absent configuration/model identity and same-process CLI. The existing `scholarly-pdf-extraction-locators` non-goals exclude OCR and runtime downloads. This correction does not claim closure of the original real-provider acceptance matrix.

## Implemented contract

- The CLI invokes pypdf, Docling or explicit loopback GROBID in an independent bounded parser process. Hard limits are 4 GiB address space, 30 CPU seconds, 32 MiB per output file, 64 descriptors and no core dump; wall timeout is 45 seconds. Timeout kills the process group. Missing providers, unsupported resource limits, malformed responses and resource failure expose typed `pdf_*` error codes. No fallback occurs.
- PDF bytes remain bounded at 8 MiB, extracted text at 8 MiB, pages at 500, structural items at 20,000 and table cells per item at 20,000. The worker receives PDF bytes rather than arbitrary source filesystem paths.
- Docling sections, table text, reference text, pages and bboxes come from source document items/provenance. Regions use normalized top-left coordinates, including bottom-left-origin conversion. No Markdown inference is used. Unknown pages, multi-provenance items and partial charspan mappings never become invented evidence.
- Docling reference TextItems provide reference text but no complete structured author/year/title record. `reference_metadata` is explicitly unsupported, and `references` stays empty. These raw reference locators do not qualify for canonical `reference_entry` admission, which still requires a shared ReferenceRecord. Table-cell-specific locators are also unsupported; the table text locator remains available. The existing canonical locator vocabulary is unchanged.
- New v2 receipts bind the effective configuration and verified model manifest by digest. Old v1 receipts remain readable with unknown identities. CLI manifests and review files use the extraction-manifest digest; text retains its text digest filename. Existing files are neither renamed nor overwritten.

## Offline assets

`--provider docling --docling-artifacts-path <authorized-model-root>` requires a supplied `arw-docling-assets.json` in that root:

```json
{"schema_version":"arw.docling-assets.v1","files":[{"path":"relative/model-file","sha256":"<actual-64-hex-digest>","size_bytes":123}]}
```

The inventory must list every file except itself, with no duplicates, traversal, symlinks or special files; maximum 512 files and 8 GiB total. It is verified before converter initialization and again after conversion. Supply it only from already authorized, verified offline assets. ARW does not download models or generate a model license/qualification assertion. The inventory binds bytes and does not independently establish their origin or license. SDK layout/model requirements may still fail explicitly.

Receipts expose hashes, not the local model directory, pipeline option contents or asset filenames. The subprocess forwards only selected process environment settings, sets offline Hugging Face/Transformers flags before SDK imports, and denies Python socket audit events for offline providers. This is not a full OS sandbox: native-library filesystem/network confinement and immutable model snapshots are not established. Asset mutation during conversion is detected by the final verification, not prevented by read-only mounts. Real native provider behavior remains unqualified.

## Source-backed API baseline

The mapper uses the upstream [DoclingDocument item/provenance API (docling-core v2.50.0)](https://github.com/docling-project/docling-core/blob/v2.50.0/docling_core/types/doc/document.py), including item iteration, header levels, table cell text, reference labels and bbox origin. Offline asset handling follows the supplied-path branches of [Docling v2.60.0 layout model](https://github.com/docling-project/docling/blob/v2.60.0/docling/models/layout_model.py) and [table model](https://github.com/docling-project/docling/blob/v2.60.0/docling/models/table_structure_model.py). The implementation retains the existing open-ended dependency declaration; those source versions are review baselines, not new dependency bounds or real-runtime qualification.

## Actual verification

Tests use Docling-shaped converter doubles and fake parser modules inside real subprocesses. They are not real Docling or public-paper evidence. Test PDF bytes are locally generated fixtures. Runtime probing found `importlib.util.find_spec("docling") is None`; no verified Docling asset root was supplied. No model downloads, model license assertions or real-public-PDF qualification were performed.

Commands and final outcomes are also recorded in the matching OpenSpec verification file. Parent review should rerun these with `PYTHONPATH` pointing to this checkout's `src` while using the available project virtualenv.


Final targeted run: **55 passed**. Ruff: `All checks passed!`. `git diff --check`: no output. OpenSpec strict validation: valid. Exact commands and TDD results are retained in `openspec/changes/scholarly-pdf-extraction-locators/verification.md`.

## Parent independent verification

On 2026-10-23 the parent reviewed the production mapper, bounded parser process,
receipt identities and historical compatibility changes, then reran the same
four targeted test files: **55 passed in 12.62s**. Strict OpenSpec validation
and the commit diff check passed. Real Docling/model execution remains unverified;
converter doubles and actual resource-limited child processes are distinguished
above. The private primary checkout and its pending edits were not modified.
