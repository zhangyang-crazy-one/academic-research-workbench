"""Offline Agent Skills, routing and archived-import regressions."""

from __future__ import annotations

import hashlib
import json
import runpy
from collections import Counter
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = runpy.run_path(str(ROOT / "scripts/validate-skills"))
SCANNER = runpy.run_path(str(ROOT / "scripts/scan-skill-import"))
validate_skill = VALIDATOR["validate_skill"]
validate_tree = VALIDATOR["validate_tree"]
stage_allowlist = VALIDATOR["stage_allowlist"]


def _skill(tmp_path: Path, frontmatter: str, body: str = "# Example\n") -> Path:
    path = tmp_path / "example" / "SKILL.md"
    path.parent.mkdir()
    path.write_text(f"---\n{frontmatter}---\n\n{body}", encoding="utf-8")
    return path


def _description(name: str) -> str:
    path = ROOT / "skills" / name / "SKILL.md"
    return yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])[
        "description"
    ]


def test_real_skills_match_stage_allowlist_and_structure() -> None:
    allowed = stage_allowlist(ROOT / "scripts/stage-plugin")
    assert allowed == {
        "academic-research-workbench",
        "academic-research-suite",
        "submission",
    }
    errors, warnings = validate_tree(ROOT / "skills", allowed)
    assert errors == []
    assert warnings == []
    stage_script = (ROOT / "scripts/stage-plugin").read_text(encoding="utf-8")
    assert 'copy_tree "skills/academic-research-workbench/references"' in stage_script
    assert (
        'arw_references = project_root / "skills/academic-research-workbench/references"'
        in stage_script
    )


@pytest.mark.parametrize(
    ("frontmatter", "fragment"),
    [
        ("description: present\n", "name must"),
        ("name: other\ndescription: present\n", "does not match"),
        ("name: example\ndescription: ''\n", "description must"),
        ("name: example\ndescription: okay\nname: example\n", "duplicate"),
        ("name: example\ndescription: okay\nmetadata: [bad]\n", "metadata must"),
        (
            "name: example\ndescription: okay\ncompatibility: " + "x" * 501 + "\n",
            "compatibility",
        ),
    ],
)
def test_frontmatter_rejections(
    tmp_path: Path, frontmatter: str, fragment: str
) -> None:
    errors, _ = validate_skill(_skill(tmp_path, frontmatter))
    assert any(fragment in error for error in errors)


def test_description_limit_and_body_warning(tmp_path: Path) -> None:
    path = _skill(
        tmp_path, f"name: example\ndescription: {'x' * 1025}\n", "# Body\n" * 501
    )
    errors, warnings = validate_skill(path)
    assert "description must be 1-1024 characters" in errors
    assert any("recommended at most 500" in warning for warning in warnings)


@pytest.mark.parametrize(
    "target",
    ["references/missing.md", "../outside.md", "/etc/passwd", "file:///etc/passwd"],
)
def test_local_links_must_resolve_within_skill(tmp_path: Path, target: str) -> None:
    path = _skill(tmp_path, "name: example\ndescription: okay\n", f"[link]({target})\n")
    errors, _ = validate_skill(path)
    assert any("file link" in error for error in errors)


def test_stage_allowlist_rejects_unlisted_skill(tmp_path: Path) -> None:
    path = _skill(tmp_path, "name: example\ndescription: okay\n")
    errors, _ = validate_tree(path.parent.parent, {"academic-research-workbench"})
    assert any("absent from stage allowlist" in error for error in errors)


def test_symlinked_skill_directory_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_text(
        "---\nname: example\ndescription: okay\n---\n# Body\n", encoding="utf-8"
    )
    link = tmp_path / "example"
    link.symlink_to(outside, target_is_directory=True)
    errors, _ = validate_skill(link / "SKILL.md")
    assert any("symlink" in error for error in errors)


def test_import_scanner_is_bounded_and_rejects_symlinks(tmp_path: Path) -> None:
    source = tmp_path / "oversized.md"
    source.write_bytes(b"x" * (128 * 1024 + 1))
    with pytest.raises(ValueError, match="byte limit"):
        SCANNER["scan"](source)
    link = tmp_path / "linked.md"
    link.symlink_to(source)
    with pytest.raises(ValueError, match="symlink"):
        SCANNER["scan"](link)


def test_bilingual_routing_corpus_has_disjoint_description_cues() -> None:
    cases = json.loads(
        (ROOT / "tests/fixtures/skill-routing-cases.json").read_text(encoding="utf-8")
    )["cases"]
    assert Counter(case["language"] for case in cases) == {"zh": 30, "en": 30}
    assert len({case["prompt"] for case in cases}) == 60
    descriptions = {
        name: _description(name).casefold()
        for name in stage_allowlist(ROOT / "scripts/stage-plugin")
    }
    for case in cases:
        cue = case["cue"].casefold()
        assert cue in case["prompt"].casefold(), case
        matches = [name for name, desc in descriptions.items() if cue in desc]
        assert matches == [case["route"]], (case, matches)
        assert case["ambiguity"] == "none"
    assert all(len(description) <= 1024 for description in descriptions.values())


def test_ars_progressive_split_keeps_original_contract_and_attribution() -> None:
    suite = ROOT / "skills/academic-research-suite"
    assert len((suite / "SKILL.md").read_text(encoding="utf-8").splitlines()) < 500
    for path, phrase in (
        (
            "codex/references/manuscript_artifact_and_figures.md",
            "## Manuscript Artifact Boundary",
        ),
        ("codex/references/agent_file_index.md", "## Canonical Agent Files"),
    ):
        text = (suite / path).read_text(encoding="utf-8")
        assert phrase in text
        assert "CC BY-NC 4.0" in text
        assert path in (suite / "SKILL.md").read_text(encoding="utf-8")
        assert path in (ROOT / "MODIFICATIONS.md").read_text(encoding="utf-8")


def test_external_source_receipt_and_advisory_boundary() -> None:
    archive = ROOT / "third_party/admissions/k-dense-database-lookup"
    receipt = json.loads(
        (archive / "admission-receipt.json").read_text(encoding="utf-8")
    )
    source = archive / "source-skill.md"
    assert receipt["source"]["commit"] == "49c6e97775eaa18ba791bebe23162a70ae601c18"
    assert (
        receipt["source"]["selected_tree_git_sha1"]
        == "fdb92cf1bf19aa09a7662379cf91e8150338994c"
    )
    assert (
        receipt["source"]["file_sha256"]
        == hashlib.sha256(source.read_bytes()).hexdigest()
    )
    blob = source.read_bytes()
    git_blob = hashlib.sha1(f"blob {len(blob)}\0".encode() + blob).hexdigest()
    assert git_blob == receipt["source"]["file_git_blob_sha1"]
    assert (
        receipt["legal"]["skill_declared_license"]
        == receipt["legal"]["repository_license"]
        == "MIT"
    )
    assert "Copyright (c) 2025 K-Dense Inc." in (archive / "LICENSE.md").read_text(
        encoding="utf-8"
    )
    assert (
        receipt["legal"]["archived_license_sha256"]
        == hashlib.sha256((archive / "LICENSE.md").read_bytes()).hexdigest()
    )
    assert receipt["scan"] == SCANNER["scan"](source)
    assert {
        item["category"] for item in receipt["scan"]["findings"] if item["count"]
    } >= {"shell_execution", "network_access", "credential_access", "self_citation"}
    assert (
        receipt["disposition"]["human"]
        == "user_directed_archive_only_and_reject_direct_staging"
    )
    assert receipt["disposition"]["trusted_admission"] == "pending_human_review"
    assert receipt["disposition"]["staging"] == "source_archive_only"
    assert "third_party/admissions" not in (ROOT / "scripts/stage-plugin").read_text(
        encoding="utf-8"
    )
    advisory = (ROOT / receipt["disposition"]["derivative_path"]).read_text(
        encoding="utf-8"
    )
    assert (
        receipt["disposition"]["derivative_sha256"]
        == hashlib.sha256(advisory.encode("utf-8")).hexdigest()
    )
    assert (
        receipt["disposition"]["scanner_sha256"]
        == hashlib.sha256((ROOT / "scripts/scan-skill-import").read_bytes()).hexdigest()
    )
    for forbidden in (
        "curl",
        "Bash",
        ".env",
        "API_KEY",
        "Always cite",
        "Citing Scientific Agent Skills",
        "```bash",
    ):
        assert forbidden not in advisory
    notice = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "K-Dense" in notice and "MIT License" in notice
    notice_builder = (ROOT / "scripts/license-gate").read_text(encoding="utf-8")
    assert "## K-Dense database-lookup license (preserved)" in notice_builder


def test_generated_notice_includes_advisory_mit_license(tmp_path: Path) -> None:
    create_notices = runpy.run_path(str(ROOT / "scripts/license-gate"))[
        "create_notices"
    ]
    upstream = tmp_path / "upstream-notices.md"
    upstream.write_text("Upstream notice\n", encoding="utf-8")
    manifest = {
        "components": [
            {"id": name, "version": "fixture", "licenses": [{"spdx": license_id}]}
            for name, license_id in (
                ("academic-research-skills", "CC-BY-NC-4.0"),
                ("experiment-agent", "CC-BY-NC-4.0"),
                ("file-base", "MIT"),
            )
        ],
        "patches": [],
    }
    create_notices(upstream, manifest, [], tmp_path)
    generated = (tmp_path / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "K-Dense-AI/scientific-agent-skills" in generated
    assert "Copyright (c) 2025 K-Dense Inc." in generated
    assert "Direct skill staging remains pending human admission" in generated
