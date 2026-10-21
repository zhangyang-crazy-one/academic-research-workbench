"""Real network-free namespace probes preserve CLI paths and hide host data."""

import importlib.machinery
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def module():
    loader = importlib.machinery.SourceFileLoader("qualify_codex_isolation", str(ROOT / "scripts/qualify-codex-host"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    instance = importlib.util.module_from_spec(spec)
    loader.exec_module(instance)
    return instance


def _namespace_probe_skip() -> str | None:
    """Skip when this runner cannot host the actual namespace probe."""
    if not shutil.which("bwrap") or not shutil.which("node"):
        return "bubblewrap and Node are required for this actual namespace probe"
    node = Path(shutil.which("node") or "").resolve()
    if not node.is_file() or node.parent.name != "bin":
        return "the exact Node runtime for the Codex launcher is unavailable"
    probe = subprocess.run(
        [
            "bwrap",
            "--die-with-parent",
            "--unshare-pid",
            "--ro-bind",
            "/",
            "/",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--",
            "/bin/true",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=5,
        check=False,
    )
    if probe.returncode != 0:
        return "bubblewrap user namespaces are unavailable on this runner"
    return None


@pytest.mark.parametrize("symlink", [None, "outside", "inside"])
def test_real_namespace_executes_only_mounted_runtime_and_keeps_host_files_hidden(tmp_path, symlink):
    reason = _namespace_probe_skip()
    if reason:
        pytest.skip(reason)
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


@pytest.mark.parametrize("visible", ["/usr/local/bin", "/etc"])
@pytest.mark.parametrize("native", [False, True])
def test_visible_launcher_through_hidden_middle_alias_executes_in_actual_namespace(tmp_path, visible, native):
    reason = _namespace_probe_skip()
    if reason:
        pytest.skip(reason)
    package = tmp_path / "private-prefix/lib/node_modules/codex"
    (package / "bin").mkdir(parents=True)
    (package / "package.json").write_text('{"type":"module"}')
    script = package / "bin" / ("native-codex" if native else "codex.js")
    sentinel = tmp_path / "private-prefix/credential-sentinel"
    sentinel.write_text("dummy credential sentinel")
    if native:
        script.write_text('#!/bin/sh\ntest ! -e "$1" || exit 7\nprintf "NATIVE_VISIBLE\\n"\n')
    else:
        script.write_text('''#!/usr/bin/env node
import fs from 'node:fs';
if (fs.existsSync(process.argv[2])) process.exit(7);
try { fs.writeFileSync(new URL('../forbidden-write', import.meta.url), 'bad'); process.exit(8); }
catch (error) { if (error.code !== 'EROFS' && error.code !== 'EACCES') throw error; }
console.log('RUNTIME_VISIBLE');
''')
    script.chmod(0o755)
    middle = tmp_path / "hidden-alias/codex"
    middle.parent.mkdir()
    middle.symlink_to(script)
    exposed = tmp_path / "visible"
    exposed.mkdir()
    (exposed / "arw-codex-review-fixture").symlink_to(middle)
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    (fresh / "home").mkdir()
    (fresh / "codex-home").mkdir()
    # Overlay only this process's namespace, never the actual /usr or /etc.
    probe = '''import importlib.machinery,importlib.util,sys
loader=importlib.machinery.SourceFileLoader("probe",sys.argv[1])
spec=importlib.util.spec_from_loader(loader.name,loader)
code=importlib.util.module_from_spec(spec); loader.exec_module(code)
from pathlib import Path
result=code._run_isolated(Path(sys.argv[2]),[sys.argv[3],sys.argv[4]])
sys.stdout.buffer.write(result.stdout);sys.stderr.buffer.write(result.stderr)
raise SystemExit(result.returncode)
'''
    result = subprocess.run(["bwrap", "--die-with-parent", "--unshare-pid", "--ro-bind", "/", "/",
        "--proc", "/proc", "--dev", "/dev",
        "--ro-bind", str(exposed), visible, "--", sys.executable, "-c", probe,
        str(ROOT / "scripts/qualify-codex-host"), str(fresh), f"{visible}/arw-codex-review-fixture", str(sentinel)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout == (b"NATIVE_VISIBLE\n" if native else b"RUNTIME_VISIBLE\n")
    assert not (package / "forbidden-write").exists()


@pytest.mark.parametrize("invalid", ["missing", "cycle"])
def test_missing_or_cyclic_launcher_is_clearly_blocked(tmp_path, invalid):
    code = module()
    launcher = tmp_path / "codex"
    launcher.symlink_to(tmp_path / "missing" if invalid == "missing" else launcher)
    with pytest.raises(code.CanaryError, match="missing|cycle"):
        code._codex_runtime_mounts(launcher)
