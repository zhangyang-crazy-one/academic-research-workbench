---
name: submission
description: Route auditable manuscript submission and revision work through ARW's parent-owned submission contracts.
---

# Submission workflow

This is a thin plugin route. Resolve the installed plugin root as the parent of
this `skills/` directory and invoke the installed `bin/arw` submission command.
Do not write journal events, gates, manifests, or human approvals directly from
the skill. The parent control plane owns canonical admission, provenance,
retries, readiness, and final human decisions.

Supported operations are additive and bounded:

```text
arw submission prepare
arw submission record
arw submission review-import
arw submission response-record
arw submission check
arw submission qualify
arw submission record-result
arw submission status
```

`check`, `status`, and `prepare` are read-only. `qualify --scope readiness`
records the aggregate check/gate result; `qualify --scope confirmation`
records only a narrow subject-eligibility gate and still requires the existing
authenticated human-decision flow. There is no portal login, upload, payment,
email, automatic retry, or `submit` operation. A saved portal page is not proof
of submission; external facts must be explicitly recorded as user-confirmed or
bound to a retained platform receipt.
