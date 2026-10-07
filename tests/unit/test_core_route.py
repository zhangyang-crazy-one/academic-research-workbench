"""Core routing remains independent of host qualification and fails on drift."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import jsonschema
import pytest

from arw.cli import main
from arw.kernel.policy.core_integrity import (
    CoreIntegrityError,
    _structural_canary_closure,
    verify_staged_core,
)


def test_source_core_route_is_explicitly_unverified(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("ARW_PLUGIN_ROOT", raising=False)
    monkeypatch.delenv("ARW_RUNTIME_MODE", raising=False)
    assert main(["route", "--core", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    jsonschema.validate(report, json.loads((Path(__file__).parents[2] / "schemas/v1/core-route.schema.json").read_text()))
    assert report["core_integrity"] == "UNVERIFIED"
    assert report["execution_adapters"][0]["provider_status"] == "requires_host_qualification"


def test_incomplete_installed_root_blocks_operations(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(tmp_path))
    monkeypatch.setenv("ARW_RUNTIME_MODE", "plugin")
    assert main(["artifact", "inspect", "--root", str(tmp_path), "--path", "paper.txt"]) == 65
    assert json.loads(capsys.readouterr().out)["reason_code"] == "core_integrity_invalid_or_drifted"
    assert main(["route", "--core", "--json"]) == 65
    report = json.loads(capsys.readouterr().out)
    assert report["core_integrity"] == "BLOCKED"
    assert all(row["provider_status"] == "not_evaluated" for row in report["capabilities"])


def test_embedded_canary_requires_structural_refs_without_success_verdict(tmp_path: Path) -> None:
    import hashlib

    from arw.kernel.core.canonical import canonical_json_bytes

    root = tmp_path
    canary = root / "supply-chain/host-canary/canary.json"
    canary.parent.mkdir(parents=True)
    canary.write_text('{}')
    with pytest.raises(CoreIntegrityError, match="reference structure"):
        bundle = canary.parent / "bundle.json"
        bundle.write_bytes(canonical_json_bytes({}))
        canary.write_bytes(canonical_json_bytes({"technical_qualification": "FAIL", "evidence_bundle": {"path": "bundle.json", "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest()}, "fresh_home_receipts": []}))
        _structural_canary_closure(root, {"supply-chain/host-canary/canary.json", "supply-chain/host-canary/bundle.json"})


def test_failed_host_evidence_is_structurally_closed_but_not_qualified(tmp_path: Path) -> None:
    import hashlib

    from arw.kernel.core.canonical import canonical_json_bytes
    from arw.kernel.policy.integration_lock import (
        IntegrationLockError,
        _referenced_host_canary_paths,
    )

    evidence = tmp_path / "supply-chain/host-canary"
    evidence.mkdir(parents=True)
    def write(name: str, content: object) -> dict[str, str]:
        raw = canonical_json_bytes(content)
        (evidence / name).write_bytes(raw)
        return {"path": name, "sha256": hashlib.sha256(raw).hexdigest()}

    receipts = [write(f"receipt-{n}.json", {"status": "unknown"}) for n in range(3)]
    classifications = [
        {"evidence": write(f"parity-{n}.json", {"official_hook_receipt": None})}
        for n in range(5)
    ]
    bundle = write("bundle.json", {"fresh_home_receipts": receipts, "hook_status_classifications": classifications})
    canary = evidence / "canary.json"
    canary.write_bytes(canonical_json_bytes({"technical_qualification": "FAIL", "evidence_bundle": bundle, "fresh_home_receipts": receipts}))
    actual = {path.relative_to(tmp_path).as_posix() for path in evidence.iterdir()}
    _structural_canary_closure(tmp_path, actual)
    with pytest.raises(IntegrationLockError):
        _referenced_host_canary_paths(tmp_path, canary)
    (evidence / "orphan.json").write_bytes(b"{}")
    with pytest.raises(CoreIntegrityError, match="unreferenced"):
        _structural_canary_closure(tmp_path, actual | {"supply-chain/host-canary/orphan.json"})


@pytest.mark.skipif(not os.environ.get("ARW_CORE_TEST_STAGE"), reason="complete retained stage not supplied")
def test_live_core_without_codex_and_tamper(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stage = Path(os.environ["ARW_CORE_TEST_STAGE"])
    assert verify_staged_core(stage)["first_party_wheel_sha256"]
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(stage))
    monkeypatch.setenv("ARW_PLUGIN_MANIFEST", str(stage / ".codex-plugin/plugin.json"))
    monkeypatch.setenv("ARW_RUNTIME_MODE", "plugin")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty-codex-home"))
    # This test imports the checkout source, not the retained stage's older
    # wheel. The direct installed route must reject that origin mismatch.
    assert main(["route", "--core", "--json"]) == 65
    assert json.loads(capsys.readouterr().out)["core_integrity"] == "BLOCKED"
    assert main(["route", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["integration_status"] == "BLOCKED"
    research = tmp_path / "research"
    research.mkdir()
    (research / "paper.txt").write_text("A bounded manuscript.\n")
    source_root = Path(__file__).parents[2]
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(source_root))
    monkeypatch.setenv("ARW_PLUGIN_MANIFEST", str(source_root / ".codex-plugin/plugin.json"))
    monkeypatch.setenv("ARW_RUNTIME_MODE", "agent")
    assert main(["route", "--core", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["core_integrity"] == "UNVERIFIED"
    assert main(["artifact", "inspect", "--root", str(research), "--path", "paper.txt"]) == 0
    assert json.loads(capsys.readouterr().out)["schema_version"]

    stage_temp_parent = Path(__file__).parents[2] / "build/tmp"
    stage_temp_parent.mkdir(parents=True, exist_ok=True)
    copied = Path(tempfile.mkdtemp(prefix="core-route-test-", dir=stage_temp_parent)) / "stage"
    shutil.copytree(stage, copied, copy_function=os.link)
    (copied / "unexpected.txt").write_text("undeclared")
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(copied))
    monkeypatch.setenv("ARW_RUNTIME_MODE", "plugin")
    assert main(["route", "--core", "--json"]) == 65
    assert json.loads(capsys.readouterr().out)["core_integrity"] == "BLOCKED"
    assert main(["artifact", "inspect", "--root", str(research), "--path", "paper.txt"]) == 65
    assert json.loads(capsys.readouterr().out)["reason_code"] == "core_integrity_invalid_or_drifted"
    (copied / "unexpected.txt").unlink()
    import hashlib

    altered = "skills/academic-research-suite/ars/academic-paper/WORKFLOW.md"
    old_content = (copied / altered).read_bytes()
    (copied / altered).unlink()
    (copied / altered).write_bytes(old_content + b"\n")
    changed_sha = hashlib.sha256((copied / altered).read_bytes()).hexdigest()
    for metadata, entries in (
        ("share/arw/build-identity.json", "staged_payloads"),
        ("supply-chain/stage-inventory.json", "covered_files"),
    ):
        path = copied / metadata
        value = json.loads(path.read_text())
        for row in value[entries]:
            if row["path"] == altered:
                row["sha256"] = changed_sha
            if row["path"] == "share/arw/build-identity.json":
                row["sha256"] = hashlib.sha256((copied / "share/arw/build-identity.json").read_bytes()).hexdigest()
        path.unlink()
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    # The two self-declared audit manifests are coherent. The first-party
    # source-tree pin remains independent and rejects the changed ARS bytes.
    with pytest.raises(CoreIntegrityError, match="bundled ARS source tree"):
        verify_staged_core(copied)
    for relative in (altered, "share/arw/build-identity.json", "supply-chain/stage-inventory.json"):
        (copied / relative).unlink()
        shutil.copy2(stage / relative, copied / relative)
    assert verify_staged_core(copied)

    verdict_relative = "supply-chain/license-verdict.json"
    verdict_path = copied / verdict_relative
    verdict = json.loads(verdict_path.read_text())
    verdict["release_qualification"] = "PASS"
    verdict["reason_codes"] = []
    verdict_path.unlink()
    verdict_path.write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n")
    verdict_sha = hashlib.sha256(verdict_path.read_bytes()).hexdigest()
    identity_path = copied / "share/arw/build-identity.json"
    identity = json.loads(identity_path.read_text())
    for row in identity["staged_payloads"]:
        if row["path"] == verdict_relative:
            row["sha256"] = verdict_sha
    identity_path.unlink()
    identity_path.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n")
    inventory_path = copied / "supply-chain/stage-inventory.json"
    inventory = json.loads(inventory_path.read_text())
    for row in inventory["covered_files"]:
        if row["path"] == verdict_relative:
            row["sha256"] = verdict_sha
        elif row["path"] == "share/arw/build-identity.json":
            row["sha256"] = hashlib.sha256(identity_path.read_bytes()).hexdigest()
    inventory_path.unlink()
    inventory_path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
    with pytest.raises(CoreIntegrityError, match="license verdict"):
        verify_staged_core(copied)

    for relative in (verdict_relative, "share/arw/build-identity.json", "supply-chain/stage-inventory.json"):
        (copied / relative).unlink()
        shutil.copy2(stage / relative, copied / relative)
    declaration_relative = "supply-chain/use-distribution.json"
    declaration_path = copied / declaration_relative
    declaration = json.loads(declaration_path.read_text())
    declaration["intended_use"] = {"status": "declared", "value": "internal"}
    declaration_path.unlink()
    declaration_path.write_text(json.dumps(declaration, indent=2, sort_keys=True) + "\n")
    declaration_sha = hashlib.sha256(declaration_path.read_bytes()).hexdigest()
    identity = json.loads(identity_path.read_text())
    for row in identity["staged_payloads"]:
        if row["path"] == declaration_relative:
            row["sha256"] = declaration_sha
    identity_path.unlink()
    identity_path.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n")
    inventory = json.loads(inventory_path.read_text())
    for row in inventory["covered_files"]:
        if row["path"] == declaration_relative:
            row["sha256"] = declaration_sha
        elif row["path"] == "share/arw/build-identity.json":
            row["sha256"] = hashlib.sha256(identity_path.read_bytes()).hexdigest()
    inventory_path.unlink()
    inventory_path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
    with pytest.raises(CoreIntegrityError, match="license verdict blockers"):
        verify_staged_core(copied)
    shutil.rmtree(copied.parent)
