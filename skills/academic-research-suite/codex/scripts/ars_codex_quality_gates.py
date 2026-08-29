#!/usr/bin/env python3
"""Static quality gates for the ARS-Codex full-runtime adapter."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

SCRIPT = Path(__file__).resolve()
CODEX_ROOT = SCRIPT.parents[1]
SUITE_ROOT = SCRIPT.parents[2]
ARS_ROOT = SUITE_ROOT / "ars"
PLUGIN_ROOT_CANDIDATE = SUITE_ROOT.parents[1]
PLUGIN_ROOT = (
    PLUGIN_ROOT_CANDIDATE
    if (PLUGIN_ROOT_CANDIDATE / ".codex-plugin" / "plugin.json").is_file()
    else SUITE_ROOT.parents[1] / "plugins" / "ars-codex"
)
FULL_RUNTIME_MANIFEST = CODEX_ROOT / "full-runtime-manifest.json"
PACKAGE_MANIFEST = SUITE_ROOT / "manifest.json"
HOOK_PACK = CODEX_ROOT / "hooks" / "hooks.json"
ROOT_HOOK_PATHS = ("hooks/hooks.json", "hooks/arw_hook.py")
VENUE_PROFILES = CODEX_ROOT / "references" / "annual_venue_profiles.json"
VENUE_PROFILE_VALIDATOR = CODEX_ROOT / "scripts" / "validate_venue_profiles.py"

FORBIDDEN_HOOK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\benv\b"),
    re.compile(r"\bprintenv\b"),
    re.compile(r"\bexport\b"),
    re.compile(r"\bcurl\b"),
    re.compile(r"\bwget\b"),
    re.compile(r"\brm\b"),
    re.compile(r"\bmv\b"),
    re.compile(r"\bcp\b"),
    re.compile(r"\bsudo\b"),
    re.compile(r"\bchmod\b"),
    re.compile(r"\bchown\b"),
    re.compile(r">"),
    re.compile(r"\|\s*sh\b"),
    re.compile(r"\|\s*bash\b"),
    re.compile(r"\.ssh"),
    re.compile(r"ANTHROPIC_API_KEY"),
    re.compile(r"OPENAI_API_KEY"),
)


# ---------------------------------------------------------------------------
# Static AST policy for the root hook handler.
#
# The Codex comment 3882633278 noted that the legacy substring check
# (``"from arw" not in handler``) was bypassed by ``import arw.runtime``
# or by ``Path('state.json').write_text(...)``-style writes that hide
# behind a different surface.  The gate below replaces that fragile
# substring check with a structural default-deny AST policy: the handler
# is parsed with ``ast.parse`` (never executed) and the tree is walked
# with an ``ast.NodeVisitor``.
#
# **What this gate is and is not.**
#
# This is a **secondary** defense layered on top of the primary
# integrity check: every root hook file must already be content-bound
# to an exact SBOM row (``hashes[*].content`` must equal the SHA-256 of
# the bytes on disk).  The AST policy below does *not* prove complete
# non-interference; it closes the structural categories the SBOM-bound
# bytes could still enable if they were swapped for adversarial code:
#
#   * non-allowlist import roots (e.g. ``arw``, ``subprocess``, ``shutil``,
#     ``urllib``, ``socket``),
#   * dangerous Python builtins (exec / eval / getattr / __import__ / …),
#   * direct file / filesystem writes (``Path('x').write_text(...)``,
#     ``Path('x').write_bytes(...)``, ``stream.writelines(...)``,
#     ``os.write`` / ``os.remove`` / ``os.rename`` / …).  The carve-out
#     attrs ``write`` / ``mkdir`` / ``unlink`` are accepted **only** when
#     their leftmost terminal ``Name`` matches one of the six real-hook
#     sites in :data:`ROOT_HOOK_ALLOWED_TERMINAL_RECEIVERS`
#     (``stream.write``, ``sys.stdout.buffer.write`` / ``sys.stderr.write``,
#     ``data_path.mkdir``, ``candidate.mkdir``, ``temporary.unlink``);
#     the companion binding check confirms each safe local name is
#     assigned exactly the value the allowlist assumes (``stream``
#     must come from ``os.fdopen(...)``; ``data_path`` / ``temporary``
#     must come from ``Path(...)``; ``candidate`` must come from a
#     ``left / right`` ``BinOp``; ``sys`` must come from an unaliased
#     ``import sys`` and must never be reassigned),
#   * process / spawn family (``os.system``, ``os.popen``, ``os.execv*``,
#     ``os.posix_spawn``, ``os.fork``, …),
#   * alternate tempfile constructors (``NamedTemporaryFile``,
#     ``TemporaryFile``, ``SpooledTemporaryFile``, ``TemporaryDirectory``
#     are rejected; ``tempfile.mkstemp`` is allowed),
#   * network / DNS lookups (``urllib.request.urlopen``,
#     ``socket.getaddrinfo`` / ``gethostbyname(_ex)`` / ``gethostbyaddr``
#     / ``getnameinfo``),
#   * dunder class-graph walk (``__class__``, ``__bases__``,
#     ``__subclasses__``, ``__globals__``, ``__builtins__``, ``__mro__``,
#     ``__dict__``, ``__getattribute__``, ``__getattr__``,
#     ``__init_subclass__``).
#
# The exact SBOM digest identity (the primary boundary) and the three
# authority markers remain as separate, independent checks; the AST
# policy is *additive* on top of them.
#
# **Out of scope (residuals the parent layer must enforce).**
#
#   * Ambient env reads beyond the static allowlist (``os.environ``,
#     ``os.environ.get`` / ``os.environ.items``, ``os.getenv``,
#     ``sys.argv``).
#   * Pseudo-filesystem reads (``/proc`` / ``/sys`` / device files).
#   * Sanitization of any ``additionalContext`` string on the stdout
#     wire.
#   * Semantic analysis of runtime values produced by the policy-clean
#     primitives listed above.
#
# The handler is **never executed**: this module uses ``ast.parse`` plus
# ``ast.NodeVisitor`` only.  Syntax errors and relative imports fail
# closed.
# ---------------------------------------------------------------------------

ROOT_HOOK_ALLOWED_IMPORT_ROOTS: frozenset[str] = frozenset(
    {
        "__future__",
        "hashlib",
        "json",
        "os",
        "stat",
        "sys",
        "tempfile",
        "collections",
        "pathlib",
        "typing",
    }
)


def _build_denied_attrs() -> dict[str, str]:
    """Categorized default-deny set for ``visit_Attribute`` / ``visit_Name``.

    The value is the category label (used only in error messages).  The
    only category with a non-trivial check is ``"os-write"``: that
    category's attribute is also a legitimate stream / file method name
    (``stream.write`` is the real hook's only file-write primitive), so
    the visitor must structurally confirm the receiver is ``os`` (or
    could resolve to ``os`` via ``IfExp`` / ``or`` alias) before
    denying.  Every other category is denied regardless of receiver.
    """

    denied: dict[str, str] = {}

    def add(names: tuple[str, ...], category: str) -> None:
        for name in names:
            denied[name] = category

    # Python builtins that must never appear in Load context.
    add(
        (
            "exec",
            "eval",
            "compile",
            "__import__",
            "getattr",
            "hasattr",
            "setattr",
            "delattr",
            "globals",
            "locals",
            "vars",
            "breakpoint",
            "open",
            "input",
        ),
        "builtin",
    )
    # High-level file writes (pathlib / file-object).
    add(("write_text", "write_bytes", "writelines"), "high-level-write")
    # Process / spawn / exec family.
    add(
        (
            "system",
            "spawn",
            "posix_spawn",
            "popen",
            "fork",
            "sendfile",
            "execvp",
            "execvpe",
            "execve",
            "execv",
            "execl",
            "execle",
            "execlp",
            "execlpe",
        ),
        "process",
    )
    # Filesystem mutation.  ``mkdir`` / ``makedirs`` / ``unlink`` are
    # ambiguous (the real hook legitimately uses ``Path('x').mkdir(...)``
    # and ``Path('x').unlink(...)``), so they live in
    # ``path-or-os-mutation`` (receiver-checked) rather than
    # ``filesystem`` (denied regardless of receiver).
    add(
        (
            "rename",
            "replace",
            "remove",
            "chmod",
            "chown",
            "truncate",
            "symlink",
            "rmtree",
        ),
        "filesystem",
    )
    add(
        ("mkdir", "makedirs", "unlink"),
        "path-or-os-mutation",
    )
    # Alternate tempfile constructors (``tempfile.mkstemp`` / ``mkdtemp``
    # remain allowed primitives).
    add(
        (
            "NamedTemporaryFile",
            "TemporaryFile",
            "SpooledTemporaryFile",
            "TemporaryDirectory",
        ),
        "tempfile-ctor",
    )
    # Network / DNS lookups.
    add(
        (
            "urlopen",
            "getaddrinfo",
            "gethostbyname",
            "gethostbyname_ex",
            "gethostbyaddr",
            "getnameinfo",
        ),
        "network",
    )
    # Dunder class-graph walk: every entry here is a known gadget for
    # reaching ``object.__subclasses__`` -> ``os`` / ``subprocess`` etc.
    add(
        (
            "__class__",
            "__bases__",
            "__subclasses__",
            "__globals__",
            "__builtins__",
            "__mro__",
            "__dict__",
            "__getattribute__",
            "__getattr__",
            "__init_subclass__",
        ),
        "dunder-class-graph",
    )
    # ``os.write`` is the one dangerous attr that overlaps with a
    # legitimate stream / file-object method (``stream.write``).  The
    # visitor checks the receiver structurally to distinguish.
    denied["write"] = "os-write"
    return denied


ROOT_HOOK_DENIED_ATTRS: dict[str, str] = _build_denied_attrs()
ROOT_HOOK_OS_RECEIVER_ATTRS: frozenset[str] = frozenset(
    attr for attr, category in ROOT_HOOK_DENIED_ATTRS.items()
    if category in {"os-write", "path-or-os-mutation"}
)

# Explicit terminal-receiver allowlist for the carve-out attrs
# (``write``, ``mkdir``, ``unlink``).  Each entry binds the attr to the
# leftmost terminal ``ast.Name`` reached by walking the Attribute
# chain.  Any other terminal (including ``Path`` from an inline
# ``Path('x').mkdir(...)`` call, ``os`` from a leaked os reference,
# or any user-defined local) is denied.
ROOT_HOOK_ALLOWED_TERMINAL_RECEIVERS: frozenset[tuple[str, str]] = frozenset(
    {
        ("write", "stream"),       # ``stream.write(body)`` in ``_persist_receipt``
        ("write", "sys"),          # ``sys.stdout.buffer.write(...)`` and ``sys.stderr.write(...)``
        ("mkdir", "data_path"),    # ``data_path.mkdir(mode=0o700, parents=True, exist_ok=True)``
        ("mkdir", "candidate"),    # ``candidate.mkdir(mode=0o700)`` in ``_receipt_directory``
        ("unlink", "temporary"),   # ``temporary.unlink(missing_ok=True)`` in ``_persist_receipt``
    }
)

# Safe local names and the binding pattern each must satisfy.
# ``"unaliased-import"`` is special — the name must come from the import
# allowlist (which already rejects ``import sys as s``) and must not be
# reassigned anywhere in the handler.
ROOT_HOOK_SAFE_LOCAL_NAMES: dict[str, str] = {
    "stream": "os.fdopen",
    "data_path": "Path",
    "temporary": "Path",
    "candidate": "BinOp(Div)",
    "sys": "unaliased-import",
}


def _leftmost_terminal_name(value: ast.expr) -> str | None:
    """Walk an ``ast.Attribute`` chain to the leftmost terminal ``Name``.

    Returns the bound name (``str``) or ``None`` if the chain does not
    terminate at a bare ``ast.Name`` (e.g. ``Call(...)``, ``Subscript``,
    ``IfExp``, ``Starred``).  ``os.write`` chains back to ``"os"`` via
    the bare module reference; ``os.something.write`` chains back to
    ``"os"`` too (the outer attribute is still rooted at ``os``).
    """

    current = value
    while isinstance(current, ast.Attribute):
        current = current.value
    return current.id if isinstance(current, ast.Name) else None


def _safe_unparse(node: ast.AST) -> str:
    """Best-effort source for an AST node.

    :func:`ast.unparse` can raise :class:`SyntaxError`, :class:`ValueError`,
    or :class:`TypeError` on exotic / forward-reference forms.  The
    gate's diagnostic messages must never fail to render, so any of
    these failures falls back to a stable
    ``<unparsable ast.<NodeType>>`` token.
    """

    try:
        return ast.unparse(node)  # type: ignore[arg-type]
    except (SyntaxError, ValueError, TypeError):
        return f"<unparsable ast.{type(node).__name__}>"


def _is_os_fdopen_call(value: ast.expr) -> bool:
    """True if ``value`` is a Call to ``os.fdopen(...)``."""
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "os"
        and func.attr == "fdopen"
    )


def _is_path_call(value: ast.expr) -> bool:
    """True if ``value`` is a Call to ``Path(...)``."""
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "Path"
    )


def _is_div_binop(value: ast.expr) -> bool:
    """True if ``value`` is a ``left / right`` ``BinOp``."""
    return isinstance(value, ast.BinOp) and isinstance(value.op, ast.Div)


def _binding_value_matches(name: str, value: ast.expr) -> bool:
    """Return True if ``value`` matches the expected binding pattern for ``name``."""
    pattern = ROOT_HOOK_SAFE_LOCAL_NAMES.get(name)
    if pattern == "os.fdopen":
        return _is_os_fdopen_call(value)
    if pattern == "Path":
        return _is_path_call(value)
    if pattern == "BinOp(Div)":
        return _is_div_binop(value)
    return False


def _names_in_target(target: ast.expr) -> list[str]:
    """Flatten every binding Name out of a for / comprehension / except target.

    Returns an empty list if ``target`` has no ``ast.Name`` children
    (e.g. an attribute-only target).  Handles ``Name``, ``Tuple``,
    ``List`` and ``Starred`` (a starred target like ``for *x, y in iter:``
    still binds every leaf name).
    """

    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        out: list[str] = []
        for elt in target.elts:
            out.extend(_names_in_target(elt))
        return out
    if isinstance(target, ast.Starred):
        return _names_in_target(target.value)
    return []


class _RootHookASTVisitor(ast.NodeVisitor):
    """Walk a handler AST and collect every static-policy violation.

    ``visit_Attribute`` rejects by attr alone (regardless of receiver)
    for every category except ``os-write`` (``write``) and
    ``path-or-os-mutation`` (``mkdir``, ``makedirs``, ``unlink``).
    For those carve-out attrs, the visitor computes the leftmost
    terminal ``Name`` and admits the call **only** when
    ``(attr, name)`` appears in
    :data:`ROOT_HOOK_ALLOWED_TERMINAL_RECEIVERS`.  The companion
    ``visit_Assign`` / ``visit_AnnAssign`` / ``visit_NamedExpr`` /
    ``visit_withitem`` checks ensure that each safe local name is
    bound to the precise pattern the allowlist assumes (``stream``
    must come from ``os.fdopen(...)``; ``data_path`` / ``temporary``
    must come from ``Path(...)``; ``candidate`` must come from a
    ``left / right`` ``BinOp``; ``sys`` must come from an unaliased
    ``import sys`` and must never be reassigned).  ``visit_Name``
    uses the same denylist so a name bound by a
    ``from <module> import <denied>`` route is also caught.
    """

    def __init__(self) -> None:
        self.errors: list[str] = []

    # ---- imports ----------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            top = alias.name.split(".", 1)[0]
            if top not in ROOT_HOOK_ALLOWED_IMPORT_ROOTS:
                self.errors.append(
                    f"import root {top!r} is not in the static AST allowlist "
                    f"(saw {alias.name!r})"
                )
            if alias.asname is not None:
                self.errors.append(
                    f"import aliasing is forbidden on top-level imports "
                    f"(saw {alias.name!r} as {alias.asname!r})"
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level and node.level > 0:
            self.errors.append(
                f"relative import is forbidden in the root hook handler "
                f"(saw level={node.level}, module={node.module!r})"
            )
            self.generic_visit(node)
            return
        module = node.module or ""
        top = module.split(".", 1)[0]
        if top not in ROOT_HOOK_ALLOWED_IMPORT_ROOTS:
            self.errors.append(
                f"from-import root {top!r} is not in the static AST allowlist "
                f"(saw from {module!r})"
            )
        for alias in node.names:
            if alias.name == "*":
                self.errors.append(
                    f"star import is forbidden (saw from {module!r} import *)"
                )
            if top == "os" and alias.name in ROOT_HOOK_OS_RECEIVER_ATTRS:
                self.errors.append(
                    f"selective import of forbidden os symbol is denied "
                    f"(saw from os import {alias.name!r})"
                )
        self.generic_visit(node)

    # ---- safe local-name bindings ----------------------------------------

    def _validate_safe_binding(
        self, name: str, value: ast.expr | None, *, location_label: str
    ) -> None:
        pattern = ROOT_HOOK_SAFE_LOCAL_NAMES.get(name)
        if pattern is None:
            return
        if pattern == "unaliased-import":
            # ``sys`` must come from the import allowlist (which already
            # rejects ``import sys as s``) and must not be reassigned
            # anywhere in the handler — covers Assign / AnnAssign /
            # NamedExpr / withitem / For / AsyncFor / comprehension /
            # arguments / ExceptHandler.
            self.errors.append(
                f"safe local name {name!r} must not be reassigned "
                f"(import is already constrained to be unaliased, saw "
                f"{location_label})"
            )
            return
        if value is None or not _binding_value_matches(name, value):
            rhs = (
                _safe_unparse(value)
                if value is not None
                else "<binding form without allowlisted pattern>"
            )
            self.errors.append(
                f"safe local name {name!r} must be bound to {pattern!r} "
                f"(saw {rhs} in {location_label})"
            )

    def _validate_arguments(
        self, args: ast.arguments, *, location_label: str
    ) -> None:
        """Reject every safe name bound as a function / lambda argument.

        Covers posonlyargs, args, kwonlyargs, vararg (``*x``) and
        kwarg (``**x``).  The real hook does not bind any safe name
        this way; the check exists to close a future rebind vector.
        """

        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
            self._validate_safe_binding(arg.arg, None, location_label=location_label)
        if args.vararg is not None:
            self._validate_safe_binding(
                args.vararg.arg, None, location_label=location_label
            )
        if args.kwarg is not None:
            self._validate_safe_binding(
                args.kwarg.arg, None, location_label=location_label
            )

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name):
                self._validate_safe_binding(
                    target.id, node.value, location_label="Assign"
                )
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
            self._validate_safe_binding(
                node.target.id, node.value, location_label="AnnAssign"
            )
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        if isinstance(node.target, ast.Name):
            self._validate_safe_binding(
                node.target.id, node.value, location_label="NamedExpr"
            )
        self.generic_visit(node)

    def visit_withitem(self, node: ast.withitem) -> None:
        # Defensive coverage of the real hook's ``with os.fdopen(...) as
        # stream:`` pattern: rejects ``with os as stream:`` and similar
        # rebinds that would otherwise let ``stream.write`` reach
        # ``os.write``.
        if isinstance(node.optional_vars, ast.Name):
            self._validate_safe_binding(
                node.optional_vars.id,
                node.context_expr,
                location_label="withitem",
            )
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        for name in _names_in_target(node.target):
            self._validate_safe_binding(name, None, location_label="For target")
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        for name in _names_in_target(node.target):
            self._validate_safe_binding(
                name, None, location_label="AsyncFor target"
            )
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        for name in _names_in_target(node.target):
            self._validate_safe_binding(
                name, None, location_label="comprehension target"
            )
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._validate_arguments(
            node.args, location_label=f"def {node.name} arguments"
        )
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._validate_arguments(
            node.args, location_label=f"def {node.name} arguments"
        )
        self.generic_visit(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._validate_arguments(node.args, location_label="lambda arguments")
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        # Python 3.11+: ``ExceptHandler.name`` is a plain ``str``.
        if isinstance(node.name, str) and node.name:
            self._validate_safe_binding(
                node.name, None, location_label="except as"
            )
        self.generic_visit(node)

    # ---- last-resort default-deny constructs -----------------------------

    def visit_Match(self, node: ast.Match) -> None:
        # Any ``match`` / ``case`` statement is rejected outright — the
        # pattern grammar (``MatchSequence`` / ``MatchMapping`` /
        # ``MatchClass`` / ``MatchAs`` / ``MatchStar``) is deliberately
        # not flattened for safe-name checks because the simpler
        # structural default-deny is sufficient for an observation hook.
        self.errors.append(
            "match statement is forbidden in the root hook handler "
            "(pattern-flattening is intentionally not implemented)"
        )
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        names = ", ".join(repr(n) for n in node.names)
        self.errors.append(
            f"global declaration is forbidden in the root hook handler (saw {names})"
        )
        self.generic_visit(node)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        names = ", ".join(repr(n) for n in node.names)
        self.errors.append(
            f"nonlocal declaration is forbidden in the root hook handler (saw {names})"
        )
        self.generic_visit(node)

    def visit_TypeAlias(self, node) -> None:  # type: ignore[no-untyped-def]
        # PEP 695 type alias (``type X = ...``) — added in Python 3.12.
        # ``ast.TypeAlias`` is not in the 3.11 stubs, so we annotate the
        # parameter as untyped.  The shape is identical across 3.12 /
        # 3.13 / 3.14 so a single rejection suffices.
        self.errors.append(
            f"type alias (PEP 695) is forbidden in the root hook handler "
            f"(saw {_safe_unparse(node)})"
        )
        self.generic_visit(node)

    # ---- names / attributes ----------------------------------------------

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and node.id in ROOT_HOOK_DENIED_ATTRS:
            category = ROOT_HOOK_DENIED_ATTRS[node.id]
            self.errors.append(
                f"forbidden {category} name is denied in Load context "
                f"(saw {node.id!r})"
            )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        category = ROOT_HOOK_DENIED_ATTRS.get(node.attr)
        if category is not None:
            if category in {"os-write", "path-or-os-mutation"}:
                # Explicit terminal-receiver allowlist: only the six
                # real-hook sites in
                # :data:`ROOT_HOOK_ALLOWED_TERMINAL_RECEIVERS` are
                # accepted.  Inline ``Path('x').mkdir(...)``,
                # ``o.write`` after ``import os as o`` (also caught by
                # the import rule), ``obj.write`` for an arbitrary
                # ``obj``, and any rebind of a safe local to a
                # dangerous value (caught by the binding check) all fail
                # closed here.
                terminal = _leftmost_terminal_name(node.value)
                if terminal is None or (
                    node.attr,
                    terminal,
                ) not in ROOT_HOOK_ALLOWED_TERMINAL_RECEIVERS:
                    self.errors.append(
                        f"forbidden {category} call is denied "
                        f"(saw {_safe_unparse(node)})"
                    )
            else:
                self.errors.append(
                    f"forbidden {category} attribute is denied (saw .{node.attr})"
                )
        self.generic_visit(node)


def _parse_handler(handler_source: str) -> ast.AST:
    """Parse ``handler_source`` and surface syntax errors as ``GateFailure``.

    Extracted from :func:`_enforce_root_hook_static_policy` so the
    exception-as-control-flow path lives in its own function — this
    keeps the policy orchestrator free of try/except boilerplate and
    avoids any linter false positive on the exception binding syntax.
    """

    try:
        return ast.parse(handler_source, type_comments=False)
    except SyntaxError:
        raise GateFailure(
            "root hook handler failed static AST parse (syntax error)"
        ) from None


def _enforce_root_hook_static_policy(handler_source: str) -> None:
    """Apply the default-deny AST policy to ``handler_source``.

    The handler is **never executed**: this function uses
    :func:`ast.parse` plus :class:`ast.NodeVisitor` only.  Any policy
    violation raises :class:`GateFailure` with a precise, audit-friendly
    cause.  Syntax errors and relative imports fail closed.
    """

    tree = _parse_handler(handler_source)
    visitor = _RootHookASTVisitor()
    try:
        visitor.visit(tree)
    except (RecursionError, ValueError, TypeError) as exc:
        # ``ast.NodeVisitor.visit`` can raise ``RecursionError`` on
        # pathologically deep ASTs (e.g. adversarial nested expressions)
        # and ``ValueError`` / ``TypeError`` on malformed nodes that
        # ``ast.parse`` accepted but the visitor's typed accessors
        # cannot handle.  All three are failure-closed; convert to
        # ``GateFailure`` so the gate never leaks a Python exception.
        raise GateFailure(
            "root hook handler failed static AST traversal "
            f"({type(exc).__name__}: {exc})"
        ) from exc
    if not visitor.errors:
        return
    # Surface every distinct cause (with a +N more suffix for very long
    # lists) so the CI output is self-describing but bounded.
    unique: list[str] = []
    seen: set[str] = set()
    for err in visitor.errors:
        if err not in seen:
            unique.append(err)
            seen.add(err)
    if len(unique) > 5:
        head = "; ".join(unique[:5])
        raise GateFailure(
            "root hook handler failed static AST default-deny policy: "
            f"{head} (+{len(unique) - 5} more)"
        )
    raise GateFailure(
        "root hook handler failed static AST default-deny policy: "
        + "; ".join(unique)
    )


class GateFailure(RuntimeError):
    pass


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GateFailure(f"cannot read JSON object {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise GateFailure(f"expected a JSON object in {path}")
    return cast(dict[str, Any], payload)


def _resolve_manifest_path(value: str) -> Path:
    path = Path(value)
    if path.parts and path.parts[0] == "skills":
        return SUITE_ROOT.parents[1] / path
    return SUITE_ROOT / path


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GateFailure(message)


def _narrow(condition: bool, message: str) -> None:
    """Runtime invariant used to narrow optional types for the type checker.

    Mirrors :func:`_require` but documents that the check is a defensive
    post-``_require`` invariant — it must not be elided by Python's
    ``-O`` flag and must raise :class:`GateFailure` if the upstream
    contract is ever violated.
    """

    if not condition:
        raise GateFailure(f"internal invariant violated: {message}")


def check_manifest() -> list[str]:
    manifest = _json(FULL_RUNTIME_MANIFEST)
    messages = ["full-runtime manifest parses as JSON"]

    for key, value in manifest["paths"].items():
        if key in {"adapter_root"}:
            continue
        path = _resolve_manifest_path(value)
        _require(path.exists(), f"manifest path missing for {key}: {value}")
    messages.append("declared adapter paths exist")

    aliases: set[str] = set()
    for command in manifest["commands"]:
        for alias in command["aliases"]:
            _require(alias not in aliases, f"duplicate alias: {alias}")
            aliases.add(alias)
        recipe = SUITE_ROOT / command["recipe"]
        _require(recipe.exists(), f"command recipe missing: {command['recipe']}")
    for required in (
        "ars-reviewer",
        "ars-mark-read",
        "ars-unmark-read",
        "ars-cache-invalidate",
        "ars-3w",
        "ars-rebuttal-audit",
        "ars-full",
        "ars-plan",
        "ars-lit-review",
    ):
        _require(required in aliases, f"required alias absent: {required}")
    messages.append(f"{len(manifest['commands'])} command routes have recipes")

    for name, workflow in manifest["workflows"].items():
        workflow_path = SUITE_ROOT / workflow["workflow_path"]
        _require(workflow_path.exists(), f"workflow path missing for {name}: {workflow['workflow_path']}")
        template = SUITE_ROOT / workflow["agent_template"]
        _require(template.exists(), f"agent template missing for {name}: {workflow['agent_template']}")
    messages.append(f"{len(manifest['workflows'])} workflows have templates")
    return messages


def check_single_root_skill() -> list[str]:
    root_skill = SUITE_ROOT / "SKILL.md"
    _require(root_skill.exists(), "root SKILL.md missing")
    vendored_skill_files = sorted(ARS_ROOT.rglob("SKILL.md"))
    _require(not vendored_skill_files, "vendored workflow SKILL.md files would expose duplicate Codex skills: " + ", ".join(str(p) for p in vendored_skill_files))
    workflow_files = sorted(ARS_ROOT.glob("*/WORKFLOW.md"))
    workflow_names = {path.parent.name for path in workflow_files}
    expected = {"deep-research", "academic-paper", "academic-paper-reviewer", "academic-pipeline", "experiment-agent"}
    _require(expected.issubset(workflow_names), f"missing WORKFLOW.md files: {sorted(expected - workflow_names)}")
    return ["single root skill is the only Codex-discoverable skill", f"{len(workflow_files)} vendored workflow entry files use WORKFLOW.md"]


def check_hook_safety() -> list[str]:
    pack = _json(HOOK_PACK)
    default_enabled = pack.get("default_enabled")
    _require(
        isinstance(default_enabled, bool) and not default_enabled,
        "hook pack must be disabled by default",
    )
    _require(pack.get("enabled_when") == "ARS_CODEX_HOOKS=1", "hook pack must require ARS_CODEX_HOOKS=1")
    hooks = pack.get("hooks", [])
    _require(isinstance(hooks, list), "hooks must be a list")
    for hook in hooks:
        mutates_files = hook.get("mutates_files")
        _require(
            isinstance(mutates_files, bool) and not mutates_files,
            f"hook mutates files: {hook.get('id')}",
        )
        command = hook.get("command", "")
        _require(command.startswith("python3 "), f"hook command must use python3 wrapper: {command}")
        _require("ars_codex_hook.py" in command, f"hook command must use adapter hook wrapper: {command}")
        for pattern in FORBIDDEN_HOOK_PATTERNS:
            _require(not pattern.search(command), f"unsafe hook command pattern {pattern.pattern!r}: {command}")
    return [f"{len(hooks)} hook command(s) are disabled-by-default and pass static safety checks"]


def check_root_hook_supply_chain(plugin_root: Path | None = None) -> list[str]:
    """Bind the installed observational root hooks directly to unique SBOM rows."""

    root = (plugin_root or PLUGIN_ROOT).resolve()
    sbom = _json(root / "SBOM.cdx.json")
    components_raw = sbom.get("components")
    _require(isinstance(components_raw, list), "SBOM components must be a list")
    _narrow(isinstance(components_raw, list), "SBOM components must be a list")
    components: list[object] = cast(list[object], components_raw)
    for relative in ROOT_HOOK_PATHS:
        path = root / relative
        _require(path.is_file() and not path.is_symlink(), f"root hook missing: {relative}")
        observed = hashlib.sha256(path.read_bytes()).hexdigest()
        expected_ref = f"artifact:{relative}"
        rows: list[dict[str, object]] = [
            row
            for row in components
            if isinstance(row, dict)
            and (row.get("name") == relative or row.get("bom-ref") == expected_ref)
        ]
        _require(len(rows) == 1, f"{relative} must have one unique SBOM component")
        row = rows[0]
        _require(
            row.get("name") == relative
            and row.get("bom-ref") == expected_ref
            and row.get("type") == "file",
            f"{relative} SBOM identity is not exact",
        )
        _require(
            row.get("hashes") == [{"alg": "SHA-256", "content": observed}],
            f"{relative} SBOM digest differs from installed root hook bytes",
        )

    pack = _json(root / "hooks/hooks.json")
    hooks_by_event_raw = pack.get("hooks")
    _require(
        isinstance(hooks_by_event_raw, dict)
        and set(hooks_by_event_raw) == {"SessionStart", "SubagentStop", "Stop"},
        "root hook pack must contain only observational lifecycle events",
    )
    _narrow(isinstance(hooks_by_event_raw, dict), "root hook pack events must be a dict")
    hooks_by_event: dict[object, object] = cast(dict[object, object], hooks_by_event_raw)
    command_count = 0
    for event, groups_raw in hooks_by_event.items():
        groups_raw_list = groups_raw
        _require(
            isinstance(groups_raw_list, list) and bool(groups_raw_list),
            f"root hook event is empty: {event}",
        )
        _narrow(isinstance(groups_raw_list, list), f"root hook event groups must be a list: {event}")
        groups: list[object] = cast(list[object], groups_raw_list)
        for group in groups:
            _require(isinstance(group, dict), f"root hook group is invalid: {event}")
            group_dict: dict[str, Any] = cast(dict[str, Any], group)
            commands: list[object] = cast(list[object], group_dict.get("hooks") or [])
            _require(
                isinstance(commands, list) and bool(commands),
                f"root hook commands are empty: {event}",
            )
            for command in commands:
                command_count += 1
                _require(
                    isinstance(command, dict)
                    and command.get("type") == "command"
                    and command.get("command")
                    == 'python3 "${PLUGIN_ROOT}/hooks/arw_hook.py"'
                    and command.get("timeout") == 10,
                    f"root hook command is not the bounded observational handler: {event}",
                )

    handler = (root / "hooks/arw_hook.py").read_text(encoding="utf-8")
    for marker in (
        '"authority": "observational"',
        "parent_controls",
        "admission, retries, provenance, and gates remain parent-owned",
    ):
        _require(marker in handler, f"root hook handler lost authority marker: {marker}")
    # The legacy ``"from arw" not in handler`` substring check was the
    # original detector for ``from arw import ...``.  Codex comment
    # 3882633278 noted that ``import arw.runtime`` slipped past it.  The
    # structural default-deny AST gate below catches that payload *and*
    # every other escape hatch the observation hook should never need
    # (subprocess, exec/eval/getattr, ``os.write``/``os.remove``/etc.,
    # ``Path('x').write_text(...)``, relative imports, syntax errors).
    # The handler is parsed with ``ast.parse`` only — it is never
    # executed by this gate.
    _enforce_root_hook_static_policy(handler)
    return [
        "2 root hook files have unique exact SBOM components",
        f"{command_count} root command(s) remain bounded and observational",
    ]


def check_reviewer_fixture(fixture: Path | None = None) -> list[str]:
    fixture = fixture or CODEX_ROOT / "tests" / "fixtures" / "reviewer_full_independent_sections.md"
    text = fixture.read_text(encoding="utf-8")
    required = [
        "## Independent Reviewer: Methodology",
        "## Independent Reviewer: Domain",
        "## Independent Reviewer: Interdisciplinary",
        "## Independent Reviewer: Devil's Advocate",
        "## Editorial Synthesis",
    ]
    positions = []
    for heading in required:
        position = text.find(heading)
        _require(position >= 0, f"reviewer fixture missing heading: {heading}")
        positions.append(position)
    _require(positions == sorted(positions), "editorial synthesis must appear after independent reviewer sections")
    synthesis = text[positions[-1]:]
    for marker in ("methodology concern retained", "domain concern retained", "devil's advocate dissent retained"):
        _require(marker in synthesis, f"synthesis dropped minority marker: {marker}")
    return ["paper-reviewer full-mode fixture preserves independent reviewer sections before synthesis"]


def check_upstream_lock() -> list[str]:
    package = _json(PACKAGE_MANIFEST)
    sources = {item["name"]: item for item in package["source_repositories"]}
    ars_raw = sources.get("academic-research-skills")
    _require(bool(ars_raw), "package manifest missing academic-research-skills source")
    _narrow(isinstance(ars_raw, dict), "academic-research-skills source must be a dict")
    ars: dict[str, Any] = cast(dict[str, Any], ars_raw)
    commit_raw = ars.get("commit", "")
    _require(isinstance(commit_raw, str), "academic-research-skills commit must be a string")
    commit = commit_raw
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", commit)), f"academic-research-skills lock is not a full SHA: {commit}")
    included_raw = ars.get("included_paths", [])
    _require(isinstance(included_raw, list), "included_paths must be a list")
    included: set[object] = set(cast(list[object], included_raw))
    for path in ("commands", "hooks", "tests", "docs", "shared", "scripts"):
        _require(path in included or any(isinstance(item, str) and path in item for item in included), f"included_paths missing {path}")
    return [f"upstream lock pins academic-research-skills@{commit[:7]}"]


def check_desktop_plugin_bundle() -> list[str]:
    plugin_manifest = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
    plugin_skills = PLUGIN_ROOT / "skills"
    suite_entry = plugin_skills / "academic-research-suite"
    skill_md = suite_entry / "SKILL.md"
    package_manifest = suite_entry / "manifest.json"

    _require(plugin_manifest.is_file(), f"Desktop plugin manifest missing: {plugin_manifest}")
    manifest = _json(plugin_manifest)
    plugin_identity = (
        manifest.get("name"),
        manifest.get("interface", {}).get("displayName"),
    )
    supported_identities = {
        ("ars-codex", "ARS-Codex"),
        ("academic-research-workbench", "Academic Research Workbench"),
    }
    _require(
        plugin_identity in supported_identities,
        "Desktop plugin must identify as ARS-Codex or Academic Research Workbench",
    )
    if manifest.get("name") == "ars-codex":
        _require(
            PLUGIN_ROOT.name == manifest.get("name"),
            "standalone ARS-Codex plugin directory must match plugin manifest name",
        )
    _require(manifest.get("skills") == "./skills/", "Desktop plugin manifest must point at ./skills/")
    _require(plugin_skills.exists(), f"Desktop plugin skills path missing: {plugin_skills}")
    _require(plugin_skills.is_dir(), "Desktop plugin skills path must be a directory")
    _require(not plugin_skills.is_symlink(), "Desktop plugin skills path must not be a symlink")
    _require(suite_entry.is_dir(), "Desktop plugin bundle must include academic-research-suite")
    _require(skill_md.is_file(), "Desktop plugin bundle academic-research-suite is missing SKILL.md")
    _require(package_manifest.is_file(), "Desktop plugin bundle academic-research-suite is missing manifest.json")

    marketplace_path = SUITE_ROOT.parents[1] / ".agents" / "plugins" / "marketplace.json"
    if marketplace_path.is_file():
        marketplace = _json(marketplace_path)
        _require(marketplace.get("name") == "ars-codex", "repo marketplace name must be ars-codex")
        _require(
            marketplace.get("interface", {}).get("displayName") == "ARS-Codex",
            "repo marketplace display name must be ARS-Codex",
        )
        entries = [entry for entry in marketplace.get("plugins", []) if entry.get("name") == "ars-codex"]
        _require(len(entries) == 1, "repo marketplace must contain exactly one ars-codex entry")
        source = entries[0].get("source", {})
        _require(source.get("source") == "local", "ars-codex marketplace source must be local")
        _require(source.get("path") == "./plugins/ars-codex", "ars-codex marketplace path is incorrect")
        policy = entries[0].get("policy", {})
        _require(policy.get("installation") == "AVAILABLE", "ars-codex must be available to install")
        _require(policy.get("authentication") == "ON_INSTALL", "ars-codex auth policy must be ON_INSTALL")
        _require(entries[0].get("category") == "Research", "ars-codex marketplace category must be Research")

    symlinks = sorted(
        str(path.relative_to(PLUGIN_ROOT))
        for path in plugin_skills.rglob("*")
        if path.is_symlink()
    )
    _require(
        not symlinks,
        "Desktop plugin bundle must not contain symlinks: " + ", ".join(symlinks[:20]),
    )
    return [
        f"Desktop plugin identity is valid: {manifest['name']}",
        "Desktop plugin bundle uses a materialized skills directory",
        "academic-research-suite is bundled without symlinks",
    ]


def check_venue_profiles() -> list[str]:
    spec: Any = importlib.util.spec_from_file_location(
        "validate_venue_profiles", VENUE_PROFILE_VALIDATOR
    )
    _require(bool(spec and spec.loader), "cannot load annual venue-profile validator")
    _narrow(spec is not None and spec.loader is not None, "venue profile validator spec must load")
    typed_spec: Any = cast(Any, spec)
    module = importlib.util.module_from_spec(typed_spec)  # type: ignore[arg-type]
    typed_loader: Any = typed_spec.loader
    typed_loader.exec_module(module)
    errors = module.validate_path(VENUE_PROFILES)
    _require(not errors, "annual venue profiles failed validation: " + "; ".join(errors))
    payload: dict[str, Any] = _json(VENUE_PROFILES)
    review_systems_raw = payload.get("review_systems", [])
    venues_raw = payload.get("venues", [])
    _require(
        isinstance(review_systems_raw, list) and isinstance(venues_raw, list),
        "annual venue profiles must list review_systems and venues",
    )
    count = len(cast(list[object], review_systems_raw)) + len(cast(list[object], venues_raw))
    return [f"{count} source-audited annual venue profile(s) pass precedence and provenance checks"]


GATES: dict[str, Callable[[], list[str]]] = {
    "desktop-plugin-bundle": check_desktop_plugin_bundle,
    "manifest": check_manifest,
    "single-root-skill": check_single_root_skill,
    "hook-safety": check_hook_safety,
    "root-hook-supply-chain": check_root_hook_supply_chain,
    "reviewer-fixture": check_reviewer_fixture,
    "upstream-lock": check_upstream_lock,
    "venue-profiles": check_venue_profiles,
}


def run_gate(name: str) -> list[str]:
    return GATES[name]()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gate", choices=sorted([*GATES, "all"]))
    parser.add_argument("--json", action="store_true", help="Emit machine-readable result")
    args = parser.parse_args()

    selected = list(GATES) if args.gate == "all" else [args.gate]
    results: dict[str, Any] = {}
    failed = False
    for name in selected:
        try:
            results[name] = {"ok": True, "messages": run_gate(name)}
        except GateFailure as exc:
            failed = True
            results[name] = {"ok": False, "error": str(exc)}

    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    else:
        for name, result in results.items():
            if result["ok"]:
                print(f"OK {name}: " + "; ".join(result["messages"]))
            else:
                print(f"FAIL {name}: {result['error']}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
