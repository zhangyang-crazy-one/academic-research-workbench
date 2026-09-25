"""Fail-closed Grok Bot adaptation layer (not a Codex plugin install)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GROK_BOT = REPOSITORY_ROOT / "grok-bot"
GROK_BOT_DOC = GROK_BOT / "GROK_BOT.md"
STAGE_PLUGIN = REPOSITORY_ROOT / "scripts" / "stage-plugin"
PLUGIN_MANIFEST = REPOSITORY_ROOT / ".codex-plugin" / "plugin.json"
SOURCE_ROUTER = REPOSITORY_ROOT / "skills" / "academic-research-suite" / "SKILL.md"
CANONICAL_REPOSITORY = "https://github.com/zhangyang-crazy-one/academic-research-workbench"
DEEP_RESEARCH = "skills/academic-research-suite/ars/deep-research/WORKFLOW.md"
INSTALL_DEPS = REPOSITORY_ROOT / "scripts" / "install-unmanaged-deps.py"

PORTABLE_SKILLS = (
    GROK_BOT / "skills" / "arw" / "SKILL.md",
    GROK_BOT / "skills" / "arw-route" / "SKILL.md",
    GROK_BOT / "skills" / "arw-literature" / "SKILL.md",
    GROK_BOT / "skills" / "arw-evidence" / "SKILL.md",
)

BUNDLED_POINTERS = (
    "skills/academic-research-suite/SKILL.md",
    "skills/academic-research-suite/ars/deep-research/WORKFLOW.md",
    "skills/academic-research-suite/ars/academic-paper/WORKFLOW.md",
    "skills/academic-research-suite/ars/academic-paper-reviewer/WORKFLOW.md",
    "skills/academic-research-suite/ars/academic-pipeline/WORKFLOW.md",
    "skills/academic-research-suite/ars/experiment-agent/WORKFLOW.md",
    "skills/academic-research-suite/codex/references/science_workbench_mvp.md",
    "skills/literature/SKILL.md",
    "skills/evidence/SKILL.md",
    "skills/audit/SKILL.md",
    "skills/files/SKILL.md",
    "docs/runtime/scientific-integrity.md",
    "schemas/v1/route-result.schema.json",
)

INSTALL_SUCCESS_CLAIMS = (
    "codex plugin marketplace add ./build/marketplace",
    "codex plugin add academic-research-workbench@arw-local",
    "release_qualification` = `PASS`",
    "release_qualification: PASS",
)

ROUTE_REQUIRED_FIELDS = (
    "schema_version",
    "workflow_family",
    "execution_mode",
    "source_adapter_version",
    "source_dependency_model",
    "source_bundled",
    "integration_status",
    "integration_lock_sha256",
    "release_qualification",
    "reason_codes",
    "experiment_execution",
    "paper_ast_export",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalized(body: str) -> str:
    return " ".join(body.split())


def _section(body: str, heading: str) -> str:
    marker = f"{heading}\n"
    assert body.count(marker) == 1, heading
    level = len(heading) - len(heading.lstrip("#"))
    lines = []
    fence = None
    for line in body.split(marker, 1)[1].splitlines():
        delimiter = re.match(r" {0,3}(`{3,}|~{3,})", line)
        if fence is not None:
            if (
                delimiter
                and delimiter.group(1)[0] == fence[0]
                and len(delimiter.group(1)) >= len(fence)
                and not line[delimiter.end() :].strip()
            ):
                fence = None
            lines.append(line)
            continue
        if delimiter:
            fence = delimiter.group(1)
            lines.append(line)
            continue
        if line.startswith("#") and len(line) - len(line.lstrip("#")) <= level:
            break
        lines.append(line)
    return "\n".join(lines)


def _advisory_rows(body: str, heading: str) -> list[tuple[str, str]]:
    section = _section(body, heading)
    rows = []
    for line in section.splitlines():
        if line.startswith("| ") and not line.startswith("| ---"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            assert len(cells) == 2, line
            rows.append((cells[0], cells[1]))
    return rows


def test_section_ignores_headings_inside_fenced_code() -> None:
    body = "## Route\n```bash\n# shell comment\n## not a heading\n```\nkept\n## Next\nexcluded\n"
    section = _section(body, "## Route")
    assert "# shell comment" in section
    assert "## not a heading" in section
    assert "kept" in section
    assert "## Next" not in section


def test_grok_bot_folder_is_consumption_not_plugin_skill() -> None:
    assert GROK_BOT_DOC.is_file()
    assert (GROK_BOT / "README.md").is_file()
    manifest = _read(PLUGIN_MANIFEST)
    assert '"skills": "./skills/"' in manifest
    assert "grok-bot" not in manifest


def test_stage_plugin_allowlist_excludes_grok_bot() -> None:
    text = _read(STAGE_PLUGIN)
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("copy_file", "copy_tree", "copy_as")):
            assert "grok-bot" not in stripped


def test_portable_skills_exist_with_frontmatter() -> None:
    for path in PORTABLE_SKILLS:
        assert path.is_file(), path
        body = _read(path)
        assert body.startswith("---\n")
        assert "name:" in body.split("---", 2)[1]


def test_boundary_doc_states_invocation_and_fail_closed_route() -> None:
    doc = _normalized(_read(GROK_BOT_DOC)).lower()
    assert "not a second" in doc and "plugin" in doc
    assert "codex plugin marketplace" in doc
    assert "local `bin/arw` on the grok box" in doc
    assert "file-base" in doc
    assert "python -m arw.cli route --json" in _read(GROK_BOT_DOC)
    assert "./bin/arw route --json" in _read(GROK_BOT_DOC)
    assert "runtime-artifact-missing" in doc
    assert "academic-pipeline" in doc
    assert "no silent fallback" in doc
    assert "cc by-nc" in doc
    assert "does **not** relicense" in doc
    for field in ROUTE_REQUIRED_FIELDS:
        assert field in _read(GROK_BOT_DOC)


def test_adaptation_does_not_claim_codex_plugin_on_grok() -> None:
    blobs = [_read(GROK_BOT_DOC), *(_read(path) for path in PORTABLE_SKILLS)]
    combined = _normalized("\n".join(blobs))
    lowered = combined.lower()
    for claim in INSTALL_SUCCESS_CLAIMS:
        assert claim.lower() not in lowered
    assert "does **not** work inside grok bot" in lowered
    assert "do not claim grok can run the codex plugin" in lowered
    assert "do not tell the user to `git clone`" in lowered
    assert "do not clone onto the user's machine" in lowered
    assert 'release_qualification` = `"blocked"`' in lowered


def test_bundled_ars_pointers_exist_and_are_not_copied_into_grok_bot() -> None:
    grok_files = {path.relative_to(GROK_BOT).as_posix() for path in GROK_BOT.rglob("*") if path.is_file()}
    assert not any(path.startswith("ars/") or "/ars/" in path for path in grok_files)
    for relative in BUNDLED_POINTERS:
        assert (REPOSITORY_ROOT / relative).is_file(), relative
        mentioned = any(relative in _read(path) for path in (GROK_BOT_DOC, *PORTABLE_SKILLS))
        assert mentioned, relative


def test_route_skill_separates_control_plane_from_advisory_tree() -> None:
    route = _read(GROK_BOT / "skills" / "arw-route" / "SKILL.md")
    plain = _normalized(_section(route, "### Success criteria"))
    advisory = _normalized(_section(route, "## B. Advisory workflow-file tree"))
    assert "exit code `0`" in plain
    assert "stdout is one JSON object" in plain
    assert "`schema_version` = `1.0.0`" in plain
    assert "`workflow_family` = `academic-pipeline`" in plain
    assert "No synthetic `RouteResult`" in plain
    assert "Say **advisory**" in advisory
    assert "do not add families" in advisory.lower()


def test_copied_skills_identify_one_canonical_source_revision() -> None:
    for path in PORTABLE_SKILLS:
        body = _normalized(_read(path))
        assert CANONICAL_REPOSITORY in body, path
        assert "Read the entire `grok-bot/GROK_BOT.md` before using this imported skill" in body, path
        assert "commit SHA" in body, path
        assert "import provenance" in body, path
        assert "same resolved source commit" in body, path
        assert "every portable skill and referenced ARS file" in body, path
        assert "pair CLI output only from that same commit" in body, path
        assert "git rev-parse HEAD" in body, path
        assert "git status --porcelain" in body, path
        assert "to equal the recorded SHA" in body, path
        assert "to be empty" in body, path
        assert "otherwise do not pair its CLI output with this skill import" in body, path
        assert "not a dependency or runtime compatibility pin" in body, path
    boundary = _normalized(_read(GROK_BOT_DOC))
    assert CANONICAL_REPOSITORY in boundary
    assert "grok-bot/GROK_BOT.md" in boundary
    assert "record the repository URL and resolved SHA as import provenance" in boundary
    assert "git rev-parse HEAD" in boundary
    assert "not an exact dependency or runtime compatibility requirement" in boundary
    assert "Parent orchestration owns acceptance" in boundary
    assert "hooks only observe" in boundary


def test_advisory_writing_override_follows_source_router() -> None:
    source = _normalized(_section(_read(SOURCE_ROUTER), "### Paper Topic Scoping Override"))
    assert "before the general paper/pipeline routing rule" in source
    assert "do **not** provide a clear, answerable research question" in source
    assert "`ars/deep-research/WORKFLOW.md` in `socratic` mode first" in source
    for exception in ("clear RQ", "approved study frame", "data/results", "literature matrix", "draft", "explicitly asks to skip scoping"):
        assert exception in source
    for path, heading in (
        (GROK_BOT_DOC, "## Advisory workflow-file tree"),
        (PORTABLE_SKILLS[1], "## B. Advisory workflow-file tree"),
    ):
        body = _read(path)
        section = _normalized(_section(body, heading))
        rows = _advisory_rows(body, heading)
        assert "skills/academic-research-suite/SKILL.md" in section
        assert "override" in section.lower() and "precedence" in section.lower()
        assert "without a clear, answerable research question" in rows[1][0]
        assert rows[1][1] == f"`{DEEP_RESEARCH}` in `socratic` mode first"
        assert "ars-*" in section
        assert "3–5 narrowing questions" in section
        assert "explicit" in section and "skip scoping" in section
        for exception in ("clear research question", "approved study frame", "data/results", "literature matrix", "draft"):
            assert exception in section, (path, exception)


def test_plain_route_and_diagnostics_have_distinct_output_contracts() -> None:
    route = _read(PORTABLE_SKILLS[1])
    plain = _normalized(_section(route, "### Success criteria"))
    diagnostic = _normalized(_section(route, "### Diagnostics are a separate contract"))
    assert "`RouteResult`" in plain
    assert "exit code `0`" in plain
    assert "`arw.integration-diagnostic.v1` object to **stdout**, not a `RouteResult`" in diagnostic
    assert "`0` for `status: PASS` and `65` for `status: BLOCKED`" in diagnostic
    assert "parse and report stdout even if stderr is empty" in diagnostic
    assert "do not discard the diagnostic object or validate it against" in diagnostic
    boundary = _normalized(_section(_read(GROK_BOT_DOC), "## Authoritative CloudAgent route"))
    assert "Plain `route --json` writes a `RouteResult` to stdout" in boundary
    assert "`route --json --diagnostics` writes an `arw.integration-diagnostic.v1` object to stdout" in boundary
    assert "Parse the diagnostics stdout even on exit `65`, including when stderr is empty" in boundary


def test_unmanaged_installer_reads_declared_groups_and_propagates_uv_status(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = importlib.util.spec_from_file_location("install_unmanaged_deps", INSTALL_DEPS)
    assert spec is not None and spec.loader is not None
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    calls = []

    def fake_call(command: list[str], *, cwd: Path) -> int:
        calls.append((command, cwd))
        return 17

    monkeypatch.setattr(installer.subprocess, "call", fake_call)
    monkeypatch.setattr(installer.sys, "argv", [str(INSTALL_DEPS), "--all-extras", "dev", "ars-test"])
    assert installer.main() == 17
    declared_groups = installer.tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text())["dependency-groups"]
    assert calls == [(
        ["uv", "pip", "install", "--python", installer.sys.executable,
         "--editable", ".", "-r", "pyproject.toml", "--all-extras",
         *declared_groups["dev"], *declared_groups["ars-test"]],
        REPOSITORY_ROOT,
    )]


def test_unmanaged_installer_rejects_option_like_group_requirement(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = importlib.util.spec_from_file_location("install_unmanaged_deps_invalid", INSTALL_DEPS)
    assert spec is not None and spec.loader is not None
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    monkeypatch.setattr(installer.sys, "argv", [str(INSTALL_DEPS), "dev"])
    monkeypatch.setattr(installer.tomllib, "load", lambda _: {"dependency-groups": {"dev": ["--index-url", "https://example.invalid"]}})
    monkeypatch.setattr(installer.subprocess, "call", lambda *_args, **_kwargs: pytest.fail("uv must not be called"))
    with pytest.raises(SystemExit) as error:
        installer.main()
    assert error.value.code == 2
