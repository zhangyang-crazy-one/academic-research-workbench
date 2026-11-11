"""Plugin runtime hardening: file-base daemon isolation, manifest gating, and evidence CLI."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from arw.cli import main
from arw.composition import (
    configured_semantic_provider,
    default_router,
    resolve_plugin_manifest,
)
from arw.graph_projection import project_canonical_records
from arw.graph_store import GraphStore
from arw.kernel.capabilities import CapabilityUnavailable
from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex

ROOT = Path(__file__).resolve().parents[2]


def _write_manifest(path: Path, capabilities: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "name": "academic-research-workbench",
                "version": "0.2.1",
                "interface": {"capabilities": capabilities},
            }
        ),
        encoding="utf-8",
    )
    return path


def _make_provider_fixture(tmp_path: Path) -> Path:
    plugin = tmp_path / "plugin"
    for relative in ("scripts/file-base-mcp", "extensions/file-base-mcp/bin/provider"):
        dst = plugin / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, dst)
        dst.chmod(0o755)
    stub = plugin / "libexec/file-base-mcp"
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'{"CBM_RUNTIME_DIR":"%s"}\\n\' "${CBM_RUNTIME_DIR:-}"\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return plugin


def test_provider_isolates_cbm_runtime_dir_and_rejects_unsafe_override(
    tmp_path: Path,
) -> None:
    plugin = _make_provider_fixture(tmp_path)
    launcher = plugin / "scripts/file-base-mcp"
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    long_cache = tmp_path / ("deep-" + "c" * 60) / "cache"
    base_env = {
        "PATH": os.environ["PATH"],
        "CBM_ALLOWED_ROOT": str(allowed),
        "CBM_ALLOWED_ROOT_ID": "research-root",
        "CBM_CACHE_DIR": str(long_cache),
    }
    expected_tag = hashlib.sha256(str(long_cache).encode()).hexdigest()[:12]
    tmp_base = Path("/private/tmp") if Path("/private/tmp").is_dir() else Path("/tmp")
    expected_rt = tmp_base / f"arw-fb-{os.geteuid()}-{expected_tag}"
    try:
        completed = subprocess.run(
            [str(launcher)],
            cwd=tmp_path,
            env=base_env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        observed = Path(json.loads(completed.stdout)["CBM_RUNTIME_DIR"])
        assert observed == expected_rt
        assert len(str(observed)) <= 56
        assert stat.S_IMODE(observed.lstat().st_mode) == 0o700
    finally:
        shutil.rmtree(expected_rt, ignore_errors=True)

    # Relative CBM_RUNTIME_DIR fails closed with exit 64.
    rel_result = subprocess.run(
        [str(launcher)],
        cwd=tmp_path,
        env={**base_env, "CBM_RUNTIME_DIR": "relative-rt"},
        text=True,
        capture_output=True,
        check=False,
    )
    assert rel_result.returncode == 64

    # Symlink CBM_RUNTIME_DIR fails closed with exit 66.
    real_rt = tmp_path / "real-rt"
    real_rt.mkdir(mode=0o700)
    link_rt = tmp_path / "link-rt"
    link_rt.symlink_to(real_rt, target_is_directory=True)
    sym_result = subprocess.run(
        [str(launcher)],
        cwd=tmp_path,
        env={**base_env, "CBM_RUNTIME_DIR": str(link_rt)},
        text=True,
        capture_output=True,
        check=False,
    )
    assert sym_result.returncode == 66


def test_claude_and_codex_plugin_manifests_declare_same_capabilities() -> None:
    codex = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    claude = json.loads(
        (ROOT / "packaging/claude/plugin.json").read_text(encoding="utf-8")
    )
    assert claude["interface"]["capabilities"] == codex["interface"]["capabilities"]
    assert "evidence" in codex["interface"]["capabilities"]


def test_resolve_plugin_manifest_and_capability_gating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Installed mode without ARW_PLUGIN_MANIFEST fails closed.
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(tmp_path / "installed"))
    monkeypatch.delenv("ARW_PLUGIN_MANIFEST", raising=False)
    with pytest.raises(ValueError, match="plugin_manifest_missing"):
        resolve_plugin_manifest()

    # Symlink manifest fails closed.
    real_manifest = _write_manifest(tmp_path / "real.json", ["research"])
    symlink_manifest = tmp_path / "link.json"
    symlink_manifest.symlink_to(real_manifest)
    monkeypatch.setenv("ARW_PLUGIN_MANIFEST", str(symlink_manifest))
    with pytest.raises(ValueError, match="plugin_manifest_unreadable"):
        resolve_plugin_manifest()

    # Manifest omitting provenance/semantic/evidence gates all three commands.
    monkeypatch.setenv("ARW_PLUGIN_MANIFEST", str(real_manifest))
    monkeypatch.delenv("ARW_PLUGIN_ROOT", raising=False)

    with pytest.raises(CapabilityUnavailable, match="knowledge.semantic_search"):
        configured_semantic_provider(
            tmp_path / "store.sqlite3",
            tmp_path / "run",
            tmp_path / "missing-model.bin",
            "0" * 64,
        )

    assert (
        main(
            [
                "provenance",
                "verify",
                "--run-root",
                str(tmp_path / "nonexistent-run"),
                "--store",
                str(tmp_path / "store.sqlite3"),
            ]
        )
        == 65
    )
    assert "knowledge.provenance" in capsys.readouterr().err

    with pytest.raises(CapabilityUnavailable, match="evidence.impact"):
        default_router(plugin_manifest=real_manifest).resolve("evidence.impact")


def test_launcher_resume_memory_handoff_manifest_contract(tmp_path: Path) -> None:
    plugin = tmp_path / "checkout"
    (plugin / "bin").mkdir(parents=True)
    shutil.copy2(ROOT / "bin/arw", plugin / "bin/arw")
    (plugin / "src/arw").mkdir(parents=True)
    (plugin / "src/arw/__init__.py").write_text("", encoding="utf-8")
    (plugin / "src/arw/cli.py").write_text(
        "import json, os, sys\n"
        "if '--help' in sys.argv:\n"
        "    print('usage: arw resume')\n"
        "    raise SystemExit(0)\n"
        "print(json.dumps({'manifest': os.environ.get('ARW_PLUGIN_MANIFEST')}))\n",
        encoding="utf-8",
    )
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path / "home"),
        "ARW_RUNTIME": "agent",
        "ARW_PYTHON": sys.executable,
    }

    # Without .codex-plugin/plugin.json: resume --help and plain resume work,
    # while resume --memory-handoff fails closed with exit 66.
    help_res = subprocess.run(
        [str(plugin / "bin/arw"), "resume", "--help"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert help_res.returncode == 0

    plain_res = subprocess.run(
        [
            str(plugin / "bin/arw"),
            "resume",
            "--run-root",
            "/tmp/r",
            "--request",
            "/tmp/q",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert plain_res.returncode == 0
    assert json.loads(plain_res.stdout)["manifest"] is None

    missing_res = subprocess.run(
        [str(plugin / "bin/arw"), "resume", "--memory-handoff", "mem-1"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert missing_res.returncode == 66
    assert "plugin-manifest-missing" in missing_res.stderr

    # With .codex-plugin/plugin.json present: resume --memory-handoff binds it.
    manifest_file = _write_manifest(
        plugin / ".codex-plugin/plugin.json", ["memory", "research"]
    )
    bound_res = subprocess.run(
        [str(plugin / "bin/arw"), "resume", "--memory-handoff", "mem-1"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert bound_res.returncode == 0, bound_res.stderr
    assert json.loads(bound_res.stdout)["manifest"] == str(manifest_file)


def test_evidence_impact_cli_workflow_and_gating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = json.loads(
        (ROOT / "evals/evidence_revision/public.json").read_text(encoding="utf-8")
    )
    records = [
        dict(record, source_digest=sha256_hex(canonical_json_bytes(record)))
        for record in fixture["records"]
    ]
    before_bytes = canonical_json_bytes(records)
    projection = project_canonical_records(
        records, ledger_watermark=1, ledger_head_sha256=sha256_hex(before_bytes)
    )
    control_root = tmp_path / "control"
    store = GraphStore(control_root, "paper-root")
    store.build(projection)

    case = fixture["rounds"][0]["updates"][0]
    update_path = tmp_path / "update.json"
    update_path.write_text(json.dumps(case["update"]), encoding="utf-8")
    proposals_path = tmp_path / "proposals.json"
    proposals_path.write_text(json.dumps(case["proposed_text"]), encoding="utf-8")

    manifest_with_evidence = _write_manifest(
        tmp_path / "plugin-ok.json", ["evidence", "graph"]
    )
    monkeypatch.setenv("ARW_PLUGIN_MANIFEST", str(manifest_with_evidence))

    code = main(
        [
            "evidence",
            "impact",
            "--control-root",
            str(control_root),
            "--root-id",
            "paper-root",
            "--update",
            str(update_path),
            "--expected-watermark",
            "1",
            "--proposals",
            str(proposals_path),
        ]
    )
    assert code == 0
    checklist = json.loads(capsys.readouterr().out)
    assert checklist["schema_version"] == "arw.evidence-impact-checklist.v1"
    assert checklist["status"] == "review_required"
    assert checklist["accepted_outputs_modified"] is False
    assert checklist["human_review_required"] is True
    assert {c["record_id"] for c in checklist["candidates"]} == set(
        case["labels"]["required_revisions"]
    )

    # Watermark mismatch yields status == "incomplete" and exit 65 without mutating store.
    stale_code = main(
        [
            "evidence",
            "impact",
            "--control-root",
            str(control_root),
            "--root-id",
            "paper-root",
            "--update",
            str(update_path),
            "--expected-watermark",
            "99",
        ]
    )
    assert stale_code == 65
    stale_report = json.loads(capsys.readouterr().out)
    assert stale_report["status"] == "incomplete"

    # Removing "evidence" from plugin manifest blocks the CLI with CapabilityUnavailable.
    manifest_no_evidence = _write_manifest(tmp_path / "plugin-no-ev.json", ["graph"])
    monkeypatch.setenv("ARW_PLUGIN_MANIFEST", str(manifest_no_evidence))
    blocked_code = main(
        [
            "evidence",
            "impact",
            "--control-root",
            str(control_root),
            "--root-id",
            "paper-root",
            "--update",
            str(update_path),
            "--expected-watermark",
            "1",
        ]
    )
    assert blocked_code == 65
    blocked = json.loads(capsys.readouterr().out)
    assert blocked["code"] == "CapabilityUnavailable"


def test_launcher_bootstrap_memoizes_per_invocation_sha_reads() -> None:
    script = (ROOT / "bin/arw").read_text(encoding="utf-8")
    assert "digests: dict[Path, str] = {}" in script
    assert "observed = sha(wheels[0])" in script
