"""Static AST policy gate for ``check_root_hook_supply_chain`` (Codex 3882633278).

Scope: replaces the legacy ``"from arw" not in handler`` substring check
with a structural default-deny AST gate on the root hook handler.

Catches: non-allowlist import roots; dangerous Python builtins
(exec / eval / getattr / __import__ / …); direct file / filesystem
writes (``Path('x').write_text(...)``, ``os.write`` / ``os.remove`` /
``os.rename`` / ``os.sendfile``); the carve-out attrs ``write`` /
``mkdir`` / ``unlink`` are accepted **only** when the leftmost terminal
``Name`` matches one of the six real-hook sites in
``ROOT_HOOK_ALLOWED_TERMINAL_RECEIVERS`` (``stream.write``,
``sys.stdout.buffer.write`` / ``sys.stderr.write``, ``data_path.mkdir``,
``candidate.mkdir``, ``temporary.unlink``); process / spawn family;
alternate tempfile constructors; network / DNS lookups; dunder
class-graph walk; relative / star imports; top-level ``import … as …``
aliases; safe-local rebinds in **every** binding form — Assign /
AnnAssign / NamedExpr / ``withitem`` / ``For`` / ``AsyncFor`` target /
comprehension target / function-or-lambda argument (posonly / regular /
vararg / kwarg) / ``ExceptHandler.name``; the last-resort constructs
``match`` / ``global`` / ``nonlocal`` / PEP 695 ``type X = ...``
(rejected wholesale — pattern-flattening intentionally not
implemented); syntax errors.

Chained-alias guarantee: ``p = os; o = p; o.write(...)`` cannot reach
the carve-out because (a) the terminal-name allowlist only contains
``{stream, sys, data_path, candidate, temporary}`` so any other
terminal — including a Name reached through an alias chain — is
rejected by ``visit_Attribute``; and (b) a safe local rebound through
a Name (e.g. ``stream = os.fdopen_alias``) fails the binding-shape
check because the RHS is not the exact ``Call(os.fdopen, ...)`` /
``Call(Path, ...)`` / ``BinOp(``/``)`` pattern the allowlist assumes.
The two ``test_chained_alias_*`` tests pin both layers.

Residuals (parent layer): ambient env reads (``os.environ`` /
``os.environ.get`` / ``os.getenv`` / ``sys.argv``),
pseudo-filesystem reads (``/proc`` / ``/sys`` / device files),
``additionalContext`` sanitization, runtime-value semantic analysis.
The **primary** boundary is the exact SBOM digest row — the AST gate
is a secondary defense layered on top of it and does **not** prove
complete non-interference.

Atomic maintenance contract: ``ROOT_HOOK_ALLOWED_TERMINAL_RECEIVERS``
and the ``REAL_HOOK_SAFE_SITES`` tuple below must be updated
**together** whenever the real hook adds / removes / renames a
``write`` / ``mkdir`` / ``unlink`` site; the binding patterns in
``ROOT_HOOK_SAFE_LOCAL_NAMES`` must be updated alongside the
binding that introduces each safe local name. The real hook
currently has exactly six sites; the positive test enforces every
one. The handler is **never executed** — ``ast.parse`` +
``ast.NodeVisitor`` only.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import textwrap
from pathlib import Path
from typing import cast

import pytest  # type: ignore[import-not-found]


def _json_object_from_text(text: str, *, label: str) -> dict[str, object]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        raise AssertionError(f"{label} is not valid JSON") from None
    if not isinstance(value, dict):
        raise AssertionError(f"{label} must be a JSON object")
    return cast(dict[str, object], value)


def _read_json_object(path: Path) -> dict[str, object]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise AssertionError(f"cannot read JSON fixture: {path}") from None
    return _json_object_from_text(text, label=str(path))

CODEX_ROOT = Path(__file__).resolve().parents[1]
GATES_PATH = CODEX_ROOT / "scripts" / "ars_codex_quality_gates.py"
REPOSITORY_ROOT = CODEX_ROOT.parents[2]
HOOKS_DIR = REPOSITORY_ROOT / "hooks"
REAL_HANDLER = (HOOKS_DIR / "arw_hook.py").read_text(encoding="utf-8")
REAL_HOOKS_JSON = _read_json_object(HOOKS_DIR / "hooks.json")


# Loader + fixture

@pytest.fixture
def gates():
    spec = importlib.util.spec_from_file_location("ars_root_hook_ast_gates", GATES_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)
    return module


def _stage(tmp_path, handler, hooks_json=None):
    """Materialize a plugin root with a matching SBOM digest rebound."""
    root = tmp_path / "plugin"
    hd = root / "hooks"
    hd.mkdir(parents=True)
    (hd / "arw_hook.py").write_text(handler, encoding="utf-8")
    (hd / "arw_hook.py").chmod(0o755)
    payload = hooks_json or {
        "hooks": {ev: [{"matcher": ".*", "hooks": [{"type": "command",
                "command": 'python3 "${PLUGIN_ROOT}/hooks/arw_hook.py"', "timeout": 10}]}]
            for ev in ("SessionStart", "SubagentStop", "Stop")}}
    (hd / "hooks.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    components = []
    for rel in ("hooks/hooks.json", "hooks/arw_hook.py"):
        body = (root / rel).read_bytes()
        components.append({"bom-ref": f"artifact:{rel}", "name": rel, "type": "file",
            "version": "1", "hashes": [{"alg": "SHA-256", "content": hashlib.sha256(body).hexdigest()}]})
    (root / "SBOM.cdx.json").write_text(json.dumps({"components": components}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return root


PRELUDE = textwrap.dedent("""
    from __future__ import annotations
    import hashlib, json, os, stat, sys, tempfile
    from collections.abc import Mapping
    from pathlib import Path
    from typing import Any
    AUTHORITY_DOC = '"authority": "observational"'
    PARENT_CONTROLS_DOC = 'parent_controls'
    ADMISSION_DOC = 'admission, retries, provenance, and gates remain parent-owned'
""").strip()
def _wrap(payload):
    return (f"{PRELUDE}\n{payload}\n\ndef main():\n"
            "    return {AUTHORITY_DOC: True, PARENT_CONTROLS_DOC: [], ADMISSION_DOC: True}\n")


# Categorized exploit matrix.  ``expected`` matches the GateFailure message.
EXPLOIT_MATRIX = (
    # imports / module graph
    ("import-arw",            "import arw.runtime",                                       r"arw|allowlist"),
    ("from-arw",              "from arw import runtime",                                  r"arw|allowlist"),
    ("import-subprocess",     "import subprocess\nsubprocess.run(['x'])",                 r"subprocess|allowlist"),
    ("import-shutil-rmtree",  "import shutil\nshutil.rmtree('/')",                        r"shutil|rmtree|allowlist"),
    ("import-urllib",         "import urllib.request\nurllib.request.urlopen('x')",       r"urllib|allowlist"),
    ("import-socket-dns",     "import socket\nsocket.getaddrinfo('x', 80)",               r"socket|allowlist"),
    ("from-os-write",         "from os import write\nwrite(1, b'')",                      r"write|os"),
    ("from-os-star",          "from os import *",                                          r"star"),
    ("from-tempfile-named",   "from tempfile import NamedTemporaryFile\nNamedTemporaryFile()",  r"NamedTemporaryFile"),
    ("from-tempfile-tmp",     "from tempfile import TemporaryFile\nTemporaryFile()",     r"TemporaryFile"),
    ("from-tempfile-spool",   "from tempfile import SpooledTemporaryFile\nSpooledTemporaryFile()", r"SpooledTemporaryFile"),
    ("from-tempfile-dir",     "from tempfile import TemporaryDirectory\nTemporaryDirectory()", r"TemporaryDirectory"),
    ("relative-import",       "from . import sibling",                                     r"relative"),
    ("relative-import-2",     "from ..pkg import helper",                                  r"relative"),
    ("import-alias",          "import os as o",                                            r"aliasing"),
    # Python builtins
    ("exec",                  "exec('x')",                                                 r"builtin|exec"),
    ("eval",                  "eval('x')",                                                 r"builtin|eval"),
    ("compile",               "compile('x', '<s>', 'exec')",                              r"builtin|compile"),
    ("__import__",            "__import__('subprocess')",                                  r"builtin|__import__"),
    ("getattr",               "getattr(os, 'remove')",                                     r"builtin|getattr"),
    ("hasattr",               "hasattr(os, 'remove')",                                     r"builtin|hasattr"),
    ("setattr",               "setattr(x, 'a', 1)",                                        r"builtin|setattr"),
    ("delattr",               "delattr(x, 'a')",                                           r"builtin|delattr"),
    ("globals",               "globals()['x'] = 1",                                        r"builtin|globals"),
    ("locals",                "locals()['x'] = 1",                                         r"builtin|locals"),
    ("vars",                  "vars()['x'] = 1",                                           r"builtin|vars"),
    ("breakpoint",            "breakpoint()",                                              r"builtin|breakpoint"),
    ("open",                  "open('/etc/passwd')",                                       r"builtin|open"),
    ("input",                 "input()",                                                   r"builtin|input"),
    # direct writes (pathlib / stream object)
    ("pathlib-write-text",    "Path('x').write_text('y')",                                 r"write_text"),
    ("pathlib-write-bytes",   "Path('x').write_bytes(b'y')",                               r"write_bytes"),
    ("stream-writelines",     "stream.writelines([b'x'])",                                 r"writelines"),
    # carve-out attrs — terminal-name allowlist enforcement
    ("generic-write",         "obj.write(b'x')",                                           r"os-write|allowed"),
    ("generic-mkdir",         "obj.mkdir()",                                               r"path-or-os-mutation|allowed"),
    ("generic-unlink",        "obj.unlink()",                                              r"path-or-os-mutation|allowed"),
    ("inline-Path-mkdir",     "Path('x').mkdir()",                                         r"path-or-os-mutation|allowed"),
    ("inline-Path-unlink",    "Path('x').unlink()",                                        r"path-or-os-mutation|allowed"),
    ("inline-Path-makedirs",  "Path('x').makedirs()",                                      r"path-or-os-mutation|allowed"),
    ("o=os-write",            "import os as o\no.write(1, b'')",                           r"aliasing|os-write|allowed"),
    ("o=os-mkdir",            "import os as o\no.mkdir('a')",                              r"aliasing|path-or-os-mutation|allowed"),
    ("o=os-unlink",           "import os as o\no.unlink('a')",                             r"aliasing|path-or-os-mutation|allowed"),
    # safe-name malicious rebind (binding check fires before the attr check)
    ("stream=os;stream.write",   "stream = os\nstream.write(b'x')",                       r"safe local name 'stream'"),
    ("temporary=os;temporary.unlink", "temporary = os\ntemporary.unlink('a')",            r"safe local name 'temporary'"),
    ("data_path=os;data_path.mkdir",  "data_path = os\ndata_path.mkdir()",               r"safe local name 'data_path'"),
    ("candidate=os;candidate.mkdir",  "candidate = os\ncandidate.mkdir()",               r"safe local name 'candidate'"),
    # additional binding forms the brief asks the gate to close
    ("for-stream-in-os",       "for stream in [os]: stream.write(b'x')",                r"safe local name 'stream'"),
    ("comp-stream",            "(stream.write(b'x') for stream in [os])",               r"safe local name 'stream'"),
    ("lambda-stream",          "(lambda stream: stream.write(b'x'))(os)",              r"safe local name 'stream'"),
    ("except-temporary",       "try:\n    pass\nexcept Exception as temporary:\n    temporary.unlink('a')", r"safe local name 'temporary'"),
    ("def-stream-arg",         "def fn(stream): stream.write(b'x')\nfn(os)",           r"safe local name 'stream'"),
    ("def-data_path-arg",      "def fn(data_path): data_path.mkdir()\n(fn(os))",     r"safe local name 'data_path'"),
    ("def-temporary-arg",      "def fn(temporary): temporary.unlink('a')\n(fn(os))", r"safe local name 'temporary'"),
    ("def-candidate-arg",      "def fn(candidate): candidate.mkdir()\n(fn(os))",     r"safe local name 'candidate'"),
    ("def-sys-arg",            "def fn(sys): pass\nfn(os)",                             r"safe local name 'sys'"),
    ("def-stream-vararg",      "def fn(*stream): stream.write(b'x')\nfn(os)",          r"safe local name 'stream'"),
    ("def-stream-kwarg",       "def fn(**stream): stream.write(b'x')\nfn(stream=os)", r"safe local name 'stream'"),
    # last-resort default-deny constructs (rejected wholesale)
    ("match-stream",           "match x:\n    case stream:\n        stream.write(b'x')", r"match statement"),
    ("global-stream",          "global stream",                                      r"global declaration"),
    ("nonlocal-stream",        "nonlocal stream",                                    r"nonlocal declaration"),
    # os.X writes / filesystem mutation (always denied regardless of receiver)
    ("os-write",              "os.write(1, b'')",                                          r"os-write"),
    ("os-rename",             "os.rename('a','b')",                                        r"filesystem"),
    ("os-replace",            "os.replace('a','b')",                                       r"filesystem"),
    ("os-remove",             "os.remove('a')",                                            r"filesystem"),
    ("os-unlink",             "os.unlink('a')",                                            r"path-or-os-mutation|allowed"),
    ("os-mkdir",              "os.mkdir('a')",                                             r"path-or-os-mutation|allowed"),
    ("os-makedirs",           "os.makedirs('a')",                                          r"path-or-os-mutation|allowed"),
    ("os-chmod",              "os.chmod('a', 0o777)",                                      r"filesystem"),
    ("os-chown",              "os.chown('a', 0, 0)",                                       r"filesystem"),
    ("os-truncate",           "os.truncate('a', 0)",                                       r"filesystem"),
    ("os-symlink",            "os.symlink('a','b')",                                       r"filesystem"),
    ("os-sendfile",           "os.sendfile(1, 2, 0, 4)",                                   r"process"),
    # process / spawn / exec family
    ("os-system",             "os.system('rm -rf /')",                                     r"process"),
    ("os-popen",              "os.popen('x').read()",                                      r"process"),
    ("os-fork",               "os.fork()",                                                 r"process"),
    ("os-spawn",              "os.spawn('x')",                                             r"process"),
    ("os-posix-spawn",        "os.posix_spawn('x', [], [])",                               r"process"),
    ("os-execvp",             "os.execvp('x', [])",                                         r"process"),
    ("os-execve",             "os.execve('x', [], {})",                                    r"process"),
    ("os-execlp",             "os.execlp('x', 'x')",                                       r"process"),
    # DNS / network
    ("dns-getaddrinfo",       "import socket\nsocket.getaddrinfo('x', 80)",                r"network"),
    ("dns-gethostbyname",     "import socket\nsocket.gethostbyname('x')",                 r"network"),
    ("dns-gethostbyname-ex",  "import socket\nsocket.gethostbyname_ex('x')",              r"network"),
    ("dns-gethostbyaddr",     "import socket\nsocket.gethostbyaddr('1.2.3.4')",           r"network"),
    ("dns-getnameinfo",       "import socket\nsocket.getnameinfo(('x', 80))",             r"network"),
    ("urllib-urlopen",        "from urllib.request import urlopen\nurlopen('x')",          r"network"),
    # dunder class-graph walk
    ("dunder-class",          "().__class__",                                              r"dunder-class-graph"),
    ("dunder-bases",          "().__class__.__bases__[0]",                                 r"dunder-class-graph"),
    ("dunder-subclasses",     "().__class__.__subclasses__()",                             r"dunder-class-graph"),
    ("dunder-globals",        "(lambda: 0).__globals__",                                   r"dunder-class-graph"),
    ("dunder-builtins",       "x = __builtins__",                                          r"dunder-class-graph"),
    ("dunder-mro",            "().__class__.__mro__",                                      r"dunder-class-graph"),
    ("dunder-dict",           "().__dict__",                                               r"dunder-class-graph"),
    ("dunder-getattribute",   "object.__getattribute__",                                   r"dunder-class-graph"),
    ("dunder-getattr",        "object.__getattr__",                                        r"dunder-class-graph"),
    ("dunder-init-subclass",  "object.__init_subclass__",                                  r"dunder-class-graph"),
)

@pytest.mark.parametrize(("label", "payload", "expected"), EXPLOIT_MATRIX,
                         ids=[c[0] for c in EXPLOIT_MATRIX])
def test_static_ast_policy_rejects_malicious_pattern(gates, tmp_path, label, payload, expected):
    with pytest.raises(gates.GateFailure, match=expected):
        gates.check_root_hook_supply_chain(_stage(tmp_path, _wrap(payload)))


# Baseline / rebound-SBOM exploit / syntax / never-execute
def test_real_root_hook_passes_the_static_ast_policy_gate(gates, tmp_path):
    msgs = gates.check_root_hook_supply_chain(_stage(tmp_path, REAL_HANDLER, REAL_HOOKS_JSON))
    assert any("SBOM" in m for m in msgs)


def test_full_runtime_quality_gates_still_pass_for_in_tree_layout():
    import subprocess
    import sys as _sys
    r = subprocess.run([_sys.executable, str(GATES_PATH), "all", "--json"],
                       cwd=REPOSITORY_ROOT, capture_output=True, text=True, check=False)
    payload = _json_object_from_text(r.stdout, label="quality-gate stdout")
    root_hook_result = payload.get("root-hook-supply-chain")
    assert isinstance(root_hook_result, dict)
    assert r.returncode == 0 and bool(root_hook_result.get("ok"))


def test_syntax_error_fails_closed(gates, tmp_path):
    handler = f"{PRELUDE}\ndef broken(:\n    pass\n\ndef main():\n    return {{}}\n"
    with pytest.raises(gates.GateFailure, match="syntax"):
        gates.check_root_hook_supply_chain(_stage(tmp_path, handler))


def test_end_to_end_exploit_with_rebound_sbom_digest_is_still_rejected(gates, tmp_path):
    """Codex 3882633278: legacy substring check missed ``import arw.runtime``;
    even with SBOM digest rebound to the exploit bytes the AST gate stops it."""
    handler = _wrap("import arw.runtime\nPath('state.json').write_text('hijacked')")
    with pytest.raises(gates.GateFailure) as info:
        gates.check_root_hook_supply_chain(_stage(tmp_path, handler))
    assert "arw" in str(info.value) or "write_text" in str(info.value)


def test_exploit_handler_is_never_executed(gates, tmp_path):
    handler = f"{PRELUDE}\nraise SystemExit(42)\nimport this_module_does_not_exist\n"
    with pytest.raises(gates.GateFailure) as info:
        gates.check_root_hook_supply_chain(_stage(tmp_path, handler))
    msg = str(info.value)
    assert "ImportError" not in msg and "Traceback" not in msg
    assert "allowlist" in msg or "policy" in msg or "denied" in msg


# PEP 695 type-alias test: ``ast.TypeAlias`` only exists on Python 3.12+;
# unit-test the visitor method (always runnable when the type exists)
# and parse the source for a full-gate integration test (skipped on 3.11).
def test_type_alias_visitor_method_flags_node(gates):
    import ast as _ast
    type_alias_cls = getattr(_ast, "TypeAlias", None)
    if type_alias_cls is None:
        pytest.skip("ast.TypeAlias requires Python 3.12+")
    type_alias_ctor = cast("type", type_alias_cls)
    name = _ast.Name(id="stream", ctx=_ast.Store())
    value = _ast.Name(id="int", ctx=_ast.Load())
    node = type_alias_ctor(name=name, value=value, type_params=[])
    visitor = gates._RootHookASTVisitor()
    visitor.visit_TypeAlias(node)
    assert any("type alias" in err for err in visitor.errors), visitor.errors


@pytest.mark.skipif(not hasattr(__import__("ast"), "TypeAlias"),
                    reason="PEP 695 type alias requires Python 3.12+")
def test_type_alias_in_handler_source_is_rejected(gates, tmp_path):
    handler = f"{PRELUDE}\ntype stream = int\ndef main():\n    return {{}}\n"
    with pytest.raises(gates.GateFailure, match="type alias"):
        gates.check_root_hook_supply_chain(_stage(tmp_path, handler))


# Chained-alias guarantee (see module docstring).
def test_chained_alias_o_p_os_is_rejected_by_terminal_name_allowlist(gates, tmp_path):
    handler = _wrap("p = os\no = p\no.write(1, b'')")
    with pytest.raises(gates.GateFailure, match="os.write|os-write"):
        gates.check_root_hook_supply_chain(_stage(tmp_path, handler))


def test_chained_alias_stream_rebound_via_name_is_rejected_by_binding_shape(gates, tmp_path):
    handler = _wrap("os.fdopen_alias = os.fdopen\nstream = os.fdopen_alias\nstream.write(b'x')")
    with pytest.raises(gates.GateFailure, match="safe local name 'stream'"):
        gates.check_root_hook_supply_chain(_stage(tmp_path, handler))

# Real-hook safe sites (six in the current ``hooks/arw_hook.py``):
# each must be admitted by the terminal-receiver allowlist AND bound
# to the ``ROOT_HOOK_SAFE_LOCAL_NAMES`` pattern.  Atomic maintenance
# contract: every new safe site in the real hook must be added to
# both ``ROOT_HOOK_ALLOWED_TERMINAL_RECEIVERS`` and this tuple.
REAL_HOOK_SAFE_SITES = (
    ("stream.write",            "stream = os.fdopen(os.fdopen(1, 'wb'), 'wb'); stream.write(b'data')"),
    ("sys.stdout.buffer.write", "import sys; sys.stdout.buffer.write(b'data')"),
    ("sys.stderr.write",        "import sys; sys.stderr.write('msg')"),
    ("data_path.mkdir",         "data_path = Path('/tmp'); data_path.mkdir(mode=0o700, parents=True, exist_ok=True)"),
    ("candidate.mkdir",         "candidate = Path('/tmp') / 'sub'; candidate.mkdir(mode=0o700)"),
    ("temporary.unlink",        "temporary = Path('/tmp/x'); temporary.unlink(missing_ok=True)"),
)
@pytest.mark.parametrize(("label", "snippet"), REAL_HOOK_SAFE_SITES,
                         ids=[s[0] for s in REAL_HOOK_SAFE_SITES])
def test_real_hook_safe_site_is_admitted(gates, tmp_path, label, snippet):
    """Every site the real hook relies on must round-trip cleanly through the gate."""
    handler = f"{PRELUDE}\ndef main():\n    {snippet}\n    return {{}}\n"
    msgs = gates.check_root_hook_supply_chain(_stage(tmp_path, handler))
    assert any("SBOM" in m for m in msgs)