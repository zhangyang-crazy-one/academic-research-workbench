# ARW v2 Invariants

This document enumerates the invariants that every v2 change (see
`openspec/V2-ROADMAP.md`) must preserve. Each invariant is enforced by the
compatibility baseline in `tests/compat/`, gated by the `v2_compat` pytest
marker:

```bash
uv run pytest -m v2_compat
```

A v2 PR may not merge while `pytest -m v2_compat` is red, and may not weaken a
fixture to make it pass — fixture changes require an explicit, reviewed
amendment to this document.

## I1 — The append-only ledger is the only canonical state

The journal (`events.jsonl`) and immutable manifests remain the authoritative
record. No projection, index, graph store, or external tool state may
authorize a state transition. Enforced by: golden replay fixtures
(`test_replay_golden.py`) pinning the reduced-state digest, event count, and
rejection behavior.

## I2 — Replay determinism

Replaying the same canonical event bytes produces the same state digest on
every run, on every supported Python (3.13 and 3.14), regardless of wall
clock, process identity, or filesystem location. Enforced by:
`test_replay_digest_is_repeat_stable` and the pinned `replay_digest.json`.

## I3 — CLI contract stability

The v1 command tree (commands, flags, choice sets, defaults), exit codes, and
output structure are pinned in `tests/compat/cli_contract.json` plus golden
command transcripts. v2 may add commands; it may not remove or alter v1
surface without a contract amendment.

Success-path pinning is layered: golden transcripts cover the nine lifecycle
commands exercised by the full lifecycle stream (init, transition,
decision-request, attempt-start, artifact-accept, attempt-close,
decision-resolve, checkpoint, resume) plus `append`, `replay`, and `status`;
the shared missing-request error envelope (exit 65) is pinned for every
`--request` command including nested `files extraction register`.
Orchestration command success paths are pinned by the dedicated Phase-4
integration suites (`test_orchestration_lifecycle.py` et al.), which run in
the same CI job. Enforced by: `test_cli_contract.py`, `test_replay_golden.py`.

## I4 — File-plane MCP contract stability

The read-only tool set (`list_files`, `read_file`, `search_files`,
`get_outline`, `get_context`), input schemas, JSON-RPC response envelopes
(id echo, `jsonrpc`, `isError`), and the discriminated error/status taxonomy
(`unknown_tool`, `invalid_request`, `root_denied`, `identity_mismatch`,
`invalid_utf8`/`encoding_error`, `anchor_out_of_range`, `degraded`,
`no_structure`) are pinned against the pure-Python read-only profile. The
vendored file-base native binary's surface (protocol `2025-11-25`, tool names,
descriptions, input schemas) is pinned separately in
`test_filebase_mcp_contract.py`; its behavioral confinement and security
branches are pinned by `test_mcp_confinement.py` and `test_files_security.py`,
During migration, both providers must satisfy
their respective frozen surfaces. PR CI runs the `v2_compat` marker plus the
license gate; the native-binary-dependent suites (native surface, confinement,
file security) require the pinned C toolchain and run in the local
qualification flow (`scripts/verify-phase-*`), matching release.yml — PR CI
deliberately does not rebuild the binary (a clean-runner build would
rebaseline `vendor/source-manifest.json` with toolchain-drifted hashes).

Note on the seven-tool research contract (`list_files`, `read_file`,
`search_files`, `get_file_outline`, `get_file_context`,
`ingest_research_manifest`, `sync_research_run`): that is the v2 TARGET
surface for the FileProvider port, not a v1 reality — neither the five-tool
Python read-only profile nor the pinned native graph-profile binary
implements it today. This baseline therefore freezes actual v1 behavior; the
seven-tool contract is introduced and pinned by the `ports-and-adapters`
change, at which point this section's fixtures extend to cover it.

## I5 — Projection rebuildability

Graph projections are disposable: deleting and rebuilding from canonical
evidence reproduces the pinned projection digest byte-identically. A checksum
or digest mismatch is an audit fault, never silent data loss. Enforced by:
`test_projection_equivalence.py`.

## I6 — Allowed-root confinement and bounded reads

File access remains restricted to registered roots with canonical-path and
symlink-escape rejection, byte/line/result/depth/timeout caps, and opaque
cursor pagination. The confinement posture is pinned by the error-taxonomy
goldens and the v1 confinement suites (`tests/integration/test_mcp_confinement.py`,
`test_files_security.py`), which v2 must keep green.

## I7 — Fail-closed license and qualification behavior

Source identity, digest pins, license classification (including CC BY-NC 4.0
duties for ARS and experiment-agent), and integration-lock verification remain
fail-closed: an unresolved or incompatible classification blocks
qualification. Refactors must not weaken these gates to reduce repository
size or dependency count.

## Fixture normalization policy

Goldens pin structure, not prose: timestamps (`<TS>`), absolute paths
(`<RUN_ROOT>`, `<TMP_PATH>`), and environment-specific digests
(`<SCRUBBED>` for live-vs-indexed digest echoes) are normalized. Command
shape, exit codes, error codes, event bytes, and canonical digests are pinned
exactly.

## Regenerating goldens

Goldens are regenerated only by a deliberate, reviewed contract amendment —
never to silence a failure. The procedure is self-contained in this
repository (planning artifacts under `openspec/changes/` are intentionally
local-only and are not required for regeneration):

1. Reproduce the failure and confirm the change is an intended contract
   amendment, not a regression. Record the rationale in the PR description.
2. Regenerate only the affected golden files by re-running the exact
   scenarios the tests assert (each test module's docstring names its
   scenario set; the goldens under `tests/compat/golden/` are plain
   canonical JSON):
   - CLI transcripts: run the command sequence from
     `test_cli_contract.py` against a fresh recovery-seed run root,
     normalize timestamps/paths via `tests/compat/normalize.py`.
   - MCP surfaces: re-drive the seeded corpus from
     `test_mcp_contract.py::_prepare` (pure-Python server) or the
     confinement fixture root against `.file-base/bin/file-base`
     (`test_filebase_mcp_contract.py`), scrubbing only the fields named in
     the module docstrings (`hit_id`, `message`).
   - Replay/projection digests: rebuild from the recovery seed and the
     Phase-5 fixture records; recompute the pinned SHA-256 values.
3. Review the golden diff line-by-line in the PR. A golden change without a
   corresponding, explained production change is a red flag.
4. Re-run `uv run pytest -m v2_compat` plus the confinement and
   file-security suites before merge.
