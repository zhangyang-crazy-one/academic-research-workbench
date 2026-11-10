# CI Python compatibility verification — 2026-10-23

## 已验证

Personal checkout paths below are rendered as `<primary-checkout>`; raw local logs retain the actual commands.

Worktree `/tmp/arw-ci-python-compat-20261023`, branch `fix/ci-python-extras-compatibility`, baseline `c8760e03df9843a69b68141f1e15a0dbf397a768`. Only CI, its tests, README support matrix and this change are modified. `pyproject.toml` is unchanged.

### Actual hosted failure and source

Read-only commands:

```bash
gh run view 39569504862 --repo zhangyang-crazy-one/academic-research-workbench --job 119121900907 --log
gh run view 39569504862 --repo zhangyang-crazy-one/academic-research-workbench --json headSha,conclusion,event,url,jobs
gh api 'repos/zhangyang-crazy-one/academic-research-workbench/contents/.github/workflows/ci.yml?ref=94efa630350775872f58d0b1034f92e6167a55bc' -H 'Accept: application/vnd.github.raw+json'
```

[PR #176 Python job](https://github.com/zhangyang-crazy-one/academic-research-workbench/actions/runs/39569504862/job/119121900907), event `pull_request`, conclusion `failure`, head SHA `af41101d4401a0e8f2e721c08f7285e49dfcfb45`. The checkout log identifies merge SHA `94efa630350775872f58d0b1034f92e6167a55bc`; its workflow source confirms `3.x` and the all-extras/dev/ars-test/storm install. This merge object was not present locally, so source was retrieved through GitHub's read-only contents API. Relevant original log lines (ANSI escape notation removed only):

```text
Python	UNKNOWN STEP	2026-10-21T08:33:29.4217737Z   python-version: 3.x
Python	UNKNOWN STEP	2026-10-21T08:33:29.5471891Z Successfully set up CPython (3.15.0)
Python	UNKNOWN STEP	2026-10-21T08:33:34.4498347Z ##[group]Run uv venv && ./scripts/install-python --all-extras --group dev --group ars-test --group storm
Python	UNKNOWN STEP	2026-10-21T08:33:34.4499128Z uv venv && ./scripts/install-python --all-extras --group dev --group ars-test --group storm
Python	UNKNOWN STEP	2026-10-21T08:33:34.9935670Z   cause: Because torch>=2.2.2 has no wheels with a matching Python ABI tag (e.g., `cp315`) and all of:
Python	UNKNOWN STEP	2026-10-21T08:33:35.0218784Z hint: You require CPython 3.15 (`cp315`), but we only found wheels for `torch` (v2.14.1) with the following Python ABI tags: `cp310`, `cp311`, `cp312`, `cp313`, `cp314`, `cp314t`
Python	UNKNOWN STEP	2026-10-21T08:33:35.0230102Z ##[error]Process completed with exit code 1.
```

### TDD and targeted behavior

Before modifying the workflow, run:

```bash
PYTHONPATH=/tmp/arw-ci-python-compat-20261023/src:/tmp/arw-ci-python-compat-20261023 \
  <primary-checkout>/.venv/bin/python -m pytest -q \
  tests/unit/test_ci_python_compatibility.py
```

Actual RED summary:

```text
=========================== short test summary info ============================
FAILED tests/unit/test_ci_python_compatibility.py::test_complete_optional_environment_uses_compatible_ci_minor
FAILED tests/unit/test_ci_python_compatibility.py::test_latest_python_core_is_independent_of_optional_ecosystem
2 failed, 1 passed in 0.08s
```

The assertions report `3.x != 3.14` and missing `python-core-latest`; the open-range policy already passes. After the fix, run with the same `PYTHONPATH` and interpreter:

```bash
PYTHONPATH=/tmp/arw-ci-python-compat-20261023/src:/tmp/arw-ci-python-compat-20261023 \
  <primary-checkout>/.venv/bin/python -m pytest -q \
  tests/unit/test_ci_python_compatibility.py tests/unit/test_ci_test_discovery.py \
  tests/unit/test_ci_native_sanitizer_workflow.py tests/unit/test_ci_release_native_qualification.py \
  tests/unit/test_release_workflow_contract.py tests/unit/test_canonical.py \
  tests/unit/test_manifests.py tests/unit/test_recovery_scan.py tests/unit/test_platform_support.py
```

```text
........................................................................ [ 74%]
.........................                                                [100%]
97 passed in 5.67s
```

An import probe explicitly printed `/tmp/arw-ci-python-compat-20261023/src/arw/kernel/core/canonical.py` and `/tmp/arw-ci-python-compat-20261023/src/arw/kernel/policy/integration_lock.py`, avoiding the main checkout's editable source.

A separate clean environment used `uv venv --python /usr/bin/python3.14` and `./scripts/install-python --group dev`. The actual workflow test command was extracted from YAML and executed with `PYTHONNOUSERSITE=1`, `UV_OFFLINE=1` and the same worktree `PYTHONPATH`:

```text
core source: /tmp/arw-ci-python-compat-20261023/src/arw/kernel/core/canonical.py
torch: absent
docling: absent
knowledge-storm: absent
sentence-transformers: absent
workflow command: .venv/bin/python -m pytest -q tests/unit/test_canonical.py tests/unit/test_manifests.py tests/unit/test_recovery_scan.py tests/unit/test_platform_support.py tests/unit/test_ci_python_compatibility.py
........................................                                 [100%]
40 passed in 3.14s
```

After final test formatting/range-operator changes, the same five modules were rerun:

```text
........................................                                 [100%]
40 passed in 3.80s
```

### Complete optional scope resolution on Python 3.14

```bash
uv venv --python /usr/bin/python3.14 /tmp/arw-ci-python-compat-20261023-resolve-venv
/tmp/arw-ci-python-compat-20261023-resolve-venv/bin/python \
  scripts/install-unmanaged-deps.py --dry-run --all-extras dev ars-test storm
```

```text
Using Python 3.14.6 environment at: /tmp/arw-ci-python-compat-20261023-resolve-venv
Resolved 213 packages in 26.51s
Would download 96 packages
Would install 213 packages
 + docling==2.142.0
 + knowledge-storm==1.1.1
 + sentence-transformers==5.7.0
 + torch==2.14.1
```

This is a real online dependency resolver dry-run using declared ranges, including the full requested dependency scope; it does not install or execute those optional packages and creates no lockfile. Recorded resolved versions are observations, not constraints. The existing workflow's helper is unchanged and still installs all extras followed by the same declared groups.

Static checks: `.venv/bin/ruff check --isolated --select E4,E7,E9,F tests/unit/test_ci_python_compatibility.py`, `.venv/bin/ruff format --check tests/unit/test_ci_python_compatibility.py`, `git diff --check`, and `openspec validate ci-python-extras-compatibility --strict`. All passed. The main checkout's `.venv/bin/ruff` was absent; lint/format checks used the clean worktree environment instead. Initial format check found formatting in the new test, corrected before final checks.

## 未验证

- New hosted Actions execution and branch-protection treatment of the new check await the main agent's reviewed PR.
- No local CPython 3.15 interpreter was installed (`uv python list --only-installed` retained). Core execution above is Python 3.14.6; current cp315 core behavior is delegated to the added floating job.
- No local cp315 optional-dependency acceptance is claimed. The historic hosted log proves the specific failure; current cp315 optional resolution was not retried.
- No complete optional package installation, document parsing, model inference, full non-host tree, native/candidate/host canary or release qualification was run locally for this CI-only patch. The complete existing CI lane remains responsible for those applicable checks.

## 阻塞

No local implementation or targeted-test blocker remains. No push, issue, PR or comment was performed.

## Retained raw local evidence

Full logs remain at the following local paths; the source-linked excerpts above are committed with this plan. These local paths are for handoff and are not portable artifacts.

- `/tmp/arw-ci-python-compat-20261023-ci-failure.log` — SHA-256 `837b722f4ea839829a8753867e59ed54628b7bf3b57f20d877de16dc25c9ac64`
- `/tmp/arw-ci-python-compat-20261023-ci-run.json` — SHA-256 `c430df53ad9005707e1820dcc33ee641e6c046b0dd768109df2b1063bee35347`
- `/tmp/arw-ci-python-compat-20261023-failed-workflow.yml` — SHA-256 `b88188f97b63801dcec7a2247223cc7a7c0de5ba300ffa69fca1afaa2387493e`
- `/tmp/arw-ci-python-compat-20261023-red.log` — SHA-256 `7e706e693ac00463cf4558485b8c849fb1a58dfbbec63b8e4ab8ee7834db0a18`
- `/tmp/arw-ci-python-compat-20261023-green.log` — SHA-256 `0c297ca69bbde8696f2cea84d560ed10feb04e5ca268d84fcfefe5d92006b628`
- `/tmp/arw-ci-python-compat-20261023-cp314-resolution.log` — SHA-256 `1dc071a9ad7c4a5d4bc919079d5414f3d1443981e1b746a11e9af82478e02e19`
- `/tmp/arw-ci-python-compat-20261023-core-install.log` — SHA-256 `ac51d8b5620b4f02045e42ef0e77953c64556a6bf21e525b2f821248b27e14ba`
- `/tmp/arw-ci-python-compat-20261023-clean-core.log` — SHA-256 `fe42aef2f01ee62d2b4d63f28db704c5569106d439ce79ba6286acbb0302613c`
- `/tmp/arw-ci-python-compat-20261023-clean-core-final.log` — SHA-256 `deee0bd30636aa3dfa50d8a1e4d7c3a2ee78297cbfb2598f4facc7446677d811`
- `/tmp/arw-ci-python-compat-20261023-interpreters.log` — SHA-256 `ee5bdc2a2d66dd01b3de935b9b5684b31cd182d6f8ede2b974e67552b195f772`

## Revalidation and latest-interpreter repair — 2026-11-10

Reviewed remote #177 head `cff4b7642f3d7672f4fd6ba45932a8546529d5ec`
against its explicit #170 base `3cb8651a9dfaadbf7a075da343ae4c93d1791ba6`.
Main was still `c8760e03df9843a69b68141f1e15a0dbf397a768`, already an ancestor;
no merge of main or rewrite of the prerequisite stack was needed. No review
comments were present. This repair changes only latest-core interpreter lookup,
its contract regression, and documentation. The full optional environment,
complete test-tree discovery, package metadata and #170 prerequisites are unchanged.

### Historical hosted evidence does not establish current latest-Python coverage

The original [CI run 39922068397](https://github.com/zhangyang-crazy-one/academic-research-workbench/actions/runs/39922068397)
was green on October 23. Its checkout was synthetic merge
`fb89ff132e5ed8300a65753914f4f983c540f841` into #170, not a merge into main.
The [latest-core log](https://github.com/zhangyang-crazy-one/academic-research-workbench/actions/runs/39922068397/job/120309420561)
shows `check-latest: false`, CPython **3.14.8**, and 40 passed.
Thus this green run does not demonstrate CPython 3.15 core execution.

The [full optional job](https://github.com/zhangyang-crazy-one/academic-research-workbench/actions/runs/39922068397/job/120311259387)
also used CPython 3.14.8 and installed `knowledge-storm==1.1.1`,
`litellm==1.80.0` and `fastuuid==0.14.0`. Its recorded results were:

- Source verification: 4 passed, 1 skipped.
- Compatibility baseline: 74 passed, 3 skipped.
- Complete non-host tree: 2731 passed, 95 skipped, 80 deselected.
- Bundled ARS self-tests: 10106 passed, 2 skipped, 430 subtests passed.

These are historical observations of that exact stack, not fresh evidence for
newly resolved dependencies, a revised head, or the current newest interpreter.

### Repair and local regression results

Enable `check-latest: true` only in `python-core-latest`; `3.x` continues to
exclude prereleases by default. A new regression requires that setting, rejects
conditional or error-tolerant core steps, preserves isolated/offline test
execution, and prohibits the PyO3 forward-compatibility bypass in the workflow.
The regression failed before the workflow edit: **1 failed, 3 passed**, with
`check-latest` absent. It passed after the edit.

In a new isolated core+dev environment on existing **CPython 3.13.5**:

```text
tests/unit/test_ci_python_compatibility.py
tests/unit/test_ci_test_discovery.py
tests/unit/test_ci_native_sanitizer_workflow.py
tests/unit/test_ci_release_native_qualification.py
tests/unit/test_release_workflow_contract.py
tests/unit/test_canonical.py
tests/unit/test_manifests.py
tests/unit/test_recovery_scan.py
tests/unit/test_platform_support.py

98 passed in 5.61s
```

The actual latest-core command was extracted from workflow YAML and executed
with its declared environment: **41 passed**. The import probe identified this
worktree's `src/arw/kernel/core/canonical.py`; `torch`, `docling`,
`knowledge-storm`, `sentence-transformers`, and `fastuuid` were absent.
CI-scoped Ruff lint, Ruff format-check and `git diff --check` passed after
formatting the new test.

An independent temporary worktree applied only the original #177 commit to
main, excluding #170: the same original focused set passed **97 tests** on
3.13.5. This proves that the lane-separation patch applies cleanly and its
focused regressions do not depend on #170. It does not qualify source
verification without #170: the unstacked Python job still lacks the pinned
receipt restoration and the source-verification test still lacks its required
retained native/notice prerequisites. No hosted unstacked run was triggered.

### Remaining limits and handoff

- No local Python 3.14 or 3.15 execution was available. A fresh exact-head hosted
  run must establish the selected latest version and its real installation and
  test result. No updated hosted result is claimed here.
- An exploratory resolver check with source builds disabled was too strict for
  these declarations: target-3.15 core needs a PyYAML source build, and the
  target-3.14 optional scope includes source-only `wikipedia==1.4.0`. These checks
  are not equivalent to the normal CI installer and are not CI-failure evidence.
  No new complete optional installation or execution was performed locally.
- Local source-materialization tests reported **1 passed, 4 skipped** because
  this clean worktree has no materialized snapshots, retained native evidence,
  or usable strace/ptrace confinement. No source/native qualification is claimed.
- The OpenSpec CLI was unavailable in this environment, so the prior strict
  validation result above does not cover these documentation edits.
- #170 remains a separate prerequisite review and integration decision. This
  repair neither merges it nor silently incorporates additional #170 changes.
- No remote publication, branch retargeting, CI rerun, or merge was performed.

Local logs are retained under `/workspace/shared/arw-ci-177-evidence/`, including
`red.log`, `targeted-final-cp313.log`, and `without-170-cp313.log`.
