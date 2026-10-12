## 1. Query reuse

- [x] 1.1 Add private exact-prefix query cache and share it with anchor/AcceptedRef validation.
- [x] 1.2 Reuse monotone dependency closure without changing non-extending or unavailable-proof paths.

## 2. Verification and delivery

- [x] 2.1 Count replay work at 30/60 anchors and compare cached/uncached bytes; verify new-query and lock/tamper behavior.
- [x] 2.2 Run claim authority/caption/compatibility regressions, document scope and submit one unmerged PR for #124.
