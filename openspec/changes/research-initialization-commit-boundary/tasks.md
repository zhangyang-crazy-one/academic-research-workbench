## 1. Transaction boundary

- [x] 1.1 Add exact durable prepared/completed initialization receipts and seal before parent mutations.
- [x] 1.2 Share fail-closed pending recovery checks across initialization and research status/resume.

## 2. Verification and delivery

- [x] 2.1 Reproduce #125 and prove status/resume preserve the damaged scene, including interrupted-first-event then direct acceptance.
- [x] 2.2 Preserve SIGKILL, legacy healthy, relocation and unsafe/tampered boundary regressions; document ambiguous recovery.
- [ ] 2.3 Run focused regressions and quality gates, commit and submit one PR for #125 without merging.
