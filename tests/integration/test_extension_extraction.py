"""Physical provider locations and unchanged native wire surface through extension."""

import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from arw.composition import default_router
from arw.kernel.capabilities import CapabilityUnavailable
from tests.compat.normalize import read_golden_json
from tests.file_plane_helpers import canonical_request, invoke_jsonrpc_process

ROOT = Path(__file__).resolve().parents[2]


def test_ars_is_physically_external_and_optional(monkeypatch):
    from arw import composition

    adapter = default_router().resolve("research.literature")
    assert type(adapter).__module__ == "arw_ars"
    assert adapter.registry()
    assert adapter.resolve(adapter.registry()[0].definition_id) == adapter.registry()[0]
    original = composition.import_module

    def absent(name):
        if name == "arw_ars":
            raise ImportError("fixture removed")
        return original(name)

    monkeypatch.setattr(composition, "import_module", absent)
    with pytest.raises(CapabilityUnavailable):
        default_router().resolve("research.literature")


def test_minimal_import_never_attempts_storm_dependencies():
    program = """
import importlib.abc, sys
class Deny(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if fullname.split('.')[0] in {'knowledge_storm','sentence_transformers','tavily','litellm','torch','transformers'}:
   raise AssertionError('unexpected dependency import: ' + fullname)
sys.meta_path.insert(0,Deny())
import arw.cli
arw.cli.build_parser()
from arw.composition import default_router
default_router().resolve('research.literature')
assert 'arw_storm' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", program], check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_no_kernel_concrete_extension_imports():
    for file in (ROOT / "src/arw/kernel").rglob("*.py"):
        for node in ast.walk(ast.parse(file.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(
                    ("arw_ars", "arw_storm", "arw_writing")
                )


def test_native_surface_through_relocated_provider(tmp_path, monkeypatch):
    binary = ROOT / ".file-base/bin/file-base"
    if not binary.is_file():
        pytest.skip("native binary not materialized")
    plugin = tmp_path / "plugin"
    for relative in ("scripts/file-base-mcp", "extensions/file-base-mcp/bin/provider"):
        destination = plugin / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    (plugin / "libexec").mkdir()
    os.link(binary, plugin / "libexec/file-base-mcp")
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    environment = {
        "CBM_ALLOWED_ROOT": str(allowed),
        "CBM_ALLOWED_ROOT_ID": "research-root",
        "CBM_CACHE_DIR": str(tmp_path / "cache"),
        "CBM_DISABLE_UPDATE_CHECK": "1",
        "CBM_LOG_LEVEL": "error",
        "HOME": str(tmp_path / "home"),
        "PATH": os.environ["PATH"],
    }
    result = invoke_jsonrpc_process(
        [str(plugin / "scripts/file-base-mcp")],
        [
            canonical_request(
                1,
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "fixture", "version": "1"},
                },
            ),
            canonical_request(2, "tools/list", {}),
        ],
        environment=environment,
        cwd=tmp_path,
    )
    golden = read_golden_json(ROOT / "tests/compat/golden/filebase/native_surface.json")
    responses = result.responses
    assert responses[0]["result"]["capabilities"] == golden["capabilities"]
    tools = responses[1]["result"]["tools"]
    assert [t["name"] for t in tools] == golden["tool_names"]
    assert {t["name"]: t["inputSchema"] for t in tools} == golden["input_schemas"]

    # Reuse the frozen happy-path/traversal/error contract without weakening it.
    from tests.compat import test_filebase_mcp_contract as baseline

    monkeypatch.setattr(baseline, "NATIVE_BINARY", plugin / "scripts/file-base-mcp")
    native_errors = tmp_path / "native-errors"
    native_errors.mkdir()
    baseline.test_native_read_file_call_envelopes_match_golden(native_errors)
