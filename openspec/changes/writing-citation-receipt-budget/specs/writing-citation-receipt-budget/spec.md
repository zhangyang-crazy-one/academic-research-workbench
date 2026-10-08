# Writing citation receipt budget

## ADDED Requirements

### Requirement: Versioned and scoped citation assertions
The writing workflow SHALL store new citation bindings as versioned indexes
into source and candidate sentence occurrences. Each assertion SHALL carry a
verifiable UTF-8 byte offset, byte length, and SHA-256 digest; each citation
SHALL point to an assertion index. The full sentence SHALL not be copied per
citation. Reading SHALL detect changed offsets, lengths, digests, or citation
scope. Legacy sentence-valued bindings SHALL remain readable and replayable
under their original sentence matching semantics.

#### Scenario: Long sentence with six citations
Given a source and candidate with 1,000 long sentences and six citations per
sentence, each under 1 MiB, prepare produces 1,000 assertion rows and 6,000
small bindings per side. The resulting citation data does not exceed the
retained receipt budget through repeated sentence copies.

#### Scenario: Multibyte scope and historical receipt
Given a Chinese sentence with citations, a reader verifies the exact UTF-8
byte slice and digest. Given an older accepted receipt, a fresh WritingService
reads its candidate and replay validates its accepted artifact. A changed scope
index or digest fails validation.

### Requirement: Complete receipt admission budget
Before publishing any writing receipt or accepted paper candidate, the writing
workflow SHALL measure the complete canonical receipt including proposal,
diagnostics, verification, bindings, and request identity. A receipt above
8,388,608 bytes SHALL fail with recoverable `receipt_budget_exceeded` and SHALL
leave no new candidate, receipt, or journal event.

#### Scenario: Oversized derived receipt
Given individually admissible texts whose complete result exceeds the receipt
budget, `writing record` rejects before publication; the request can be revised
and retried. A reviewer-approved in-budget result can be retained, read again,
and replayed from a fresh service.
