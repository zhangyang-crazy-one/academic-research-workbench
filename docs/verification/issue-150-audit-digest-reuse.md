# Issue #150 / PR171: invocation-local audit digest stability

Date: 2026-10-23. Personal checkout paths in command excerpts are rendered as `<primary-checkout>`; raw local logs retain the actual invocation. Repair branch: `fix/pr171-audit-stability` in `/tmp/arw-pr171-repair-20261023`. Parent: existing PR171 head `a0d5f1c97959631970fa93b7ebe481959638c893` (`origin/fix/issue-150-digest-reuse`). This repair preserves that history, the CI #169 prerequisite and the launcher startup implementation. It does not close #150.

## 已验证

The public `build_integration_lock`, `validate_live_audit_manifests`, `observe_build_identity_binding` and `verify_integration_lock` entrypoints own fresh private caches. The new caller-cache parameters on `FileBinding.from_path`, `build_integration_lock` and `validate_live_audit_manifests` were removed: supplying `cache=` now raises `TypeError`. Internal helpers retain sharing across reconstruction, build-identity checks and manifest auditing within one `verify_integration_lock` call. This intentionally narrows PR171's newly introduced API so callers cannot turn invocation-local reuse into trust across calls.

Every cache access opens a live regular file. Available `O_NOFOLLOW`, `O_NONBLOCK` and `O_CLOEXEC` flags prevent following final symlinks, FIFO blocking and descriptor inheritance. Path and descriptor device, inode, size, mtime, ctime and mode must agree before and after hashing/reuse. An already observed identity cannot be replaced or rewritten within the audit, even with identical replacement bytes. All cached paths are checked again before a public return; the host-canary closure checks its own local bindings before return. Missing/zero inode or change time, or a non-POSIX platform, disables digest reuse. Independent reads still compare against the initially observed digest and reject detected changes. Existing root, closed membership, coverage, manifest and claimed-digest checks remain active.

The main checkout's original 19-case regression module was run against the untouched remote PR171 implementation **before** this repair:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/arw-pr171-repair-20261023/src \
<primary-checkout>/.venv/bin/python \
-m pytest -q --import-mode=importlib \
<primary-checkout>/tests/unit/test_audit_digest_reuse.py
```

Observed: **16 failed, 3 passed in 6.62s**. Direct filesystem cases showed restored-mtime writes, identical-byte replacement, chmod and symlink drift being accepted; a direct FIFO test timed out at five seconds. This is the raw compatibility/regression result, not 16 independent vulnerability proofs: some original tests injected through `hashlib.file_digest` or `os.open`, whereas the remote implementation used `sha256_file` / `Path.open`, so those hooks did not intercept its actual reads. The repair uses descriptor-based streaming; final tests inject at that real path and retain the launcher-specific `Path.open` tests separately.

The remote tests previously allowed a warmed audit cache to accept replacement or restored-mtime content by rehashing and resetting its baseline. `test_one_audit_reuses_a_payload_digest_and_rejects_replacement` and the audit branches in `test_streaming_integrity_hash.py` now require `IntegrationLockError` on such drift. A fresh invocation still independently reads and checks the replacement. Launcher assertions retain the behavior already present in PR171; its implementation was not modified. Old audit-only mocks that patched `Path.open` or fabricated non-regular `stat` results were replaced with descriptor/open-race, actual FIFO, unusable inode/ctime and platform-fallback cases in `test_audit_digest_reuse.py`.

Final commands, from the repair worktree:

```sh
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/tmp/arw-pr171-repair-20261023/src
<primary-checkout>/.venv/bin/python \
  -m pytest -q tests/unit/test_core_route.py tests/unit/test_audit_digest_reuse.py \
  tests/unit/test_streaming_integrity_hash.py tests/unit/test_integration_lock.py \
  --tb=short --junitxml=/tmp/arw-pr171-repair-20261023-integrity.xml
ruff check --isolated --select E4,E7,E9,F src/arw/kernel/policy/integration_lock.py \
  tests/unit/test_audit_digest_reuse.py tests/unit/test_streaming_integrity_hash.py \
  tests/unit/test_integration_lock.py
ruff format --check tests/unit/test_audit_digest_reuse.py
openspec validate portable-release-qualification --strict
git diff --check
git diff a0d5f1c97959631970fa93b7ebe481959638c893 -- .github bin/arw
```

Observed: **320 passed, 1 skipped in 50.46s**; lint, new-test formatting, strict OpenSpec validation and diff checks passed; CI/launcher diff was empty. The skipped `test_core_route.py:92` case requires a complete retained stage. Full output: `/tmp/arw-pr171-repair-20261023-integrity.log`; JUnit: `/tmp/arw-pr171-repair-20261023-integrity.xml`. Runtime: Python 3.14.6, Linux; an explicit import check resolved `integration_lock.__file__` to the repair worktree `src`.

The 37 digest-reuse cases include actual restored-mtime writes, same-byte inode replacement, chmod, missing paths, symlinks, mutations/read errors during hashing, first-open and warmed-cache replacement races, reopen permission failures, direct/raced FIFO rejection in subprocesses with five-second bounds, zero/None inode/ctime fallback, simulated non-POSIX fallback, independent public calls, rejection after final internal build/verify/observe checks and host-canary closure validation. The 32/512 MiB sparse-file case compares SHA-256 with reference bytes and bounds peak traced hashing allocation below 4 MiB. The shared-cache native payload is hashed once per POSIX build/verify/observe invocation; this counter covers descriptor-cache hashing only, not independent stage-tree/host preflight reads, physical disk traffic or installed process-tree resource use.

## 未验证

Installed `version`, `route`, memory/files MCP startup A/B wall time, process-tree RSS/PSS, idle/exit behavior and cross-process preflight deduplication remain #150 follow-up work. These unit tests and traced allocations are not installed startup performance measurements. No native/materialized-source suite, signed release qualification or live Codex host qualification is established here. Windows fallback is simulated; no live Windows filesystem was tested. Filesystem timestamp resolution/consistency bounds identity-based change detection; the implementation does not provide an atomic snapshot against arbitrary concurrent writers or protect mutations occurring after verification returns.

## 阻塞

No blocker for this local repair and commit. Installed A/B measurements and full retained-stage/native/host qualification remain outside the evidence produced by this repair. No push, issue/PR comment or competing PR was created.
