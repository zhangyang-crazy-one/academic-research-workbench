"""The stage producer accepts registered shared schemas and rejects unknown files."""

from __future__ import annotations

from pathlib import Path

import pytest

from arw.kernel.policy.core_stage_allowlist import allowed_stage_path
from arw.kernel.policy.schema_registry import SCHEMA_NAMES, regenerate_schemas

STAGE_SCRIPT = Path(__file__).resolve().parents[2] / "scripts/stage-plugin"


def _schema_allowlist() -> set[str]:
    source = STAGE_SCRIPT.read_text(encoding="utf-8")
    start = source.index("static_files = {")
    end = source.index("arw_references =", start)
    namespace = {"SCHEMA_NAMES": SCHEMA_NAMES}
    # Execute only the repository producer's static inventory declarations.
    exec(compile(source[start:end], str(STAGE_SCRIPT), "exec"), namespace)  # noqa: S102
    return {
        relative for relative in namespace["static_files"]
        if relative.startswith("share/arw/schemas/")
    }


def _check_inventory(actual: set[str], expected: set[str]) -> None:
    source = STAGE_SCRIPT.read_text(encoding="utf-8")
    start = source.index("if actual != expected:")
    end = source.index("\nprivate_path =", start)
    # Exercise the actual producer's mismatch check without assembling a binary.
    exec(  # noqa: S102
        compile(source[start:end], str(STAGE_SCRIPT), "exec"),
        {"actual": actual, "expected": expected},
    )


def test_stage_accepts_the_complete_registered_schema_projection(tmp_path: Path) -> None:
    regenerate_schemas(tmp_path / "share/arw/schemas")
    observed = {
        path.relative_to(tmp_path).as_posix()
        for path in (tmp_path / "share/arw/schemas").iterdir()
    }
    expected = _schema_allowlist()
    assert expected == {f"share/arw/schemas/{name}" for name in SCHEMA_NAMES}
    _check_inventory(observed, expected)
    assert all(
        allowed_stage_path(relative, "academic_research_workbench-0.2.0-py3-none-any.whl")
        for relative in observed
    )
    assert allowed_stage_path(
        "schemas/v1/release-authority.schema.json",
        "academic_research_workbench-0.2.0-py3-none-any.whl",
    )


@pytest.mark.parametrize("extra", ("unregistered.schema.json", "private.txt"))
def test_stage_rejects_unknown_shared_schema_directory_files(extra: str) -> None:
    expected = _schema_allowlist()
    with pytest.raises(SystemExit, match=extra.replace(".", r"\.")):
        _check_inventory(expected | {f"share/arw/schemas/{extra}"}, expected)
    assert not allowed_stage_path(
        f"share/arw/schemas/{extra}", "academic_research_workbench-0.2.0-py3-none-any.whl"
    )


def test_stage_rejects_missing_registered_schema() -> None:
    expected = _schema_allowlist()
    missing = "share/arw/schemas/accepted-ref.schema.json"
    with pytest.raises(SystemExit, match="missing=.*accepted-ref"):
        _check_inventory(expected - {missing}, expected)


@pytest.mark.parametrize("relative", (
    "share/arw/schemas/nested/accepted-ref.schema.json",
    "share/arw/schemas/../accepted-ref.schema.json",
    "schemas/v1/unregistered.schema.json",
))
def test_installed_loader_rejects_unregistered_schema_paths(relative: str) -> None:
    assert not allowed_stage_path(
        relative, "academic_research_workbench-0.2.0-py3-none-any.whl"
    )
