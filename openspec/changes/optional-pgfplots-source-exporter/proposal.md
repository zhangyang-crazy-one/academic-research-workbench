## Why

#123 asks for an optional PGFPlots source exporter so authors can use existing verified result data in TeX manuscripts. It must share the SVG numeric compilation and preserve truthful publication/render qualification.

## What Changes

- Add deterministic PGFPlots source generation from compiled result_plot values and original IDs.
- Escape all user labels as inert text and emit only exporter-owned keys/macros.
- Expose an explicit source-only artifact export operation and immutable export manifest.
- Keep render/publication status not_verified, without installing or invoking TeX.

## Capabilities

### New Capabilities
- `pgfplots-source-export`: safe optional TeX source export of exact accepted plot values.

### Modified Capabilities
None. SVG receipts and qualification remain unchanged.

## Impact

Optional research-artifact extension and CLI adapter, focused tests/docs. No dependency change or TeX runtime invocation. One unmerged PR for #123.
