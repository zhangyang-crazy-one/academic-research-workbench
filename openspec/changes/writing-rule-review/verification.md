# Verification

- `PYTHONPATH=src:extensions/academic-humanization/src /home/zhangyangrui/my_programes/academic-research-workbench/.venv/bin/python -m pytest tests/integration/test_writing_review_rules.py tests/integration/test_writing.py tests/integration/test_writing_detection.py tests/unit/test_writing_fact_audit.py tests/unit/test_capability_activation.py tests/compat/test_kernel_dependency_direction.py -q`: **52 passed, 1 skipped in 3.63s**. The skipped existing HTTP integration is `tests/integration/test_writing_detection.py:265`, because this sandbox denies loopback sockets. The new CLI prepare, exact source/candidate/plan binding, review report retention, stale/span/empty field rejection, and legacy `not_run` cases passed.
- The parent reran only `tests/integration/test_writing_detection.py::test_http_requires_opt_in_and_rejects_redirect_and_mismatch` with authorized local loopback access: **1 passed in 0.86s**. This was a separate run, not part of the 52-pass run.
- `ruff check extensions/academic-humanization/src/arw_writing/review_rules.py extensions/academic-humanization/src/arw_writing/transformer.py extensions/academic-humanization/src/arw_writing/service.py tests/integration/test_writing_review_rules.py`: passed.
- `ruff format --check` on the same four Python files: passed.
- `pyright -p /tmp/arw-review-pyrightconfig.json extensions/academic-humanization/src/arw_writing/review_rules.py extensions/academic-humanization/src/arw_writing/transformer.py`: **0 errors**, using the existing project virtual environment read-only. The wider service module has existing ledger event union narrowing errors, so no full-service typecheck claim is made.
- `openspec validate writing-rule-review --strict`: passed.
- `git diff --check`: passed.

No language model reviewer or private manuscript was run through these tests. The reviewer identity in integration tests is explicitly a public synthetic fixture.
