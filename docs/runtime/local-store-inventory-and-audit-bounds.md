# Local-store inventory and audit bounds

The production files adapter binds each read snapshot to a fingerprint derived
from `load_query_generation` and its verified canonical database. Changes to
cache rows or trigram row multiplicities are rejected even when generation
metadata remains unchanged. Canonical anchor failures reject adapter startup;
legacy adapters without a canonical root retain their existing behavior.

All five file operations validate the inventory inside the same read transaction
used by the operation. Fingerprints include typed, length-framed values, so NULL,
empty text, and numeric values cannot silently substitute for one another.

The request deadline covers Python fingerprinting and SQLite inventory/FTS work.
The inventory checks enforce a 100 MiB per-value ceiling, a 200 MiB + 1 KiB framed
row ceiling, and a 256 MiB aggregate ceiling. SQLite byte-length preflight rejects
oversized stored values before decoding their text in Python. Canonical folding
is additionally checked after normalization. Corpus sizes beyond these limits
return a typed fault; successful ingestion alone does not guarantee queryability.
FTS comparison returns only an existence marker, never a list of differing bodies.

Audit receipt loading defaults to a 256 KiB aggregate UTF-8 output budget,
including every retained fault field. Oversized output returns a deterministic
`audit_receipt_output_truncated` marker within that budget. Malformed receipts,
large receipt identifiers, Unicode, and early directory errors use the same
budget. Reading does not alter persisted receipts.

`arw status` also uses the existing read-only journal lock path. A damaged run
without a lock is rejected without creating `.journal.lock`; writers retain the
existing lock creation behavior.

## Verification

On 2026-09-08, the broad unit/integration/compatibility run returned 1080 passed,
7 failed and 1 skipped. Three failures (license export and offline namespace
checks) passed when rerun outside the filesystem/network sandbox. The status
read-side mutation was fixed and the remaining installed-version/Phase 1 checks
passed in the final targeted rerun (141 passed in 92.96 seconds, including
compatibility, schema, inventory, audit budgets and status). Together with the
three sandbox-external checks (3 passed in 92.70 seconds), every initial failure
has a passing rerun. The skipped installed research
journey requires retained exact host qualification evidence, which is absent.

OpenSpec strict validation passed all 12 items. Ruff passed for the inventory
module, audit receipt module and new budget tests; `git diff --check` passed.
The OpenSpec contract is in `openspec/specs/sqlite-projection-store/spec.md`;
this checkout ignores the `openspec/` tree, so this tracked runtime document also
records the implemented contract for review.

Commands (serial; the shared pytest temporary root must not be used concurrently):

```sh
.venv/bin/pytest tests/unit tests/integration tests/compat -q -m 'not codex_host'
.venv/bin/pytest tests/integration/test_license_gate.py::test_post_materialization_gate_preserves_native_toolchain_and_receipt tests/integration/test_source_materialization.py::test_network_denied_verification_retains_namespace_and_syscall_evidence tests/integration/test_source_materialization.py::test_offline_runner_rejects_network_capable_commands -q
.venv/bin/pytest tests/integration/test_phase1_walking_skeleton.py tests/integration/test_version_report.py tests/integration/test_runtime_status.py tests/integration/test_files_store_inventory_binding.py tests/unit/test_audit_receipt_budget.py tests/unit/test_inventory_budgets.py tests/compat tests/schema -q
openspec validate --all --strict --no-interactive
```
