## ADDED Requirements

### Requirement: Safe local PDF extraction with explicit optional providers

ARW SHALL use pypdf by default. GROBID SHALL require an explicit loopback endpoint and Docling SHALL require installed offline assets without runtime model downloads. Extraction SHALL enforce source/output/page limits and record provider identity and version.

#### Scenario: Default offline extraction

- **WHEN** a bounded text PDF is extracted with no provider option
- **THEN** pypdf produces retained text and no network request is made

### Requirement: Structured, digest-bound locators

ARW SHALL bind every emitted page, section, paragraph, table, figure and reference locator to the source PDF and extracted text digests, exact page and retained text offsets. Unsupported structure SHALL remain unknown. Bibliography identity SHALL reuse #36 `ReferenceRecord`.

#### Scenario: Trace a paragraph quote

- **WHEN** a paragraph is used as claim evidence
- **THEN** the exact retained bytes and source page are recoverable and digest-verified

#### Scenario: Tampered extraction reaches parent admission

- **WHEN** an assertion cites a PDF section or reference entry and the retained extraction manifest or PDF changes
- **THEN** `artifact-accept` rejects the assertion before it emits canonical acceptance

### Requirement: Quality, registration and human review

ARW SHALL classify empty, malformed, inaccessible and low-quality extraction distinctly, queue human review, and register only complete accessible outputs through the existing extraction contract. Parent admission remains required for scientific evidence.

#### Scenario: Image-only PDF

- **WHEN** extraction finds no reliable text
- **THEN** a human/OCR review item is produced and no verified full-text registration or PASS is emitted

### Requirement: Structured Docling output and extraction identity

The local Docling adapter SHALL derive retained text and labels from document items, table cells and physical provenance, never Markdown heuristics. Regions SHALL normalize explicit Docling coordinates to top-left unit-page coordinates. Missing or ambiguous provenance SHALL remain unsupported or require review. Reference labels without structured bibliographic metadata SHALL retain exact reference text without invented ReferenceRecord fields.

New extraction receipts SHALL use `arw.pdf-extraction.v2` with a configuration digest. The local Docling path SHALL additionally bind a caller-supplied asset manifest digest after verifying all listed regular files before and after conversion. Asset verification SHALL NOT imply license qualification or extraction accuracy. Historical v1 receipts SHALL remain readable without assigning synthetic configuration/model identities.

#### Scenario: Docling item mapping

- **WHEN** Docling supplies section headers, table cells, reference labels, physical pages and bbox provenance
- **THEN** retained locators recover the exact corresponding UTF-8 bytes and normalized source coordinates, without parsing exported Markdown or guessing bibliography metadata

#### Scenario: Changed configuration or weights with identical text

- **WHEN** extraction configuration or the verified asset manifest changes while retained text stays identical
- **THEN** the manifest identity and published manifest path change, while historical outputs remain intact

### Requirement: Independent bounded CLI parser process

The CLI SHALL parse every selected PDF provider in an independent child with enforced CPU, address-space, file-size, descriptor and wall-time limits. Unsupported platforms, missing optional providers, timeout, invalid responses and resource failure SHALL return explicit error codes without silently falling back. Child output SHALL be bounded before parent decoding. Model downloads SHALL remain disabled; only the explicit verified model root may supply Docling assets. This process boundary SHALL NOT be represented as a full operating-system filesystem or network sandbox.

#### Scenario: Hung or verbose parser

- **WHEN** a parser exceeds wall time or its output-file budget
- **THEN** its process group is terminated or fails at its hard resource boundary and no complete extraction is published
