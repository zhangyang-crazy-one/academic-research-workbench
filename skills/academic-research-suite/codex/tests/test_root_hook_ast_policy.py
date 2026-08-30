"""Exact semantic AST fingerprint allowlist for the root hook handler.

The handler bytes must parse to an ``ast.AST`` whose canonicalized
dump (no attributes, fields annotated) hashes to one of the values
in :data:`ROOT_HOOK_AST_SHA256_BY_PYTHON` for the running Python
minor.  Comments and blank lines never reach ``ast.parse``, so the
digest is stable across purely-formatter changes; every executable,
docstring, or string-constant edit breaks the digest and fails closed.

The handler is **never executed**; only :func:`ast.parse` plus
:func:`ast.dump` are used.  Syntax errors and unsupported Python
minors fail closed.  The exact SBOM digest row and the three
authority markers remain as independent, additive checks performed
earlier in :func:`check_root_hook_supply_chain`.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest  # type: ignore[import-not-found]

CODEX_ROOT = Path(__file__).resolve().parents[1]
GATES_PATH = CODEX_ROOT / "scripts" / "ars_codex_quality_gates.py"
REPOSITORY_ROOT = CODEX_ROOT.parents[2]
REAL_HANDLER = (REPOSITORY_ROOT / "hooks" / "arw_hook.py").read_text(encoding="utf-8")


@pytest.fixture
def gates():
    spec = importlib.util.spec_from_file_location(
        "ars_root_hook_ast_gates", GATES_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stage(tmp_path, handler):
    """Materialize a plugin root with a matching SBOM digest rebound."""
    root = tmp_path / "plugin"
    hd = root / "hooks"
    hd.mkdir(parents=True)
    (hd / "arw_hook.py").write_text(handler, encoding="utf-8")
    (hd / "arw_hook.py").chmod(0o755)
    payload = {
        "hooks": {
            ev: [
                {
                    "matcher": ".*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": 'python3 "${PLUGIN_ROOT}/hooks/arw_hook.py"',
                            "timeout": 10,
                        }
                    ],
                }
            ]
            for ev in ("SessionStart", "SubagentStop", "Stop")
        }
    }
    (hd / "hooks.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    components = []
    for rel in ("hooks/hooks.json", "hooks/arw_hook.py"):
        body = (root / rel).read_bytes()
        components.append(
            {
                "bom-ref": f"artifact:{rel}",
                "name": rel,
                "type": "file",
                "version": "1",
                "hashes": [
                    {"alg": "SHA-256", "content": hashlib.sha256(body).hexdigest()}
                ],
            }
        )
    (root / "SBOM.cdx.json").write_text(
        json.dumps({"components": components}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return root


def test_real_handler_passes(gates, tmp_path):
    """Installed ``hooks/arw_hook.py`` must round-trip the fingerprint gate."""
    msgs = gates.check_root_hook_supply_chain(_stage(tmp_path, REAL_HANDLER))
    assert any("SBOM" in m for m in msgs), msgs


# Every entry below breaks the AST digest and must be rejected.  The
# list mirrors the closed exploit classes the brief enumerates plus a
# constant-edit to confirm the digest covers string-literal changes too.
EXPLOIT_MUTATIONS = (
    ("import-arw", "import arw.runtime\n"),
    ("import-os-alias", "import os as o\n"),
    ("pathlib-write-text", "import pathlib\npathlib.Path('x').write_text('y')\n"),
    ("pathlib-touch", "import pathlib\npathlib.Path('x').touch()\n"),
    ("temporary-path-unlink", "import pathlib, os\nt = pathlib.Path('events.jsonl')\nos.unlink(t)\n"),
    ("os-mutator", "import os\nos.remove('x')\n"),
    ("dunder-import", "__import__('os').system('x')\n"),
    ("exec", "exec('x')\n"),
    ("constant-change", "RECEIPT_SCHEMA = 'hijacked.v9'\n"),
)


@pytest.mark.parametrize(
    ("label", "mutation"),
    EXPLOIT_MUTATIONS,
    ids=[c[0] for c in EXPLOIT_MUTATIONS],
)
def test_executable_mutation_is_rejected(gates, tmp_path, label, mutation):
    handler = REAL_HANDLER + "\n" + mutation
    with pytest.raises(gates.GateFailure, match="fingerprint|AST"):
        gates.check_root_hook_supply_chain(_stage(tmp_path, handler))


# Comments and blank lines never reach ``ast.parse``; the digest is
# stable across purely-formatter changes.
COSMETIC_PASSES = (
    ("top-comment", "# harmless top-level comment\n"),
    ("inline-trailing", "# trailing\n"),
    ("blank-lines", "\n\n\n"),
)


@pytest.mark.parametrize(
    ("label", "mutation"), COSMETIC_PASSES, ids=[c[0] for c in COSMETIC_PASSES]
)
def test_cosmetic_change_passes(gates, tmp_path, label, mutation):
    handler = REAL_HANDLER + "\n" + mutation
    msgs = gates.check_root_hook_supply_chain(_stage(tmp_path, handler))
    assert any("SBOM" in m for m in msgs), msgs


def test_unsupported_python_minor_fails_closed(gates, tmp_path, monkeypatch):
    """``(3, 99)`` is not in ``ROOT_HOOK_AST_SHA256_BY_PYTHON``; fail closed."""
    monkeypatch.setattr(sys, "version_info", (3, 99, 0, "final", 0))
    with pytest.raises(gates.GateFailure, match="unsupported"):
        gates.check_root_hook_supply_chain(_stage(tmp_path, REAL_HANDLER))


def test_malformed_syntax_fails_closed(gates):
    """``_root_hook_ast_digest`` surfaces :class:`SyntaxError` as ``GateFailure``
    on its own (it doesn't depend on the marker / SBOM checks upstream)."""
    with pytest.raises(gates.GateFailure, match="syntax|SyntaxError|parse"):
        gates._root_hook_ast_digest("def broken(:\n    pass\n")


def test_rebound_sbom_exploit_is_still_rejected(gates, tmp_path):
    """Even with the SBOM digest rebound to the exploit bytes, the AST
    fingerprint gate stops the payload because the semantic AST differs
    from the audited one."""
    handler = REAL_HANDLER + "\nimport arw.runtime\nPath('state.json').write_text('hijacked')\n"
    with pytest.raises(gates.GateFailure) as info:
        gates.check_root_hook_supply_chain(_stage(tmp_path, handler))
    assert "fingerprint" in str(info.value) or "arw" in str(info.value)


def test_full_gate_passes_against_in_tree_layout():
    """End-to-end: the in-tree ``ars_codex_quality_gates.py all`` run
    must still pass against the unchanged hooks/ tree."""
    r = subprocess.run(
        [sys.executable, str(GATES_PATH), "all", "--json"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr or r.stdout
    payload = json.loads(r.stdout)
    assert payload["root-hook-supply-chain"]["ok"] is True
