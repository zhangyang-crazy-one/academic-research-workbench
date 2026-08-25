from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import arw.cli as cli_module
import arw.integration_lock as integration_lock_module
from arw.canonical import canonical_json_bytes
from arw.hook_contracts import (
    PARITY_SURFACES,
    CodexHookReceipt,
    CodexReceiptControl,
    HookParityMatrix,
)
from arw.integration_lock import (
    CodexHostEvidenceBundle,
    CodexHostCanaryEvidence,
    ControlledResultChannelProof,
    EXPECTED_CODEX_CREDENTIAL_POLICY_SHA256,
    FileBinding,
    FreshHomeReceipt,
    HookParityEvidenceRecord,
    HookStatusClassification,
    IntegrationLockError,
    IsolationProof,
    build_integration_lock,
    diagnose_integration_lock,
    integration_lock_bytes,
    integration_lock_schema_document,
    is_supported_codex_cli_version,
    load_and_verify_integration_lock,
    observe_codex_host,
    observe_hook_definition,
    observe_stage_identity,
    verify_integration_lock,
    write_integration_lock,
)


ARS_COMMIT = "8cc7f8f4cccda721646d9df590b42721c93cba31"
EXPERIMENT_COMMIT = "e291e7dc7ca268b2de7e1a9cf23bc2eef5dc0651"
FILE_BASE_COMMIT = "ee68144af5453addda995a27cce8142999f318fb"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _write(path: Path, value: bytes | str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, str):
        path.write_text(value, encoding="utf-8")
    else:
        path.write_bytes(value)
    if executable:
        path.chmod(0o755)


def _json(path: Path, value: object) -> None:
    _write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("value", "supported"),
    [
        ("codex-cli 0.144.3", False),
        ("codex-cli 0.144.4", True),
        ("codex-cli 0.144.5", True),
        ("codex-cli 0.147.0", True),
        ("codex-cli 1.0.0", True),
        ("codex-cli 0.144.4+build.1", True),
        ("codex-cli 0.144.7-rc.1", False),
        ("codex-cli malformed", False),
    ],
)
def test_codex_cli_minimum_version_range(value: str, supported: bool) -> None:
    assert is_supported_codex_cli_version(value) is supported


def test_codex_host_observation_accepts_one_stable_version_amid_diagnostics(
    tmp_path: Path,
) -> None:
    launcher = tmp_path / "host/codex"
    native = tmp_path / "host/codex-native"
    _write(
        launcher,
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"--version\" ]; then\n"
        "  printf '%s\\n' 'hook: SessionStart' 'codex-cli 0.147.0' 'hook: Stop'\n"
        "  printf '%s\\n' 'non-fatal nested diagnostic' >&2\n"
        "  exit 0\n"
        "fi\n"
        "exit 64\n",
        executable=True,
    )
    _write(native, "#!/bin/sh\nexit 0\n", executable=True)

    observed = observe_codex_host(launcher, native)

    assert observed.cli_version == "codex-cli 0.147.0"


def test_codex_host_observation_rejects_ambiguous_version_lines(tmp_path: Path) -> None:
    launcher = tmp_path / "host/codex"
    native = tmp_path / "host/codex-native"
    _write(
        launcher,
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"--version\" ]; then\n"
        "  printf '%s\\n' 'codex-cli 0.147.0' 'codex-cli 0.148.0'\n"
        "  exit 0\n"
        "fi\n"
        "exit 64\n",
        executable=True,
    )
    _write(native, "#!/bin/sh\nexit 0\n", executable=True)

    with pytest.raises(IntegrationLockError, match="exactly one stable version"):
        observe_codex_host(launcher, native)


def _component(
    component_id: str,
    revision: str,
    git_tree: str,
    tree_sha256: str,
    upstream_url: str,
) -> dict[str, object]:
    return {
        "id": component_id,
        "version": "pinned",
        "revision": revision,
        "git_tree": git_tree,
        "tree_sha256": tree_sha256,
        "upstream_url": upstream_url,
    }


def _make_wheel(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = (
        "Metadata-Version: 2.4\n"
        "Name: academic-research-workbench\n"
        "Version: 0.1.0\n"
        "\n"
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("arw/__init__.py", "__version__ = '0.1.0'\n")
        archive.writestr("arw/integration_lock.py", "# packaged verifier\n")
        archive.writestr(
            "academic_research_workbench-0.1.0.dist-info/METADATA", metadata
        )


@pytest.fixture
def integration_fixture(tmp_path: Path) -> dict[str, Path]:
    stage = tmp_path / "stage"
    external = stage / "skills/academic-research-suite"
    stage.mkdir()
    external.mkdir(parents=True)

    _write(
        stage / "pyproject.toml",
        "[project]\n"
        "name = \"academic-research-workbench\"\n"
        "version = \"0.1.0\"\n",
    )
    _json(
        stage / ".codex-plugin/plugin.json",
        {"name": "academic-research-workbench", "version": "0.1.0"},
    )
    _write(stage / "bin/arw", "#!/bin/sh\nexit 0\n", executable=True)
    _make_wheel(
        stage
        / "vendor/python/wheelhouse/academic_research_workbench-0.1.0-py3-none-any.whl"
    )
    _write(stage / "hooks/hooks.json", '{"hooks": {}}\n')
    _write(stage / "hooks/arw_hook.py", "#!/usr/bin/env python3\n", executable=True)

    binary = stage / "libexec/file-base-mcp"
    _write(binary, b"file-base-binary", executable=True)
    repository_manifest = json.loads(
        (REPOSITORY_ROOT / "vendor/source-manifest.json").read_text(encoding="utf-8")
    )
    patches = repository_manifest["patches"]
    for patch in patches:
        source = REPOSITORY_ROOT / patch["path"]
        destination = stage / patch["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    source_manifest = {
        "components": [
            _component(
                "academic-research-skills",
                ARS_COMMIT,
                "43b7ad965778b363b3ba1cfe3d5f3884dd29b417",
                "a401bec5f0bda52d256ee1792cbea8cf63ce6cbe02eb363ed4b790212d0c853e",
                "https://github.com/Imbad0202/academic-research-skills.git",
            ),
            _component(
                "experiment-agent",
                EXPERIMENT_COMMIT,
                "166734509cf5057e48a7f81ecce9e44573610636",
                "2985b59589805267cf1b268a126162ffd3689d0f31840a2de41b004471128bae",
                "https://github.com/Imbad0202/experiment-agent.git",
            ),
            _component(
                "file-base",
                FILE_BASE_COMMIT,
                "de88f52c6614473d04aa1596304a328ef91267e8",
                "4a1ffaa7468026293758327f143d0cfc9f7046e69bd7224efcbd63290fe059d3",
                "https://github.com/DeusData/codebase-memory-mcp.git",
            ),
        ],
        "patches": patches,
    }
    _json(stage / "vendor/source-manifest.json", source_manifest)
    _json(
        stage / "vendor/mcp-manifest.json",
        {
            "schema_version": "arw.mcp-integration-manifest.v1",
            "name": "codebase-memory-mcp",
            "arw_component_id": "file-base",
            "upstream_url": "https://github.com/DeusData/codebase-memory-mcp.git",
            "upstream_commit": FILE_BASE_COMMIT,
            "upstream_git_tree": "de88f52c6614473d04aa1596304a328ef91267e8",
            "upstream_source_tree_sha256": "4a1ffaa7468026293758327f143d0cfc9f7046e69bd7224efcbd63290fe059d3",
            "patched_source_tree_sha256": patches[-1]["post_tree_sha256"],
            "source_materialization": "vendor/sources/file-base",
            "binary": {
                "path": ".file-base/bin/file-base",
                "staged_path": "libexec/file-base-mcp",
                "sha256": _digest(binary),
            },
            "patches": [
                {"order": patch["order"], "path": patch["path"], "sha256": patch["sha256"]}
                for patch in patches
            ],
            "protocol": "MCP-2025-11-25-stdio",
            "capabilities": ["bounded-list-files"],
            "license": "MIT",
        },
    )
    _json(
        stage / ".file-base/build-evidence.json",
        {
            "schema_version": "1.0.0",
            "component": {"id": "file-base", "revision": FILE_BASE_COMMIT},
            "binary": {
                "path": ".file-base/bin/file-base",
                "sha256": _digest(binary),
            },
            "patches": [
                {key: patch[key] for key in ("order", "path", "sha256")}
                for patch in patches
            ],
            "post_patch_tree_sha256": patches[-1]["post_tree_sha256"],
        },
    )

    _json(
        stage / "supply-chain/use-distribution.json",
        {
            "schema_version": "1.0.0",
            "intended_use": {"status": "unknown"},
            "distribution_class": {"status": "unknown"},
            "accountable_approval": {"status": "missing"},
            "repository_visibility": "public",
            "private_repository_is_noncommercial_evidence": False,
            "permission_references": [],
            "evidence_hashes": [
                {
                    "path": "SBOM.cdx.json",
                    "purpose": "technical-provenance-only",
                    "sha256": "1" * 64,
                }
            ],
        },
    )
    _json(
        stage / "supply-chain/license-verdict.json",
        {
            "schema_version": "1.0.0",
            "technical_qualification": "PASS",
            "release_qualification": "BLOCKED",
            "reason_codes": [
                "INTENDED_USE_UNKNOWN",
                "DISTRIBUTION_CLASS_UNKNOWN",
                "ACCOUNTABLE_APPROVAL_MISSING",
                "CC_BY_NC_PERMISSION_UNRESOLVED",
            ],
            "use_distribution_path": "supply-chain/use-distribution.json",
        },
    )

    _write(external / "VERSION", "0.1.26\n")
    _write(
        external / "SKILL.md",
        "---\n"
        "name: academic-research-suite\n"
        "metadata:\n"
        "  version: \"0.1.26\"\n"
        "---\n"
        "# ARS\n",
    )
    _json(
        external / "manifest.json",
        {
            "name": "academic-research-suite",
            "adapter_version": "0.1.26",
            "source_repositories": [
                {
                    "name": "academic-research-skills",
                    "commit": ARS_COMMIT,
                },
                {"name": "experiment-agent", "commit": EXPERIMENT_COMMIT},
            ],
        },
    )
    _write(external / "ars/academic-pipeline/WORKFLOW.md", "# Pipeline\n")

    launcher = tmp_path / "host/codex"
    native = tmp_path / "host/codex-native"
    _write(
        launcher,
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"--version\" ]; then\n"
        "  printf 'codex-cli 0.144.6\\n'\n"
        "  exit 0\n"
        "fi\n"
        "exit 64\n",
        executable=True,
    )
    _write(native, "#!/bin/sh\nexit 0\n", executable=True)

    host = observe_codex_host(launcher, native)
    _, _, definition = observe_hook_definition(stage)
    canary = tmp_path / "evidence/codex-host-canary.json"
    canary.parent.mkdir(parents=True)
    arw_runtime_sha256 = _digest(
        stage
        / "vendor/python/wheelhouse/academic_research_workbench-0.1.0-py3-none-any.whl"
    )
    stage_sha256 = observe_stage_identity(stage)
    credential_policy_sha256 = EXPECTED_CODEX_CREDENTIAL_POLICY_SHA256
    receipt_bindings = []
    for index in range(1, 4):
        receipt_path = canary.parent / f"fresh-home-{index}.json"
        receipt = FreshHomeReceipt(
            schema_version="arw.codex-fresh-home-receipt.v1",
            home_ordinal=index,
            home_identity_sha256=str(index) * 64,
            codex_home_identity_sha256=str(index + 3) * 64,
            codex_thread_id=f"thread-{index:03d}",
            host_agent_id=f"host-{index:03d}",
            expected_assignment_id="assignment.canary",
            observed_assignment_id="assignment.canary",
            expected_attempt_id=f"attempt.canary-{index:03d}",
            observed_attempt_id=f"attempt.canary-{index:03d}",
            expected_proposal_nonce=f"nonce.canary-{index:03d}",
            observed_proposal_nonce=f"nonce.canary-{index:03d}",
            codex_host_tuple_sha256=host.tuple_sha256,
            arw_runtime_sha256=arw_runtime_sha256,
            stage_sha256=stage_sha256,
            hook_definition_sha256=definition,
            hook_execution_admission="automation_vetted_bypass",
            credential_policy_sha256=credential_policy_sha256,
            result_channel=ControlledResultChannelProof(
                channel_kind="codex-add-dir",
                channel_scope_sha256=("9", "a", "b")[index - 1] * 64,
                proposal_sha256=("c", "d", "e")[index - 1] * 64,
                write_observed=True,
                outside_scope_write_observed=False,
                status="PASS",
            ),
            isolation=IsolationProof(
                home_isolated=True,
                codex_home_isolated=True,
                cross_home_read_observed=False,
                unrelated_write_observed=False,
                status="PASS",
            ),
            credential_material_retained=False,
            secret_material_retained=False,
            absolute_path_material_retained=False,
        )
        receipt_path.write_bytes(canonical_json_bytes(receipt.model_dump(mode="json")))
        receipt_bindings.append(
            FileBinding.from_path(canary.parent, f"fresh-home-{index}.json")
        )
    receipt_payload = {
        "schema_version": "arw.codex-hook-observation.v1",
        "authority": "observational",
        "hook_event_name": "SessionStart",
        "input_sha256": "1" * 64,
        "hook_definition_sha256": definition,
        "plugin_root_sha256": "2" * 64,
        "session_id_sha256": "3" * 64,
        "turn_id_sha256": None,
        "subject_id_sha256": None,
        "agent_type_sha256": None,
        "model_sha256": "4" * 64,
        "cwd_sha256": "5" * 64,
        "permission_mode": "bypassPermissions",
        "source": "startup",
        "stop_hook_active": None,
        "status": "observed",
        "redacted_error_code": None,
        "parent_controls": tuple(
            CodexReceiptControl(
                surface=surface,
                parent_enforced=True,
                hook_bypass_safe=True,
            )
            for surface in PARITY_SURFACES
        ),
    }
    receipt_sha256 = hashlib.sha256(
        canonical_json_bytes(
            {
                key: (
                    [item.model_dump(mode="json") for item in value]
                    if key == "parent_controls"
                    else value
                )
                for key, value in receipt_payload.items()
            }
        )
    ).hexdigest()
    official_receipt = CodexHookReceipt(
        **receipt_payload,
        receipt_sha256=receipt_sha256,
    )
    official_receipt_path = canary.parent / f"{receipt_sha256}.json"
    official_receipt_path.write_bytes(
        canonical_json_bytes(official_receipt.model_dump(mode="json"))
    )
    official_receipt_binding = FileBinding.from_path(
        canary.parent, official_receipt_path.name
    )

    classifications_list = []
    authority_digest = "6" * 64
    for state, observation, parity_status in (
        ("trusted_enabled", "observed", "trusted_enabled"),
        ("disabled", "not_observed", "disabled"),
        ("untrusted", "not_observed", "untrusted"),
        ("timeout", "timed_out", "timeout"),
        ("failure", "failed", "failed"),
    ):
        parity_record = HookParityEvidenceRecord(
            schema_version="arw.hook-parity-evidence.v1",
            hook_state=state,
            observation=observation,
            hook_definition_sha256=definition,
            stage_sha256=stage_sha256,
            parity=HookParityMatrix.for_status(
                parity_status, authority_digest=authority_digest
            ),
            official_hook_receipt=(
                official_receipt_binding if state == "trusted_enabled" else None
            ),
            secret_material_retained=False,
            absolute_path_material_retained=False,
        )
        parity_bytes = canonical_json_bytes(parity_record.model_dump(mode="json"))
        parity_sha256 = hashlib.sha256(parity_bytes).hexdigest()
        parity_path = canary.parent / f"{parity_sha256}.json"
        parity_path.write_bytes(parity_bytes)
        classifications_list.append(
            HookStatusClassification(
                hook_state=state,
                observation=observation,
                classification_basis="parity_policy",
                parent_authority_unchanged=True,
                evidence=FileBinding.from_path(canary.parent, parity_path.name),
            )
        )
    classifications = tuple(classifications_list)
    bundle = CodexHostEvidenceBundle(
        schema_version="arw.codex-host-evidence-bundle.v1",
        technical_qualification="PASS",
        codex_host_tuple_sha256=host.tuple_sha256,
        arw_runtime_sha256=arw_runtime_sha256,
        stage_sha256=stage_sha256,
        hook_definition_sha256=definition,
        hook_execution_admission="automation_vetted_bypass",
        live_hook_execution="observed",
        fresh_home_default_trust="untrusted_skipped",
        credential_policy_sha256=credential_policy_sha256,
        fresh_home_receipts=tuple(receipt_bindings),
        hook_status_classifications=classifications,
        secret_material_retained=False,
        absolute_path_material_retained=False,
    )
    (canary.parent / "evidence-bundle.json").write_bytes(
        canonical_json_bytes(bundle.model_dump(mode="json"))
    )
    evidence = CodexHostCanaryEvidence(
        schema_version="arw.codex-host-canary.v1",
        technical_qualification="PASS",
        codex_host_tuple_sha256=host.tuple_sha256,
        arw_runtime_sha256=arw_runtime_sha256,
        stage_sha256=stage_sha256,
        hook_definition_sha256=definition,
        hook_execution_admission="automation_vetted_bypass",
        live_hook_execution="observed",
        fresh_home_default_trust="untrusted_skipped",
        credential_policy_sha256=credential_policy_sha256,
        three_home_isolation="PASS",
        assignment_identity_mapping="PASS",
        credential_hygiene="PASS",
        controlled_result_channel="PASS",
        hook_status_classification="PASS",
        evidence_bundle=FileBinding.from_path(canary.parent, "evidence-bundle.json"),
        fresh_home_receipts=tuple(receipt_bindings),
        secret_material_retained=False,
        absolute_path_material_retained=False,
    )
    canary.write_bytes(canonical_json_bytes(evidence.model_dump(mode="json")))
    return {
        "stage": stage,
        "external": external,
        "launcher": launcher,
        "native": native,
        "canary": canary,
        "lock": tmp_path / "integration-lock.json",
    }


def _build(paths: dict[str, Path]):
    return build_integration_lock(
        stage_root=paths["stage"],
        codex_launcher=paths["launcher"],
        codex_native_binary=paths["native"],
        host_canary_evidence=paths["canary"],
    )


def _verify(paths: dict[str, Path], lock):
    return verify_integration_lock(
        lock,
        stage_root=paths["stage"],
        codex_launcher=paths["launcher"],
        codex_native_binary=paths["native"],
        host_canary_evidence=paths["canary"],
    )


def _refresh_evidence_bindings(paths: dict[str, Path]) -> None:
    evidence_root = paths["canary"].parent
    receipt_bindings = [
        {
            "path": f"fresh-home-{index}.json",
            "sha256": _digest(evidence_root / f"fresh-home-{index}.json"),
        }
        for index in range(1, 4)
    ]
    bundle_path = evidence_root / "evidence-bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["fresh_home_receipts"] = receipt_bindings
    bundle_path.write_bytes(canonical_json_bytes(bundle))
    canary = json.loads(paths["canary"].read_text(encoding="utf-8"))
    canary["fresh_home_receipts"] = receipt_bindings
    canary["evidence_bundle"] = {
        "path": "evidence-bundle.json",
        "sha256": _digest(bundle_path),
    }
    paths["canary"].write_bytes(canonical_json_bytes(canary))


def test_exact_external_integration_lock_round_trips_and_retains_legal_block(
    integration_fixture: dict[str, Path],
) -> None:
    lock = _build(integration_fixture)
    assert lock.ars.adapter_version == "0.1.26"
    assert lock.ars.bundled is True
    assert lock.ars.source_repositories[0].commit == ARS_COMMIT
    assert lock.file_base.commit == FILE_BASE_COMMIT
    assert [patch.order for patch in lock.file_base.ordered_patches] == [1, 2, 3, 4]
    assert lock.technical_qualification == "PASS"
    assert lock.release_qualification == "BLOCKED"
    assert lock.hook.hook_execution_admission == "automation_vetted_bypass"
    assert lock.hook.live_hook_execution == "observed"
    assert lock.hook.fresh_home_default_trust == "untrusted_skipped"
    assert lock.license.reason_codes[-1] == "CC_BY_NC_PERMISSION_UNRESOLVED"

    digest = write_integration_lock(integration_fixture["lock"], lock)
    assert digest == hashlib.sha256(integration_lock_bytes(lock)).hexdigest()
    receipt = load_and_verify_integration_lock(
        integration_fixture["lock"],
        stage_root=integration_fixture["stage"],
        codex_launcher=integration_fixture["launcher"],
        codex_native_binary=integration_fixture["native"],
        host_canary_evidence=integration_fixture["canary"],
    )
    assert receipt.technical_qualification == "PASS"
    assert receipt.release_qualification == "BLOCKED"


def test_same_upstream_commit_does_not_hide_adapter_version_drift(
    integration_fixture: dict[str, Path],
) -> None:
    manifest = json.loads(
        (integration_fixture["external"] / "manifest.json").read_text(encoding="utf-8")
    )
    manifest["adapter_version"] = "0.1.19"
    _json(integration_fixture["external"] / "manifest.json", manifest)
    with pytest.raises(IntegrationLockError, match="version identities disagree"):
        _build(integration_fixture)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("manifest", "version identities disagree"),
        ("version", "version identities disagree"),
        ("router", "version identities disagree"),
            ("local-only", "canary covered another live stage identity"),
        ("upstream-commit", "bundled ARS commits"),
    ],
)
def test_bundled_ars_identity_mismatches_fail_closed(
    integration_fixture: dict[str, Path], mutation: str, message: str
) -> None:
    """Every bundled ARS identity surface is independently lock-bound."""

    lock = _build(integration_fixture)
    external = integration_fixture["external"]
    if mutation == "manifest":
        manifest = json.loads((external / "manifest.json").read_text(encoding="utf-8"))
        manifest["adapter_version"] = "0.1.19"
        _json(external / "manifest.json", manifest)
    elif mutation == "version":
        _write(external / "VERSION", "0.1.19\n")
    elif mutation == "router":
        _write(
            external / "SKILL.md",
            "---\nname: academic-research-suite\nmetadata:\n"
            "  version: \"0.1.19\"\n---\n",
        )
    elif mutation == "local-only":
        _write(external / "ars/academic-pipeline/WORKFLOW.md", "# changed\n")
    else:
        manifest = json.loads((external / "manifest.json").read_text(encoding="utf-8"))
        manifest["source_repositories"][0]["commit"] = "0" * 40
        _json(external / "manifest.json", manifest)

    with pytest.raises(IntegrationLockError, match=message):
        _verify(integration_fixture, lock)


def test_bundled_ars_root_must_be_present_and_not_a_symlink(
    integration_fixture: dict[str, Path],
) -> None:
    lock = _build(integration_fixture)
    bundled = integration_fixture["external"]
    backup = bundled.parent / "ars-real"
    bundled.rename(backup)
    missing = integration_fixture["stage"] / "skills/academic-research-suite"
    with pytest.raises(IntegrationLockError, match="bundled ARS"):
        verify_integration_lock(
            lock,
            stage_root=integration_fixture["stage"],
            codex_launcher=integration_fixture["launcher"],
            codex_native_binary=integration_fixture["native"],
            host_canary_evidence=integration_fixture["canary"],
        )

    symlink = integration_fixture["stage"] / "skills/academic-research-suite"
    symlink.symlink_to(backup, target_is_directory=True)
    with pytest.raises(IntegrationLockError, match="bundled ARS"):
        verify_integration_lock(
            lock,
            stage_root=integration_fixture["stage"],
            codex_launcher=integration_fixture["launcher"],
            codex_native_binary=integration_fixture["native"],
            host_canary_evidence=integration_fixture["canary"],
        )


@pytest.mark.parametrize(
    ("target", "kind"),
    [
        ("external:ars/academic-pipeline/WORKFLOW.md", "append"),
        (
            "stage:vendor/python/wheelhouse/"
            "academic_research_workbench-0.1.0-py3-none-any.whl",
            "append",
        ),
        ("stage:libexec/file-base-mcp", "append"),
        (
            "stage:vendor/patches/file-base/0001-file-base-server-name.patch",
            "append",
        ),
        ("stage:hooks/hooks.json", "append"),
        ("stage:hooks/arw_hook.py", "append"),
        ("stage:supply-chain/use-distribution.json", "append"),
        ("launcher:", "append"),
        ("native:", "append"),
        ("canary:", "append"),
    ],
)
def test_any_bound_runtime_or_evidence_drift_fails_closed(
    integration_fixture: dict[str, Path], target: str, kind: str
) -> None:
    del kind
    lock = _build(integration_fixture)
    key, relative = target.split(":", 1)
    base = integration_fixture[key]
    path = base / relative if relative else base
    original_mode = path.stat().st_mode
    path.write_bytes(path.read_bytes() + b"\ndrift\n")
    path.chmod(original_mode)
    with pytest.raises(IntegrationLockError):
        _verify(integration_fixture, lock)


def test_ordered_patch_digest_drift_fails_before_lock_acceptance(
    integration_fixture: dict[str, Path],
) -> None:
    lock = _build(integration_fixture)
    path = integration_fixture["stage"] / "vendor/source-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["patches"][1]["sha256"] = "9" * 64
    _json(path, manifest)
    with pytest.raises(IntegrationLockError, match="patch.*drift"):
        _verify(integration_fixture, lock)


def test_upstream_commit_tree_and_digest_are_all_pinned(
    integration_fixture: dict[str, Path],
) -> None:
    lock = _build(integration_fixture)
    path = integration_fixture["stage"] / "vendor/source-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["components"][0]["tree_sha256"] = "f" * 64
    _json(path, manifest)
    with pytest.raises(IntegrationLockError, match="source tree"):
        _verify(integration_fixture, lock)


def test_any_retained_fresh_home_receipt_drift_fails_closed(
    integration_fixture: dict[str, Path],
) -> None:
    lock = _build(integration_fixture)
    receipt = integration_fixture["canary"].parent / "fresh-home-2.json"
    receipt.write_bytes(receipt.read_bytes() + b"\ndrift\n")
    with pytest.raises(IntegrationLockError, match="digest drift"):
        _verify(integration_fixture, lock)


def test_bundled_dependency_cannot_be_missing_or_drifted(
    integration_fixture: dict[str, Path],
) -> None:
    shutil.rmtree(integration_fixture["external"] / "ars")
    with pytest.raises(IntegrationLockError):
        _build(integration_fixture)

    _write(
        integration_fixture["external"] / "ars/academic-pipeline/WORKFLOW.md",
        "# restored\n",
    )
    _write(
        integration_fixture["external"] / "ars/academic-pipeline/WORKFLOW.md",
        "# restored\n",
    )
    _write(integration_fixture["external"] / "SKILL.md", "# drifted\n")
    with pytest.raises(IntegrationLockError, match="router metadata version"):
        _build(integration_fixture)


def test_caller_supplied_host_booleans_cannot_replace_retained_canary(
    integration_fixture: dict[str, Path],
) -> None:
    evidence = json.loads(integration_fixture["canary"].read_text(encoding="utf-8"))
    evidence["three_home_isolation"] = False
    _json(integration_fixture["canary"], evidence)
    with pytest.raises(IntegrationLockError, match="canary is invalid"):
        _build(integration_fixture)


def test_receipts_are_parsed_as_canonical_records_not_opaque_digests(
    integration_fixture: dict[str, Path],
) -> None:
    receipt = integration_fixture["canary"].parent / "fresh-home-1.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    receipt.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _refresh_evidence_bindings(integration_fixture)
    with pytest.raises(IntegrationLockError, match="not canonical JSON"):
        _build(integration_fixture)


def test_evidence_bundle_must_itself_be_canonical_strict_json(
    integration_fixture: dict[str, Path],
) -> None:
    bundle_path = integration_fixture["canary"].parent / "evidence-bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle_path.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    canary = json.loads(integration_fixture["canary"].read_text(encoding="utf-8"))
    canary["evidence_bundle"]["sha256"] = _digest(bundle_path)
    integration_fixture["canary"].write_bytes(canonical_json_bytes(canary))
    with pytest.raises(IntegrationLockError, match="bundle bytes are not canonical JSON"):
        _build(integration_fixture)


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("home_identity_sha256", "HOME identities"),
        ("codex_home_identity_sha256", "CODEX_HOME identities"),
        ("codex_thread_id", "Codex thread IDs"),
        ("host_agent_id", "host agent IDs"),
    ],
)
def test_three_home_and_host_identities_must_be_distinct(
    integration_fixture: dict[str, Path], field: str, message: str
) -> None:
    root = integration_fixture["canary"].parent
    first = json.loads((root / "fresh-home-1.json").read_text(encoding="utf-8"))
    second_path = root / "fresh-home-2.json"
    second = json.loads(second_path.read_text(encoding="utf-8"))
    second[field] = first[field]
    second_path.write_bytes(canonical_json_bytes(second))
    _refresh_evidence_bindings(integration_fixture)
    with pytest.raises(IntegrationLockError, match=message):
        _build(integration_fixture)


def test_assignment_attempt_nonce_mapping_is_exact_not_self_reported(
    integration_fixture: dict[str, Path],
) -> None:
    receipt = integration_fixture["canary"].parent / "fresh-home-2.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["observed_attempt_id"] = "attempt.wrong-002"
    receipt.write_bytes(canonical_json_bytes(payload))
    _refresh_evidence_bindings(integration_fixture)
    with pytest.raises(IntegrationLockError, match="assignment/attempt/nonce mapping"):
        _build(integration_fixture)


def test_all_receipts_must_share_the_exact_qualification_tuple(
    integration_fixture: dict[str, Path],
) -> None:
    receipt = integration_fixture["canary"].parent / "fresh-home-3.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["credential_policy_sha256"] = "f" * 64
    receipt.write_bytes(canonical_json_bytes(payload))
    _refresh_evidence_bindings(integration_fixture)
    with pytest.raises(IntegrationLockError, match="qualification tuple drift"):
        _build(integration_fixture)


def test_stage_identity_is_derived_from_live_noncyclic_stage_bytes(
    integration_fixture: dict[str, Path],
) -> None:
    _build(integration_fixture)
    _write(integration_fixture["stage"] / "runtime-unbound.txt", "drift\n")
    with pytest.raises(IntegrationLockError, match="live stage identity"):
        _build(integration_fixture)


def test_cycle_forming_final_metadata_is_excluded_from_stage_identity(
    integration_fixture: dict[str, Path],
) -> None:
    before = observe_stage_identity(integration_fixture["stage"])
    for relative in (
        "SBOM.cdx.json",
        "share/arw/build-identity.json",
        "supply-chain/integration-lock.json",
        "supply-chain/stage-inventory.json",
        "supply-chain/use-distribution.json",
    ):
        _write(integration_fixture["stage"] / relative, f"final metadata: {relative}\n")
    assert observe_stage_identity(integration_fixture["stage"]) == before


def test_credential_policy_is_derived_from_the_exact_public_constant(
    integration_fixture: dict[str, Path],
) -> None:
    wrong = "f" * 64
    root = integration_fixture["canary"].parent
    for index in range(1, 4):
        receipt_path = root / f"fresh-home-{index}.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["credential_policy_sha256"] = wrong
        receipt_path.write_bytes(canonical_json_bytes(receipt))
    bundle_path = root / "evidence-bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["credential_policy_sha256"] = wrong
    bundle_path.write_bytes(canonical_json_bytes(bundle))
    canary = json.loads(integration_fixture["canary"].read_text(encoding="utf-8"))
    canary["credential_policy_sha256"] = wrong
    integration_fixture["canary"].write_bytes(canonical_json_bytes(canary))
    _refresh_evidence_bindings(integration_fixture)
    with pytest.raises(IntegrationLockError, match="credential policy is not qualified"):
        _build(integration_fixture)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("result_channel", "outside_scope_write_observed", True),
        ("isolation", "cross_home_read_observed", True),
        (None, "absolute_path_material_retained", True),
        (None, "home_path", "/secret/home"),
    ],
)
def test_result_channel_isolation_and_redaction_proofs_fail_closed(
    integration_fixture: dict[str, Path],
    section: str | None,
    field: str,
    value: object,
) -> None:
    receipt = integration_fixture["canary"].parent / "fresh-home-1.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    target = payload[section] if section is not None else payload
    target[field] = value
    receipt.write_bytes(canonical_json_bytes(payload))
    _refresh_evidence_bindings(integration_fixture)
    with pytest.raises(IntegrationLockError, match="fresh-home receipt 1 is invalid"):
        _build(integration_fixture)


def test_hook_status_classification_is_exact_and_authority_neutral(
    integration_fixture: dict[str, Path],
) -> None:
    bundle_path = integration_fixture["canary"].parent / "evidence-bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["hook_status_classifications"][1]["observation"] = "observed"
    bundle_path.write_bytes(canonical_json_bytes(bundle))
    _refresh_evidence_bindings(integration_fixture)
    with pytest.raises(IntegrationLockError, match="classification matrix"):
        _build(integration_fixture)


def test_hook_classification_loads_content_addressed_parity_bytes(
    integration_fixture: dict[str, Path],
) -> None:
    root = integration_fixture["canary"].parent
    bundle_path = root / "evidence-bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    disabled = bundle["hook_status_classifications"][1]
    old_path = root / disabled["evidence"]["path"]
    record = json.loads(old_path.read_text(encoding="utf-8"))
    record["parity"]["authority_digest"] = "7" * 64
    for control in record["parity"]["controls"]:
        control["authority_digest"] = "7" * 64
    raw = canonical_json_bytes(record)
    digest = hashlib.sha256(raw).hexdigest()
    new_path = root / f"{digest}.json"
    new_path.write_bytes(raw)
    disabled["evidence"] = {"path": new_path.name, "sha256": digest}
    bundle_path.write_bytes(canonical_json_bytes(bundle))
    _refresh_evidence_bindings(integration_fixture)
    with pytest.raises(IntegrationLockError, match="changed the parent authority"):
        _build(integration_fixture)


def test_hook_classification_rejects_non_content_addressed_evidence_path(
    integration_fixture: dict[str, Path],
) -> None:
    root = integration_fixture["canary"].parent
    bundle_path = root / "evidence-bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    classification = bundle["hook_status_classifications"][2]
    source = root / classification["evidence"]["path"]
    replacement = root / "not-content-addressed.json"
    replacement.write_bytes(source.read_bytes())
    classification["evidence"] = {
        "path": replacement.name,
        "sha256": _digest(replacement),
    }
    bundle_path.write_bytes(canonical_json_bytes(bundle))
    _refresh_evidence_bindings(integration_fixture)
    with pytest.raises(IntegrationLockError, match="filename is not content addressed"):
        _build(integration_fixture)


def test_live_hook_admission_is_bypass_not_persisted_trust(
    integration_fixture: dict[str, Path],
) -> None:
    canary = json.loads(integration_fixture["canary"].read_text(encoding="utf-8"))
    canary["hook_execution_admission"] = "trusted_enabled"
    integration_fixture["canary"].write_bytes(canonical_json_bytes(canary))
    with pytest.raises(IntegrationLockError, match="canary is invalid"):
        _build(integration_fixture)


def test_observed_definition_digest_matches_real_hook_receipt(tmp_path: Path) -> None:
    stage = tmp_path / "plugin"
    data = tmp_path / "plugin-data"
    _write(stage / "hooks/hooks.json", (REPOSITORY_ROOT / "hooks/hooks.json").read_bytes())
    _write(stage / "hooks/arw_hook.py", (REPOSITORY_ROOT / "hooks/arw_hook.py").read_bytes())
    payload = canonical_json_bytes(
        {
            "cwd": "/redacted-by-hook",
            "hook_event_name": "SessionStart",
            "model": "gpt-test",
            "permission_mode": "bypassPermissions",
            "session_id": "session-definition-test",
            "source": "startup",
            "transcript_path": None,
        }
    )
    result = subprocess.run(
        [sys.executable, str(stage / "hooks/arw_hook.py")],
        cwd=tmp_path,
        env={
            "PATH": str(Path(sys.executable).parent),
            "PLUGIN_DATA": str(data),
            "PLUGIN_ROOT": str(stage),
        },
        input=payload,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    receipt_path = next((data / "hook-observations/v1").glob("*.json"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    _, _, observed = observe_hook_definition(stage)
    expected = hashlib.sha256(
        b"hooks/hooks.json\0"
        + (stage / "hooks/hooks.json").read_bytes()
        + b"\0hooks/arw_hook.py\0"
        + (stage / "hooks/arw_hook.py").read_bytes()
        + b"\0"
    ).hexdigest()
    assert observed == expected == receipt["hook_definition_sha256"]


def test_use_distribution_technical_hashes_do_not_create_a_lock_cycle(
    integration_fixture: dict[str, Path],
) -> None:
    before = _build(integration_fixture)
    stage_before = observe_stage_identity(integration_fixture["stage"])
    path = integration_fixture["stage"] / "supply-chain/use-distribution.json"
    declaration = json.loads(path.read_text(encoding="utf-8"))
    declaration["evidence_hashes"][0]["sha256"] = "9" * 64
    _json(path, declaration)
    after = _build(integration_fixture)
    assert observe_stage_identity(integration_fixture["stage"]) == stage_before
    assert integration_lock_bytes(after) == integration_lock_bytes(before)
    assert after.license.use_distribution_policy_sha256 == (
        before.license.use_distribution_policy_sha256
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("intended_use", {"status": "commercial"}),
        ("permission_references", [{"permission": "unverified"}]),
        ("private_repository_is_noncommercial_evidence", True),
    ],
)
def test_use_distribution_semantic_policy_drift_fails_closed(
    integration_fixture: dict[str, Path], field: str, value: object
) -> None:
    path = integration_fixture["stage"] / "supply-chain/use-distribution.json"
    declaration = json.loads(path.read_text(encoding="utf-8"))
    declaration[field] = value
    _json(path, declaration)
    with pytest.raises(IntegrationLockError, match="exact legal blockers"):
        _build(integration_fixture)


def test_noncanonical_lock_bytes_are_rejected(
    integration_fixture: dict[str, Path],
) -> None:
    lock = _build(integration_fixture)
    integration_fixture["lock"].write_text(
        json.dumps(lock.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
    )
    with pytest.raises(IntegrationLockError, match="not canonical"):
        load_and_verify_integration_lock(
            integration_fixture["lock"],
            stage_root=integration_fixture["stage"],
            codex_launcher=integration_fixture["launcher"],
            codex_native_binary=integration_fixture["native"],
            host_canary_evidence=integration_fixture["canary"],
        )


def test_checked_in_integration_lock_schema_matches_model_projection() -> None:
    root = Path(__file__).resolve().parents[2]
    checked = json.loads(
        (root / "schemas/v1/integration-lock.schema.json").read_text(encoding="utf-8")
    )
    assert checked == integration_lock_schema_document()


def test_route_diagnostics_reports_noncanonical_lock_at_lock_document(
    integration_fixture: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert hasattr(integration_lock_module, "diagnose_integration_lock"), (
        "the read-only layered integration diagnostic API is missing"
    )
    assert hasattr(cli_module, "_installed_route_diagnostics_from_environment"), (
        "route diagnostics do not share installed input discovery"
    )

    lock = _build(integration_fixture)
    integration_fixture["lock"].write_text(
        json.dumps(lock.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(integration_fixture["stage"]))
    monkeypatch.setenv("ARW_INTEGRATION_LOCK", str(integration_fixture["lock"]))
    monkeypatch.setenv("ARW_CODEX_LAUNCHER", str(integration_fixture["launcher"]))
    monkeypatch.setenv(
        "ARW_CODEX_NATIVE_BINARY", str(integration_fixture["native"])
    )
    monkeypatch.setenv(
        "ARW_HOST_CANARY_EVIDENCE", str(integration_fixture["canary"])
    )

    exit_code = cli_module.main(["route", "--diagnostics", "--json"])
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 65
    assert report["schema_version"] == "arw.integration-diagnostic.v1"
    assert report["status"] == "BLOCKED"
    layers = {layer["name"]: layer for layer in report["layers"]}
    assert layers["inputs"]["status"] == "PASS"
    assert layers["lock_document"]["status"] == "BLOCKED"
    assert layers["lock_document"]["reason_code"] == "lock_document_noncanonical"
    assert all(
        layer["status"] == "NOT_EVALUATED"
        for layer in report["layers"][2:]
    )


def test_root_hook_supply_chain_gate_rejects_digest_substitution(
    tmp_path: Path,
) -> None:
    gate_path = (
        REPOSITORY_ROOT
        / "skills/academic-research-suite/codex/scripts/ars_codex_quality_gates.py"
    )
    spec = importlib.util.spec_from_file_location("ars_codex_quality_gates", gate_path)
    assert spec and spec.loader
    gates = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gates)
    assert hasattr(gates, "check_root_hook_supply_chain"), (
        "the root hook definition has no direct SBOM gate"
    )

    plugin_root = tmp_path / "plugin"
    shutil.copytree(REPOSITORY_ROOT / "hooks", plugin_root / "hooks")
    sbom = json.loads((REPOSITORY_ROOT / "SBOM.cdx.json").read_text(encoding="utf-8"))
    nested_digest = hashlib.sha256(
        (
            REPOSITORY_ROOT
            / "skills/academic-research-suite/codex/hooks/hooks.json"
        ).read_bytes()
    ).hexdigest()
    component = next(
        item for item in sbom["components"] if item.get("name") == "hooks/hooks.json"
    )
    component["hashes"] = [{"alg": "SHA-256", "content": nested_digest}]
    (plugin_root / "SBOM.cdx.json").write_text(
        json.dumps(sbom, indent=2) + "\n", encoding="utf-8"
    )

    with pytest.raises(gates.GateFailure, match="hooks/hooks.json.*digest"):
        gates.check_root_hook_supply_chain(plugin_root)


def _diagnose_fixture(
    integration_fixture: dict[str, Path],
):
    return diagnose_integration_lock(
        integration_fixture["lock"],
        stage_root=integration_fixture["stage"],
        codex_launcher=integration_fixture["launcher"],
        codex_native_binary=integration_fixture["native"],
        host_canary_evidence=integration_fixture["canary"],
    )


def test_complete_diagnostic_requires_exact_verification_and_validates_schema(
    integration_fixture: dict[str, Path],
) -> None:
    from arw.schema_registry import validate_instance

    lock = _build(integration_fixture)
    expected = write_integration_lock(integration_fixture["lock"], lock)
    report = _diagnose_fixture(integration_fixture)

    assert report.status == "PASS"
    assert report.integration_lock_sha256 == expected
    assert [layer.name for layer in report.layers] == [
        "inputs",
        "lock_document",
        "staged_arw",
        "ars_bundle",
        "file_base",
        "codex_host",
        "hook_definition",
        "hook_execution_evidence",
        "legal_state",
        "exact_lock",
    ]
    assert all(layer.status == "PASS" for layer in report.layers)
    assert report.release_qualification == "BLOCKED"
    assert report.experiment_execution == "disabled"
    validate_instance(
        "research-integrity-contracts.schema.json",
        report.model_dump(mode="json"),
    )


@pytest.mark.parametrize(
    ("mutation", "expected_layer", "expected_reason"),
    [
        ("staged-arw", "staged_arw", "staged_arw_drift"),
        ("ars", "ars_bundle", "ars_bundle_drift"),
        ("file-base", "file_base", "file_base_drift"),
        ("host", "codex_host", "codex_host_drift"),
        ("hook-definition", "hook_definition", "hook_definition_drift"),
        (
            "hook-evidence",
            "hook_execution_evidence",
            "hook_execution_evidence_drift",
        ),
        ("legal", "legal_state", "legal_state_drift"),
    ],
)
def test_diagnostic_stops_at_the_first_exact_drift_layer(
    integration_fixture: dict[str, Path],
    mutation: str,
    expected_layer: str,
    expected_reason: str,
) -> None:
    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    if mutation == "staged-arw":
        target = (
            integration_fixture["stage"]
            / "vendor/python/wheelhouse/academic_research_workbench-0.1.0-py3-none-any.whl"
        )
        target.write_bytes(target.read_bytes() + b"drift")
    elif mutation == "ars":
        target = (
            integration_fixture["external"] / "ars/academic-pipeline/WORKFLOW.md"
        )
        target.write_bytes(target.read_bytes() + b"drift")
    elif mutation == "file-base":
        target = integration_fixture["stage"] / "libexec/file-base-mcp"
        target.write_bytes(target.read_bytes() + b"drift")
    elif mutation == "host":
        target = integration_fixture["native"]
        mode = target.stat().st_mode
        target.write_bytes(target.read_bytes() + b"\n# drift\n")
        target.chmod(mode)
    elif mutation == "hook-definition":
        target = integration_fixture["stage"] / "hooks/hooks.json"
        target.write_bytes(target.read_bytes() + b" ")
    elif mutation == "hook-evidence":
        target = integration_fixture["canary"]
        target.write_bytes(target.read_bytes() + b" ")
    else:
        target = integration_fixture["stage"] / "supply-chain/use-distribution.json"
        payload = json.loads(target.read_text(encoding="utf-8"))
        payload["intended_use"] = {"status": "commercial"}
        _json(target, payload)

    report = _diagnose_fixture(integration_fixture)
    blocked_index = next(
        index for index, layer in enumerate(report.layers) if layer.status == "BLOCKED"
    )
    assert report.layers[blocked_index].name == expected_layer
    assert report.layers[blocked_index].reason_code == expected_reason
    assert all(
        layer.status == "NOT_EVALUATED"
        for layer in report.layers[blocked_index + 1 :]
    )
    serialized = canonical_json_bytes(report.model_dump(mode="json")).decode("utf-8")
    assert str(integration_fixture["stage"]) not in serialized
