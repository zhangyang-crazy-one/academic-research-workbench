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
