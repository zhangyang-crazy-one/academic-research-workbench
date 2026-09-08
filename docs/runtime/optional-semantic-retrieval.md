# Optional semantic retrieval acceptance

The semantic extra provides explicit, offline-capable retrieval over selected
accepted text artifacts. A pinned model and real sqlite-vec engine produce a
rebuildable projection; source hashes and model identity are checked again on
queries. Lexical and graph rankings compose through accepted artifact IDs.

See [the operator guide](../../extensions/local-store/SEMANTIC.md) and
[standalone paper-source selection example](../../extensions/local-store/examples/semantic_literature.py).
The latter verifies an offline synonym query, deletion/rebuild equivalence and
an accepted fixture author-choice record without claiming research improvement.

`tests/integration/test_semantic_retrieval.py` covers the real engine, optional
absence, prior store migration, model digest/version drift, changed sources,
read-only query behavior, backend failures, SQL rollback after vector replacement,
CLI commands, fusion boundaries and unsafe paths. Existing compatibility and
local-store suites verify the additive store schema migration.

`sqlite-vec==0.1.9` is an optional MIT OR Apache-2.0 dependency recorded in the
lockfile and SBOM. It is not bundled into the base installed wheelhouse. The base
plugin remains usable without semantic retrieval; operators provision the extra
in their runtime explicitly. No model is bundled, and full GraphRAG is deferred.
