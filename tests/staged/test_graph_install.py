from __future__ import annotations

import json
import zipfile
from pathlib import Path

from test_supply_chain_inventory import _stage


def test_stage_contains_graph_runtime_and_identity(tmp_path: Path) -> None:
    stage_root = tmp_path / "stage" / "academic-research-workbench"
    result = _stage(stage_root)
    assert result.returncode == 0, result.stderr
    assert (stage_root / "scripts/file-base-graph-mcp").is_file()
    assert (stage_root / "scripts/file-base-graph-mcp").stat().st_mode & 0o111
    assert (stage_root / "docs/runtime/research-graph.md").is_file()
    for name in (
        "graph-node.schema.json",
        "graph-edge.schema.json",
        "graph-projection-manifest.schema.json",
        "graph-projection-receipt.schema.json",
        "graph-query-request.schema.json",
        "graph-query-result.schema.json",
        "graph-oracle.schema.json",
    ):
        assert (stage_root / "share/arw/schemas" / name).is_file()
    identity = json.loads((stage_root / "share/arw/build-identity.json").read_text(encoding="utf-8"))
    assert identity["projection"]["algorithm"] == "research-graph-projection-v1"
    assert identity["projection"]["oracle"] == "research-graph-normalization-v1"
    assert identity["projection"]["query_profile"] == "arw-graph-mcp-v1"
    wheel = next((stage_root / "vendor/python/wheelhouse").glob("academic_research_workbench-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    assert "arw/graph_store.py" in names
    assert "arw/graph_mcp.py" in names
    assert "arw/graph_projection.py" in names


def test_graph_launcher_fails_closed_without_parent_selection(tmp_path: Path) -> None:
    stage_root = tmp_path / "stage" / "academic-research-workbench"
    result = _stage(stage_root)
    assert result.returncode == 0, result.stderr
    denied = __import__("subprocess").run(
        [str(stage_root / "scripts/file-base-graph-mcp")],
        input="",
        text=True,
        capture_output=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert denied.returncode == 64
    assert "ARW_GRAPH_CONTROL_ROOT" in denied.stderr
