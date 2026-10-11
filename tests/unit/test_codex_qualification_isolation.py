"""Real network-free namespace probes preserve CLI paths and hide host data."""

import importlib.machinery
import importlib.util
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def module():
    loader = importlib.machinery.SourceFileLoader("qualify_codex_isolation", str(ROOT / "scripts/qualify-codex-host"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    instance = importlib.util.module_from_spec(spec)
    loader.exec_module(instance)
    return instance


@pytest.mark.parametrize("symlink", [None, "outside", "inside"])
def test_real_namespace_executes_only_mounted_runtime_and_keeps_host_files_hidden(tmp_path, symlink):
    if not shutil.which("bwrap") or not shutil.which("node"):
        pytest.skip("bubblewrap and Node are required for this actual namespace probe")
    code = module()
    package = tmp_path / "private-prefix/lib/node_modules/codex"
    (package / "bin").mkdir(parents=True)
    (package / "package.json").write_text('{"type":"module"}\n')
    script = package / "bin/codex.js"
    sentinel = tmp_path / "private-prefix/credential-sentinel"
    sentinel.write_text("must-remain-outside-the-namespace")
    script.write_text('''#!/usr/bin/env node
import fs from 'node:fs';
const hidden = process.argv[2];
if (fs.existsSync(hidden)) process.exit(7);
try { fs.writeFileSync(new URL('../forbidden-write', import.meta.url), 'bad'); process.exit(8); }
catch (error) { if (error.code !== 'EROFS' && error.code !== 'EACCES') throw error; }
console.log('RUNTIME_VISIBLE_HOST_DATA_HIDDEN');
''')
    script.chmod(0o755)
    launcher = script
    if symlink:
        launcher = (package / "bin/codex") if symlink == "inside" else tmp_path / "private-prefix/bin/codex"
        launcher.parent.mkdir(exist_ok=True)
        launcher.symlink_to(script)
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    (fresh / "home").mkdir()
    (fresh / "codex-home").mkdir()
    result = code._run_isolated(fresh, [str(launcher), str(sentinel)])
    assert result.returncode == 0, result.stderr
    assert result.stdout == b"RUNTIME_VISIBLE_HOST_DATA_HIDDEN\n"
    mounts = code._codex_runtime_mounts(launcher)
    assert str(sentinel.parent) not in mounts
    assert not (package / "forbidden-write").exists()


def test_real_installed_codex_version_is_visible_without_authentication(tmp_path):
    launcher = shutil.which("codex")
    if not launcher or not shutil.which("bwrap"):
        pytest.skip("installed Codex and bubblewrap are required")
    code = module()
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    (fresh / "home").mkdir()
    (fresh / "codex-home").mkdir()
    result = code._run_isolated(fresh, [launcher, "--version"])
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(b"codex-cli ")
    assert not (fresh / "codex-home/auth.json").exists()
