# Shared sentence and citation scopes

`arw.kernel.state.text_spans` contains the existing writing surface algorithms: `SENTENCE_SEPARATOR`, `sentence_spans`, `sentences`, `PATTERNS`, `CITATION_BINDINGS_VERSION`, `_indexed_bindings`, `_legacy_bindings` and `validate_citation_bindings`.

The writing diagnostics and preservation modules directly re-export the same objects through their old import paths. No receipt, span version, regular expression, segmentation rule, UTF-8 offset, digest or validator failure rule changes. `resolve_citation_bindings` and writing preservation/diagnostic consumers keep their existing behavior.

Kernel graph consumers import these pure algorithms from the state module. They can use retained v2 byte spans and replay legacy sentence bindings without importing the optional writing engine. No dependency compatibility rule is relaxed.

Verification compares all five extracted function ASTs and the three constant ASTs exactly to main baseline `71b02ba`. The pre-extraction canonical fixture `tests/fixtures/text-spans/legacy-byte-projection.json` has SHA-256 `d3bae4e1fbeebbfdd48c3859c32974c6fad386621e8bbec081d6524f7728496e` and preserves original diagnostics, verification, character spans, UTF-8 citation tables and legacy binding output for Chinese/English, repeated sentences, decimals, CRLF/blank whitespace and mixed citations.

Dedicated object identity/byte/tamper checks plus existing writing receipt budget/legacy replay and kernel dependency compatibility tests pass (23 tests). Test imports explicitly use this worktree's source and writing extension.
