## Why

#121 requires authors to disclose AI involvement from artifact/activity provenance, including imported and unanchored text, figures and code. Existing ClaimGraph labels cannot supply human authorship or complete usage history.

## What Changes

- Add versioned parent-accepted activity receipts and human declarations for AI participation.
- Summarize all accepted material independently of claim/citation anchors, preserving unknown and original evidence references.
- Generate deterministic venue-specific drafts with frozen dated policy snapshots, replay at exact parent prefixes, and mandatory human final review.
- Associate existing ClaimGraph manuscript observations with the provenance summary without using graph labels as input.

## Capabilities

### New Capabilities
- `ai-disclosure-provenance`: source-bound involvement inventory and versioned disclosure drafts.

### Modified Capabilities
None. No scientific hard gate changes.

## Impact

Additive models, ledger/artifact reader and explicit offline CLI; schema/docs/tests and separate ARR/IEEE policy snapshots. No model/API calls, automatic submission or authorship inference. One independent unmerged PR for #121.
