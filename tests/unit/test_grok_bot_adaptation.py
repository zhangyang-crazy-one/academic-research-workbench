"""Fail-closed Grok Bot adaptation layer (not a Codex plugin install)."""

from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GROK_BOT = REPOSITORY_ROOT / "grok-bot"
GROK_BOT_DOC = GROK_BOT / "GROK_BOT.md"
STAGE_PLUGIN = REPOSITORY_ROOT / "scripts" / "stage-plugin"
PLUGIN_MANIFEST = REPOSITORY_ROOT / ".codex-plugin" / "plugin.json"

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
    doc = _read(GROK_BOT_DOC).lower()
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
    combined = "\n".join(blobs)
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
    assert "do not mix them" in route.lower() or "Two layers" in route
    assert "workflow_family` is only `academic-pipeline`" in route or "workflow_family` is only" in route
    assert "No synthetic `RouteResult`" in route or "do **not** emit a synthetic" in _read(GROK_BOT_DOC)
    assert "skills/academic-research-suite/ars/deep-research/WORKFLOW.md" in route
