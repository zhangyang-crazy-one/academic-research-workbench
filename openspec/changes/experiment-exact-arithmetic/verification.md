# Verification

- `PYTHONPATH="$PWD/src:$PWD" /home/zhangyangrui/my_programes/academic-research-workbench/.venv/bin/python -m pytest -q tests/unit/test_experiment_acceptance.py tests/integration/test_submission_acceptance.py tests/integration/test_submission_cli_acceptance.py tests/schema/test_schema_drift.py`: 110 passed.
- `ruff check --select F src/arw/kernel/artifacts/experiment_acceptance.py tests/unit/test_experiment_acceptance.py`: passed.
- `openspec validate experiment-exact-arithmetic --strict`: valid.
- The committed 1.0.0 receipt fixture was produced with `/home/zhangyangrui/my_programes/academic-research-workbench/src/arw` before switching to the worktree's evaluator; digest `ddc7628cf747ccdc9a0bf86e0a20fb1bc7efa5ebd3955599064317605deed4cc` is replayed byte-for-byte.

The wider schema run had one environment-only failure in `test_native_contract_header_is_deterministic_and_checked`: this isolated worktree has no `.venv` directory, which its wrapper script requires. The changed acceptance schema is covered by the passing schema-drift test above.
