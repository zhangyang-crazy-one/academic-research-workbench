# Retained pre-vendor receipt

`5260b8d8d99c1b2c3c4c6020468d3f7cb9fb45f36360681ff6e766edc4785523.json`
preserves the exact previously reviewed receipt. Its original fields and
qualification status are unchanged. During v0.2.0 preparation, locally
retained raw files had drifted from this receipt. Seven files were recovered
with exact original hashes; the original native-invocations log could not be
recovered completely. The partial old raw corpus is not current release proof.

The new canonical `supply-chain/pre-vendor-receipt.json` comes from a real
fresh audit on 2026-10-09. Its digest is
`065860629027f811c04bd64743d705aa2631dbddf690c00e34d9ff9bc57666e0`.
All 17 raw files, three actual commands and current upstream source identities
were independently checked. The exact existing scanner/tool contract was
used, including ScanCode 32.5.0 and Node 24.13.0.

Current readers explicitly recognize both reviewed receipt digests and still
enforce strict semantics and manifest cross-binding. New stage production
requires the new canonical receipt. Historical readability grants no new
publication authority.
