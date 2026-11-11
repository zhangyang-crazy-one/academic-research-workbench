## 1. Extraction and locators

- [x] 1.1 Implement bounded pypdf extraction, strict structured locator/quality records, and exact retained text verification.
- [x] 1.2 Implement explicit loopback GROBID and optional offline Docling adapters with no runtime downloads.
- [x] 1.3 Reuse #36 ReferenceRecord for bibliography and connect complete output to existing extraction registration.

## 2. Workflow and verification

- [x] 2.1 Provide a parent-operated CLI workflow and human-review output for empty/low-quality/malformed PDFs.
- [x] 2.2 Test text PDF, image-only PDF, offsets/digests, unsafe input, optional provider failures and registration with local fixtures only.
- [x] 2.3 Validate OpenSpec and record license/source inventory, actual unsupported behavior and outstanding acceptance.
- [x] 2.4 Bind PDF section, structured region and reference-entry quotes to v2 SourceLocator and parent provenance artifact acceptance; preserve v1 decoding and reject altered extraction bytes.

## 3. Closed-issue F05 correction (2026-10-23)

- [x] 3.1 Map Docling items/provenance/table cells/reference labels without Markdown inference; document unsupported bibliography metadata.
- [x] 3.2 Bind actual pipeline configuration and verified offline asset manifest to v2 receipts; decode historical v1 receipts.
- [x] 3.3 Run CLI providers in resource-limited child processes; bound timeout/output and distinguish unsupported/failure; avoid manifest collisions across configurations.
- [x] 3.4 Verify converter doubles, real subprocess limits/timeouts, CLI identity and legacy receipts; record actual offline-runtime availability separately.
