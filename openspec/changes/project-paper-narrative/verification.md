# Verification — project paper narrative

Date: 2026-10-02. No private manuscript, real model, authenticated host canary,
plugin installation, push, pull request, or merge was performed.

## Verified baseline and preservation

- GitHub REST `repos/zhangyang-crazy-one/academic-research-workbench/branches/main`
  returned `407a47de6bab82b5f20cac24766a0625cb0033cf`.
- The implementation workspace was populated from that exact commit's GitHub
  source archive, SHA-256
  `169c8f740bcbbe11af11d5955692836733ba4db9c7772642581737e63a49b46e`.
- The initial local `main` reference `604510b` was stale and was replaced before
  implementation. The isolated Git baseline is a synthetic source snapshot,
  not an upstream commit; the deliverable patch is against the verified archive.
- The original checkout remained on `472f285` with its original four modified
  files and one untracked file. No original-checkout files were edited.
- PR51 was rechecked as open/draft and not merged. This change does not depend
  on or transplant that branch.

## Acceptance results

- Final complete non-host pytest run: **1859 passed, 87 skipped, 4 deselected**,
  271.95 seconds. Git-dependent tests used the isolated Git metadata; subprocess
  tests reused the existing Python 3.14 virtual environment with all ARW and
  extension imports explicitly directed to the isolated source workspace.
- The separately deselected Unix-domain socket fixture passed (1 test).
- The sandbox-skipped local HTTP detector opt-in/redirect/version-mismatch
  fixture passed separately (1 test). This used a synthetic loopback server,
  not an external detector or model.
- Final focused narrative/Phase4/schema run: **28 passed**, 7.58 seconds.
- Implementation-side narrative/schema/writing/memory/CLI contracts:
  **93 passed**. Phase4 related suite: **50 passed**.
- Independent reviewer: **30 new-feature/schema tests** and **64 adjacent
  writing/memory/passport/orchestration regressions** passed; no blocking
  finding remained after repairs.
- Ruff checks passed for the new modules/tests and changed writing/memory
  services. New narrative modules' Pyright: **0 errors, 0 warnings**.
- OpenSpec strict validation and `git diff --check` passed.

The first complete run had 22 failures. One was the intentionally extended
launcher help golden; it was updated. Twenty were missing checkout Git or
virtual-environment prerequisites in the isolated archive; their corrected
test group passed (81 passed, 5 prerequisite skips). One was a sandbox-denied
Unix socket; its separate rerun passed. The final complete run has no failures.

## Cases and repairs

Executable tests cover first selection, second startup, a second service/agent,
concurrent initial selection, stale compare-and-swap and exact proposal
approval, pending versus active versions, damaged/missing history, symlink and
byte-budget rejection, short writes, project relocation, generic non-paper
runs, real Passport resume, real writing artifact/receipt admission, real
handoff body save/reload, and stale writing/handoff/assignment rejection.
Phase4 tests include a real version-1 PASS gate and rejection after approved
version 2, plus a fresh run using version 2.

Independent review prompted repairs to stable project identity and relative
root binding, lock/path validation, bounded append behavior, lightweight CLI
imports, structured startup/resume errors, the resume commit/read race,
approved-version initial preparation, final review/gate checks, installed
skill references, the run-manifest schema's duplicate property, and worker
protocol wording. Vendored ARS source was not edited; an adapter protocol
overrides unsuitable universal chapter/claim/paragraph examples.

## Limits and intentionally unperformed qualification

- A prepared Phase4 saga is immutable. An approved narrative change requires
  a fresh paper run/assignment; old results and gates cannot be accepted.
- Approval can occur while an asynchronous worker is running. The old worker
  may finish, but admission rejects its obsolete narrative. No whole-worker
  lifetime atomicity is claimed.
- Machine checks apply to ARW paper startup and its services. ARS inline work
  must enter those boundaries through the documented protocol. Arbitrary
  agent writes bypassing ARW are not globally intercepted.
- `--author-confirmed` records the operator's explicit assertion of author
  approval; neither that flag nor `author-id` independently authenticates an
  author.
- Remaining prerequisite skips concern native file-base/materialized source,
  retained qualification evidence, offline isolation tools, or optional model
  assets. Authenticated host tests were deliberately not run. No qualification
  prerequisites were installed or trust settings changed.
- Existing unrelated Phase4 lint/type diagnostics were not expanded into this
  feature's scope; the new narrative modules and targeted checks passed.
