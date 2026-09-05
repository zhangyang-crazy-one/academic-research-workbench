"""Store/run sidecar keys must preserve identity within filesystem limits."""

import os
from pathlib import Path

import pytest

from arw.cli import _provenance_sidecar_path

RUN_ID = "run-00000000-0000-4000-8000-000000000051"


@pytest.mark.parametrize("name", ["x" * 200 + ".db", "研" * 80 + ".db"])
def test_long_names_have_creatable_sidecar_and_audit_paths(
    tmp_path: Path, name: str
) -> None:
    store = tmp_path / name
    store.touch()
    sidecar = _provenance_sidecar_path(store, RUN_ID)
    audit = Path(f"{sidecar}.audit")
    assert sidecar.parent == tmp_path
    assert len(os.fsencode(audit.name)) <= 255
    sidecar.touch()
    audit.mkdir()
    assert _provenance_sidecar_path(store, RUN_ID) == sidecar


def test_short_names_preserve_existing_paths_and_store_suffixes(tmp_path: Path) -> None:
    first = _provenance_sidecar_path(tmp_path / "research.db", RUN_ID)
    second = _provenance_sidecar_path(tmp_path / "research.sqlite3", RUN_ID)
    assert first.name == f"research.db.{RUN_ID}.semantica.sqlite3"
    assert first != second


def test_long_names_and_runs_remain_isolated(tmp_path: Path) -> None:
    first = tmp_path / ("x" * 200 + ".db")
    second = tmp_path / ("x" * 200 + ".sqlite3")
    assert _provenance_sidecar_path(first, RUN_ID) != _provenance_sidecar_path(
        second, RUN_ID
    )
    assert _provenance_sidecar_path(first, RUN_ID) != _provenance_sidecar_path(
        first, RUN_ID[:-1] + "2"
    )


def test_literal_hash_name_cannot_alias_long_store(tmp_path: Path) -> None:
    long_store = tmp_path / ("x" * 200 + ".db")
    sidecar = _provenance_sidecar_path(long_store, RUN_ID)
    literal_name = sidecar.name.removesuffix(f".{RUN_ID}.semantica.sqlite3")
    assert _provenance_sidecar_path(tmp_path / literal_name, RUN_ID) != sidecar
