# Independent CPU scoring pilot

This opt-in pilot reuses the existing three original CPU tasks, public-input
export, numeric scorer, receipt replay, and all-attempt denominator. It does
not change research-direction admission: `held_out` there still means a
hash/declaration, not proof that this runner was used. It does not run a model,
add a new benchmark, publish results, or promote a heuristic.

## Protocol

The candidate is one Python standard-library script. It receives one filename
as argv[1], containing the existing public JSON, and writes exactly
`{"selected_config": "0000", "responses": [{"config": "0000", "value": 0}, ...]}`
to stdout, with all 16 unique configurations. Values must be finite numbers
with absolute magnitude at most `1e100`; this limit is frozen and keeps host
scoring arithmetic bounded. Nested structures, oversized integers, overflowing
numbers and excessively deep JSON invalidate only their submitted slot, while
the original stdout and elapsed cost remain retained. Metadata, scorer choice, file paths,
reported costs, and PASS strings are not accepted from the candidate. The
provided public-mean script is a deliberately weak plumbing example, not a
competitive method or a scientific finding.

From the repository with its normal dependencies available:

```bash
python -m evals.experiment_understanding.independent freeze \
  --method evals/experiment_understanding/examples/public_mean.py \
  --output /tmp/cpu-freeze.json
# Retain the printed SHA-256 separately before starting candidate execution.
python -m evals.experiment_understanding.independent run \
  --method evals/experiment_understanding/examples/public_mean.py \
  --freeze /tmp/cpu-freeze.json --freeze-sha256 <retained-digest> \
  --output /tmp/new-cpu-run
```

1. Freeze method bytes, exact per-task public-input bytes, fixture manifest,
   scorer/protocol source and schema identities, required controls and limits.
   Freeze never opens the hidden reference. An operator must retain the freeze
   digest outside candidate control; rewriting the freeze and trust anchor is
   not an adversary this local tool can defend against.
2. Predeclare all three slots. Stage exact method and public bytes, then run
   each candidate in a fresh bubblewrap mount/PID/network namespace. Only
   `/usr`, `/lib`, `/lib64` runtime trees, synthetic `/proc` and `/dev`, two
   read-only input files, and fresh tmpfs `/work` and `/tmp` are visible.
   Python uses `-I -S` to disable inherited Python settings and system site
   initialization hooks. Preflight rejects a checkout, fixture directory or
   hidden-reference file resolving inside any mounted runtime tree, including
   symlink targets. Environment and inherited descriptors are cleared. Host cwd, repository,
   answer files, previous stdout/stderr and resume state are not mounted.
3. Require Linux, bubblewrap and system `/usr/bin/python3`. Namespace failure
   is a failed attempt, **never** an instruction-only fallback. Per-call limits
   are 10 seconds wall time, 5 seconds CPU per process, 512 MiB address space
   per process and 256 KiB per stdout/stderr file. These are not aggregate
   process-tree CPU/memory quotas; use a separately managed container/cgroup
   before running untrusted resource-exhaustion code. Review the mounted system
   runtime trees: do not place answers or credentials in them.
4. Persist the full plan before any launch, retain every started/completed/
   failed attempt, raw outputs and measured wrapper elapsed milliseconds.
   Missing tokens and USD remain `unavailable`, never fabricated zero. An
   interrupted run has its full plan and latest inventory but no completed
   receipt. Output directories cannot be reused; there is no resume facility.
   Ordinary filesystem writes are not a crash-transactional audit ledger.
5. Only after all attempts end and their bundle is written, recheck frozen
   bindings and open the hidden reference. The independent fixed scorer must
   pass all three mandatory controls: exact oracle has zero error, zero-table
   predictions have positive contrast errors, missing predictions have zero
   delivery and null errors. Constant PASS and constant-perfect scorers fail.
   Controls are host-side and are never candidate inputs.
6. Score and replay the original harness receipt; check frozen identities again
   before publication. The receipt binds actual input bytes, all attempts and
   numeric results. `report.json` additionally binds the freeze, controls,
   receipt, logs and execution outcomes. A completed run means valid delivery,
   not high quality. Any failed launch or invalid delivery gives `incomplete`
   and a nonzero CLI exit. Retained receipt replay is the existing
   `arw-experiment-eval verify` command.

## Boundary and acceptance

A successful namespace run enforces filesystem/network isolation **for these
local candidate processes** under the trusted host, kernel and system runtime.
Source digests and controls constrain candidate-dependent scorer changes and
common constant-output faults, but do not make the host/operator untrusted or
prove the scorer's general correctness. They do not attest Python/dependency
binaries, prove the candidate author never saw the committed answers, remove
training-data contamination, or isolate a native model's tools/context. The
existing LIVE-PLAN's native model execution remains a cooperative protocol.
Neither these fixtures nor isolation prove scientific quality or causal insight.

Tests cover freeze/method/scorer tampering, omitted controls, constant-perfect
scoring, rejected candidate scorer/cost fields, failed and interrupted attempt
retention, hidden-read ordering, numerical scoring and replay. The actual
namespace test additionally tries host answer paths, cwd, logs, resume,
environment and network access across two fresh calls. A skipped namespace test
is **not** a passed isolation test. Do not claim this pilot's isolation is
validated until that test runs successfully on the intended host.

The [final hardened-source evidence](evidence/20261110-independent-hardened/README.md)
records a fresh fail-closed host run after parser and runtime-mount fixes, not a
successful isolated candidate trial. The earlier trial remains separately
retained in `evidence/20261110-independent/` for history.
