## Why

GitHub issue #39 requires paper authors to quote and review exact PDF source locations. Existing file extraction registration stores flat text without scholarly layout, page locators or a quality decision, so claims cannot reliably trace to PDF passages.

## What Changes

- Add local pypdf extraction by default, explicit localhost GROBID service mode, and optional Docling mode with model downloads forbidden at runtime.
- Emit structured page/section/paragraph/table/figure/reference locators tied to PDF and extracted-text digests.
- Record extraction version, quality, access state and human-review reasons; only eligible output enters existing registration and evidence workflows.
- Link bibliography entries to the shared #36 `ReferenceRecord` contract without redefining it.

## Capabilities

### New Capabilities

- `scholarly-pdf-extraction`: Bounded PDF extraction, structured locators, quality review and registration.

### Modified Capabilities

None.

## Impact

Adds an extraction module/CLI, optional provider dependencies and tests. Existing file registration is reused. License and source inventories must record actual resolved optional packages and service versions.
