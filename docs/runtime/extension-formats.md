# Provider extraction and artifact format support

ARS routing now resolves `arw_ars.ARSAdapter` from `extensions/ars/` through
`WorkflowProvider`. Pinned skill/source content, upstream commit and tree digests,
license text, modification marks and qualification checks remain in their existing
locations. STORM code resides in `extensions/storm/`; `research.deep_survey`
requires its optional engine. The callable provider implements the workflow port
without advertising a canonical definition: STORM produces advisory files, not
ledger-approved research. Minimal CLI/ARS imports do not import STORM or ML libraries.

The stable `scripts/file-base-mcp` executable delegates to
`extensions/file-base-mcp/bin/provider`. That extension retains explicit root/cache
configuration, store-absent fallback behavior and the native compatibility branch.
The pinned binary and patch are unchanged. Its native schema/error tests and the
frozen five FileProvider operations remain necessary: native compatibility is
still exposed by the executable when explicitly configured. It is therefore not
eligible for removal merely because the local store is the default files reader.

## Compatibility inventory

The existing thin-kernel migration used explicit moved imports. There are no
obsolete kernel aliases to remove. This change moves two concrete Python import
locations: `arw.adapters.workflow` → `arw_ars`, and `arw.storm` → `arw_storm`.
No deprecation alias was added. The documented shell/MCP entrypoint is retained;
it is active compatibility wiring, not an obsolete alias. Historical artifact
events, ARS skill identity and native binary qualification remain readable.

## Format matrix

Binary adapters run in a separate, bounded process. `artifact-formats` pins pypdf
6.14.2 and Pillow 12.3.0; neither belongs to the base offline wheelhouse. Missing
libraries report `unsupported`. DOCX ZIP/XML processing uses the standard library.

| Format | Inspection | Explicit metadata treatment | Retained-content verification |
| --- | --- | --- | --- |
| UTF-8 | Existing selected Unicode families | `--treatment unicode --remove-codepoint ...` | Every unselected character and line ending unchanged |
| PNG | EXIF chunk, Adobe XMP iTXt, C2PA caBX/JUMBF | Selected EXIF/XMP blocks; separately authorized C2PA stripping | Coding/color chunks byte-identical and decoded RGBA pixels equal |
| JPEG | EXIF APP1, standard XMP APP1, bounded sequential C2PA APP11/JUMBF | Selected EXIF/XMP blocks; separately authorized C2PA stripping | Coding/entropy segments byte-identical and decoded RGBA pixels equal |
| DOCX | Known document-property presence and private-field counts | Selected private properties only | All non-property ZIP member bytes and retained non-private property values unchanged |
| PDF | Info-property presence/private-field counts, catalog XMP, supported catalog-associated C2PA files | Selected private Info fields/XMP; separately authorized catalog C2PA stripping | Resolved page dictionaries/resources and decoded stream digests unchanged |

DOCX C2PA/EXIF/XMP, object-level or complex PDF provenance, nonstandard JUMBF
carriers, extended JPEG XMP and additional formats are explicitly unsupported or
unknown; no raw substring search certifies absence. C2PA checks identify container
presence using type UUID/label and format structure. They do not validate claims,
signatures, trust chains or cryptographic authenticity. Positive test manifests are
synthetic container fixtures, not valid signed credentials. Negative findings
apply only to performed checks, never to arbitrary watermarks.

Inspection reads source bytes without mutation. Binary sanitation requires:

```sh
bin/arw artifact sanitize --root SOURCE_ROOT --path image.png \
  --run-root RUN --request request.json --privacy --treatment metadata \
  --remove-metadata exif --strip-provenance
```

`--remove-metadata` accepts `exif`, `xmp`, `pdf_properties`, `docx_properties` and
may be repeated. Whole EXIF/XMP removal can discard attribution even without
C2PA, so it always needs separate `--strip-provenance`. Modifying a detected C2PA
carrier also requires that authorization; privacy alone does not authorize it.
DOCX/PDF private-property treatment retains other properties. A nontrivial EXIF
orientation is refused when EXIF removal would change presentation. Unsupported
provenance or signed/active documents require a separate reviewed workflow.

Source/derived bytes are recoverable from base64 fields in the immutable receipt,
with both digests, selected families, authorization, parser policy and preservation
results. Exports are create-only mirrors. The parent uses the existing artifact
writer; retry/conflict/revision behavior is unchanged. An accepted sanitation
receipt records the operation, not scientific approval or universal rendering
identity. Image pixels and declared page/body properties are the verified scope.

Limits: 1 MiB input/output, 512 ZIP entries/container parts, 8 MiB aggregate ZIP
expansion, 200:1 ZIP ratio, 100 PDF pages, 16 million pixels, one image frame,
32 PDF graph levels/50,000 visited objects, 512 MiB process memory, 5 CPU seconds
and 8 wall-clock seconds. Encrypted, malformed, unsupported or resource-exhausted
inputs return explicit unknown/unsupported outcomes and cannot be sanitized.
Source-root confinement and immutable publication retain the existing platform
checks; bounded binary workers currently require POSIX resource limits.

## Primary implementation references

- [pypdf metadata API](https://pypdf.readthedocs.io/en/stable/user/metadata.html)
  documents separate Info and XMP metadata and writer metadata updates.
- [Pillow Image API](https://pillow.readthedocs.io/en/stable/reference/Image.html)
  documents lazy loading, explicit pixel loading and decompression limits.
- [C2PA 2.2 specification](https://spec.c2pa.org/specifications/specifications/2.2/specs/C2PA_Specification.html)
  defines the Manifest Store UUID/label (§11.1.4.2), PNG/JPEG embedding (§A.3),
  and PDF associated embedded files (§A.4).
