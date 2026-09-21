from __future__ import annotations

import sys
from pathlib import Path

import pytest

from arw.cli import build_parser
from arw.composition import default_router
from arw.kernel.capabilities import CapabilityUnavailable


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


def test_submission_provider_is_optional_when_extension_is_not_importable(tmp_path, monkeypatch) -> None:
    manifest = tmp_path / "plugin.json"
    manifest.write_text(
        '{"interface":{"capabilities":["submission"]}}\n', encoding="utf-8"
    )
    monkeypatch.delitem(sys.modules, "arw_submission_workflow", raising=False)
    monkeypatch.setattr(sys, "path", [item for item in sys.path if "submission-workflow/src" not in item])
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
