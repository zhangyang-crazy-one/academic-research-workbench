## Context

File administration accepts a digest-bound UTF-8 extraction but does not perform extraction. SourceLocator supports text pages, while ResearchIntegrity EvidenceSpan has only a generic page/line/section range. #36 owns reference identity.

## Goals / Non-Goals

**Goals:** Produce retained text and structured page locators with digest-bound registration and explicit quality review. Preserve source/reference chain.

**Non-Goals:** OCR, hallucinated page numbers, automatic human approval, arbitrary remote GROBID servers or runtime Docling model downloads.

## Decisions

1. pypdf reads a bounded local PDF and emits one text page per physical PDF page. Every locator includes PDF digest, extraction digest, extractor identity/version and page number. Missing text yields a review item, not empty verified evidence.
2. GROBID is explicitly selected and accepts only loopback endpoint; TEI parsing is bounded and disables external entities. Docling is optional and must operate with preinstalled local assets and offline environment settings. Provider failures become typed review reasons.
3. Page and structural spans are derived from retained output, preserving section/paragraph/table/figure/reference labels and exact text offsets. A v2 `SourceLocator` binds the accepted extracted-text artifact to the extraction manifest and original PDF bytes; legacy v1 decoding remains intact. `pdf_region` requires explicit structural bbox coordinates and is unavailable from the default pypdf path. Unsupported structure is marked unknown, never guessed. Bibliographic references use #36 `ReferenceRecord` and check receipts.
4. An extraction can be registered only after source digest, extraction digest and quality/access checks. Parent acceptance of a provenance assertion verifies the extraction manifest, PDF digest, exact located quote and accepted text artifact. Existing file `ExtractionRegistration` and source manifest are not replaced. Human-review queue acknowledgement remains separate.

## Risks / Trade-offs

- PDF text order can be misleading → retain physical page identity, surface quality warnings and require review for low quality.
- Service/model optionality → explicit unavailable state; no fallback that silently changes provenance.
- Large or hostile PDF → byte/page/output caps and local-root checks.

## Migration Plan

Existing flat registrations remain readable. New structured output is additive; no old extraction is assigned synthetic locators.

## F05 correction, 2026-10-23

Source authority: issue #39 body from the saved audit `issues.json`; that record has no comments. The existing amendment-compatible non-goals (OCR, runtime downloads, implicit fallback) still apply. Do not reinterpret the earlier checked tasks as real Docling qualification.

The local Docling adapter now retains item text and explicit table cell strings in reading order, using physical item provenance. Section labels use source header levels. Single-page, whole-item provenance permits normalized bbox locators; ambiguous multi-provenance/partial charspan items require review rather than invented locations. Docling reference TextItems supply raw reference text, not the complete authors/title/year contract; `reference_metadata` remains unsupported and no ReferenceRecord is invented. Cell-specific canonical locator types remain unsupported.

V2 extraction receipts add `configuration_sha256`, `model_manifest_sha256` and explicit unsupported structures. Effective pipeline options (including SDK defaults) are hashed; model paths/options are not exposed in receipts. Docling requires `arw-docling-assets.json`, an exact digest/size inventory of at most 512 files and 8 GiB total in the selected asset root. Streaming reads reject symlinks, traversal and special files. Rechecking after conversion detects mutation. The inventory attests bytes only; model provenance, license and runtime suitability still require actual external evidence. A legacy caller-supplied `extract_pages` converter has unknown model identity and yields review, never complete evidence.

The CLI sends bounded PDF bytes to a subprocess with AS=4 GiB, CPU=30 s, wall=45 s, file size=32 MiB, descriptors=64 and no core dumps. Python network audit events are denied for offline providers, with offline environment flags set before imports. GROBID retains explicit loopback opt-in and transport validation. This is a resource boundary following the artifact-formats pattern, not an OS namespace filesystem/network sandbox; native-library confinement is not claimed. Unsupported platforms fail explicitly. The child receives no inherited credentials. Parent publication names manifests by their own digest and keeps text names by text digest, preserving prior immutable outputs across provider/configuration/model changes.
