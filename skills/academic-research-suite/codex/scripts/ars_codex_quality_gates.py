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
# Exact semantic AST fingerprint allowlist for the root hook handler.
#
# The legacy default-deny AST visitor / provenance / binding machinery
# (Codex 3882633278 + 3883414792) was layered and prone to bypass: any
# new path-binding the visitor didn't recognize was a fresh exploitable
# surface.  The current contract is an **exact semantic AST fingerprint
# allowlist** — the handler bytes must parse to an ``ast.AST`` whose
# canonicalized dump (no attributes, fields annotated) hashes to one of
# the values in :data:`ROOT_HOOK_AST_SHA256_BY_PYTHON` for the running
# Python minor.  This makes comments and blank lines free to change
# while turning every executable, docstring, or string-constant edit
# into a digest mismatch — the closed exploit classes include
# ``import arw.runtime``, ``import os as o``, ``Path('x').write_text``,
# ``Path('x').touch()``, ``temporary = Path('events.jsonl');
# temporary.unlink()``, ``__import__('os')``, ``exec('...')``, and
# any constant edit (``RECEIPT_SCHEMA = '...'`` etc.).
#
# **What this gate is and is not.**
#
# This is a **secondary** defense layered on top of the primary
# integrity check: every root hook file must already be content-bound
# to an exact SBOM row (``hashes[*].content`` must equal the SHA-256
# of the bytes on disk).  The AST fingerprint closes the residual
# "what if the SBOM digest happens to match a malicious payload"
# category by refusing to execute or accept any handler whose AST
# shape differs from the audited one.  The three authority markers
# and the SBOM digest identity remain as independent, additive checks
# performed earlier in :func:`check_root_hook_supply_chain`.
#
# **Python-minor portability.**
#
# The CI matrix is ``python-version: ['3.13', '3.14']`` (see
# ``.github/workflows/ci.yml``).  The current handler's AST dump is
# byte-identical across both minors (verified — the dump is 40240
# chars and the SHA-256 is identical under ``python3.13`` and
# ``python3.14``), so :data:`ROOT_HOOK_AST_SHA256_BY_PYTHON` lists
# the same digest for both entries.  A future AST-shape change in
# either minor must be reflected by recomputing the digest under that
# minor only — never by silently sharing a digest across minors
# without re-verification.  Unsupported Python minors fail closed
# with a clear, audit-friendly message; the gate never silently
# degrades to a weaker check.
#
# **Out of scope (residuals the parent layer must enforce).**
#
#   * Semantic analysis of runtime values produced by the AST-clean
#     primitives (e.g. is the *value* read from ``os.environ`` safe).
#   * Sanitization of any ``additionalContext`` string on the stdout
#     wire.
#   * The exact SBOM digest identity, the three authority markers,
#     and the bounded command shape are enforced by sibling checks
#     earlier in :func:`check_root_hook_supply_chain`.
#
# The handler is **never executed**: this gate uses :func:`ast.parse`
# plus :func:`ast.dump` only.  Syntax errors fail closed.
# ---------------------------------------------------------------------------

ROOT_HOOK_AST_SHA256_BY_PYTHON: dict[tuple[int, int], str] = {
    (3, 13): (
        "aa3873700205ce4a64d6d45ea813a80ee1cf3d18a8681f34a27d7f43cdad37ba"
    ),
    (3, 14): (
        "aa3873700205ce4a64d6d45ea813a80ee1cf3d18a8681f34a27d7f43cdad37ba"
    ),
}


def _root_hook_ast_digest(source: str) -> str:
    """SHA-256 of the canonicalized semantic AST dump for ``source``.

    The digest is the SHA-256 of
    ``ast.dump(ast.parse(source, filename='hooks/arw_hook.py'),
    include_attributes=False, annotate_fields=True)`` encoded as
    UTF-8.  Field-annotated mode makes the output deterministic
    across runs of the same Python minor; ``include_attributes=False``
    strips ``lineno`` / ``col_offset`` / ``end_lineno`` / ``end_col_offset``
    so cosmetic reformatting (e.g. ``black`` / ``ruff format``) does
    not break the fingerprint.  Comments and blank lines never reach
    the parser, so the digest is stable across purely-formatter
    changes; every executable, docstring, or string-constant edit
    does reach the parser and breaks the digest.
    """

    try:
        tree = ast.parse(source, filename="hooks/arw_hook.py")
    except SyntaxError:
        raise GateFailure(
            "root hook handler failed static AST parse (syntax error)"
        ) from None
    dump = ast.dump(tree, include_attributes=False, annotate_fields=True)
    return hashlib.sha256(dump.encode("utf-8")).hexdigest()


def _enforce_root_hook_ast_fingerprint(handler_source: str) -> None:
    """Reject any handler whose semantic AST differs from the audited digest.

    The handler is **never executed**: this function uses
    :func:`ast.parse` plus :func:`ast.dump` only.  The running Python
    minor must appear in :data:`ROOT_HOOK_AST_SHA256_BY_PYTHON`; any
    unsupported minor fails closed with a clear message.  A digest
    mismatch is the only way the actual hook bytes can be rejected
    by this gate.
    """

    observed = _root_hook_ast_digest(handler_source)
    # ``sys.version_info[:2]`` (not ``.major`` / ``.minor``) so the test
    # harness can monkeypatch ``sys.version_info`` with a plain tuple and
    # still exercise the unsupported-minor path deterministically.
    key = sys.version_info[:2]
    expected = ROOT_HOOK_AST_SHA256_BY_PYTHON.get(key)
    if expected is None:
        supported = sorted(ROOT_HOOK_AST_SHA256_BY_PYTHON)
        raise GateFailure(
            "root hook handler AST fingerprint gate is unsupported on "
            f"Python {key[0]}.{key[1]} "
            f"(supported minors: {supported}); refusing to run"
        )
    if observed != expected:
        raise GateFailure(
            "root hook handler AST fingerprint does not match the audited "
            f"digest for Python {key[0]}.{key[1]} (observed "
            f"{observed[:16]}…, expected {expected[:16]}…)"
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
        _require(
            workflow_path.exists(),
            f"workflow path missing for {name}: {workflow['workflow_path']}",
        )
        template = SUITE_ROOT / workflow["agent_template"]
        _require(
            template.exists(),
            f"agent template missing for {name}: {workflow['agent_template']}",
        )
    messages.append(f"{len(manifest['workflows'])} workflows have templates")
    return messages


def check_single_root_skill() -> list[str]:
    root_skill = SUITE_ROOT / "SKILL.md"
    _require(root_skill.exists(), "root SKILL.md missing")
    vendored_skill_files = sorted(ARS_ROOT.rglob("SKILL.md"))
    _require(
        not vendored_skill_files,
        "vendored workflow SKILL.md files would expose duplicate Codex skills: "
        + ", ".join(str(p) for p in vendored_skill_files),
    )
    workflow_files = sorted(ARS_ROOT.glob("*/WORKFLOW.md"))
    workflow_names = {path.parent.name for path in workflow_files}
    expected = {
        "deep-research",
        "academic-paper",
        "academic-paper-reviewer",
        "academic-pipeline",
        "experiment-agent",
    }
    _require(
        expected.issubset(workflow_names),
        f"missing WORKFLOW.md files: {sorted(expected - workflow_names)}",
    )
    return [
        "single root skill is the only Codex-discoverable skill",
        f"{len(workflow_files)} vendored workflow entry files use WORKFLOW.md",
    ]


def check_hook_safety() -> list[str]:
    pack = _json(HOOK_PACK)
    default_enabled = pack.get("default_enabled")
    _require(
        isinstance(default_enabled, bool) and not default_enabled,
        "hook pack must be disabled by default",
    )
    _require(
        pack.get("enabled_when") == "ARS_CODEX_HOOKS=1",
        "hook pack must require ARS_CODEX_HOOKS=1",
    )
    hooks = pack.get("hooks", [])
    _require(isinstance(hooks, list), "hooks must be a list")
    for hook in hooks:
        mutates_files = hook.get("mutates_files")
        _require(
            isinstance(mutates_files, bool) and not mutates_files,
            f"hook mutates files: {hook.get('id')}",
        )
        command = hook.get("command", "")
        _require(
            command.startswith("python3 "),
            f"hook command must use python3 wrapper: {command}",
        )
        _require(
            "ars_codex_hook.py" in command,
            f"hook command must use adapter hook wrapper: {command}",
        )
        for pattern in FORBIDDEN_HOOK_PATTERNS:
            _require(
                not pattern.search(command),
                f"unsafe hook command pattern {pattern.pattern!r}: {command}",
            )
    return [
        f"{len(hooks)} hook command(s) are disabled-by-default and pass static safety checks"
    ]


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
        _require(
            path.is_file() and not path.is_symlink(), f"root hook missing: {relative}"
        )
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
    _narrow(
        isinstance(hooks_by_event_raw, dict), "root hook pack events must be a dict"
    )
    hooks_by_event: dict[object, object] = cast(
        dict[object, object], hooks_by_event_raw
    )
    command_count = 0
    for event, groups_raw in hooks_by_event.items():
        groups_raw_list = groups_raw
        _require(
            isinstance(groups_raw_list, list) and bool(groups_raw_list),
            f"root hook event is empty: {event}",
        )
        _narrow(
            isinstance(groups_raw_list, list),
            f"root hook event groups must be a list: {event}",
        )
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
        _require(
            marker in handler, f"root hook handler lost authority marker: {marker}"
        )
    # The legacy ``"from arw" not in handler`` substring check was the
    # original detector for ``from arw import ...``.  Codex comment
    # 3882633278 noted that ``import arw.runtime`` slipped past it.  The
    # structural default-deny AST gate below catches that payload *and*
    # every other escape hatch the observation hook should never need
    # (subprocess, exec/eval/getattr, ``os.write``/``os.remove``/etc.,
    # ``Path('x').write_text(...)``, relative imports, syntax errors).
    # The handler is parsed with ``ast.parse`` only — it is never
    # executed by this gate.
    _enforce_root_hook_ast_fingerprint(handler)
    return [
        "2 root hook files have unique exact SBOM components",
        f"{command_count} root command(s) remain bounded and observational",
    ]


def check_reviewer_fixture(fixture: Path | None = None) -> list[str]:
    fixture = (
        fixture
        or CODEX_ROOT / "tests" / "fixtures" / "reviewer_full_independent_sections.md"
    )
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
    _require(
        positions == sorted(positions),
        "editorial synthesis must appear after independent reviewer sections",
    )
    synthesis = text[positions[-1] :]
    for marker in (
        "methodology concern retained",
        "domain concern retained",
        "devil's advocate dissent retained",
    ):
        _require(marker in synthesis, f"synthesis dropped minority marker: {marker}")
    return [
        "paper-reviewer full-mode fixture preserves independent reviewer sections before synthesis"
    ]


def check_upstream_lock() -> list[str]:
    package = _json(PACKAGE_MANIFEST)
    sources = {item["name"]: item for item in package["source_repositories"]}
    ars_raw = sources.get("academic-research-skills")
    _require(bool(ars_raw), "package manifest missing academic-research-skills source")
    _narrow(isinstance(ars_raw, dict), "academic-research-skills source must be a dict")
    ars: dict[str, Any] = cast(dict[str, Any], ars_raw)
    commit_raw = ars.get("commit", "")
    _require(
        isinstance(commit_raw, str), "academic-research-skills commit must be a string"
    )
    commit = commit_raw
    _require(
        bool(re.fullmatch(r"[0-9a-f]{40}", commit)),
        f"academic-research-skills lock is not a full SHA: {commit}",
    )
    included_raw = ars.get("included_paths", [])
    _require(isinstance(included_raw, list), "included_paths must be a list")
    included: set[object] = set(cast(list[object], included_raw))
    for path in ("commands", "hooks", "tests", "docs", "shared", "scripts"):
        _require(
            path in included
            or any(isinstance(item, str) and path in item for item in included),
            f"included_paths missing {path}",
        )
    return [f"upstream lock pins academic-research-skills@{commit[:7]}"]


def check_desktop_plugin_bundle() -> list[str]:
    plugin_manifest = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
    plugin_skills = PLUGIN_ROOT / "skills"
    suite_entry = plugin_skills / "academic-research-suite"
    skill_md = suite_entry / "SKILL.md"
    package_manifest = suite_entry / "manifest.json"

    _require(
        plugin_manifest.is_file(), f"Desktop plugin manifest missing: {plugin_manifest}"
    )
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
    _require(
        manifest.get("skills") == "./skills/",
        "Desktop plugin manifest must point at ./skills/",
    )
    _require(
        plugin_skills.exists(), f"Desktop plugin skills path missing: {plugin_skills}"
    )
    _require(plugin_skills.is_dir(), "Desktop plugin skills path must be a directory")
    _require(
        not plugin_skills.is_symlink(),
        "Desktop plugin skills path must not be a symlink",
    )
    _require(
        suite_entry.is_dir(),
        "Desktop plugin bundle must include academic-research-suite",
    )
    _require(
        skill_md.is_file(),
        "Desktop plugin bundle academic-research-suite is missing SKILL.md",
    )
    _require(
        package_manifest.is_file(),
        "Desktop plugin bundle academic-research-suite is missing manifest.json",
    )

    marketplace_path = (
        SUITE_ROOT.parents[1] / ".agents" / "plugins" / "marketplace.json"
    )
    if marketplace_path.is_file():
        marketplace = _json(marketplace_path)
        _require(
            marketplace.get("name") == "ars-codex",
            "repo marketplace name must be ars-codex",
        )
        _require(
            marketplace.get("interface", {}).get("displayName") == "ARS-Codex",
            "repo marketplace display name must be ARS-Codex",
        )
        entries = [
            entry
            for entry in marketplace.get("plugins", [])
            if entry.get("name") == "ars-codex"
        ]
        _require(
            len(entries) == 1,
            "repo marketplace must contain exactly one ars-codex entry",
        )
        source = entries[0].get("source", {})
        _require(
            source.get("source") == "local",
            "ars-codex marketplace source must be local",
        )
        _require(
            source.get("path") == "./plugins/ars-codex",
            "ars-codex marketplace path is incorrect",
        )
        policy = entries[0].get("policy", {})
        _require(
            policy.get("installation") == "AVAILABLE",
            "ars-codex must be available to install",
        )
        _require(
            policy.get("authentication") == "ON_INSTALL",
            "ars-codex auth policy must be ON_INSTALL",
        )
        _require(
            entries[0].get("category") == "Research",
            "ars-codex marketplace category must be Research",
        )

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
    _narrow(
        spec is not None and spec.loader is not None,
        "venue profile validator spec must load",
    )
    typed_spec: Any = cast(Any, spec)
    module = importlib.util.module_from_spec(typed_spec)  # type: ignore[arg-type]
    typed_loader: Any = typed_spec.loader
    typed_loader.exec_module(module)
    errors = module.validate_path(VENUE_PROFILES)
    _require(
        not errors, "annual venue profiles failed validation: " + "; ".join(errors)
    )
    payload: dict[str, Any] = _json(VENUE_PROFILES)
    review_systems_raw = payload.get("review_systems", [])
    venues_raw = payload.get("venues", [])
    _require(
        isinstance(review_systems_raw, list) and isinstance(venues_raw, list),
        "annual venue profiles must list review_systems and venues",
    )
    count = len(cast(list[object], review_systems_raw)) + len(
        cast(list[object], venues_raw)
    )
    return [
        f"{count} source-audited annual venue profile(s) pass precedence and provenance checks"
    ]


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
    parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable result"
    )
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
