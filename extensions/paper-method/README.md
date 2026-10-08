# Opt-in Gale–Shapley paper method

This extension independently implements deferred acceptance from D. Gale and
L. S. Shapley, *College Admissions and the Stability of Marriage* (1962),
DOI `10.1080/00029890.1962.11989827`. The method is in the Theorem 1 proof
on printed pages 12–13. The authors' Example 2 on printed page 12 supplies
the factual four-by-four reference matching in `fixtures/example-2.json`.
The reviewed PDF SHA-256 is recorded in the fixture and source capsule; no
paper PDF, prose, or third-party implementation is redistributed. The fixture
contains mathematical preferences and matching facts with attribution. The
adapter adds no third-party software dependency or additional license grant;
the repository retains its component-scoped license policy.

The adapter supports equal-sized sets of 1–64 distinct named participants,
strict complete preference permutations, and no ties. It does not handle
quotas, incomplete lists, roommates or practical-market suitability. The
algorithm is deterministic and uses at most `n²` proposals. MCP input frames
are capped at 64 KiB by the shared transport; method input at 60 KiB, method
output at 32 KiB and each execution at 2 seconds. A timeout or isolation
failure is typed and does not become a scientific admission or ledger event.

The extension is absent from the base wheel package list and default MCP
configuration. Both source-checkout use and installation are explicit.
`source-capsule.json` binds
the paper locator and PDF digest, first-party source commit and byte hashes,
input/output schemas, empty dependency inventory and execution contract. A
local, create-only receipt binds actual host environment and eight sandbox
tests. Server startup **reruns** the tests before listing the tool; source,
metadata, receipt or environment drift hides it. `status` preserves the gate
diagnostic. An asserted PASS field alone cannot enable the tool.

This adapter and its copied shared transport use only the Python standard
library. A functioning Linux `/usr/bin/bwrap` and `/usr/bin/python3` (3.13 or
newer) are required; no Python package or third-party algorithm is installed.
To create a separate, relocatable opt-in directory from the verified checkout:

```bash
PATH=/usr/bin:/bin scripts/arw-paper-method install --destination /path/to/new/paper-method
/path/to/new/paper-method/bin/arw-paper-method qualify --receipt /path/to/new/paper-method/qualification.json
/path/to/new/paper-method/bin/arw-paper-method status --receipt /path/to/new/paper-method/qualification.json
/path/to/new/paper-method/bin/arw-paper-method serve --receipt /path/to/new/paper-method/qualification.json
```

The destination's parent must exist; the directory and receipts are create-only.
The installation contains only this extension, the existing shared transport
and its standard-library canonical JSON helper. It includes a file-hash
manifest and Git commit/tree witnesses verified against every pinned file blob.
Installed qualification requires neither Git nor the original checkout and
uses Python `-S` to exclude site packages. Receipts are not bundled; qualify
again on the actual execution host. Moving the directory is supported.

For offline distribution, create a ZIP of the same materialized tree, without
a qualification receipt:

```bash
PATH=/usr/bin:/bin scripts/arw-paper-method package --destination /path/to/new/paper-method.zip
```

Extract with a tool that preserves
executable permissions, such as `unzip`, then run `bin/arw-paper-method qualify`.
For checkout use, replace the installed entry point with
`PATH=/usr/bin:/bin scripts/arw-paper-method` in the last three commands.

Point an MCP client to `serve` only after reviewing `status` and the receipt;
do not add it to user configuration automatically. The worker receives only
bounded stdin and a read-only method file inside a `bwrap` namespace that
mounts the root and system Python standard library read-only, has a writable
`/tmp` tmpfs,
no home mount, a clean environment and a separate network namespace. The
MCP host process is outside this worker sandbox. On hosts without this
isolation, qualification fails closed. `scripts/offline-exec` additionally
requires `strace` and can wrap `qualify` to retain a network-syscall audit.
The per-execution worker always uses the narrower `bwrap` isolation and
checks distinct network namespace IDs during qualification. The host MCP
process and installation step are outside the worker sandbox.

The tool's `mode: "plan"` returns `planned` with `execution_observed: false`
and no output digest. Default `execute` returns `executed` with input and
worker-output digests, or a typed `failed` status. These records can be
submitted to a parent workflow for its own acceptance decision; this server
never accepts scientific evidence or writes a parent journal.

Local evidence: source commit `4155437` is pinned in the current capsule.
On Linux x86_64, system Python 3.14.6 and the recorded `bwrap` binary, the
eight qualification cases and `scripts/offline-exec` strace audit passed
without sudo. The audit retained no INET syscall attempts. The targeted
paper-method and shared-transport suites passed **67 tests**, including a
relocated installation launched without site packages, missing receipt,
source/receipt/environment/proof tampering, read-only/credential boundaries,
injected failure, plans and both MCP protocol eras. An actual base wheel was built and inspected: its 164
members contained no `arw_paper_method`. See `evidence/local-verification.json`
and `evidence/offline-exec/`; the original `8d28edf` capsule and receipt are
preserved separately as historical evidence. The `783b209` receipt is also
preserved and superseded by the read-only-root correction; only the current
root-level capsule and receipt are candidates for the publication gate.
These results qualify this host and narrow method domain; unsupported hosts fail closed.
