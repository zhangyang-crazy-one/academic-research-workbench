from __future__ import annotations

import sys
from pathlib import Path

import pytest

from arw.cli import build_parser
from arw.composition import default_router
from arw.kernel.capabilities import CapabilityUnavailable
from arw.kernel.state.submission import (
    DeclarationField,
    SubmissionArtifactReference,
    SubmissionPacket,
)


def test_submission_provider_is_lazy_and_composition_bound(monkeypatch) -> None:
    extension_root = Path(__file__).resolve().parents[2] / "extensions/submission-workflow/src"
    monkeypatch.syspath_prepend(str(extension_root))
    provider = default_router(
        plugin_manifest=Path(__file__).resolve().parents[2] / ".codex-plugin/plugin.json"
    ).resolve("submission.prepare")
    assert type(provider).__name__ == "SubmissionWorkflowService"
    assert provider.__class__.__module__.startswith("arw_submission_workflow")
    assert provider.provider_schema_version == "arw.submission-provider.v1"
    observation = provider.observe_verifier(
        {
            "schema_version": "arw.submission-verifier-observation.v1",
            "observation_id": "observation.plugin",
            "run_id": "run-00000000-0000-4000-8000-000000000901",
            "submission_id": "submission.plugin",
            "packet_manifest_sha256": "a" * 64,
            "verifier_identity": "ars.fixture-verifier",
            "verifier_version": "v1",
            "input_sha256": "b" * 64,
            "coverage": "no checks supplied; observation only",
            "checks": [],
            "observed_at": "2026-09-21T12:00:00Z",
        }
    )
    assert observation.schema_version == "arw.submission-verifier-observation.v1"


def test_submission_provider_accepts_json_array_payloads(monkeypatch) -> None:
    extension_root = Path(__file__).resolve().parents[2] / "extensions/submission-workflow/src"
    monkeypatch.syspath_prepend(str(extension_root))
    provider = default_router(
        plugin_manifest=Path(__file__).resolve().parents[2] / ".codex-plugin/plugin.json"
    ).resolve("submission.prepare")
    manuscript = SubmissionArtifactReference(
        artifact_id="artifact.plugin.manuscript",
        manifest_sha256="a" * 64,
        content_sha256="b" * 64,
        accepting_event_id="evt-00000000-0000-4000-8000-000000000901",
    )
    policy = SubmissionArtifactReference(
        artifact_id="artifact.plugin.policy",
        manifest_sha256="c" * 64,
        content_sha256="d" * 64,
        accepting_event_id="evt-00000000-0000-4000-8000-000000000902",
    )
    not_applicable = DeclarationField(
        status="not_applicable", rationale="Not applicable in this synthetic fixture."
    )
    packet = SubmissionPacket(
        schema_version="arw.submission-packet.v1",
        project_id="project.plugin",
        run_id="run-00000000-0000-4000-8000-000000000901",
        submission_id="submission.plugin.packet",
        packet_version=1,
        journal_id="journal.plugin",
        journal_name="Synthetic Journal",
        article_type="research-article",
        round_number=0,
        manuscript_id="manuscript.plugin",
        manuscript_version="v1",
        manuscript=manuscript,
        components=(
            {
                "component_id": "component.plugin.manuscript",
                "role": "main_manuscript",
                "artifact": manuscript,
                "media_type": "text/markdown",
                "byte_length": 5,
            },
        ),
        policy_snapshot=policy,
        authors=(
            {
                "person_id": "person.plugin",
                "display_name": "Synthetic Author",
                "order": 0,
                "corresponding": True,
                "contributions": ("conceptualization",),
                "funding": not_applicable,
                "conflicts": not_applicable,
                "ethics": not_applicable,
                "data": not_applicable,
                "ai_use": not_applicable,
            },
        ),
        created_at="2026-09-23T00:00:00Z",
        created_by="parent.runtime",
    )

    payload = packet.model_dump(mode="json")
    assert isinstance(payload["components"], list)
    assert isinstance(payload["authors"], list)
    assert provider.prepare(payload) == packet


def test_submission_provider_is_optional_when_extension_is_not_importable(tmp_path, monkeypatch) -> None:
    manifest = tmp_path / "plugin.json"
    manifest.write_text(
        '{"interface":{"capabilities":["submission"]}}\n', encoding="utf-8"
    )
    monkeypatch.setitem(sys.modules, "arw_submission_workflow", None)
    router = default_router(plugin_manifest=manifest)
    try:
        router.resolve("submission.prepare")
    except CapabilityUnavailable:
        pass
    else:
        raise AssertionError("missing optional submission provider was not unavailable")


def test_submission_cli_has_no_submit_route() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["submission", "submit", "--run-root", "/tmp/run"])


def test_submission_cli_exposes_scoped_confirmation_without_submit() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "submission",
            "qualify",
            "--run-root",
            "/tmp/run",
            "--request",
            "/tmp/request.json",
            "--scope",
            "confirmation",
            "--submission-id",
            "submission.demo",
            "--subject-scope",
            "submission:submission.demo:author:person.author:funding",
            "--subject-sha256",
            "a" * 64,
        ]
    )
    assert args.scope == "confirmation"
    assert args.submission_id == "submission.demo"
