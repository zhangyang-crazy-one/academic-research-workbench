# Qualified research artifact pipeline

The two-kind MVP provides deterministic SVG compilation from a typed IR, accepted
source bindings, five independent validation levels, immutable qualification
receipts, parent-owned acceptance and supersession events, exact reproduction,
and authorized body tombstones. It adds no graph server, model or rasterization
dependency.

The complete contract and executable example are in
`extensions/research-artifact/README.md`, `CONTRACT-INVENTORY.md`, and
`examples/compile_workflow.py`. Run the example with a fresh output directory:

```sh
uv run --frozen python extensions/research-artifact/examples/compile_workflow.py build/artifact-example
```

The example is explicitly exploratory: source, semantic and render checks pass;
visual review is OPTIONAL_SKIPPED. A publication-critical figure requires a
separately accepted, exact-output-bound review and cannot use this example as
publication approval. The bilingual example was exported and visually inspected
locally; deterministic SVG reproduction passed. That observation is separate
from the example's recorded qualification policy.

## Acceptance evidence

- `tests/integration/test_research_artifacts.py`: both supported IR kinds;
  parent acceptance, CLI inspect/reproduce, deterministic source rendering,
  missing/malformed bindings, stronger confidence and causal wording, caption
  and manuscript/value drift, publication-required missing review, simulated
  review identity binding, renderer substitution, secret rejection, immutable
  supersession, concurrent retries, actual SIGKILL at three durability points,
  missing binding diagnosis/repair, and explicit tombstone retention.
- `tests/compat/test_research_artifact_events.py`: byte-stable old/new event
  replay including supersession, reader migration, and generated schema drift.
- `tests/compat/test_kernel_dependency_direction.py`: no renderer dependency in
  the kernel; existing subpackage dependency ratchet remains unchanged.
- Unit + artifact + local-store knowledge regression: 629 passed.
- Frozen-environment compatibility + artifact regression: 90 passed after the
  final renderer table pin; the external-table fixture and final lifecycle guard
  passed in the final focused rerun: 35 tests passed.

## Reader migration

Migration 0001 registers new artifact event families at envelope version 1.1.0.
Version 1.0.0 events retain their exact bytes and hashes. The reader registry is
core code and remains available when the optional renderer extension is disabled.
There is no historical JSON journal rewrite. The existing numbered SQLite
migration helper is reused only for the disposable source projection, not to
mutate canonical history.
