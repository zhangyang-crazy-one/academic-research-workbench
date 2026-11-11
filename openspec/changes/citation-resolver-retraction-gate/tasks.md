## 1. Contract and resolver

- [x] 1.1 Implement strict shared ReferenceRecord/ReferenceUse and immutable check receipt contracts with content digests.
- [x] 1.2 Implement deterministic parsers and conservative matching for Crossref, OpenAlex, DBLP and arXiv using retained response bytes.
- [x] 1.3 Implement explicit-opt-in bounded transport and content-addressed response publication/offline replay.

## 2. Gate and integration

- [x] 2.1 Implement per-use retraction gate, historical blocker preservation and receipt-derived contamination signals.
- [x] 2.2 Integrate parent-owned CLI or runtime path for accepted evidence and gate decisions; preserve source/license inventory.

## 3. Verification

- [x] 3.1 Exercise end-to-end fixture workflow including provider results, offline replay, recheck, supporting/research-object roles and no-network default.
- [x] 3.2 Run OpenSpec validation and targeted tests; report unsupported or deferred behavior explicitly.

## Compatibility acceptance

The #36 implementation adds the reviewed `policy -> ledger` edge for immutable receipt publication and parent-accepted evidence reads. The existing ledger dependency closure has no path back to policy. `tests/compat/golden/kernel_edges.json` records only this added edge; the exact-match ratchet continues to reject every other unreviewed edge change. Validate with `pytest -q -m v2_compat tests/compat`.

## 4. Issue #36 production conflict follow-up (2026-10-23)

- [x] 4.1 Add failing policy and complete CLI tests for resolver/self-report conflicts, omissions, manual notes and historical compatibility.
- [x] 4.2 Connect receipt-derived contamination observations and an explicitly selected ARS literature entry to the canonical gate journal without rewriting either input.
- [x] 4.3 Verify offline CLI replay, source identity/admission rejection, historical blockers and targeted regression checks; retain exact evidence.
