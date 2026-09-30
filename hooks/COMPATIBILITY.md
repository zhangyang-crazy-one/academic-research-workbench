# Codex hook input compatibility

The adapter recognizes `SessionStart`, `SubagentStop`, and `Stop`. Each event
must include all of its required fields with the existing type, length, and NUL
checks. Unsupported event names, malformed JSON, duplicate keys, and input
larger than 64 KiB fail closed.

Additional top-level fields are accepted as observations. Their values are
discarded. Receipts retain only the first 32 sorted, unique eligible field
names: each name must be nonempty UTF-8, at most 128 encoded bytes, and contain
no NUL. The input SHA-256 still binds the complete raw event. Known permission
modes are retained; a new well-formed mode is represented by
`permission_mode: null` and `permission_mode_unrecognized: true`. Its value is
not retained. Malformed modes fail closed.

Receipts live under `PLUGIN_DATA/hook-observations/v1` and remain observational.
The parent validates their content hash, filename, definition binding, bounded
metadata, and parent-control list. Hook observations cannot change canonical
run state or admit research evidence.

The hook contract tests run captured `SessionStart`, `SubagentStop`, and `Stop`
stdin from real Codex hosts at versions 0.144.4, 0.147.0, and 0.156.1. All
nine event/version combinations have verified real-host captures, leaving no
evidence gap for these versions. Each version's fixture README records the host
invocation and original stdin SHA-256. The JSON files add one terminal newline
for storage; golden tests remove only that newline, verify the original digest,
run the hook, and load its receipt through the parent consumer. Synthetic inputs
remain separately identified in the tests.

Retained receipts from the pre-change v1 adapter remain readable through an
explicit legacy decoder. It accepts only the old exact field set and verifies
the original canonical bytes, unsigned receipt hash, filename, and definition
binding. It does not add new metadata to or rewrite an old receipt. The
`tests/fixtures/hooks/legacy-v1/` sample was emitted by the pre-change hook
from repository `HEAD` and exercises this upgrade path.

## Supply-chain review and fingerprint refresh

The audited handler is the unchanged `hooks/arw_hook.py` from commit
`9a1053d88fb9a019fc069df70cfc445dde4e436c` (issue #28). The evidence refresh
on 2026-09-30 reviewed its diff and the corresponding parent receipt decoder.
Required event fields retain their type, UTF-8 byte-length and NUL checks;
unsupported events, duplicate keys, malformed JSON and oversized inputs still
fail closed. Additive values are discarded, eligible names are sorted and
limited to 32, and unknown well-formed permission modes are redacted. Receipts
remain observational; the parent checks exact current/legacy field shapes,
canonical bytes, unsigned hashes, filename, definition binding and metadata
bounds. The refresh changes no hook runtime behavior or validation policy.

Independently measured with CPython 3.13.5 and CPython 3.14.7:

- Handler byte SHA-256 (SBOM):
  `9176bb1d874344556aed0c1e46e5666a750a638a691c056c182d23d1b89df81e`
- AST SHA-256 on each interpreter:
  `bd5d9841b584ad653ebc0890f8f25d01848a78be2d34e7978b747e811218236f`
- Each canonical AST dump contains 41,317 characters

To reproduce, run this separately with each supported Python minor from the
repository root. It reads and parses the handler without importing or executing it:

```python
import ast
import hashlib
from pathlib import Path
import sys

path = Path("hooks/arw_hook.py")
dump = ast.dump(
    ast.parse(path.read_text(encoding="utf-8"), filename="hooks/arw_hook.py"),
    include_attributes=False,
    annotate_fields=True,
)
print(sys.version)
print("bytes:", hashlib.sha256(path.read_bytes()).hexdigest())
print("AST:", len(dump), hashlib.sha256(dump.encode("utf-8")).hexdigest())
```

For future changes, review the executable diff and parent-consumer contract
before refreshing the SBOM row and per-minor AST constants. Do not derive an
allowlist value automatically at gate runtime or assume another minor has the
same AST. Run `tests/unit/test_hook_contracts.py` and
`skills/academic-research-suite/codex/tests/test_root_hook_ast_policy.py` on each
supported minor. These cover real-host and legacy receipts, malformed inputs,
additive-field guards, rebound-SBOM executable mutations, unsupported minors,
and the checked-in evidence without test-side digest rebinding.
