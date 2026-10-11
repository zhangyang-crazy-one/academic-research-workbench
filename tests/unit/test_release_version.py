"""Current distribution identities agree while retained evidence stays historical."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from arw import __version__

ROOT = Path(__file__).resolve().parents[2]


def test_current_release_metadata_and_launcher_versions_are_coherent() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == __version__ == "0.2.0"
    for relative in (
        ".codex-plugin/plugin.json", "packaging/claude/plugin.json", "codemeta.json"
    ):
        assert json.loads((ROOT / relative).read_text(encoding="utf-8"))["version"] == __version__
    launcher_versions = re.findall(
        r'importlib\.metadata\.version\("academic-research-workbench"\) != "([^"]+)"',
        (ROOT / "bin/arw").read_text(encoding="utf-8"),
    )
    assert launcher_versions == [__version__, __version__]
