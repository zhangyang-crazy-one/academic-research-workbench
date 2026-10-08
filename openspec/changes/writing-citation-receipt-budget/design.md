# Design

`verification.citation_bindings.version` identifies
`arw.writing-citation-bindings.v2`. Each source/candidate table has `assertions`
and `bindings`. An assertion holds a UTF-8 byte `offset`, byte `length`, and
SHA-256 digest of one trimmed sentence occurrence in the corresponding retained
text. A binding holds its citation token and an integer assertion-table index.
The sentence bytes stay in the existing `source`/`candidate` fields. Sentence
splitting uses the unchanged surface segmentation; repeated citations share one
assertion row for their occurrence. Decoding and validation recompute sentence
spans and token order, so moving an index, changing a digest, or borrowing a
scope from the other text fails. Legacy source/candidate lists of
`{citation, assertion}` objects are validated using their original full-sentence
semantics and can be resolved through the same reader.

`WritingService.record` serializes the complete result with
`canonical_json_bytes` after source and review bindings and request identity are
attached. If the bytes exceed `MAX_SOURCE_BYTES`, it raises recoverable
`receipt_budget_exceeded` before calling `publish_once` for either the receipt
or an accepted paper candidate. A successful record retains its existing
immutable publication and journal admission sequence. The source/candidate
1 MiB limits and review authority are unchanged.
