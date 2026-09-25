---
name: submission
description: "ARW manuscript submission packet and decision workflow after a manuscript exists: prepare, review-import, response-record, readiness, human confirmation and result recording. Use for 投稿材料、审稿意见导入、回复审稿人、投稿就绪核查. For research methods use academic-research-suite; for operational commands use academic-research-workbench."
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
arw submission ready
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

`ready` only performs the registered parent lifecycle transition after the
current packet/report fingerprint, aggregate PASS gate and exact human
approval are rechecked under parent serialization. It is not an external
submission action. Automatic Word/PDF patching and locator remapping are
unsupported; external document revisions require retained version-bound
evidence.
