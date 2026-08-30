# pyright: reportMissingImports=false
from __future__ import annotations

import hashlib
import importlib.util
import json
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Literal, cast

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
    AUDIT_BUILD_IDENTITY_RELATIVE,
    EXPECTED_CODEX_CREDENTIAL_POLICY_SHA256,
    CodexHostCanaryEvidence,
    CodexHostEvidenceBundle,
    ControlledResultChannelProof,
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

ARS_COMMIT = "127ff85e4bbfcdd10b95040537b6c6bd7ad17aeb"
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
        'if [ "${1:-}" = "--version" ]; then\n'
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
        'if [ "${1:-}" = "--version" ]; then\n'
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
    version: str = "0.1.0",
) -> dict[str, object]:
    return {
        "id": component_id,
        "version": version,
        "revision": revision,
        "git_tree": git_tree,
        "tree_sha256": tree_sha256,
        "upstream_url": upstream_url,
    }


def _make_wheel(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = (
        "Metadata-Version: 2.4\nName: academic-research-workbench\nVersion: 0.1.0\n\n"
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("arw/__init__.py", "__version__ = '0.1.0'\n")
        archive.writestr("arw/integration_lock.py", "# packaged verifier\n")
        archive.writestr(
            "academic_research_workbench-0.1.0.dist-info/METADATA", metadata
        )


def _install_audit_manifests(stage: Path) -> None:
    """Materialize the build-identity and stage-inventory audit manifests.

    Both manifests are emitted as pretty-sorted + newline JSON to match
    ``scripts/stage-plugin``.  Every digest and aggregate is recomputed from
    the live stage bytes via the canonical helpers in :mod:`arw.schema_registry`
    so the audit gate has nothing to trust but the stage itself.
    """

    from arw.schema_registry import aggregate_schema_sha256

    schema_destination = stage / "share/arw/schemas/build-identity.schema.json"
    schema_destination.parent.mkdir(parents=True, exist_ok=True)
    schema_destination.write_bytes(
        (REPOSITORY_ROOT / "schemas/v1/build-identity.schema.json").read_bytes()
    )
    contracts_destination = stage / "share/arw/file-contracts.h"
    contracts_destination.parent.mkdir(parents=True, exist_ok=True)
    source_manifest = json.loads(
        (stage / "vendor/source-manifest.json").read_text(encoding="utf-8")
    )
    components = source_manifest["components"]
    patches = source_manifest["patches"]
    build_evidence_digest = _digest(stage / ".file-base/build-evidence.json")
    binary_digest = _digest(stage / "libexec/file-base-mcp")
    patch_set_sha256 = hashlib.sha256(
        json.dumps(
            [
                {key: item[key] for key in ("order", "path", "sha256")}
                for item in patches
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    profile_patch_sha256 = next(
        item["sha256"] for item in patches if item["order"] == 4
    )

    def collect(relative: str) -> str:
        return _digest(stage / relative)

    wheel_path = (
        "vendor/python/wheelhouse/academic_research_workbench-0.1.0-py3-none-any.whl"
    )
    wheel_path_filename = wheel_path.rsplit("/", 1)[-1]
    requirements_path = "vendor/python/wheelhouse/requirements-runtime.txt"
    (stage / requirements_path).parent.mkdir(parents=True, exist_ok=True)
    (stage / requirements_path).write_text(
        "academic-research-workbench==0.1.0\n", encoding="utf-8"
    )
    wheelhouse_lock_path = "vendor/python/wheelhouse.lock.json"
    wheelhouse_lock_payload = {
        "schema_version": "arw.wheelhouse-lock.v1",
        "wheels": [],
        "first_party_wheel": {
            "file": wheel_path_filename,
            "package": "academic-research-workbench",
            "registry": "first-party",
            "sha256": _digest(stage / wheel_path),
            "source": "built-from-clean-stage-inputs",
            "version": "0.1.0",
        },
    }
    _json(stage / wheelhouse_lock_path, wheelhouse_lock_payload)

    # Stage the real phase-01 evidence files under ``share/arw/evidence``
    # so the live recompute of the build-identity evidence block verifies
    # each surface against the strict producer contract.  The copied bytes
    # MUST satisfy the NetworkVerdict / LegalVerdict / PreVendorReceipt
    # Stage 5 surfaces of phase-01 evidence so the live recompute of the
    # build-identity evidence block verifies each digestPath without
    # depending on the original ``build/evidence/phase-01`` tree.
    # pre_vendor + legal are single JSON files; upstream + asan_ubsan +
    # tsan are 5-file bundles (verdict + command + sanitizer_verdict +
    # test_suite_sha256 + status) so the verifier can distinguish them.
    synthetic_evidence_relative: dict[str, str] = {
        "pre_vendor": "share/arw/evidence/pre_vendor.json",
        "legal": "share/arw/evidence/legal.json",
    }
    native_evidence_kinds: tuple[str, ...] = (
        "command",
        "sanitizer_verdict",
        "test_suite_sha256",
        "status",
    )
    for native_surface in ("upstream", "asan_ubsan", "tsan"):
        synthetic_evidence_relative[f"{native_surface}_verdict"] = (
            f"share/arw/evidence/{native_surface}.json"
        )
        for kind in native_evidence_kinds:
            ext = "txt" if kind in {"test_suite_sha256", "status"} else "json"
            synthetic_evidence_relative[f"{native_surface}_{kind}"] = (
                f"share/arw/evidence/{native_surface}_{kind}.{ext}"
            )
    fixture_evidence = REPOSITORY_ROOT / "tests/fixtures/phase-01-evidence"
    synthetic_evidence_source: dict[str, Path] = {
        "pre_vendor": REPOSITORY_ROOT / "supply-chain/pre-vendor-receipt.json",
        "legal": fixture_evidence / "legal.json",
    }
    # Native surfaces are canonical committed supply-chain evidence; tests and
    # production staging consume the same reviewed bytes.
    canonical_native = REPOSITORY_ROOT / "supply-chain/native-evidence"
    native_surface_dir: dict[str, str] = {
        "upstream": "upstream",
        "asan_ubsan": "asan-ubsan",
        "tsan": "tsan",
    }
    for native_surface, source_dir in native_surface_dir.items():
        fixture_dir = canonical_native / source_dir
        synthetic_evidence_source[f"{native_surface}_verdict"] = (
            fixture_dir / "verdict.json"
        )
        for kind in native_evidence_kinds:
            ext = "txt" if kind in {"test_suite_sha256", "status"} else "json"
            filename = (
                "test-suite.sha256"
                if kind == "test_suite_sha256"
                else f"{kind.replace('_', '-')}.json"
                if ext == "json"
                else f"{kind}.txt"
            )
            synthetic_evidence_source[f"{native_surface}_{kind}"] = (
                fixture_dir / filename
            )

    evidence_digests: dict[str, str] = {}
    synthetic_evidence = synthetic_evidence_relative
    for label, relative in synthetic_evidence.items():
        source = synthetic_evidence_source[label]
        if not source.is_file():
            raise FileNotFoundError(
                f"required phase-01 evidence source is missing: {source}"
            )
        destination = stage / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        evidence_digests[label] = collect(relative)
        if relative.endswith(".json"):
            # Verify the copied file passes the matching producer contract.

            try:
                json.loads(destination.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                raise RuntimeError(
                    f"staged evidence surface {label} is not valid JSON: {error}"
                ) from error

    # Native verdict surfaces go through the shared NetworkVerdict contract
    # that every other surface uses; the bundles themselves are validated
    # by the verifier's _verify_native_surface_bundle step.
    for native_surface in ("upstream", "asan_ubsan", "tsan"):
        verdict_relative = f"share/arw/evidence/{native_surface}.json"
        verdict_path = stage / verdict_relative
        try:
            integration_lock_module.NetworkVerdict.model_validate(
                json.loads(verdict_path.read_text(encoding="utf-8")),
                strict=True,
            )
        except Exception as error:
            raise RuntimeError(
                f"staged native verdict {native_surface} fails the "
                f"NetworkVerdict contract: {error}"
            ) from error

    # The query_launcher digestPath requires a real executable on disk so
    # the live byte recompute can match the declared sha256.
    graph_mcp_relative = "scripts/file-base-graph-mcp"
    graph_mcp_destination = stage / graph_mcp_relative
    graph_mcp_destination.parent.mkdir(parents=True, exist_ok=True)
    graph_mcp_destination.write_bytes(b"fixture-graph-mcp")
    graph_mcp_destination.chmod(0o755)
    graph_mcp_digest = collect(graph_mcp_relative)

    schemas_files = [
        {
            "path": "share/arw/schemas/build-identity.schema.json",
            "sha256": collect("share/arw/schemas/build-identity.schema.json"),
        }
    ]
    # Stage the real file-contract schemas so the regenerated header has
    # the same semantic content the producer must emit; the rendered bytes
    # are then written to share/arw/file-contracts.h.
    from arw.file_contracts import FILE_SCHEMA_NAMES, render_native_contract_header

    for name in FILE_SCHEMA_NAMES:
        relative = f"share/arw/schemas/{name}"
        destination = stage / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((REPOSITORY_ROOT / "schemas/v1" / name).read_bytes())
        schemas_files.append(
            {
                "path": relative,
                "sha256": collect(relative),
            }
        )

    # Regenerate the header from the staged checked schemas.  This is the
    # SAME call the producer makes; the verifier regenerates independently
    # and requires byte equality.
    regenerated_header = render_native_contract_header(stage / "share/arw/schemas")
    contracts_destination.write_bytes(regenerated_header)
    # Parse the regenerated bytes directly to get the embedded semantic.
    embedded_contract_sha256 = (
        integration_lock_module.parse_file_contract_contract_sha256_from_bytes(
            regenerated_header
        )
    )
    contracts_digest = _digest(contracts_destination)
    schemas_aggregate = aggregate_schema_sha256(
        [(entry["path"], entry["sha256"]) for entry in schemas_files]
    )

    # Pin the staged ``.python-version`` so the build_interpreter claim
    # matches the live stage bytes exactly.  The fixture generator pins it
    # before constructing the identity so the verifier's
    # ``observe_staged_python_version`` agrees with the recorded value.
    staged_python_version = "3.13.1"
    (stage / ".python-version").write_text(
        f"{staged_python_version}\n", encoding="ascii"
    )

    identity = {
        "schema_version": "1.0.0",
        "platform_claim": "linux",
        "plugin": {"name": "academic-research-workbench", "version": "0.1.0"},
        "runtime": {
            "python_requires": ">=3.13",
            "build_interpreter": staged_python_version,
        },
        "components": [
            {key: item[key] for key in ("id", "version", "revision", "tree_sha256")}
            for item in components
        ],
        "patches": [
            {key: item[key] for key in ("order", "path", "sha256")} for item in patches
        ],
        "native": {
            "binary": {"path": "libexec/file-base-mcp", "sha256": binary_digest},
            "build_evidence": {
                "path": ".file-base/build-evidence.json",
                "sha256": build_evidence_digest,
            },
            "compile_profile": "release-o2",
            "patched_source_tree_sha256": sorted(
                patches, key=lambda item: item["order"]
            )[-1]["post_tree_sha256"],
            "upstream_test_tree_sha256": source_manifest["native_test_suites"][0][
                "tree_sha256"
            ],
        },
        "projection": {
            "algorithm": "research-graph-projection-v1",
            "oracle": "research-graph-normalization-v1",
            "native_profile": "research-graph-builder-v1",
            "patch_set_sha256": patch_set_sha256,
            "profile_patch_sha256": profile_patch_sha256,
            "query_profile": "arw-graph-mcp-v1",
            "query_launcher": {
                "path": graph_mcp_relative,
                "sha256": graph_mcp_digest,
            },
        },
        "file_contract": {
            "header": {
                "path": "share/arw/file-contracts.h",
                "sha256": contracts_digest,
            },
            # Record the embedded ARW_FILES_CONTRACT_SHA256 semantic, not the
            # whole-header file digest; the verifier requires an exact match.
            "contract_sha256": embedded_contract_sha256,
            "tokenizer_id": "unicode61-cjk-v1",
            "ranking_version": "files-rank-v1",
            "outline_versions": [
                "bibtex-outline-v1",
                "latex-outline-v1",
                "markdown-outline-v1",
                "source-outline-v1",
            ],
        },
        "wheelhouse": {
            "lock": {
                "path": wheelhouse_lock_path,
                "sha256": collect(wheelhouse_lock_path),
            },
            "requirements": {
                "path": requirements_path,
                "sha256": collect(requirements_path),
            },
            "first_party": {"path": wheel_path, "sha256": collect(wheel_path)},
        },
        "schemas": {
            "aggregate_sha256": schemas_aggregate,
            "files": schemas_files,
        },
        "evidence": {
            "pre_vendor": {
                "path": synthetic_evidence["pre_vendor"],
                "sha256": evidence_digests["pre_vendor"],
            },
            "legal": {
                "path": synthetic_evidence["legal"],
                "sha256": evidence_digests["legal"],
            },
        },
    }
    # Native surfaces carry 5 digestPaths each (verdict + command +
    # sanitizer_verdict + test_suite_sha256 + status) so the verifier can
    # bind each surface to its authoritative argv / suite / pinned bytes.
    for native_surface in ("upstream", "asan_ubsan", "tsan"):
        bundle: dict[str, dict[str, str]] = {
            "verdict": {
                "path": synthetic_evidence[f"{native_surface}_verdict"],
                "sha256": evidence_digests[f"{native_surface}_verdict"],
            },
        }
        for kind in native_evidence_kinds:
            key = f"{native_surface}_{kind}"
            bundle[kind] = {
                "path": synthetic_evidence[key],
                "sha256": evidence_digests[key],
            }
        identity["evidence"][native_surface] = bundle
    actual: set[str] = set()
    for path in stage.rglob("*"):
        if path.is_symlink():
            continue
        if path.is_file():
            actual.add(path.relative_to(stage).as_posix())
    staged_payloads = sorted(
        actual - {"share/arw/build-identity.json", "supply-chain/stage-inventory.json"}
    )
    identity["staged_payloads"] = [
        {"path": relative, "sha256": collect(relative)} for relative in staged_payloads
    ]
    identity_path = stage / "share/arw/build-identity.json"
    identity_path.write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    actual.add("share/arw/build-identity.json")

    covered: list[dict[str, str]] = []
    for relative in sorted(actual):
        covered.append(
            {
                "path": relative,
                "sha256": collect(relative),
                "inventory_source": _fixture_inventory_source(relative),
            }
        )
    inventory = {
        "schema_version": "1.0.0",
        "files": sorted(actual | {"supply-chain/stage-inventory.json"}),
        "symlinks": [],
        "covered_files": covered,
    }
    (stage / "supply-chain/stage-inventory.json").write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _fixture_inventory_source(relative: str) -> str:
    """Mirror ``scripts/stage-plugin`` ``inventory_source`` for fixture files."""

    if relative in {"vendor/source-manifest.json", "vendor/mcp-manifest.json"}:
        return "source-manifest"
    if relative.startswith("vendor/python/wheelhouse/") or relative in {
        "uv.lock",
        ".python-version",
    }:
        return "wheelhouse"
    if relative.startswith(("LICENSES/", "supply-chain/")) or relative in {
        "MODIFICATIONS.md",
        "SBOM.cdx.json",
        "THIRD_PARTY_NOTICES.md",
    }:
        return "legal"
    if relative.startswith(("schemas/", ".file-base/", "libexec/", "share/arw/")):
        return "build"
    return "runtime"


@pytest.fixture
def integration_fixture(tmp_path: Path) -> dict[str, Path]:
    stage = tmp_path / "stage"
    external = stage / "skills/academic-research-suite"
    stage.mkdir()
    external.mkdir(parents=True)

    _write(
        stage / "pyproject.toml",
        '[project]\nname = "academic-research-workbench"\nversion = "0.1.0"\n',
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
                "7ce111463102462479835ce5f7c2b597d7ccfe22",
                "9f195460e1e299d7ce0a833e3a242957db315ef16ec9e8c80d29163e300afbd6",
                "https://github.com/Imbad0202/academic-research-skills.git",
                version="0.1.27",
            ),
            _component(
                "experiment-agent",
                EXPERIMENT_COMMIT,
                "166734509cf5057e48a7f81ecce9e44573610636",
                "2985b59589805267cf1b268a126162ffd3689d0f31840a2de41b004471128bae",
                "https://github.com/Imbad0202/experiment-agent.git",
                version="1.1.0",
            ),
            _component(
                "file-base",
                FILE_BASE_COMMIT,
                "de88f52c6614473d04aa1596304a328ef91267e8",
                "4a1ffaa7468026293758327f143d0cfc9f7046e69bd7224efcbd63290fe059d3",
                "https://github.com/DeusData/codebase-memory-mcp.git",
                version="v0.9.0-2-gee68144",
            ),
        ],
        "patches": patches,
        "native_test_suites": [
            {
                "name": "fixture-upstream",
                "tree_sha256": integration_lock_module.EXPECTED_FILE_BASE_TEST_TREE,
            }
        ],
    }
    repository_components = {
        item["id"]: item for item in repository_manifest["components"]
    }
    fixture_components = cast(list[dict[str, object]], source_manifest["components"])
    for component in fixture_components:
        component_id = cast(str, component["id"])
        component["legal_inputs"] = repository_components[component_id]["legal_inputs"]
    _json(stage / "vendor/source-manifest.json", source_manifest)
    _json(stage / "SBOM.cdx.json", {"components": []})
    _write(stage / "THIRD_PARTY_NOTICES.md", "fixture notices\n")
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
                {
                    "order": patch["order"],
                    "path": patch["path"],
                    "sha256": patch["sha256"],
                }
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
                    "path": relative,
                    "purpose": "technical-provenance-only",
                    "sha256": _digest(stage / relative),
                }
                for relative in (
                    "vendor/source-manifest.json",
                    "SBOM.cdx.json",
                    "THIRD_PARTY_NOTICES.md",
                )
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

    _write(external / "VERSION", "0.1.27\n")
    _write(
        external / "SKILL.md",
        "---\n"
        "name: academic-research-suite\n"
        "metadata:\n"
        '  version: "0.1.27"\n'
        "---\n"
        "# ARS\n",
    )
    _json(
        external / "manifest.json",
        {
            "name": "academic-research-suite",
            "adapter_version": "0.1.27",
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

    # Stage the pinned license files referenced by the LegalVerdict rows
    # so the live digest cross-binding in ``verify_evidence_contract``
    # has real bytes to recompute against.
    (stage / "LICENSES").mkdir(parents=True, exist_ok=True)
    for relative in (
        "LICENSES/academic-research-skills-CC-BY-NC-4.0.txt",
        "LICENSES/experiment-agent-CC-BY-NC-4.0.txt",
        "LICENSES/file-base-MIT.txt",
    ):
        shutil.copyfile(REPOSITORY_ROOT / relative, stage / relative)

    _install_audit_manifests(stage)

    launcher = tmp_path / "host/codex"
    native = tmp_path / "host/codex-native"
    _write(
        launcher,
        "#!/bin/sh\n"
        'if [ "${1:-}" = "--version" ]; then\n'
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
    classification_cases: tuple[
        tuple[
            Literal["trusted_enabled", "disabled", "untrusted", "timeout", "failure"],
            Literal["observed", "not_observed", "timed_out", "failed"],
            Literal["trusted_enabled", "disabled", "untrusted", "timeout", "failed"],
        ],
        ...,
    ] = (
        ("trusted_enabled", "observed", "trusted_enabled"),
        ("disabled", "not_observed", "disabled"),
        ("untrusted", "not_observed", "untrusted"),
        ("timeout", "timed_out", "timeout"),
        ("failure", "failed", "failed"),
    )
    for state, observation, parity_status in classification_cases:
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


def _refresh_canary_stage_identity(paths: dict[str, Path]) -> None:
    """Rebind every stage_sha256 in the canary/bundle/receipts to the live stage."""

    stage_sha256 = observe_stage_identity(paths["stage"])
    evidence_root = paths["canary"].parent
    for index in range(1, 4):
        receipt_path = evidence_root / f"fresh-home-{index}.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["stage_sha256"] = stage_sha256
        receipt_path.write_bytes(canonical_json_bytes(receipt))
    receipt_bindings = [
        {
            "path": f"fresh-home-{index}.json",
            "sha256": _digest(evidence_root / f"fresh-home-{index}.json"),
        }
        for index in range(1, 4)
    ]
    bundle_path = evidence_root / "evidence-bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["stage_sha256"] = stage_sha256
    bundle["fresh_home_receipts"] = receipt_bindings
    bundle_path.write_bytes(canonical_json_bytes(bundle))
    canary = json.loads(paths["canary"].read_text(encoding="utf-8"))
    canary["stage_sha256"] = stage_sha256
    canary["fresh_home_receipts"] = receipt_bindings
    canary["evidence_bundle"] = {
        "path": "evidence-bundle.json",
        "sha256": _digest(bundle_path),
    }
    # Update hook parity evidence records so their stage_sha256 matches.
    for classification in bundle["hook_status_classifications"]:
        parity_path = evidence_root / classification["evidence"]["path"]
        parity = json.loads(parity_path.read_text(encoding="utf-8"))
        parity["stage_sha256"] = stage_sha256
        new_bytes = canonical_json_bytes(parity)
        parity_path.write_bytes(new_bytes)
        new_digest = hashlib.sha256(new_bytes).hexdigest()
        new_filename = f"{new_digest}.json"
        if parity_path.name != new_filename:
            new_path = evidence_root / new_filename
            parity_path.rename(new_path)
        classification["evidence"] = {
            "path": new_filename,
            "sha256": new_digest,
        }
    bundle_path.write_bytes(canonical_json_bytes(bundle))
    canary["evidence_bundle"] = {
        "path": "evidence-bundle.json",
        "sha256": _digest(bundle_path),
    }
    paths["canary"].write_bytes(canonical_json_bytes(canary))


def test_exact_external_integration_lock_round_trips_and_retains_legal_block(
    integration_fixture: dict[str, Path],
) -> None:
    lock = _build(integration_fixture)
    assert lock.ars.adapter_version == "0.1.27"
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
            '---\nname: academic-research-suite\nmetadata:\n  version: "0.1.19"\n---\n',
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
    with pytest.raises(
        IntegrationLockError, match="bundle bytes are not canonical JSON"
    ):
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


def test_distinct_proposal_nonce_but_reused_proposal_digest_is_rejected(
    integration_fixture: dict[str, Path],
) -> None:
    root = integration_fixture["canary"].parent
    first = json.loads((root / "fresh-home-1.json").read_text(encoding="utf-8"))
    second_path = root / "fresh-home-2.json"
    second = json.loads(second_path.read_text(encoding="utf-8"))
    # Fixture already gives receipt 2 a distinct proposal nonce, so the
    # existing "proposal nonces are not distinct" check must NOT fire here.
    assert first["expected_proposal_nonce"] != second["expected_proposal_nonce"]
    second["result_channel"]["proposal_sha256"] = first["result_channel"][
        "proposal_sha256"
    ]
    second_path.write_bytes(canonical_json_bytes(second))
    _refresh_evidence_bindings(integration_fixture)
    with pytest.raises(IntegrationLockError, match="proposal digests are not distinct"):
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
    with pytest.raises(
        IntegrationLockError, match="credential policy is not qualified"
    ):
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
    _write(
        stage / "hooks/hooks.json", (REPOSITORY_ROOT / "hooks/hooks.json").read_bytes()
    )
    _write(
        stage / "hooks/arw_hook.py",
        (REPOSITORY_ROOT / "hooks/arw_hook.py").read_bytes(),
    )
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


@pytest.mark.parametrize("mutation", ("drop-sbom", "stale-sbom"))
def test_use_distribution_technical_hash_drift_fails_live_verification(
    integration_fixture: dict[str, Path], mutation: str
) -> None:
    _build(integration_fixture)
    stage_before = observe_stage_identity(integration_fixture["stage"])
    path = integration_fixture["stage"] / "supply-chain/use-distribution.json"
    declaration = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "drop-sbom":
        declaration["evidence_hashes"] = [
            row
            for row in declaration["evidence_hashes"]
            if row["path"] != "SBOM.cdx.json"
        ]
    else:
        sbom_row = next(
            row
            for row in declaration["evidence_hashes"]
            if row["path"] == "SBOM.cdx.json"
        )
        sbom_row["sha256"] = "9" * 64
    _json(path, declaration)
    with pytest.raises(IntegrationLockError, match="technical provenance"):
        _build(integration_fixture)
    assert observe_stage_identity(integration_fixture["stage"]) == stage_before


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("drop-component", "integration lock component"),
        ("stale-component", "integration lock component"),
        ("reformatted", "SBOM bytes"),
    ),
)
def test_live_sbom_requires_exact_integration_lock_component(
    integration_fixture: dict[str, Path], mutation: str, message: str
) -> None:
    lock = _build(integration_fixture)
    stage = integration_fixture["stage"]
    live_lock = stage / "supply-chain/integration-lock.json"
    live_lock.write_bytes(integration_lock_bytes(lock))
    lock_ref = "artifact:supply-chain/integration-lock.json"
    component = {
        "bom-ref": lock_ref,
        "hashes": [{"alg": "SHA-256", "content": _digest(live_lock)}],
        "name": "supply-chain/integration-lock.json",
        "type": "file",
        "version": "1",
    }
    sbom_path = stage / "SBOM.cdx.json"
    sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
    sbom["components"] = [component]
    _json(sbom_path, sbom)
    _build(integration_fixture)

    if mutation == "drop-component":
        sbom["components"] = []
    elif mutation == "stale-component":
        component["hashes"][0]["content"] = "0" * 64
    if mutation == "reformatted":
        sbom_path.write_text(json.dumps(sbom) + "\n", encoding="utf-8")
    else:
        _json(sbom_path, sbom)
    with pytest.raises(IntegrationLockError, match=message):
        _build(integration_fixture)


def test_original_lock_rejects_self_rebound_sbom_and_declaration(
    integration_fixture: dict[str, Path],
) -> None:
    lock = _build(integration_fixture)
    stage = integration_fixture["stage"]
    sbom_path = stage / "SBOM.cdx.json"
    sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
    sbom["components"].append(
        {
            "bom-ref": "artifact:tampered",
            "hashes": [{"alg": "SHA-256", "content": "a" * 64}],
            "name": "tampered",
            "type": "file",
            "version": "1",
        }
    )
    _json(sbom_path, sbom)
    declaration_path = stage / "supply-chain/use-distribution.json"
    declaration = json.loads(declaration_path.read_text(encoding="utf-8"))
    sbom_row = next(
        row for row in declaration["evidence_hashes"] if row["path"] == "SBOM.cdx.json"
    )
    sbom_row["sha256"] = _digest(sbom_path)
    _json(declaration_path, declaration)
    _build(integration_fixture)
    with pytest.raises(IntegrationLockError, match="live integration identity"):
        _verify(integration_fixture, lock)


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
    from arw.schema_registry import validate_instance

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
    monkeypatch.setenv("ARW_CODEX_NATIVE_BINARY", str(integration_fixture["native"]))
    monkeypatch.setenv("ARW_HOST_CANARY_EVIDENCE", str(integration_fixture["canary"]))

    exit_code = cli_module.main(["route", "--diagnostics", "--json"])
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 65
    assert report["schema_version"] == "arw.integration-diagnostic.v1"
    assert report["status"] == "BLOCKED"
    layers = {layer["name"]: layer for layer in report["layers"]}
    assert layers["inputs"]["status"] == "PASS"
    assert layers["lock_document"]["status"] == "BLOCKED"
    assert layers["lock_document"]["reason_code"] == "lock_document_noncanonical"
    assert all(layer["status"] == "NOT_EVALUATED" for layer in report["layers"][2:])
    assert layers["lock_document"]["observed_sha256"] == _digest(
        integration_fixture["lock"]
    )
    validate_instance("research-integrity-contracts.schema.json", report)

    layers["lock_document"]["observed_sha256"] = None
    with pytest.raises(ValueError, match="semantic validation failed"):
        validate_instance("research-integrity-contracts.schema.json", report)


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
            REPOSITORY_ROOT / "skills/academic-research-suite/codex/hooks/hooks.json"
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

    contradictory = report.model_dump(mode="json")
    contradictory["layers"][1]["observed_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="semantic validation failed"):
        validate_instance("research-integrity-contracts.schema.json", contradictory)

    unbound_exact_lock = report.model_dump(mode="json")
    unbound_exact_lock["integration_lock_sha256"] = "e" * 64
    with pytest.raises(ValueError, match="semantic validation failed"):
        validate_instance(
            "research-integrity-contracts.schema.json", unbound_exact_lock
        )

    blocked_after_prior_passes = report.model_dump(mode="json")
    blocked_after_prior_passes["status"] = "BLOCKED"
    blocked_after_prior_passes["technical_qualification"] = "BLOCKED"
    blocked_after_prior_passes["integration_lock_sha256"] = None
    blocked_after_prior_passes["reason_codes"] = ["legal_state_drift"]
    blocked_layer = blocked_after_prior_passes["layers"][8]
    blocked_layer["status"] = "BLOCKED"
    blocked_layer["reason_code"] = "legal_state_drift"
    blocked_layer["detail"] = "legal policy differs from the qualified blocked state"
    final_layer = blocked_after_prior_passes["layers"][9]
    final_layer["status"] = "NOT_EVALUATED"
    final_layer["reason_code"] = None
    final_layer["detail"] = None
    final_layer["expected_sha256"] = None
    final_layer["observed_sha256"] = None
    blocked_after_prior_passes["layers"][1]["observed_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="semantic validation failed"):
        validate_instance(
            "research-integrity-contracts.schema.json", blocked_after_prior_passes
        )

    prior_lock = blocked_after_prior_passes["layers"][1]
    prior_lock["observed_sha256"] = prior_lock["expected_sha256"]
    blocked_layer["observed_sha256"] = blocked_layer["expected_sha256"]
    with pytest.raises(ValueError, match="semantic validation failed"):
        validate_instance(
            "research-integrity-contracts.schema.json", blocked_after_prior_passes
        )

    blocked_layer["expected_sha256"] = None
    blocked_layer["observed_sha256"] = None
    with pytest.raises(ValueError, match="semantic validation failed"):
        validate_instance(
            "research-integrity-contracts.schema.json", blocked_after_prior_passes
        )

    blocked = diagnose_integration_lock(
        None,
        stage_root=None,
        codex_launcher=None,
        codex_native_binary=None,
        host_canary_evidence=None,
    ).model_dump(mode="json")
    blocked["reason_codes"] = ["legal_state_drift"]
    blocked["layers"][0]["reason_code"] = "legal_state_drift"
    blocked["layers"][0]["detail"] = (
        "legal policy differs from the qualified blocked state"
    )
    with pytest.raises(ValueError, match="semantic validation failed"):
        validate_instance("research-integrity-contracts.schema.json", blocked)

    blocked["reason_codes"] = ["integration_inputs_incomplete"]
    blocked["layers"][0]["reason_code"] = "integration_inputs_incomplete"
    blocked["layers"][0]["detail"] = "required integration inputs are absent or unsafe"
    blocked["layers"][0]["expected_sha256"] = "a" * 64
    blocked["layers"][0]["observed_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="semantic validation failed"):
        validate_instance("research-integrity-contracts.schema.json", blocked)


def test_diagnostic_accepts_launcher_symlink_as_safe_input(
    integration_fixture: dict[str, Path],
) -> None:
    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    launcher = integration_fixture["launcher"]
    launcher_link = launcher.with_name("codex-symlink")
    launcher_link.symlink_to(launcher)

    report = diagnose_integration_lock(
        integration_fixture["lock"],
        stage_root=integration_fixture["stage"],
        codex_launcher=launcher_link,
        codex_native_binary=integration_fixture["native"],
        host_canary_evidence=integration_fixture["canary"],
    )

    assert report.layers[0].name == "inputs"
    assert report.layers[0].status == "PASS"
    assert report.layers[5].name == "codex_host"
    assert report.layers[5].reason_code == "codex_host_drift"


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
        target = integration_fixture["external"] / "ars/academic-pipeline/WORKFLOW.md"
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
        layer.status == "NOT_EVALUATED" for layer in report.layers[blocked_index + 1 :]
    )
    serialized = canonical_json_bytes(report.model_dump(mode="json")).decode("utf-8")
    assert str(integration_fixture["stage"]) not in serialized


def test_audit_manifest_gate_passes_on_synthesized_fixture(
    integration_fixture: dict[str, Path],
) -> None:
    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    verification = _verify(integration_fixture, lock)
    assert verification.technical_qualification == "PASS"


def test_audit_manifest_gate_rejects_missing_build_identity(
    integration_fixture: dict[str, Path],
) -> None:
    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    (integration_fixture["stage"] / "share/arw/build-identity.json").unlink()
    with pytest.raises(IntegrationLockError, match="build identity"):
        _verify(integration_fixture, lock)


def test_audit_manifest_gate_rejects_missing_stage_inventory(
    integration_fixture: dict[str, Path],
) -> None:
    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    (integration_fixture["stage"] / "supply-chain/stage-inventory.json").unlink()
    with pytest.raises(IntegrationLockError, match="stage inventory"):
        _verify(integration_fixture, lock)


def test_audit_manifest_gate_rejects_corrupt_build_identity_bytes(
    integration_fixture: dict[str, Path],
) -> None:
    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    identity = integration_fixture["stage"] / "share/arw/build-identity.json"
    identity.write_bytes(identity.read_bytes() + b"\ndrift\n")
    with pytest.raises(IntegrationLockError, match="build identity"):
        _verify(integration_fixture, lock)


def test_audit_manifest_gate_rejects_corrupt_stage_inventory_bytes(
    integration_fixture: dict[str, Path],
) -> None:
    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    inventory = integration_fixture["stage"] / "supply-chain/stage-inventory.json"
    inventory.write_bytes(inventory.read_bytes() + b"\ndrift\n")
    with pytest.raises(IntegrationLockError, match="stage inventory"):
        _verify(integration_fixture, lock)


def test_audit_manifest_gate_rejects_inventory_coverage_digest_mismatch(
    integration_fixture: dict[str, Path],
) -> None:
    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    inventory_path = integration_fixture["stage"] / "supply-chain/stage-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    for entry in inventory["covered_files"]:
        if entry["path"] == "share/arw/file-contracts.h":
            entry["sha256"] = "0" * 64
    inventory_path.write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(IntegrationLockError, match="stage inventory.*coverage"):
        _verify(integration_fixture, lock)


def test_audit_manifest_gate_rejects_staged_payloads_digest_mismatch(
    integration_fixture: dict[str, Path],
) -> None:
    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    identity_path = integration_fixture["stage"] / "share/arw/build-identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    for entry in identity["staged_payloads"]:
        if entry["path"] == "share/arw/file-contracts.h":
            entry["sha256"] = "0" * 64
    identity_path.write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    inventory_path = integration_fixture["stage"] / "supply-chain/stage-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    for entry in inventory["covered_files"]:
        if entry["path"] == "share/arw/build-identity.json":
            entry["sha256"] = _digest(identity_path)
    inventory_path.write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(IntegrationLockError, match="build identity.*staged_payload"):
        _verify(integration_fixture, lock)


def test_audit_manifest_gate_rejects_rebound_staged_payloads_set(
    integration_fixture: dict[str, Path],
) -> None:
    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    identity_path = integration_fixture["stage"] / "share/arw/build-identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    original = identity["staged_payloads"]
    identity["staged_payloads"] = [
        entry for entry in original if entry["path"] != "hooks/hooks.json"
    ]
    identity_path.write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    inventory_path = integration_fixture["stage"] / "supply-chain/stage-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    for entry in inventory["covered_files"]:
        if entry["path"] == "share/arw/build-identity.json":
            entry["sha256"] = _digest(identity_path)
    inventory_path.write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(IntegrationLockError, match="build identity.*coverage"):
        _verify(integration_fixture, lock)


def test_audit_manifest_gate_rejects_inventory_source_drift(
    integration_fixture: dict[str, Path],
) -> None:
    """Inventory source labels must be recomputed from the path, not trusted.

    A malicious manifest could pin a file under a benign ``inventory_source``
    label to claim a wrong class.  The gate recomputes the label and rejects
    the drift.
    """

    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    inventory_path = integration_fixture["stage"] / "supply-chain/stage-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    for entry in inventory["covered_files"]:
        if entry["path"] == "share/arw/file-contracts.h":
            entry["inventory_source"] = "runtime"  # canonical label is build
    inventory_path.write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(IntegrationLockError, match="source drift"):
        _verify(integration_fixture, lock)


@pytest.mark.parametrize(
    "tamper",
    (
        "components_revision",
        "native_patched_tree",
        "evidence_digest",
        "build_interpreter",
    ),
)
def test_audit_manifest_gate_rejects_metadata_falsification(
    integration_fixture: dict[str, Path], tamper: str
) -> None:
    lock = _build(integration_fixture)
    identity_path = integration_fixture["stage"] / "share/arw/build-identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    if tamper == "components_revision":
        identity["components"][0]["revision"] = "0" * 40
    elif tamper == "native_patched_tree":
        identity["native"]["patched_source_tree_sha256"] = "f" * 64
    elif tamper == "evidence_digest":
        identity["evidence"]["pre_vendor"]["sha256"] = "1" * 64
    else:
        identity["runtime"]["build_interpreter"] = "3.10.0"
    identity_path.write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    inventory_path = integration_fixture["stage"] / "supply-chain/stage-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    for entry in inventory["covered_files"]:
        if entry["path"] == "share/arw/build-identity.json":
            entry["sha256"] = _digest(identity_path)
    inventory_path.write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(IntegrationLockError):
        _verify(integration_fixture, lock)


@pytest.mark.parametrize(
    ("manifest_field", "match"),
    (
        ("post_tree", "post-patch tree"),
        ("test_tree", "native test tree drifts from the pinned expectation"),
    ),
)
def test_paired_manifest_identity_tree_rebind_rejected(
    integration_fixture: dict[str, Path], manifest_field: str, match: str
) -> None:
    """RED: paired manifest+identity tree rewrite cannot move the pinned trees.

    The attacker rewrites ``vendor/source-manifest.json`` (post-patch or
    native test tree) and regenerates the build identity from the tampered
    manifest so both producer artifacts agree.  The verifier must still
    reject because both trees are pinned to constants in the wheel-bound
    verifier code.
    """

    stage = integration_fixture["stage"]
    manifest_path = stage / "vendor/source-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    forged = "9" * 64
    if manifest_field == "post_tree":
        for patch in manifest["patches"]:
            patch["post_tree_sha256"] = forged
    else:
        manifest["native_test_suites"][0]["tree_sha256"] = forged
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if manifest_field == "test_tree":
        # A maximal attacker also rebinds the use/distribution declaration's
        # recorded source-manifest digest so the license gate's live digest
        # comparison stays consistent; only the pinned constant can reject.
        declaration_path = stage / "supply-chain/use-distribution.json"
        declaration = json.loads(declaration_path.read_text(encoding="utf-8"))
        tampered_digest = _digest(manifest_path)
        for record in declaration["evidence_hashes"]:
            if record["path"] == "vendor/source-manifest.json":
                record["sha256"] = tampered_digest
        declaration_path.write_text(
            json.dumps(declaration, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    # Rebuild the audit manifests from the tampered manifest so identity,
    # staged_payloads and inventory all agree with the forged tree.
    _install_audit_manifests(stage)
    _refresh_canary_stage_identity(integration_fixture)
    # Both pinned-tree gates fire while the lock is built: the post-patch
    # tree is cross-checked against staged build evidence, and the native
    # test tree hits the pinned constant in observe_build_identity_binding.
    with pytest.raises(IntegrationLockError, match=match):
        _build(integration_fixture)


def test_build_identity_projection_excludes_staged_payloads(
    integration_fixture: dict[str, Path],
) -> None:
    stage = integration_fixture["stage"]
    source_manifest = json.loads(
        (stage / "vendor/source-manifest.json").read_text(encoding="utf-8")
    )
    before = integration_lock_module.observe_build_identity_binding(
        stage, source_manifest
    )
    identity_path = stage / "share/arw/build-identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity["staged_payloads"] = list(reversed(identity["staged_payloads"]))
    identity_path.write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    after = integration_lock_module.observe_build_identity_binding(
        stage, source_manifest
    )

    assert after == before


def test_audit_manifest_gate_accepts_exact_referenced_canary_tree(
    integration_fixture: dict[str, Path],
) -> None:
    stage = integration_fixture["stage"]
    target = stage / "supply-chain/host-canary"
    shutil.copytree(integration_fixture["canary"].parent, target)
    staged_paths = dict(integration_fixture)
    staged_paths["canary"] = target / integration_fixture["canary"].name
    (stage / "share/arw/build-identity.json").unlink()
    (stage / "supply-chain/stage-inventory.json").unlink()
    _install_audit_manifests(stage)

    lock = _build(staged_paths)
    verification = _verify(staged_paths, lock)

    assert verification.technical_qualification == "PASS"


def test_audit_manifest_gate_rejects_unreferenced_canary_file_after_rebind(
    integration_fixture: dict[str, Path],
) -> None:
    stage = integration_fixture["stage"]
    lock = _build(integration_fixture)
    rogue_relative = "supply-chain/host-canary/unreferenced.json"
    rogue = stage / rogue_relative
    rogue.parent.mkdir(parents=True)
    rogue.write_text("{}\n", encoding="utf-8")

    identity_path = stage / "share/arw/build-identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity["staged_payloads"].append(
        {"path": rogue_relative, "sha256": _digest(rogue)}
    )
    identity["staged_payloads"].sort(key=lambda item: item["path"])
    identity_path.write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    inventory_path = stage / "supply-chain/stage-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    inventory["files"].append(rogue_relative)
    inventory["files"].sort()
    inventory["covered_files"].append(
        {
            "inventory_source": "legal",
            "path": rogue_relative,
            "sha256": _digest(rogue),
        }
    )
    for entry in inventory["covered_files"]:
        if entry["path"] == "share/arw/build-identity.json":
            entry["sha256"] = _digest(identity_path)
    inventory["covered_files"].sort(key=lambda item: item["path"])
    inventory_path.write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(IntegrationLockError, match="canary evidence set is not closed"):
        _verify(integration_fixture, lock)


# ---------------------------------------------------------------------------
# Compact parametrized tamper matrix for the build-identity v2 live recompute.
#
# Each row covers one verifiable surface class; the verifier MUST reject the
# drift on the first live recompute attempt.  The matrix pairs a one-line
# mutation with the precise verifier error string so the audit gate cannot be
# satisfied by a partial rebind attack.
# ---------------------------------------------------------------------------


def _rebind_build_identity(
    stage: Path, *, mutate, extra_rebind_paths: tuple[str, ...] = ()
) -> None:
    """Rebuild the identity + inventory after a mutation.

    The user mutation touches the identity file's content; we then refresh
    every place that records the identity's own digest (the identity's
    own ``staged_payloads`` row + the inventory's ``covered_files`` row) so
    the audit manifest gate does not fail before the live recompute runs.
    When ``extra_rebind_paths`` is supplied, every additional staged file
    whose bytes have changed is also rebinded in both ``staged_payloads``
    and ``covered_files`` so a full consistent rebind attack can be
    exercised by the tests.
    """

    identity_path = stage / "share/arw/build-identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    mutate(identity)
    for path in extra_rebind_paths:
        current = _digest(stage / path)
        for entry in identity["staged_payloads"]:
            if entry["path"] == path:
                entry["sha256"] = current
    identity_path.write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    new_identity_digest = _digest(identity_path)
    for entry in identity["staged_payloads"]:
        if entry["path"] == AUDIT_BUILD_IDENTITY_RELATIVE:
            entry["sha256"] = new_identity_digest
    identity_path.write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    inventory_path = stage / "supply-chain/stage-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    for entry in inventory["covered_files"]:
        if entry["path"] == AUDIT_BUILD_IDENTITY_RELATIVE:
            entry["sha256"] = new_identity_digest
        elif entry["path"] in extra_rebind_paths:
            entry["sha256"] = _digest(stage / entry["path"])
    inventory_path.write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


@pytest.mark.parametrize(
    ("field", "mutate", "match"),
    [
        # ---- one row per evidence digestPath --------------------------------
        (
            "evidence.pre_vendor.sha256",
            lambda identity: identity["evidence"]["pre_vendor"].__setitem__(
                "sha256", "1" * 64
            ),
            "evidence.pre_vendor",
        ),
        (
            "evidence.legal.sha256",
            lambda identity: identity["evidence"]["legal"].__setitem__(
                "sha256", "2" * 64
            ),
            "evidence.legal",
        ),
        (
            "evidence.upstream.verdict.sha256",
            lambda identity: identity["evidence"]["upstream"]["verdict"].__setitem__(
                "sha256", "3" * 64
            ),
            "evidence.upstream",
        ),
        (
            "evidence.asan_ubsan.verdict.sha256",
            lambda identity: identity["evidence"]["asan_ubsan"]["verdict"].__setitem__(
                "sha256", "4" * 64
            ),
            "evidence.asan_ubsan",
        ),
        (
            "evidence.tsan.verdict.sha256",
            lambda identity: identity["evidence"]["tsan"]["verdict"].__setitem__(
                "sha256", "5" * 64
            ),
            "evidence.tsan",
        ),
        # ---- schema aggregate / individual schema file -----------------------
        (
            "schemas.aggregate_sha256",
            lambda identity: identity["schemas"].__setitem__(
                "aggregate_sha256", "f" * 64
            ),
            "schemas aggregate sha256",
        ),
        (
            "schemas.files[1].sha256",
            lambda identity: identity["schemas"]["files"][1].__setitem__(
                "sha256", "9" * 64
            ),
            "schemas entry #1",
        ),
        # ---- derived projection digests -------------------------------------
        (
            "projection.patch_set_sha256",
            lambda identity: identity["projection"].__setitem__(
                "patch_set_sha256", "a" * 64
            ),
            "projection.patch_set_sha256",
        ),
        (
            "projection.profile_patch_sha256",
            lambda identity: identity["projection"].__setitem__(
                "profile_patch_sha256", "b" * 64
            ),
            "projection.profile_patch_sha256",
        ),
        (
            "projection.query_launcher.sha256",
            lambda identity: identity["projection"]["query_launcher"].__setitem__(
                "sha256", "c" * 64
            ),
            "projection.query_launcher",
        ),
        # ---- file contract header / embedded contract sha256 ---------------
        (
            "file_contract.header.sha256",
            lambda identity: identity["file_contract"]["header"].__setitem__(
                "sha256", "d" * 64
            ),
            "file_contract.header",
        ),
        (
            "file_contract.contract_sha256",
            lambda identity: identity["file_contract"].__setitem__(
                "contract_sha256", "e" * 64
            ),
            "file_contract.contract_sha256",
        ),
        # ---- wheelhouse digestPaths ----------------------------------------
        (
            "wheelhouse.lock.sha256",
            lambda identity: identity["wheelhouse"]["lock"].__setitem__(
                "sha256", "0" * 64
            ),
            "wheelhouse.lock",
        ),
        (
            "wheelhouse.requirements.sha256",
            lambda identity: identity["wheelhouse"]["requirements"].__setitem__(
                "sha256", "1" * 64
            ),
            "wheelhouse.requirements",
        ),
        (
            "wheelhouse.first_party.sha256",
            lambda identity: identity["wheelhouse"]["first_party"].__setitem__(
                "sha256", "2" * 64
            ),
            "wheelhouse.first_party",
        ),
        # ---- native digestPaths ---------------------------------------------
        (
            "native.binary.sha256",
            lambda identity: identity["native"]["binary"].__setitem__(
                "sha256", "3" * 64
            ),
            "native.binary",
        ),
        (
            "native.build_evidence.sha256",
            lambda identity: identity["native"]["build_evidence"].__setitem__(
                "sha256", "4" * 64
            ),
            "native.build_evidence",
        ),
        # ---- plugin.version -------------------------------------------------
        (
            "plugin.version",
            lambda identity: identity["plugin"].__setitem__(
                "version", "0.1.0+falsified"
            ),
            "plugin.version",
        ),
        # ---- source-manifest component trees (non-recomputable authority) ----
        (
            "native.patched_source_tree_sha256",
            lambda identity: identity["native"].__setitem__(
                "patched_source_tree_sha256", "f" * 64
            ),
            "native.patched_source_tree_sha256",
        ),
        (
            "native.upstream_test_tree_sha256",
            lambda identity: identity["native"].__setitem__(
                "upstream_test_tree_sha256", "e" * 64
            ),
            "native.upstream_test_tree_sha256",
        ),
    ],
)
def test_build_identity_live_recompute_tamper_matrix(
    integration_fixture: dict[str, Path], field: str, mutate, match: str
) -> None:
    """Each verifiable surface must reject on the first live recompute attempt."""

    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    _rebind_build_identity(integration_fixture["stage"], mutate=mutate)
    with pytest.raises(IntegrationLockError, match=match):
        _verify(integration_fixture, lock)


@pytest.mark.parametrize(
    ("label", "target_relative"),
    [
        ("pre_vendor", "share/arw/evidence/pre_vendor.json"),
        ("legal", "share/arw/evidence/legal.json"),
        ("upstream", "share/arw/evidence/upstream.json"),
        ("asan_ubsan", "share/arw/evidence/asan_ubsan.json"),
        ("tsan", "share/arw/evidence/tsan.json"),
    ],
)
def test_evidence_partial_rebind_rejects_on_live_bytes_drift(
    integration_fixture: dict[str, Path], label: str, target_relative: str
) -> None:
    """Partial rebind: only ``inventory.covered_files`` is updated.

    A naive attacker flips ``technical_qualification`` on the staged file
    *and* rebinds the inventory's coverage digest but leaves the identity
    digestPath claim on the old bytes.  The verifier must catch this on the
    first live recompute pass (digestPath live bytes mismatch) before the
    PASS-semantic check has a chance to run.
    """

    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    target = integration_fixture["stage"] / target_relative
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["technical_qualification"] = "BLOCKED"
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    # Partial rebind: only the inventory is updated; the identity digestPath
    # claim is left on the stale bytes so the verifier must reject on the
    # live bytes check, not on the PASS semantic check.
    inventory_path = integration_fixture["stage"] / "supply-chain/stage-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    for entry in inventory["covered_files"]:
        if entry["path"] == target_relative:
            entry["sha256"] = _digest(target)
    inventory_path.write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _refresh_canary_stage_identity(integration_fixture)
    with pytest.raises(IntegrationLockError, match="live bytes do not match"):
        _verify(integration_fixture, lock)


def test_evidence_path_redirect_to_uncovered_file_is_rejected(
    integration_fixture: dict[str, Path],
) -> None:
    """A digestPath cannot be redirected at a file absent from staged_payloads."""

    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    # Choose a file that is in the stage but not in staged_payloads (the
    # identity file itself is cycle-excluded and is the only "shadow" target).
    identity_path = integration_fixture["stage"] / "share/arw/build-identity.json"
    identity_digest = _digest(identity_path)
    target = "share/arw/build-identity.json"

    def _redirect(identity: dict[str, object]) -> None:
        evidence = cast(dict[str, object], identity["evidence"])
        evidence["pre_vendor"] = {
            "path": target,
            "sha256": identity_digest,
        }

    _rebind_build_identity(integration_fixture["stage"], mutate=_redirect)
    with pytest.raises(IntegrationLockError, match="cycle-forming metadata"):
        _verify(integration_fixture, lock)


@pytest.mark.parametrize(
    ("label", "target_relative"),
    [
        ("pre_vendor", "share/arw/evidence/pre_vendor.json"),
        ("legal", "share/arw/evidence/legal.json"),
        ("upstream", "share/arw/evidence/upstream.json"),
        ("asan_ubsan", "share/arw/evidence/asan_ubsan.json"),
        ("tsan", "share/arw/evidence/tsan.json"),
    ],
)
def test_evidence_full_consistent_rebind_rejects_on_pass_semantic(
    integration_fixture: dict[str, Path], label: str, target_relative: str
) -> None:
    """Full consistent rebind: identity, staged_payloads, AND inventory.

    An attacker rewrites the staged evidence file (flipping
    ``technical_qualification`` from PASS to BLOCKED) and updates all
    three digest records to the new bytes:

    * ``identity.evidence[label].sha256``
    * ``identity.staged_payloads[path].sha256``
    * ``inventory.covered_files[path].sha256``

    The canary stage_sha256 is also refreshed to track the new live stage
    identity.  With every digest claim consistent, the verifier MUST reject
    only because of the closed ``technical_qualification: PASS`` semantic
    binding the evidence surface.
    """

    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    target = integration_fixture["stage"] / target_relative
    payload = json.loads(target.read_text(encoding="utf-8"))
    # Flip the semantic gate: every evidence surface must DERIVE PASS from
    # its content; flipping the declared field to BLOCKED without changing
    # the semantics is the closed semantic-attack the new verifier catches.
    payload["technical_qualification"] = "BLOCKED"
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    def _rebind(identity: dict[str, object]) -> None:
        evidence = cast(dict[str, object], identity["evidence"])
        entry = cast(dict[str, object], evidence[label])
        if label in {"pre_vendor", "legal"}:
            entry["sha256"] = _digest(target)
            return
        verdict = cast(dict[str, object], entry["verdict"])
        verdict["sha256"] = _digest(target)

    # _rebind_build_identity refreshes identity.evidence[label], the
    # identity's own staged_payloads row, the inventory.covered_files row
    # for the evidence file, AND the inventory.covered_files row for the
    # identity file.  ``extra_rebind_paths`` additionally rebinds the
    # identity's ``staged_payloads`` entry for the tampered evidence file so
    # all three digest records (identity.evidence, identity.staged_payloads,
    # inventory.covered_files) move together.
    _rebind_build_identity(
        integration_fixture["stage"],
        mutate=_rebind,
        extra_rebind_paths=(target_relative,),
    )
    _refresh_canary_stage_identity(integration_fixture)
    # With every digest claim consistent, the rejection MUST come from the
    # closed ``technical_qualification: PASS`` semantic - never from a
    # digestPath live-bytes or staged_payloads mismatch.  The verifier
    # reports the semantic derivation mismatch (``declared='BLOCKED'``
    # vs derived='PASS') so the regex anchors on the surface and
    # derivation language.
    with pytest.raises(
        IntegrationLockError,
        match=f"evidence.{label}.*derive 'PASS'",
    ):
        _verify(integration_fixture, lock)


def test_installed_verifier_does_not_read_original_build_evidence_tree(
    integration_fixture: dict[str, Path],
) -> None:
    """The live recompute must be bound to staged copies only.

    Removing the original ``build/evidence`` tree (which would not exist in a
    clean install) must not affect the audit gate: the staged copies under
    ``share/arw/evidence`` are the sole live source.
    """

    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    # A clean install has no ``build/evidence`` tree at all; the verifier
    # must still produce a passing receipt because every claim is bound to the
    # staged copies.
    receipt = _verify(integration_fixture, lock)
    assert receipt.technical_qualification == "PASS"


# ---------------------------------------------------------------------------
# Codex P1 3884109619: file_contract.contract_sha256 must equal the embedded
# ``ARW_FILES_CONTRACT_SHA256`` carried inside the staged header.  An earlier
# revision accepted either the embedded semantic OR the whole-header file
# digest; the latter was an unjustified alias that allowed a rebind attack
# to satisfy the contract claim by rewriting only the header bytes.  The
# compact RED/GREEN tests below pin the new semantic.
# ---------------------------------------------------------------------------


def test_file_contract_contract_sha256_must_equal_embedded_semantic_red(
    integration_fixture: dict[str, Path],
) -> None:
    """RED: outer header digest cannot alias the embedded contract semantic.

    The identity passes schema validation AND the digestPath live-bytes
    check (the header file is unchanged), but records the whole-header
    digest in place of the embedded ``ARW_FILES_CONTRACT_SHA256`` value.
    The verifier MUST reject this rebind.
    """

    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    contracts_path = integration_fixture["stage"] / "share/arw/file-contracts.h"
    outer_header_digest = _digest(contracts_path)

    def _swap(identity: dict[str, object]) -> None:
        # Replace the embedded semantic with the whole-header file digest;
        # this would have been accepted by the prior ``in {a, b}`` alias.
        file_contract = cast(dict[str, object], identity["file_contract"])
        file_contract["contract_sha256"] = outer_header_digest

    _rebind_build_identity(integration_fixture["stage"], mutate=_swap)
    with pytest.raises(
        IntegrationLockError, match="embedded in the regenerated header"
    ):
        _verify(integration_fixture, lock)


def test_file_contract_contract_sha256_embedded_semantic_green(
    integration_fixture: dict[str, Path],
) -> None:
    """GREEN: identity that records the embedded value passes the verifier."""

    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    receipt = _verify(integration_fixture, lock)
    assert receipt.technical_qualification == "PASS"
    # The producer recorded the embedded value, NOT the whole-header digest;
    # these are distinct by construction.
    contracts_path = integration_fixture["stage"] / "share/arw/file-contracts.h"
    contracts_digest = _digest(contracts_path)
    identity = json.loads(
        (integration_fixture["stage"] / "share/arw/build-identity.json").read_text(
            encoding="utf-8"
        )
    )
    assert identity["file_contract"]["contract_sha256"] != contracts_digest, (
        "fixture must record the embedded semantic, not the whole-header digest"
    )


def test_schema_aggregate_matches_canonical_helper(
    integration_fixture: dict[str, Path],
) -> None:
    """The identity's schemas aggregate must equal ``aggregate_schema_sha256``."""

    from arw.schema_registry import aggregate_schema_sha256

    identity = json.loads(
        (integration_fixture["stage"] / "share/arw/build-identity.json").read_text(
            encoding="utf-8"
        )
    )
    entries = [(item["path"], item["sha256"]) for item in identity["schemas"]["files"]]
    assert aggregate_schema_sha256(entries) == identity["schemas"]["aggregate_sha256"]


# ---------------------------------------------------------------------------
# Codex P1 3884328234 / 3884328236: parser hardening and python_requires pin.
#
# The producer must use the SAME comment-aware parser as the verifier; the
# ``runtime.build_interpreter`` claim must equal the live staged
# ``.python-version`` exactly; the verifier must NEVER compare against its
# own runtime.  The compact RED/GREEN tests below pin each invariant.
# ---------------------------------------------------------------------------


def _write_header(path: Path, body: str) -> str:
    path.write_text(body, encoding="ascii")
    return _digest(path)


def test_file_contract_parser_rejects_line_comment_decoy(tmp_path: Path) -> None:
    """RED: line-commented define cannot satisfy the directive."""

    header = tmp_path / "file-contracts.h"
    real_value = "a" * 64
    _write_header(
        header,
        '// #define ARW_FILES_CONTRACT_SHA256 "' + "f" * 64 + '"\n'
        '#define ARW_FILES_CONTRACT_SHA256 "' + real_value + '"\n',
    )
    assert (
        integration_lock_module.parse_file_contract_contract_sha256(header)
        == real_value
    )


def test_file_contract_parser_rejects_block_comment_decoy(tmp_path: Path) -> None:
    """RED: block-commented define cannot shadow the active directive."""

    header = tmp_path / "file-contracts.h"
    real_value = "b" * 64
    _write_header(
        header,
        '/*\n  #define ARW_FILES_CONTRACT_SHA256 "' + "f" * 64 + '"\n*/\n'
        '#define ARW_FILES_CONTRACT_SHA256 "' + real_value + '"\n',
    )
    assert (
        integration_lock_module.parse_file_contract_contract_sha256(header)
        == real_value
    )


def test_file_contract_parser_rejects_duplicate_active_defines(tmp_path: Path) -> None:
    """RED: more than one active define is a hard error (no aliasing)."""

    header = tmp_path / "file-contracts.h"
    _write_header(
        header,
        '#define ARW_FILES_CONTRACT_SHA256 "' + "c" * 64 + '"\n'
        '#define ARW_FILES_CONTRACT_SHA256 "' + "d" * 64 + '"\n',
    )
    with pytest.raises(IntegrationLockError, match="more than once"):
        integration_lock_module.parse_file_contract_contract_sha256(header)


def test_file_contract_parser_rejects_missing_active_define(tmp_path: Path) -> None:
    """RED: no active define (only commented decoys) is rejected."""

    header = tmp_path / "file-contracts.h"
    _write_header(
        header,
        '// #define ARW_FILES_CONTRACT_SHA256 "' + "e" * 64 + '"\n',
    )
    with pytest.raises(IntegrationLockError, match="does not embed an active"):
        integration_lock_module.parse_file_contract_contract_sha256(header)


def test_runtime_build_interpreter_must_equal_staged_python_version(
    integration_fixture: dict[str, Path],
) -> None:
    """RED: consistent rebind of build_interpreter to a non-staged value is rejected."""

    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)

    def _tamper(identity: dict[str, object]) -> None:
        runtime = cast(dict[str, object], identity["runtime"])
        runtime["build_interpreter"] = "3.13.99"

    _rebind_build_identity(integration_fixture["stage"], mutate=_tamper)
    with pytest.raises(IntegrationLockError, match="must equal staged .python-version"):
        _verify(integration_fixture, lock)


def test_runtime_build_interpreter_green_exact_staged_pin(
    integration_fixture: dict[str, Path],
) -> None:
    """GREEN: identity whose build_interpreter equals the staged pin passes."""

    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    receipt = _verify(integration_fixture, lock)
    assert receipt.technical_qualification == "PASS"
    staged = (
        (integration_fixture["stage"] / ".python-version")
        .read_text(encoding="ascii")
        .strip()
    )
    identity = json.loads(
        (integration_fixture["stage"] / "share/arw/build-identity.json").read_text(
            encoding="utf-8"
        )
    )
    assert identity["runtime"]["build_interpreter"] == staged


def test_runtime_build_interpreter_verifier_runtime_is_not_compared(
    integration_fixture: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """GREEN: verifier running on a different interpreter still passes.

    The verifier must NOT compare ``build_interpreter`` against
    ``sys.version_info``; it only reads the staged ``.python-version``.
    Mock the current platform so the assertion below would fail if the
    verifier ever sneaks in a runtime self-comparison.
    """

    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)

    class _FakeVersionInfo:
        major = 9
        minor = 9
        micro = 9
        releaselevel = "final"
        serial = 0

    monkeypatch.setattr(sys, "version_info", _FakeVersionInfo())
    monkeypatch.setattr(platform, "python_version", lambda: "9.9.9")
    receipt = _verify(integration_fixture, lock)
    assert receipt.technical_qualification == "PASS"


def test_build_identity_schema_rejects_legacy_python_310_interpreter(
    tmp_path: Path,
) -> None:
    """RED: 3.10.x build_interpreter is rejected by the tightened schema."""

    from arw.schema_registry import validate_instance

    identity = {
        "schema_version": "1.0.0",
        "platform_claim": "linux",
        "plugin": {"name": "academic-research-workbench", "version": "0.1.0"},
        "runtime": {"python_requires": ">=3.13", "build_interpreter": "3.10.0"},
        "components": [
            {
                "id": "academic-research-skills",
                "version": "pinned",
                "revision": "0" * 40,
                "tree_sha256": "a" * 64,
            }
        ],
        "patches": [],
        "native": {
            "binary": {"path": "libexec/file-base-mcp", "sha256": "b" * 64},
            "build_evidence": {
                "path": ".file-base/build-evidence.json",
                "sha256": "c" * 64,
            },
            "compile_profile": "release-o2",
            "patched_source_tree_sha256": "d" * 64,
            "upstream_test_tree_sha256": "e" * 64,
        },
        "projection": {
            "algorithm": "research-graph-projection-v1",
            "oracle": "research-graph-normalization-v1",
            "native_profile": "research-graph-builder-v1",
            "patch_set_sha256": "f" * 64,
            "profile_patch_sha256": "0" * 64,
            "query_profile": "arw-graph-mcp-v1",
            "query_launcher": {"path": "scripts/x", "sha256": "1" * 64},
        },
        "file_contract": {
            "header": {"path": "share/arw/file-contracts.h", "sha256": "2" * 64},
            "contract_sha256": "3" * 64,
            "tokenizer_id": "unicode61-cjk-v1",
            "ranking_version": "files-rank-v1",
            "outline_versions": [
                "bibtex-outline-v1",
                "latex-outline-v1",
                "markdown-outline-v1",
                "source-outline-v1",
            ],
        },
        "wheelhouse": {
            "lock": {"path": "vendor/python/wheelhouse.lock.json", "sha256": "4" * 64},
            "requirements": {"path": "x", "sha256": "5" * 64},
            "first_party": {"path": "y", "sha256": "6" * 64},
        },
        "schemas": {
            "aggregate_sha256": "7" * 64,
            "files": [
                {
                    "path": "share/arw/schemas/build-identity.schema.json",
                    "sha256": "8" * 64,
                }
            ],
        },
        "evidence": {
            "pre_vendor": {
                "path": "share/arw/evidence/pre_vendor.json",
                "sha256": "9" * 64,
            },
            "legal": {"path": "share/arw/evidence/legal.json", "sha256": "a" * 64},
            "upstream": {
                "path": "share/arw/evidence/upstream.json",
                "sha256": "b" * 64,
            },
            "asan_ubsan": {
                "path": "share/arw/evidence/asan_ubsan.json",
                "sha256": "c" * 64,
            },
            "tsan": {"path": "share/arw/evidence/tsan.json", "sha256": "d" * 64},
        },
        "staged_payloads": [{"path": "z", "sha256": "e" * 64}],
    }
    with pytest.raises(Exception, match="3\\.10|build_interpreter"):
        validate_instance("build-identity.schema.json", identity)


# ---------------------------------------------------------------------------
# Codex P1 3884618556 / 3884618560 / 3884618565: regenerated file-contract
# header is the security authority, not the staged bytes.
#
# The verifier regenerates the expected header from the staged checked
# schemas, requires byte equality, and extracts the embedded semantic from
# the regeneration.  The staged bytes are no longer authoritative, so a
# paired rebind (rewrite header + identity + staged_payloads + inventory)
# is rejected on the regeneration step.  Python support is exact 3.13/3.14.
# ---------------------------------------------------------------------------


def test_file_contract_paired_rebind_rejects_on_regeneration_mismatch(
    integration_fixture: dict[str, Path],
) -> None:
    """RED: paired rewrite of header+identity+staged_payloads+inventory rejected."""

    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    header_path = integration_fixture["stage"] / "share/arw/file-contracts.h"

    # Tamper the staged header with an arbitrary new embedded value AND
    # rebind every digestPath reference to the new bytes.  This is the
    # strongest possible rebind attack: identity, staged_payloads, AND
    # inventory all carry the new digest.  The regeneration step still
    # catches the drift because the staged bytes are not what the staged
    # schemas regenerate.
    fake_value = "1" * 64
    fake_bytes = (
        b"/* Generated by scripts/generate-file-contract-header. Do not edit. */\n"
        b"#ifndef ARW_GENERATED_FILE_CONTRACTS_H\n"
        b"#define ARW_GENERATED_FILE_CONTRACTS_H\n"
        b'#define ARW_FILES_CONTRACT_SHA256 "' + fake_value.encode() + b'"\n'
        b"#endif\n"
    )
    header_path.write_bytes(fake_bytes)

    def _mutate(identity: dict[str, object]) -> None:
        file_contract = cast(dict[str, object], identity["file_contract"])
        header = cast(dict[str, object], file_contract["header"])
        header["sha256"] = _digest(header_path)
        file_contract["contract_sha256"] = fake_value

    _rebind_build_identity(
        integration_fixture["stage"],
        mutate=_mutate,
        extra_rebind_paths=("share/arw/file-contracts.h",),
    )
    _refresh_canary_stage_identity(integration_fixture)
    with pytest.raises(
        IntegrationLockError, match="regenerated from the staged checked schemas"
    ):
        _verify(integration_fixture, lock)


def test_file_contract_if0_decoy_plus_continued_define_rejects(
    integration_fixture: dict[str, Path],
) -> None:
    """RED: #if 0 decoy followed by a continued real define is rejected.

    Even if the parser has to handle ``#if 0`` blocks, the regeneration
    step is the security authority.  Any attempt to wrap a fake define in
    preprocessor conditionals that the parser does not honour is moot
    because the staged bytes still must equal the regeneration.
    """

    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    header_path = integration_fixture["stage"] / "share/arw/file-contracts.h"
    original_bytes = header_path.read_bytes()

    # Inject ``#if 0 ... #endif`` that contains a fake real define plus
    # shadowed real content.  The regeneration step rejects the drift
    # regardless of how the parser would handle the conditional.
    fake_value = "2" * 64
    tampered = (
        b"#if 0\n"
        b'#define ARW_FILES_CONTRACT_SHA256 "' + fake_value.encode() + b'"\n'
        b"#endif\n" + original_bytes
    )
    header_path.write_bytes(tampered)

    def _mutate(identity: dict[str, object]) -> None:
        file_contract = cast(dict[str, object], identity["file_contract"])
        header = cast(dict[str, object], file_contract["header"])
        header["sha256"] = _digest(header_path)
        file_contract["contract_sha256"] = fake_value

    _rebind_build_identity(
        integration_fixture["stage"],
        mutate=_mutate,
        extra_rebind_paths=("share/arw/file-contracts.h",),
    )
    _refresh_canary_stage_identity(integration_fixture)
    with pytest.raises(
        IntegrationLockError, match="regenerated from the staged checked schemas"
    ):
        _verify(integration_fixture, lock)


def test_file_contract_current_header_exact_regeneration_green(
    integration_fixture: dict[str, Path],
) -> None:
    """GREEN: identity whose header is exactly the regenerated bytes passes."""

    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    receipt = _verify(integration_fixture, lock)
    assert receipt.technical_qualification == "PASS"


def _rebind_inventory_coverage(stage: Path, *relative_paths: str) -> None:
    inventory_path = stage / "supply-chain/stage-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    covered = {item["path"]: item for item in inventory["covered_files"]}
    for relative in relative_paths:
        covered[relative]["sha256"] = _digest(stage / relative)
    inventory_path.write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def test_runtime_python_version_15_is_rejected_by_verifier(
    integration_fixture: dict[str, Path],
) -> None:
    """RED: 3.15 staged pin is rejected by ``observe_staged_python_version``."""

    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    (integration_fixture["stage"] / ".python-version").write_text(
        "3.15.0\n", encoding="ascii"
    )

    def _mutate(identity: dict[str, object]) -> None:
        runtime = cast(dict[str, object], identity["runtime"])
        runtime["build_interpreter"] = "3.15.0"

    _rebind_build_identity(
        integration_fixture["stage"],
        mutate=_mutate,
        extra_rebind_paths=(".python-version",),
    )
    _refresh_canary_stage_identity(integration_fixture)
    # Schema validation catches 3.15 before the runtime check; either
    # gate is an acceptable rejection.
    with pytest.raises(
        IntegrationLockError,
        match="exactly 3\\.13\\.x or 3\\.14\\.x|does not match '\\^3",
    ):
        _verify(integration_fixture, lock)


def test_runtime_python_version_13_and_14_are_green(
    integration_fixture: dict[str, Path],
) -> None:
    """GREEN: 3.13.x and 3.14.x staged pins both pass the verifier."""

    for pin in ("3.13.7", "3.14.2"):
        stage = integration_fixture["stage"]
        (stage / ".python-version").write_text(f"{pin}\n", encoding="ascii")

        def _mutate(identity: dict[str, object], pinned: str = pin) -> None:
            runtime = cast(dict[str, object], identity["runtime"])
            runtime["build_interpreter"] = pinned

        _rebind_build_identity(
            stage, mutate=_mutate, extra_rebind_paths=(".python-version",)
        )
        _refresh_canary_stage_identity(integration_fixture)
        # Rebuild the lock from the live stage so the rebuild path is
        # exercised, then re-verify with that lock.
        integration_fixture["lock"].unlink(missing_ok=True)
        fresh_lock = _build(integration_fixture)
        write_integration_lock(integration_fixture["lock"], fresh_lock)
        receipt = _verify(integration_fixture, fresh_lock)
        assert receipt.technical_qualification == "PASS"


# ---------------------------------------------------------------------------
# Codex round-42 P1 (comment 3886042142): the verifier must DERIVE
# ``technical_qualification`` from full semantic validation of each
# phase-01 evidence surface, never trust a self-asserted field.  The
# NetworkVerdict / LegalVerdict / PreVendorReceipt producer contracts in
# ``arw.integration_lock`` are the single source of truth for both the
# installed verifier and the producer (``stage-plugin`` ``staged_evidence``).
# ---------------------------------------------------------------------------


EVIDENCE_SURFACES = (
    ("pre_vendor", "share/arw/evidence/pre_vendor.json"),
    ("legal", "share/arw/evidence/legal.json"),
    ("upstream", "share/arw/evidence/upstream.json"),
    ("upstream_command", "share/arw/evidence/upstream_command.json"),
    (
        "upstream_sanitizer_verdict",
        "share/arw/evidence/upstream_sanitizer_verdict.json",
    ),
    ("upstream_test_suite_sha256", "share/arw/evidence/upstream_test_suite_sha256.txt"),
    ("upstream_status", "share/arw/evidence/upstream_status.txt"),
    ("asan_ubsan", "share/arw/evidence/asan_ubsan.json"),
    ("asan_ubsan_command", "share/arw/evidence/asan_ubsan_command.json"),
    (
        "asan_ubsan_sanitizer_verdict",
        "share/arw/evidence/asan_ubsan_sanitizer_verdict.json",
    ),
    (
        "asan_ubsan_test_suite_sha256",
        "share/arw/evidence/asan_ubsan_test_suite_sha256.txt",
    ),
    ("asan_ubsan_status", "share/arw/evidence/asan_ubsan_status.txt"),
    ("tsan", "share/arw/evidence/tsan.json"),
    ("tsan_command", "share/arw/evidence/tsan_command.json"),
    ("tsan_sanitizer_verdict", "share/arw/evidence/tsan_sanitizer_verdict.json"),
    ("tsan_test_suite_sha256", "share/arw/evidence/tsan_test_suite_sha256.txt"),
    ("tsan_status", "share/arw/evidence/tsan_status.txt"),
)

EVIDENCE_REJECTION_PATTERN = (
    r"producer contract|NativeCommandReceipt contract|"
    r"NativeSanitizerVerdict contract|test suite digest|status file|"
    r"test_suite_sha256\.txt|status\.txt"
)


def _replace_staged_evidence_with_passthrough_stub(
    integration_fixture: dict[str, Path], target_relative: str
) -> None:
    """Replace a staged evidence file with a stub that asserts only PASS.

    This is the attack the new verifier must reject: a single self-asserted
    field cannot satisfy the producer contract.
    """

    target = integration_fixture["stage"] / target_relative
    target.write_text(
        json.dumps({"technical_qualification": "PASS"}, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _rebind_all_evidence_records(
    integration_fixture: dict[str, Path], target_relative: str
) -> None:
    """Refresh identity, staged_payloads, and inventory for a tampered file.

    For pre_vendor/legal (single digestPath surface) the rebind is a
    simple digest update.  For native surfaces (5-file bundle), the
    matching sub-field gets its digest updated and any other sub-fields
    in the same bundle keep their existing digests - the audit manifest
    gate only re-verifies the digest we tampered with.
    """

    target = integration_fixture["stage"] / target_relative
    target_digest = _digest(target)

    def _mutate(identity: dict[str, object]) -> None:
        evidence = cast(dict[str, object], identity["evidence"])
        # pre_vendor + legal are single digestPath surfaces.
        if target_relative in {
            "share/arw/evidence/pre_vendor.json",
            "share/arw/evidence/legal.json",
        }:
            for label, relative in EVIDENCE_SURFACES:
                if relative == target_relative:
                    evidence[label] = {
                        "path": relative,
                        "sha256": target_digest,
                    }
        else:
            # Native surface bundle: figure out which kind within the
            # bundle was tampered with by matching the path suffix.
            for native_surface in ("upstream", "asan_ubsan", "tsan"):
                for kind in (
                    "verdict",
                    "command",
                    "sanitizer_verdict",
                    "test_suite_sha256",
                    "status",
                ):
                    kind_relative = integration_lock_module.native_evidence_path(
                        native_surface, kind
                    )
                    if kind_relative == target_relative:
                        bundle = cast(dict[str, object], evidence[native_surface])
                        bundle[kind] = {
                            "path": kind_relative,
                            "sha256": target_digest,
                        }

    _rebind_build_identity(
        integration_fixture["stage"],
        mutate=_mutate,
        extra_rebind_paths=(target_relative,),
    )
    _refresh_canary_stage_identity(integration_fixture)


@pytest.mark.parametrize(("label", "target_relative"), EVIDENCE_SURFACES)
def test_evidence_stub_only_passthrough_always_rejected(
    integration_fixture: dict[str, Path], label: str, target_relative: str
) -> None:
    """RED: a passthrough stub {"technical_qualification":"PASS"} is rejected.

    Even with full consistent rebinds (identity, staged_payloads,
    inventory), the verifier must reject because the file lacks every
    required producer-contract field.
    """

    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    _replace_staged_evidence_with_passthrough_stub(integration_fixture, target_relative)
    _rebind_all_evidence_records(integration_fixture, target_relative)
    with pytest.raises(
        IntegrationLockError,
        match=EVIDENCE_REJECTION_PATTERN,
    ):
        _verify(integration_fixture, lock)


@pytest.mark.parametrize(("label", "target_relative"), EVIDENCE_SURFACES)
def test_evidence_stub_only_passthrough_rejected_at_build_too(
    integration_fixture: dict[str, Path], label: str, target_relative: str
) -> None:
    """RED: a passthrough stub is also rejected by ``build_integration_lock``.

    The build path calls ``observe_build_identity_binding`` which in turn
    calls ``_verify_evidence_pass``; the contract gate fires before any
    audit manifest gate can run.
    """

    # Build the baseline lock so the canary stage_sha256 is set against
    # the unmodified stage; mutate the evidence afterwards and rebind
    # identity + staged_payloads + inventory to the new bytes so the
    # rebuild flow reaches the producer-contract gate (not the digestPath
    # live-bytes gate).
    _build(integration_fixture)
    _replace_staged_evidence_with_passthrough_stub(integration_fixture, target_relative)
    _rebind_all_evidence_records(integration_fixture, target_relative)
    with pytest.raises(IntegrationLockError, match=EVIDENCE_REJECTION_PATTERN):
        _build(integration_fixture)


def _mutate_network_verdict(integration_fixture: dict[str, Path], mutation) -> None:
    """Apply a mutation to the upstream NetworkVerdict and rebind all evidence."""

    target = integration_fixture["stage"] / "share/arw/evidence/upstream.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    mutation(payload)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _rebind_all_evidence_records(
        integration_fixture, "share/arw/evidence/upstream.json"
    )


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (
            lambda p: p.__setitem__("command_status", 1),
            "producer contract|derive 'BLOCKED'",
        ),
        (
            lambda p: p.__setitem__("network_namespace_denied", False),
            "producer contract|derive 'BLOCKED'",
        ),
        (
            lambda p: p.__setitem__("network_syscall_attempts", ["connect"]),
            "producer contract|derive 'BLOCKED'",
        ),
        (
            lambda p: p.__setitem__(
                "child_network_namespace", p["host_network_namespace"]
            ),
            "producer contract|derive 'BLOCKED'",
        ),
    ],
)
def test_network_verdict_semantic_falsifications_rejected(
    integration_fixture: dict[str, Path], mutation, match: str
) -> None:
    """RED: every NetworkVerdict semantic falsifier is rejected.

    The verifier derives ``PASS`` from ``command_status==0 AND
    network_namespace_denied is True AND network_syscall_attempts is []``;
    flipping any of those flips the derivation to BLOCKED.
    """

    _mutate_network_verdict(integration_fixture, mutation)
    with pytest.raises(IntegrationLockError, match=match):
        _build(integration_fixture)


def test_legal_verdict_component_sha_mismatch_rejected(
    integration_fixture: dict[str, Path],
) -> None:
    """RED: legal verdict with mismatched source/staged sha256 is rejected."""

    target = integration_fixture["stage"] / "share/arw/evidence/legal.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["components"][0]["staged_sha256"] = "f" * 64
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _rebind_all_evidence_records(integration_fixture, "share/arw/evidence/legal.json")
    with pytest.raises(
        IntegrationLockError, match="staged_sha256 must equal source_sha256"
    ):
        _build(integration_fixture)


def test_legal_verdict_wrong_reason_codes_rejected(
    integration_fixture: dict[str, Path],
) -> None:
    """RED: legal verdict with wrong reason_codes is rejected."""

    target = integration_fixture["stage"] / "share/arw/evidence/legal.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["reason_codes"] = list(reversed(payload["reason_codes"]))
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _rebind_all_evidence_records(integration_fixture, "share/arw/evidence/legal.json")
    with pytest.raises(IntegrationLockError, match="qualified blockers"):
        _build(integration_fixture)


def test_pre_vendor_unmodified_false_rejected(
    integration_fixture: dict[str, Path],
) -> None:
    """RED: pre_vendor with native_file_base_gate.unmodified=false is rejected."""

    target = integration_fixture["stage"] / "share/arw/evidence/pre_vendor.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["native_file_base_gate"]["unmodified"] = False
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _rebind_all_evidence_records(
        integration_fixture, "share/arw/evidence/pre_vendor.json"
    )
    with pytest.raises(IntegrationLockError, match="unmodified"):
        _build(integration_fixture)


def test_pre_vendor_wrong_pinned_license_sha256_rejected(
    integration_fixture: dict[str, Path],
) -> None:
    """RED: pre_vendor with the pinned academic-research-skills sha256 changed is rejected."""

    target = integration_fixture["stage"] / "share/arw/evidence/pre_vendor.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    for license_row in payload["component_licenses"]:
        if license_row["component"] == "academic-research-skills":
            license_row["sha256"] = "f" * 64
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _rebind_all_evidence_records(
        integration_fixture, "share/arw/evidence/pre_vendor.json"
    )
    with pytest.raises(IntegrationLockError, match="sha256 drift"):
        _build(integration_fixture)


def test_pre_vendor_empty_legal_inputs_rejected(
    integration_fixture: dict[str, Path],
) -> None:
    """RED: pre_vendor with empty legal_inputs is rejected."""

    target = integration_fixture["stage"] / "share/arw/evidence/pre_vendor.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["legal_inputs"] = []
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _rebind_all_evidence_records(
        integration_fixture, "share/arw/evidence/pre_vendor.json"
    )
    with pytest.raises(IntegrationLockError, match="legal_inputs"):
        _build(integration_fixture)


def test_real_evidence_green_passes_full_lock_rebuild(
    integration_fixture: dict[str, Path],
) -> None:
    """GREEN: real evidence (copied in the fixture) passes the verifier."""

    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    receipt = _verify(integration_fixture, lock)
    assert receipt.technical_qualification == "PASS"
    # Every JSON staged evidence surface passes the matching producer
    # contract.  Plain-text files (test_suite_sha256.txt, status.txt)
    # have their own content checks in the verifier; just confirm
    # presence here.
    for label, relative in EVIDENCE_SURFACES:
        path = integration_fixture["stage"] / relative
        if relative.endswith(".txt"):
            assert path.is_file(), f"missing text evidence: {relative}"
            continue
        if label not in integration_lock_module._EVIDENCE_MODEL_BY_SURFACE:
            # Native bundle sub-files are validated by their own contracts
            # (NativeCommandReceipt, NativeSanitizerVerdict).  Sanity-
            # check by re-parsing JSON here.
            json.loads(path.read_text(encoding="utf-8"))
            continue
        model_cls = integration_lock_module._EVIDENCE_MODEL_BY_SURFACE[label]
        model_cls.model_validate(
            json.loads(path.read_text(encoding="utf-8")), strict=True
        )


# ---------------------------------------------------------------------------
# Codex round-43 P1 findings (3886636729, 3886670801, 3886670806): tighten the
# producer contracts to bind per-component rows to the staged vendor manifest
# and to live staged bytes, plus strict RFC3339-Z datetime validation for
# the pre-vendor ``created_at`` field.
# ---------------------------------------------------------------------------


def _rebind_one_evidence(
    integration_fixture: dict[str, Path], target_relative: str, mutate_payload
) -> None:
    """Mutate the staged evidence file and rebind identity + staged_payloads.

    Also refreshes the canary stage_sha256 so the verify path exercises the
    semantic gate rather than the canary stage-identity mismatch.
    """

    target = integration_fixture["stage"] / target_relative
    payload = json.loads(target.read_text(encoding="utf-8"))
    mutate_payload(payload)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _rebind_all_evidence_records(integration_fixture, target_relative)


def _mutate_pre_vendor_component(
    integration_fixture: dict[str, Path], mutation
) -> None:
    """Apply a mutation to a pre-vendor component row + rebind the file."""

    def _mutate(payload: dict[str, object]) -> None:
        rows = cast(list[dict[str, object]], payload["components"])
        for row in rows:
            if row.get("id") == "academic-research-skills":
                mutation(row)

    _rebind_one_evidence(
        integration_fixture, "share/arw/evidence/pre_vendor.json", _mutate
    )


@pytest.mark.parametrize(
    ("field", "tamper"),
    [
        ("revision", "0" * 40),
        ("git_tree", "0" * 40),
        ("tree_sha256", "f" * 64),
        ("version", "9.9.9"),
        ("upstream_url", "https://example.com/different.git"),
    ],
)
def test_pre_vendor_component_field_drift_rejected(
    integration_fixture: dict[str, Path], field: str, tamper: str
) -> None:
    """RED: any drift in pinned manifest fields rejects at verify path.

    Each pinned field (revision, git_tree, tree_sha256, version,
    upstream_url) is verified against the staged vendor/source-manifest.json
    via the shared ``verify_evidence_contract`` helper.  Both the rebuild
    path (``build_integration_lock``) and the verify path are covered.
    """

    def _tamper(row: dict[str, object]) -> None:
        row[field] = tamper  # type: ignore[index]

    # Build baseline lock + refresh canary while evidence is consistent.
    lock = _build_with_consistent_evidence(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)

    # Tamper the staged pre-vendor.json and rebind all digest records.
    _mutate_pre_vendor_component(integration_fixture, _tamper)
    with pytest.raises(IntegrationLockError, match=f"field {field} drifts"):
        _verify(integration_fixture, lock)


def _build_with_consistent_evidence(integration_fixture: dict[str, Path]):
    """Build the lock and return it; the canary has already been refreshed.

    Used by the RED tests that need the lock + canary to be in sync
    before applying a tamper that mutates a staged file.  The caller
    is responsible for not breaking the evidence state.
    """

    lock = _build(integration_fixture)
    _refresh_canary_stage_identity(integration_fixture)
    return lock


def _mutate_legal_row(
    integration_fixture: dict[str, Path], component_id: str, mutation
) -> None:
    """Apply a mutation to a LegalVerdict row and rebind the evidence file."""

    def _mutate(payload: dict[str, object]) -> None:
        rows = cast(list[dict[str, object]], payload["components"])
        for row in rows:
            if row.get("component_id") == component_id:
                mutation(row)

    _rebind_one_evidence(integration_fixture, "share/arw/evidence/legal.json", _mutate)


def test_legal_row_pinned_drift_to_mit_satisfied_rejected(
    integration_fixture: dict[str, Path],
) -> None:
    """RED: legal row changed to MIT/SATISFIED for ARS rejects at build + verify."""

    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)

    def _tamper(row: dict[str, object]) -> None:
        row["license"] = "MIT"
        row["release_status"] = "SATISFIED"

    _mutate_legal_row(integration_fixture, "academic-research-skills", _tamper)
    _rebind_inventory_coverage = globals()["_rebind_inventory_coverage"]
    _rebind_inventory_coverage(
        integration_fixture["stage"], "share/arw/evidence/legal.json"
    )
    _refresh_canary_stage_identity(integration_fixture)
    with pytest.raises(IntegrationLockError, match="must equal pinned"):
        _verify(integration_fixture, lock)


def test_legal_staged_license_file_bytes_flipped_rejected(
    integration_fixture: dict[str, Path],
) -> None:
    """RED: live digest of staged license file flipped rejects via cross-check."""

    lock = _build(integration_fixture)
    write_integration_lock(integration_fixture["lock"], lock)
    staged_license = (
        integration_fixture["stage"]
        / "LICENSES/academic-research-skills-CC-BY-NC-4.0.txt"
    )
    staged_license.write_bytes(b"flipped content\n")
    _refresh_canary_stage_identity(integration_fixture)
    with pytest.raises(IntegrationLockError, match="live-bytes cross-check"):
        _verify(integration_fixture, lock)


@pytest.mark.parametrize(
    "value",
    [
        "2026-99-99T99:99:99Z",  # impossible calendar fields
        "2026-02-29T12:00:00Z",  # non-leap February 29
        "2026-13-01T00:00:00Z",  # month 13
        "2026-01-32T00:00:00Z",  # day 32
        "2026-01-01T24:00:00Z",  # hour 24
        "not-a-timestamp",  # garbage
        "",  # empty
    ],
)
def test_pre_vendor_created_at_strict_rfc3339_z_rejects_impossible_dates(
    integration_fixture: dict[str, Path], value: str
) -> None:
    """RED: impossible / non-leap / non-UTC dates reject at model validation."""

    target = integration_fixture["stage"] / "share/arw/evidence/pre_vendor.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["created_at"] = value
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _rebind_one_evidence(
        integration_fixture, "share/arw/evidence/pre_vendor.json", lambda p: None
    )
    with pytest.raises(IntegrationLockError, match="created_at|RFC3339|calendar"):
        _build(integration_fixture)


def test_pre_vendor_created_at_leap_year_accepts_at_model_level(
    integration_fixture: dict[str, Path],
) -> None:
    """GREEN: a real leap year timestamp passes the strict parser."""

    target = integration_fixture["stage"] / "share/arw/evidence/pre_vendor.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["created_at"] = "2024-02-29T12:00:00Z"
    receipt = integration_lock_module.PreVendorReceipt.model_validate(
        payload, strict=True
    )
    assert receipt.created_at == "2024-02-29T12:00:00Z"
    assert receipt.derive_qualification() == "PASS"


def test_pre_vendor_native_command_nonzero_status_rejected(
    integration_fixture: dict[str, Path],
) -> None:
    """RED: every native license-gate command must exit with status zero."""

    def _tamper(payload: dict[str, object]) -> None:
        gate = cast(dict[str, object], payload["native_file_base_gate"])
        commands = cast(list[dict[str, object]], gate["commands"])
        commands[0]["status"] = 1

    _rebind_one_evidence(
        integration_fixture, "share/arw/evidence/pre_vendor.json", _tamper
    )
    with pytest.raises(IntegrationLockError, match="status|producer contract"):
        _build(integration_fixture)


def test_native_upstream_bundle_cannot_substitute_for_asan_ubsan(
    integration_fixture: dict[str, Path],
) -> None:
    """RED: a fully rebound upstream bundle cannot certify ASan/UBSan."""

    stage = integration_fixture["stage"]
    substitutions = (
        ("upstream.json", "asan_ubsan.json"),
        ("upstream_command.json", "asan_ubsan_command.json"),
        (
            "upstream_sanitizer_verdict.json",
            "asan_ubsan_sanitizer_verdict.json",
        ),
        ("upstream_test_suite_sha256.txt", "asan_ubsan_test_suite_sha256.txt"),
        ("upstream_status.txt", "asan_ubsan_status.txt"),
    )
    for source_name, target_name in substitutions:
        source = stage / "share/arw/evidence" / source_name
        target = stage / "share/arw/evidence" / target_name
        target.write_bytes(source.read_bytes())
        _rebind_all_evidence_records(
            integration_fixture, f"share/arw/evidence/{target_name}"
        )

    with pytest.raises(
        IntegrationLockError,
        match="canonical surface receipt|native surface argv drift|sanitizer verdict suite",
    ):
        _build(integration_fixture)


@pytest.mark.parametrize("argv", [[], ["true"]])
def test_pre_vendor_command_argv_sequence_is_pinned(
    integration_fixture: dict[str, Path], argv: list[str]
) -> None:
    """RED: status zero cannot bless a missing or substituted license gate."""

    def _tamper(payload: dict[str, object]) -> None:
        gate = cast(dict[str, object], payload["native_file_base_gate"])
        commands = cast(list[dict[str, object]], gate["commands"])
        commands[0]["argv"] = argv

    _rebind_one_evidence(
        integration_fixture, "share/arw/evidence/pre_vendor.json", _tamper
    )
    with pytest.raises(IntegrationLockError, match="command #1 argv"):
        _build(integration_fixture)


def test_sanitizer_verdict_suite_must_match_current_surface(
    integration_fixture: dict[str, Path],
) -> None:
    """RED: a TSan command cannot retain an ASan/UBSan suite verdict."""

    def _tamper(payload: dict[str, object]) -> None:
        payload["suite"] = "asan-ubsan"

    _rebind_one_evidence(
        integration_fixture,
        "share/arw/evidence/tsan_sanitizer_verdict.json",
        _tamper,
    )
    with pytest.raises(
        IntegrationLockError, match="suite must equal current surface 'tsan'"
    ):
        _build(integration_fixture)


@pytest.mark.parametrize(
    "observations",
    [
        [{}],
        [{"phase": "before", "exists": False}],
        [{"phase": "before", "exists": True}],
        [
            {"phase": "after", "exists": False},
            {"phase": "before", "exists": False},
        ],
    ],
)
def test_pre_vendor_absence_observations_are_closed_and_ordered(
    integration_fixture: dict[str, Path], observations: list[dict[str, object]]
) -> None:
    """RED: fieldless, affirmative or reordered absence proofs reject."""

    def _tamper(payload: dict[str, object]) -> None:
        payload["vendor_sources_observations"] = observations

    _rebind_one_evidence(
        integration_fixture, "share/arw/evidence/pre_vendor.json", _tamper
    )
    with pytest.raises(
        IntegrationLockError, match="vendor_sources_observations|phase|exists"
    ):
        _build(integration_fixture)


@pytest.mark.parametrize("mode", ["dummy", "duplicate", "missing"])
def test_pre_vendor_legal_inputs_match_closed_manifest_inventory(
    integration_fixture: dict[str, Path], mode: str
) -> None:
    """RED: a typed subset, duplicate, or omission cannot replace inventory."""

    def _tamper(payload: dict[str, object]) -> None:
        legal_inputs = cast(list[dict[str, object]], payload["legal_inputs"])
        if mode == "dummy":
            payload["legal_inputs"] = [
                {
                    "component": "academic-research-skills",
                    "kind": "license",
                    "path": "DUMMY",
                    "sha256": "0" * 64,
                }
            ]
        elif mode == "duplicate":
            legal_inputs.append(dict(legal_inputs[0]))
        else:
            legal_inputs.pop()

    _rebind_one_evidence(
        integration_fixture, "share/arw/evidence/pre_vendor.json", _tamper
    )
    with pytest.raises(
        IntegrationLockError, match="legal_inputs drift from the exact closed"
    ):
        _build(integration_fixture)


@pytest.mark.parametrize("field", ["generated_notices", "tools"])
def test_pre_vendor_native_gate_inventory_is_canonical(
    integration_fixture: dict[str, Path], field: str
) -> None:
    """RED: dummy notice/tool rows cannot replace producer inventory."""

    def _tamper(payload: dict[str, object]) -> None:
        gate = cast(dict[str, object], payload["native_file_base_gate"])
        gate[field] = [{"path": "DUMMY", "sha256": "0" * 64}]

    _rebind_one_evidence(
        integration_fixture, "share/arw/evidence/pre_vendor.json", _tamper
    )
    with pytest.raises(
        IntegrationLockError, match="generated_notices|five-tool producer inventory"
    ):
        _build(integration_fixture)


def test_pre_vendor_raw_evidence_requires_canonical_receipt_bytes(
    integration_fixture: dict[str, Path],
) -> None:
    """RED: one typed raw-evidence row cannot replace retained evidence."""

    def _tamper(payload: dict[str, object]) -> None:
        payload["raw_evidence"] = [{"path": "DUMMY", "sha256": "0" * 64}]

    _rebind_one_evidence(
        integration_fixture, "share/arw/evidence/pre_vendor.json", _tamper
    )
    with pytest.raises(
        IntegrationLockError, match="raw bytes drift from canonical reviewed evidence"
    ):
        _build(integration_fixture)


def test_pre_vendor_file_base_license_digest_is_pinned(
    integration_fixture: dict[str, Path],
) -> None:
    """RED: file-base MIT identity must equal its bound LICENSE digest."""

    def _tamper(payload: dict[str, object]) -> None:
        rows = cast(list[dict[str, object]], payload["component_licenses"])
        for row in rows:
            if row["component"] == "file-base":
                row["sha256"] = "0" * 64

    _rebind_one_evidence(
        integration_fixture, "share/arw/evidence/pre_vendor.json", _tamper
    )
    with pytest.raises(IntegrationLockError, match="sha256 drift for file-base"):
        _build(integration_fixture)


def test_pre_vendor_tool_identities_are_canonical(
    integration_fixture: dict[str, Path],
) -> None:
    """RED: arbitrary nonempty tool versions cannot become provenance."""

    def _tamper(payload: dict[str, object]) -> None:
        identities = cast(dict[str, object], payload["tool_identities"])
        identities["git"] = "unknown"

    _rebind_one_evidence(
        integration_fixture, "share/arw/evidence/pre_vendor.json", _tamper
    )
    with pytest.raises(
        IntegrationLockError, match="tool_identities.git must equal canonical"
    ):
        _build(integration_fixture)


def test_native_verdict_is_content_bound_to_surface_command(
    integration_fixture: dict[str, Path],
) -> None:
    """RED: an upstream network verdict cannot certify ASan/UBSan."""

    stage = integration_fixture["stage"]
    source = stage / "share/arw/evidence/upstream.json"
    target_relative = "share/arw/evidence/asan_ubsan.json"
    target = stage / target_relative
    target.write_bytes(source.read_bytes())
    _rebind_all_evidence_records(integration_fixture, target_relative)
    with pytest.raises(
        IntegrationLockError, match="verdict bytes.*canonical command surface"
    ):
        _build(integration_fixture)


def test_staged_evidence_json_rejects_duplicate_object_keys(
    integration_fixture: dict[str, Path],
) -> None:
    """RED: attested JSON has one unambiguous interpretation for auditors."""

    target_relative = "share/arw/evidence/upstream.json"
    target = integration_fixture["stage"] / target_relative
    raw = target.read_text(encoding="utf-8")
    needle = '  "network_syscall_attempts": [],'
    assert raw.count(needle) == 1
    target.write_text(
        raw.replace(
            needle,
            '  "network_syscall_attempts": ["connect"],\n' + needle,
        ),
        encoding="utf-8",
    )
    _rebind_all_evidence_records(integration_fixture, target_relative)
    with pytest.raises(
        IntegrationLockError, match="duplicate JSON object key|strict unambiguous JSON"
    ):
        _build(integration_fixture)
