# Research figure asset collection / 科研图独立素材

200 reusable objects (A001–A200), each with an editable SVG, transparent 512×512
PNG, original AI-generated raster prototype and original generation prompt.
These are individual objects, not complete methodology figures or experimental results.

Open [index.html](index.html) locally to browse and search the collection. No server,
network request, external library or account is required. Each object links to its
SVG, PNG, prototype and prompt. The five categories contain 40 objects each.

## Use / 使用

- Prefer `svg/Axxx.svg` for editable paper figures; use `png/Axxx.png` for slides.
- Keep the intrinsic shape; add task-specific labels, arrows and evidence separately.
- `prototypes/` preserves all original generated images, not the editable final artwork.
- `manifest.json` records names, categories, public contextual references, relative
  paths and SHA-256 digests. Paper references supply semantic context only; no paper
  crops or third-party figure bytes are included.
- Run `python3 scripts/validate-research-figure-assets` from the repository root to
  verify inventory, hashes, PNG dimensions and safe native SVG structure.
- Run `python3 scripts/package-research-figure-assets /tmp/research-figures.zip`
  to make a complete portable ZIP. Archives are generated on demand, not duplicated
  in Git. Original prototype pixels are retained without lossy re-encoding.

## Provenance and limits

The raster prototypes were produced with an AI image-generation workflow and the
final SVGs reconstructed as editable geometry. These illustrations are conceptual,
not medically or mechanically certified diagrams. A reference to a publication does
not imply endorsement, tracing or permission to reuse its own figures.

The repository uses component-scoped licenses; its root LICENSE is not a blanket
grant. This collection introduces no new license grant. Maintainers should settle
the collection's distribution terms before promoting it beyond draft review.

## Packaging boundary

This is an optional repository asset pack, not an ARW runtime dependency or an
installed scientific-figure backend. It does not register commands, alter research
state, or claim ARW scientific acceptance. The directory is excluded from the
Python source distribution, and lies outside every wheel package. The plugin's
explicit staging inputs do not include this directory. Downloading/cloning the
repository still includes the original prototypes (about 151 MB); the browser
initially displays only lazy-loaded final PNG previews.
