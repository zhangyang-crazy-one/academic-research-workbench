# PR #105 candidate fixture repair

The dependency-update branch raises `platformdirs` to `>=4.13.0`, while the synthetic candidate inventory still declares `4.11.6`. The wheel metadata follows `pyproject.toml`, so valid-candidate controls fail before reaching the license and RECORD checks they are supposed to exercise.

Observed RED: both `test_candidate_requires_source_declared_wheel_license` and `test_candidate_wheel_metadata_and_record_are_validated` fail with `resolved runtime inventory lacks a satisfying direct dependency: platformdirs`. This matches the original package-boundary failure in [run 38860706321](https://github.com/zhangyang-crazy-one/academic-research-workbench/actions/runs/38860706321/job/116842095681).

The test fixture now builds its synthetic direct-runtime rows from the declared open lower bounds, with a separate copied environment inventory so mutation controls remain independent. Production validation and dependency ranges are unchanged. These rows are synthetic test data, not observed installations or license declarations.

## 已验证

- `PYTHONPATH=src python -m pytest -q tests/unit/test_candidate_gate.py`: 47 passed, including missing/unsatisfied dependencies and mismatched inventories.
- `PYTHONPATH=src python -m pytest -q tests/integration/test_candidate_bundle.py tests/unit/test_reproducible_wheel.py tests/unit/test_candidate_temporary_environment.py`: 16 passed.
- `ruff check --isolated --select E4,E7,E9,F tests/unit/test_candidate_gate.py` and `git diff --check`: passed.

The interpreter was the primary checkout's existing Python 3.14 environment; `PYTHONPATH` selected this PR worktree's source.

## 未验证

Installation and execution of every newly proposed optional dependency, hosted CI on the repaired head, and release qualification. The separate floating-Python optional-wheel resolution failure requires the independent CI compatibility repair.
