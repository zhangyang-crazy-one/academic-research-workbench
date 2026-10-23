# Verification: issue #39 / F05 correction (2026-10-23)

**已验证**: converter-double structure mapping; exact UTF-8 locators; source-derived normalized bboxes and table/reference text; verified asset inventory; configuration/model digest changes; historical v1 decoding; real subprocess resource limits/offline flags/credential omission, running-parser timeout termination and output cap; CLI manifest identity/idempotency; existing parent artifact admission and tamper rejection.

**未验证**: real Docling package and verified model assets, real GROBID service, original Chinese/English/two-column/table/scanned-paper matrix, resolved optional dependency/model license inventory. Runtime probing returned `None` for `importlib.util.find_spec("docling")`. No models were downloaded and no model license or real-PDF evidence was fabricated.

Initial TDD: four new tests failed against the original implementation (Markdown-only behavior, unverified asset use, missing receipt identities). The isolated-process tests then failed because `extract_pdf_isolated` did not exist. A real child test exposed Python's ignored SIGXFSZ; restoring its default termination made output-limit failure explicit.

Final commands/outcomes are recorded below after execution. See `docs/verification/issue-39-pdf-structure-boundary.md` for exact supported/unsupported behavior and upstream API references. This correction does not promote historical mocks into real-provider qualification or archive the still unqualified acceptance work.


## Final recorded commands

`ARW_TEST_PYTHON` was set to the existing main-checkout virtualenv interpreter; no environment/key files were read. Commands ran from this repair checkout, using its own source:

```bash
PYTHONPATH="$PWD/src" "$ARW_TEST_PYTHON" -m pytest tests/unit/test_pdf_extraction.py tests/unit/test_pdf_structure_boundary.py tests/integration/test_scholarly_cli.py tests/integration/test_precise_source_locators.py -q
```

Output: `55 passed` (includes locally generated pypdf fixtures, converter doubles and a fake Docling-shaped SDK inside the actual CLI child).

```bash
ruff check src/arw/pdf_extraction.py src/arw/cli_scholarly.py tests/unit/test_pdf_extraction.py tests/unit/test_pdf_structure_boundary.py tests/integration/test_scholarly_cli.py
```

Output: `All checks passed!`

```bash
git diff --check
openspec validate scholarly-pdf-extraction-locators --strict
```

Outputs: no whitespace errors; `Change 'scholarly-pdf-extraction-locators' is valid`.

Historical v1 manifest output is checked byte-for-byte after publishing configuration/model variants. The fake-SDK CLI case verifies that published receipts contain neither the selected model directory nor the model filename. The worker real-child case observes the installed rlimits, offline flags and omitted test-secret environment variable. No native-library network or filesystem confinement is claimed.
