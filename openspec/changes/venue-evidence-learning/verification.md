# Verification

The implementation passed focused synthetic tests for reviewed source binding, duplicate DOI/URL/source hash rejection, metadata-only limits, exact independent sample subsets, counterexample handling, explicit qualification and promotion, legacy-profile migration, rebuild, historical narrative-bound outcome observation, and read-only promoted Phase 2 advice. The historical learning event golden remained byte identical. Run the affected suite with the project interpreter and the optional learning extension on `PYTHONPATH`:

```bash
PYTHONPATH=src:extensions/research-learning/src python -m pytest -q tests/integration/test_research_learning.py tests/unit/test_venue_learning.py tests/compat/test_research_learning_events.py tests/schema/test_schema_drift.py
```

The published source accepts caller-supplied reviewed source records and bounded PDF provenance declarations. Callers must independently verify transient PDF bytes, size, digest, and page count before admission; the published product validates retained capsule/review/exemplar bindings and declared provenance, and cannot reverify absent PDF bytes. Synthetic engineering checks cover source-version declarations, candidate evaluation, unpromoted advice exclusion, disposable-index reconstruction, and optional public-source fit replay. These checks do not approve a scientific finding, promote a heuristic, establish venue rules, or create a selected author narrative. Research source records and local execution receipts are retained outside this source publication.

Final affected engineering tests passed for venue unit/integration, selected/public fit, learning compatibility, and schema drift. Ruff and strict OpenSpec validation passed. The final new models and producer scripts had zero Pyright errors; existing diagnostics in the research-learning service were unchanged by this work.
