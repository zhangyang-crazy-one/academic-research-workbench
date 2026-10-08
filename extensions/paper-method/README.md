# Opt-in Gale–Shapley paper method

This extension independently implements deferred acceptance from D. Gale and
L. S. Shapley, *College Admissions and the Stability of Marriage* (1962),
DOI `10.1080/00029890.1962.11989827`. The method is in the Theorem 1 proof
on printed pages 12–13. The authors' Example 2 on printed page 12 supplies
the factual four-by-four reference matching in `fixtures/example-2.json`.
The reviewed PDF SHA-256 is recorded in the fixture and source capsule; no
paper PDF, prose, or third-party implementation is redistributed.

The adapter supports equal-sized sets of 1–64 distinct named participants,
strict complete preference permutations, and no ties. It does not handle
quotas, incomplete lists, roommates or practical-market suitability. The
algorithm is deterministic and uses at most `n²` proposals. MCP input frames
are capped at 64 KiB by the shared transport; method input at 60 KiB, method
output at 32 KiB and each execution at 2 seconds. A timeout or isolation
failure is typed and does not become a scientific admission or ledger event.

The extension is absent from the base wheel package list and default MCP
configuration. Source-checkout use is explicit. `source-capsule.json` binds
the paper locator and PDF digest, first-party source commit and byte hashes,
input/output schemas, empty dependency inventory and execution contract. A
local, create-only receipt binds actual host environment and seven sandbox
tests. Server startup **reruns** the tests before listing the tool; source,
metadata, receipt or environment drift hides it. `status` preserves the gate
diagnostic. An asserted PASS field alone cannot enable the tool.

For the current checkout, use a Python environment with the already-declared
ARW dependencies and a functioning Linux `bwrap` installation. No install,
model or network call is performed by these commands:

```bash
PATH=/path/to/venv/bin:$PATH scripts/arw-paper-method qualify --receipt /tmp/arw-paper-method-receipt.json
PATH=/path/to/venv/bin:$PATH scripts/arw-paper-method status --receipt /tmp/arw-paper-method-receipt.json
PATH=/path/to/venv/bin:$PATH scripts/arw-paper-method serve --receipt /tmp/arw-paper-method-receipt.json
```

Point an MCP client to `serve` only after reviewing `status` and the receipt;
do not add it to user configuration automatically. The worker receives only
bounded stdin and a read-only method file inside a `bwrap` namespace that
mounts the system Python standard library read-only, has an ephemeral tmpfs,
no home mount, a clean environment and a separate network namespace. The
MCP host process is outside this worker sandbox. On hosts without this
isolation, qualification fails closed. `scripts/offline-exec` additionally
requires `strace`; when unavailable, this extension's narrower `bwrap`
isolation is used and verified through distinct network namespace IDs.

The tool's `mode: "plan"` returns `planned` with `execution_observed: false`
and no output digest. Default `execute` returns `executed` with input and
worker-output digests, or a typed `failed` status. These records can be
submitted to a parent workflow for its own acceptance decision; this server
never accepts scientific evidence or writes a parent journal.
