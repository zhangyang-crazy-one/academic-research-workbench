"""Stage scratch remains disjoint when pytest itself lives inside build/tmp."""

from pathlib import Path

from tests.candidate_inputs import isolated_stage_temporary_environment


def test_owned_stage_scratch_ignores_broad_caller_temporary_roots(tmp_path, monkeypatch):
    pytest_root = tmp_path / "build/tmp/pytest/test-install"
    monkeypatch.setenv("TMPDIR", str(tmp_path / "build/tmp"))
    monkeypatch.setenv("ARW_STAGE_TMP_ROOT", str(tmp_path / "build/tmp"))
    environment = isolated_stage_temporary_environment(pytest_root / "isolation")
    roots = [Path(value) for value in environment.values()]
    assert all(path.is_dir() for path in roots)
    assert not roots[0].is_relative_to(roots[1])
    assert not roots[1].is_relative_to(roots[0])
    for output in (pytest_root / "stage", pytest_root / "evidence"):
        assert all(not output.is_relative_to(path) for path in roots)
        assert all(not path.is_relative_to(output) for path in roots)
