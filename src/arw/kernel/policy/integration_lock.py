"""Fail-closed qualification lock for the bundled ARS/Codex integration.

The lock is deliberately independent of mutable run state.  It binds the
exact staged ARW wheel, the bundled ARS adapter, the reconstructed
file-base binary and ordered patch series, the Codex launcher/native host
tuple, the hook definition plus retained trust canary, and the legal verdict.

No boolean supplied by an orchestration caller is accepted as qualification
evidence.  Host and hook qualification are read from files and recomputed from
the installed bytes every time the lock is verified.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import stat
import subprocess
import tempfile
import tomllib
import zipfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Self, TypeVar, cast

import jsonschema
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from arw.kernel.core.canonical import canonical_json_bytes, strict_json_loads
from arw.kernel.policy.hook_contracts import CodexHookReceipt, HookParityMatrix

EXPECTED_ARS_ADAPTER_VERSION = "0.1.27"
MINIMUM_CODEX_CLI_VERSION = (0, 144, 4)
CODEX_CLI_VERSION_REQUIREMENT = ">=0.144.4"
_CODEX_CLI_STABLE_VERSION_RE = re.compile(
    r"^codex-cli (?P<major>[0-9]+)\.(?P<minor>[0-9]+)\.(?P<patch>[0-9]+)(?:\+[0-9A-Za-z.-]+)?$"
)
EXPECTED_CODEX_CLI_VERSION = "codex-cli 0.144.4"
EXPECTED_ARS_UPSTREAM_COMMIT = "127ff85e4bbfcdd10b95040537b6c6bd7ad17aeb"
EXPECTED_EXPERIMENT_AGENT_COMMIT = "e291e7dc7ca268b2de7e1a9cf23bc2eef5dc0651"

EXPECTED_FILE_BASE_COMMIT = "ee68144af5453addda995a27cce8142999f318fb"
EXPECTED_UPSTREAM_URLS = {
    "academic-research-skills": "https://github.com/Imbad0202/academic-research-skills.git",
    "experiment-agent": "https://github.com/Imbad0202/experiment-agent.git",
}
EXPECTED_SOURCE_IDENTITIES = {
    "academic-research-skills": {
        "commit": EXPECTED_ARS_UPSTREAM_COMMIT,
        "git_tree": "7ce111463102462479835ce5f7c2b597d7ccfe22",
        "source_tree_sha256": "9f195460e1e299d7ce0a833e3a242957db315ef16ec9e8c80d29163e300afbd6",
    },
    "experiment-agent": {
        "commit": EXPECTED_EXPERIMENT_AGENT_COMMIT,
        "git_tree": "166734509cf5057e48a7f81ecce9e44573610636",
        "source_tree_sha256": "2985b59589805267cf1b268a126162ffd3689d0f31840a2de41b004471128bae",
    },
    "file-base": {
        "commit": EXPECTED_FILE_BASE_COMMIT,
        "git_tree": "de88f52c6614473d04aa1596304a328ef91267e8",
        "source_tree_sha256": "4a1ffaa7468026293758327f143d0cfc9f7046e69bd7224efcbd63290fe059d3",
    },
}
EXPECTED_FILE_BASE_PATCHES = (
    (
        1,
        "vendor/patches/file-base/0001-file-base-server-name.patch",
        "dd6022c69819804db015019058feaecebf0ee9c31e5cc55eb8bad6b47003da1a",
    ),
    (
        2,
        "vendor/patches/file-base/0002-phase1-confined-read.patch",
        "1197346f62d06f0bad62c1e58fd374082b2f88e3eb8301746103f8066ba5c029",
    ),
    (
        3,
        "vendor/patches/file-base/0003-phase3-generation-builder.patch",
        "12676a7b619981f4140c2f922bfc0fd90b1bdd0f75b0da04ed00e78840da9dfc",
    ),
    (
        4,
        "vendor/patches/file-base/0004-phase5-research-graph.patch",
        "11244e68243651611fe1f8b3d4d386e2d3680ec66226b02c4dbd58bad19f519c",
    ),
)
EXPECTED_FILE_BASE_POST_PATCH_TREE = (
    "a75f538244503d8cd4e7b178dce93bdea4c80ac546220bfb4e6022cfcf491fd1"
)
EXPECTED_FILE_BASE_TEST_TREE = (
    "4ace6a4c832b8d3e04d9366f5d7684833eadf338fd4be367e03fb7f8d274da2a"
)
EXPECTED_PRE_VENDOR_RECEIPT_SHA256 = (
    "e0e23637bb2c8c45f5487e33cf9b0c41f173f7830ed4c42eec0d0406c06e81c9"
)
STAGE_IDENTITY_EXCLUDED_PATHS = frozenset(
    {
        "SBOM.cdx.json",
        "share/arw/build-identity.json",
        "supply-chain/host-canary.json",
        "supply-chain/integration-lock.json",
        "supply-chain/stage-inventory.json",
        "supply-chain/use-distribution.json",
    }
)
EXPECTED_TECHNICAL_PROVENANCE_PATHS = frozenset(
    {
        "vendor/source-manifest.json",
        "SBOM.cdx.json",
        "THIRD_PARTY_NOTICES.md",
    }
)
STAGE_IDENTITY_EXCLUDED_PREFIXES = ("supply-chain/host-canary/",)
AUDIT_BUILD_IDENTITY_RELATIVE = "share/arw/build-identity.json"
AUDIT_STAGE_INVENTORY_RELATIVE = "supply-chain/stage-inventory.json"
AUDIT_BUILD_IDENTITY_SCHEMA_RELATIVE = "share/arw/schemas/build-identity.schema.json"
# Phase 1 evidence must be staged into the plugin root so the installed
# verifier does not depend on the original ``build/evidence/phase-01`` tree.
# Each staged file MUST carry ``technical_qualification: PASS``; the
# ``digestPath`` in the build identity points at these staged copies, and the
# audit manifest gate recomputes every claim from the live bytes.
EVIDENCE_PATH_PRE_VENDOR = "share/arw/evidence/pre_vendor.json"
EVIDENCE_PATH_LEGAL = "share/arw/evidence/legal.json"
NATIVE_SURFACES: tuple[str, ...] = ("upstream", "asan_ubsan", "tsan")
NATIVE_EVIDENCE_KINDS: tuple[str, ...] = (
    "command",
    "sanitizer_verdict",
    "test_suite_sha256",
    "status",
)
NATIVE_VERDICT_KIND = "verdict"


def native_evidence_path(surface: str, kind: str) -> str:
    """Return the staged evidence path for one native surface + kind.

    The ``test_suite_sha256`` and ``status`` files are plain-text byte
    digests (``status.txt`` is ``"0\\n"`` exactly; the test-suite file is
    the pinned upstream test tree digest); the rest are JSON.
    """

    if surface not in NATIVE_SURFACES:
        raise ValueError(f"unknown native surface: {surface}")
    if kind == NATIVE_VERDICT_KIND:
        return f"share/arw/evidence/{surface}.json"
    extension = "txt" if kind in {"test_suite_sha256", "status"} else "json"
    return f"share/arw/evidence/{surface}_{kind}.{extension}"


NATIVE_EVIDENCE_RELATIVE_PATHS: frozenset[str] = frozenset(
    native_evidence_path(surface, kind)
    for surface in NATIVE_SURFACES
    for kind in (NATIVE_VERDICT_KIND, *NATIVE_EVIDENCE_KINDS)
)
EVIDENCE_RELATIVE_PATHS: frozenset[str] = frozenset(
    {
        EVIDENCE_PATH_PRE_VENDOR,
        EVIDENCE_PATH_LEGAL,
    }
    | NATIVE_EVIDENCE_RELATIVE_PATHS
)
BUILD_IDENTITY_PROJECTION_ALGORITHM = "build-identity-metadata-v1"
BUILD_IDENTITY_PROJECTION_KEYS = (
    "schema_version",
    "platform_claim",
    "plugin",
    "runtime",
    "components",
    "patches",
    "native",
    "projection",
    "file_contract",
    "wheelhouse",
    "schemas",
    "evidence",
)
AUDIT_STAGE_INVENTORY_REQUIRED_KEYS = frozenset(
    {"schema_version", "files", "symlinks", "covered_files"}
)
# Verbatim copy of the live private-path class filter used by
# scripts/stage-plugin (--validate-only section, lines ~287-390).  The audit
# manifest gate and the live stage builder must agree on what is private.
_AUDIT_PRIVATE_PATH_RE = re.compile(
    r"(^|/)(?:\.cache|\.git|\.building[^/]*|barriers?|extractions?|generations?|receipts?|"
    r"extracted-text|papers?|runs?|indexes?|credentials?|private|undeclared)(?:/|$)|"
    r"\.(?:db|sqlite3?|pem|key)$",
    re.IGNORECASE,
)
LegalBlocker = Literal[
    "INTENDED_USE_UNKNOWN",
    "DISTRIBUTION_CLASS_UNKNOWN",
    "ACCOUNTABLE_APPROVAL_MISSING",
    "CC_BY_NC_PERMISSION_UNRESOLVED",
]
EXPECTED_LEGAL_BLOCKERS: tuple[LegalBlocker, ...] = (
    "INTENDED_USE_UNKNOWN",
    "DISTRIBUTION_CLASS_UNKNOWN",
    "ACCOUNTABLE_APPROVAL_MISSING",
    "CC_BY_NC_PERMISSION_UNRESOLVED",
)

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
GitObjectId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
EvidenceId = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
]
MappingId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9._-]{2,95}$")]


class IntegrationLockError(RuntimeError):
    """The qualification lock or one of its bound inputs is invalid."""


class LockModel(BaseModel):
    """Strict immutable base for integration-lock records."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        json_schema_extra={"$schema": "https://json-schema.org/draft/2020-12/schema"},
    )


EvidenceModel = TypeVar("EvidenceModel", bound=BaseModel)


class CodexCredentialPolicy(LockModel):
    schema_version: Literal["arw.codex-credential-policy.v1"]
    source: Literal["preconfigured-codex-home"]
    copied_files: tuple[Literal["auth.json"]]
    generated_files: tuple[Literal["config.toml"]]
    directory_mode: Literal["0700"]
    copied_file_mode: Literal["0600"]
    environment_policy: Literal["positive-allowlist"]
    api_key_environment: Literal["stripped"]
    cleanup: Literal["auth-removed-after-each-invocation"]
    secret_material_retained: Literal[False]
    source_path_retained: Literal[False]


EXPECTED_CODEX_CREDENTIAL_POLICY = CodexCredentialPolicy(
    schema_version="arw.codex-credential-policy.v1",
    source="preconfigured-codex-home",
    copied_files=("auth.json",),
    generated_files=("config.toml",),
    directory_mode="0700",
    copied_file_mode="0600",
    environment_policy="positive-allowlist",
    api_key_environment="stripped",
    cleanup="auth-removed-after-each-invocation",
    secret_material_retained=False,
    source_path_retained=False,
)
EXPECTED_CODEX_CREDENTIAL_POLICY_SHA256 = hashlib.sha256(
    canonical_json_bytes(EXPECTED_CODEX_CREDENTIAL_POLICY.model_dump(mode="json"))
).hexdigest()


def _relative_path(value: str) -> str:
    if not value or "\x00" in value or "\\" in value:
        raise ValueError("path must be a normalized relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise ValueError("path must be a normalized relative POSIX path")
    if {"", ".", ".."}.intersection(path.parts):
        raise ValueError("path must be a normalized relative POSIX path")
    return value


class FileBinding(LockModel):
    path: str
    sha256: Sha256

    @classmethod
    def from_path(cls, root: Path, relative: str) -> FileBinding:
        path = _regular_file_under(root, relative)
        return cls(path=relative, sha256=_digest(path))

    @field_validator("path")
    @classmethod
    def normalized_path(cls, value: str) -> str:
        return _relative_path(value)


class SourceRepositoryBinding(LockModel):
    component_id: Literal["academic-research-skills", "experiment-agent"]
    upstream_url: str
    commit: GitObjectId
    git_tree: GitObjectId
    source_tree_sha256: Sha256


class ARSBinding(LockModel):
    dependency_model: Literal["bundled-pinned-adapter"]
    bundled: Literal[True]
    adapter_name: Literal["academic-research-suite"]
    adapter_version: Literal["0.1.27"]
    adapter_tree_sha256: Sha256
    upstream_content_tree_sha256: Sha256
    manifest: FileBinding
    version_file: FileBinding
    router: FileBinding
    source_repositories: tuple[SourceRepositoryBinding, SourceRepositoryBinding]

    @model_validator(mode="after")
    def exact_upstreams(self) -> Self:
        if tuple(item.component_id for item in self.source_repositories) != (
            "academic-research-skills",
            "experiment-agent",
        ):
            raise ValueError("ARS source repositories must use the canonical order")
        commits = {item.component_id: item.commit for item in self.source_repositories}
        urls = {
            item.component_id: item.upstream_url for item in self.source_repositories
        }
        if commits["academic-research-skills"] != EXPECTED_ARS_UPSTREAM_COMMIT:
            raise ValueError("ARS upstream commit is not the qualified revision")
        if commits["experiment-agent"] != EXPECTED_EXPERIMENT_AGENT_COMMIT:
            raise ValueError("experiment-agent commit is not the qualified revision")
        if urls != EXPECTED_UPSTREAM_URLS:
            raise ValueError("ARS upstream URLs are not the qualified repositories")
        for item in self.source_repositories:
            expected = EXPECTED_SOURCE_IDENTITIES[item.component_id]
            if {
                "commit": item.commit,
                "git_tree": item.git_tree,
                "source_tree_sha256": item.source_tree_sha256,
            } != expected:
                raise ValueError(
                    f"{item.component_id} source tree is not the qualified identity"
                )
        return self


class ARWRuntimeBinding(LockModel):
    package: Literal["academic-research-workbench"]
    version: Literal["0.1.0"]
    pyproject: FileBinding
    plugin_manifest: FileBinding
    cli_launcher: FileBinding
    wheel: FileBinding
    wheel_tree_sha256: Sha256


class OrderedPatchBinding(LockModel):
    order: Annotated[int, Field(ge=1)]
    path: str
    sha256: Sha256

    @field_validator("path")
    @classmethod
    def normalized_path(cls, value: str) -> str:
        return _relative_path(value)


class FileBaseBinding(LockModel):
    component_id: Literal["file-base"]
    commit: Literal["ee68144af5453addda995a27cce8142999f318fb"]
    git_tree: GitObjectId
    source_tree_sha256: Sha256
    source_manifest: FileBinding
    build_evidence: FileBinding
    binary: FileBinding
    ordered_patches: tuple[OrderedPatchBinding, ...] = Field(min_length=1)
    post_patch_tree_sha256: Sha256

    @model_validator(mode="after")
    def patches_are_contiguous(self) -> Self:
        if tuple(item.order for item in self.ordered_patches) != tuple(
            range(1, len(self.ordered_patches) + 1)
        ):
            raise ValueError("file-base patch order must be contiguous")
        if len({item.path for item in self.ordered_patches}) != len(
            self.ordered_patches
        ):
            raise ValueError("file-base patch paths must be unique")
        observed = tuple(
            (item.order, item.path, item.sha256) for item in self.ordered_patches
        )
        if observed != EXPECTED_FILE_BASE_PATCHES:
            raise ValueError("file-base patch set is not the qualified ordered series")
        expected_source = EXPECTED_SOURCE_IDENTITIES["file-base"]
        if {
            "commit": self.commit,
            "git_tree": self.git_tree,
            "source_tree_sha256": self.source_tree_sha256,
        } != expected_source:
            raise ValueError("file-base source tree is not the qualified identity")
        if self.post_patch_tree_sha256 != EXPECTED_FILE_BASE_POST_PATCH_TREE:
            raise ValueError("file-base post-patch tree is not the qualified identity")
        return self


class ExecutableBinding(LockModel):
    invoked_path: str
    resolved_path: str
    sha256: Sha256

    @field_validator("invoked_path", "resolved_path")
    @classmethod
    def absolute_path(cls, value: str) -> str:
        if not value or "\x00" in value or not Path(value).is_absolute():
            raise ValueError("host executable paths must be absolute")
        return value


class CodexHostBinding(LockModel):
    cli_version: Annotated[
        str,
        StringConstraints(
            pattern=r"^codex-cli [0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$"
        ),
    ]
    platform_system: Annotated[str, Field(min_length=1, max_length=64)]
    platform_release: Annotated[str, Field(min_length=1, max_length=128)]
    platform_machine: Annotated[str, Field(min_length=1, max_length=64)]
    launcher: ExecutableBinding
    native_binary: ExecutableBinding
    tuple_sha256: Sha256

    @model_validator(mode="after")
    def tuple_hash_is_derived(self) -> Self:
        if self.tuple_sha256 != _host_tuple_sha256(self):
            raise ValueError(
                "Codex host tuple hash is not derived from canonical fields"
            )
        return self


class ControlledResultChannelProof(LockModel):
    channel_kind: Literal["codex-add-dir"]
    channel_scope_sha256: Sha256
    proposal_sha256: Sha256
    write_observed: Literal[True]
    outside_scope_write_observed: Literal[False]
    status: Literal["PASS"]


class IsolationProof(LockModel):
    home_isolated: Literal[True]
    codex_home_isolated: Literal[True]
    cross_home_read_observed: Literal[False]
    unrelated_write_observed: Literal[False]
    status: Literal["PASS"]


class FreshHomeReceipt(LockModel):
    schema_version: Literal["arw.codex-fresh-home-receipt.v1"]
    home_ordinal: Annotated[int, Field(ge=1, le=3)]
    home_identity_sha256: Sha256
    codex_home_identity_sha256: Sha256
    codex_thread_id: EvidenceId
    host_agent_id: EvidenceId
    expected_assignment_id: MappingId
    observed_assignment_id: MappingId
    expected_attempt_id: MappingId
    observed_attempt_id: MappingId
    expected_proposal_nonce: MappingId
    observed_proposal_nonce: MappingId
    codex_host_tuple_sha256: Sha256
    arw_runtime_sha256: Sha256
    stage_sha256: Sha256
    hook_definition_sha256: Sha256
    hook_execution_admission: Literal["automation_vetted_bypass"]
    credential_policy_sha256: Sha256
    result_channel: ControlledResultChannelProof
    isolation: IsolationProof
    credential_material_retained: Literal[False]
    secret_material_retained: Literal[False]
    absolute_path_material_retained: Literal[False]

    @model_validator(mode="after")
    def exact_mapping_is_observed(self) -> Self:
        expected = (
            self.expected_assignment_id,
            self.expected_attempt_id,
            self.expected_proposal_nonce,
        )
        observed = (
            self.observed_assignment_id,
            self.observed_attempt_id,
            self.observed_proposal_nonce,
        )
        if observed != expected:
            raise ValueError("fresh-home assignment/attempt/nonce mapping drift")
        return self


class HookStatusClassification(LockModel):
    hook_state: Literal[
        "trusted_enabled", "disabled", "untrusted", "timeout", "failure"
    ]
    observation: Literal["observed", "not_observed", "timed_out", "failed"]
    classification_basis: Literal["parity_policy"]
    parent_authority_unchanged: Literal[True]
    evidence: FileBinding


class HookParityEvidenceRecord(LockModel):
    """Content-addressed proof for one hook-state parity classification.

    The matrix is the parent-owned authority projection.  The trusted/enabled
    row additionally binds an official-wire Codex receipt, proving that
    ``observed`` was not merely asserted in the evidence bundle.
    """

    schema_version: Literal["arw.hook-parity-evidence.v1"]
    hook_state: Literal[
        "trusted_enabled", "disabled", "untrusted", "timeout", "failure"
    ]
    observation: Literal["observed", "not_observed", "timed_out", "failed"]
    hook_definition_sha256: Sha256
    stage_sha256: Sha256
    parity: HookParityMatrix
    official_hook_receipt: FileBinding | None
    secret_material_retained: Literal[False]
    absolute_path_material_retained: Literal[False]

    @model_validator(mode="after")
    def parity_and_observation_are_exact(self) -> Self:
        expected = {
            "trusted_enabled": ("observed", "trusted_enabled"),
            "disabled": ("not_observed", "disabled"),
            "untrusted": ("not_observed", "untrusted"),
            "timeout": ("timed_out", "timeout"),
            "failure": ("failed", "failed"),
        }
        observation, parity_status = expected[self.hook_state]
        if self.observation != observation or self.parity.hook_status != parity_status:
            raise ValueError("hook parity evidence state or observation drift")
        if (self.official_hook_receipt is not None) != (
            self.hook_state == "trusted_enabled"
        ):
            raise ValueError(
                "only trusted/enabled parity evidence requires an official hook receipt"
            )
        return self


class CodexHostEvidenceBundle(LockModel):
    schema_version: Literal["arw.codex-host-evidence-bundle.v1"]
    technical_qualification: Literal["PASS"]
    codex_host_tuple_sha256: Sha256
    arw_runtime_sha256: Sha256
    stage_sha256: Sha256
    hook_definition_sha256: Sha256
    hook_execution_admission: Literal["automation_vetted_bypass"]
    live_hook_execution: Literal["observed"]
    fresh_home_default_trust: Literal["untrusted_skipped"]
    credential_policy_sha256: Sha256
    fresh_home_receipts: tuple[FileBinding, FileBinding, FileBinding]
    hook_status_classifications: tuple[
        HookStatusClassification,
        HookStatusClassification,
        HookStatusClassification,
        HookStatusClassification,
        HookStatusClassification,
    ]
    secret_material_retained: Literal[False]
    absolute_path_material_retained: Literal[False]

    @model_validator(mode="after")
    def classification_matrix_is_exact(self) -> Self:
        expected = (
            ("trusted_enabled", "observed"),
            ("disabled", "not_observed"),
            ("untrusted", "not_observed"),
            ("timeout", "timed_out"),
            ("failure", "failed"),
        )
        observed = tuple(
            (item.hook_state, item.observation)
            for item in self.hook_status_classifications
        )
        if observed != expected:
            raise ValueError(
                "hook status classification matrix is incomplete or reordered"
            )
        if (
            len({item.evidence.sha256 for item in self.hook_status_classifications})
            != 5
        ):
            raise ValueError("hook status classifications require distinct evidence")
        if len({item.evidence.path for item in self.hook_status_classifications}) != 5:
            raise ValueError(
                "hook status classifications require distinct evidence paths"
            )
        if len({item.path for item in self.fresh_home_receipts}) != 3:
            raise ValueError("bundle must retain three distinct fresh-home receipts")
        return self


class HookBinding(LockModel):
    config: FileBinding
    handler: FileBinding
    definition_algorithm: Literal["relative-name-nul-bytes-nul-v1"]
    definition_sha256: Sha256
    hook_execution_admission: Literal["automation_vetted_bypass"]
    live_hook_execution: Literal["observed"]
    fresh_home_default_trust: Literal["untrusted_skipped"]
    host_canary_evidence_sha256: Sha256
    evidence_bundle_sha256: Sha256
    fresh_home_receipt_sha256: tuple[Sha256, Sha256, Sha256]
    arw_runtime_sha256: Sha256
    stage_identity_algorithm: Literal["content-tree-excluding-cycle-metadata-v1"]
    stage_sha256: Sha256
    credential_policy_sha256: Sha256

    @model_validator(mode="after")
    def evidence_is_distinct(self) -> Self:
        if len(set(self.fresh_home_receipt_sha256)) != 3:
            raise ValueError("hook binding requires three distinct receipt digests")
        return self


class CodexHostCanaryEvidence(LockModel):
    schema_version: Literal["arw.codex-host-canary.v1"]
    technical_qualification: Literal["PASS"]
    codex_host_tuple_sha256: Sha256
    arw_runtime_sha256: Sha256
    stage_sha256: Sha256
    hook_definition_sha256: Sha256
    hook_execution_admission: Literal["automation_vetted_bypass"]
    live_hook_execution: Literal["observed"]
    fresh_home_default_trust: Literal["untrusted_skipped"]
    credential_policy_sha256: Sha256
    three_home_isolation: Literal["PASS"]
    assignment_identity_mapping: Literal["PASS"]
    credential_hygiene: Literal["PASS"]
    controlled_result_channel: Literal["PASS"]
    hook_status_classification: Literal["PASS"]
    evidence_bundle: FileBinding
    fresh_home_receipts: tuple[FileBinding, FileBinding, FileBinding]
    secret_material_retained: Literal[False]
    absolute_path_material_retained: Literal[False]

    @model_validator(mode="after")
    def fresh_homes_are_distinct(self) -> Self:
        if len({item.path for item in self.fresh_home_receipts}) != 3:
            raise ValueError(
                "the Codex canary must retain three distinct fresh-home receipts"
            )
        if self.evidence_bundle.path in {
            item.path for item in self.fresh_home_receipts
        }:
            raise ValueError(
                "evidence bundle must be separate from fresh-home receipts"
            )
        return self


class UseDistributionPolicyProjection(LockModel):
    """Cycle-free legal meaning derived from the evidence declaration.

    ``LicenseBinding`` separately binds the declaration's raw bytes. This
    projection retains the exact legal facts used for release qualification
    without treating mutable policy state as independent authority.
    """

    schema_version: Literal["arw.use-distribution-policy-projection.v1"]
    source_path: Literal["supply-chain/use-distribution.json"]
    declaration_schema_version: Literal["1.0.0"]
    repository_visibility: Literal["public"]
    intended_use_status: Literal["unknown"]
    distribution_class_status: Literal["unknown"]
    accountable_approval_status: Literal["missing"]
    permission_reference_count: Literal[0]
    private_repository_is_noncommercial_evidence: Literal[False]


class LicenseBinding(LockModel):
    verdict: FileBinding
    use_distribution_path: Literal["supply-chain/use-distribution.json"]
    use_distribution_sha256: Sha256
    use_distribution_policy: UseDistributionPolicyProjection
    use_distribution_policy_sha256: Sha256
    technical_qualification: Literal["PASS"]
    release_qualification: Literal["BLOCKED"]
    reason_codes: tuple[
        Literal[
            "INTENDED_USE_UNKNOWN",
            "DISTRIBUTION_CLASS_UNKNOWN",
            "ACCOUNTABLE_APPROVAL_MISSING",
            "CC_BY_NC_PERMISSION_UNRESOLVED",
        ],
        ...,
    ]

    @model_validator(mode="after")
    def exact_legal_blockers(self) -> Self:
        if self.reason_codes != EXPECTED_LEGAL_BLOCKERS:
            raise ValueError(
                "license blockers must retain the exact SUP-04 evidence gaps"
            )
        expected = hashlib.sha256(
            canonical_json_bytes(self.use_distribution_policy.model_dump(mode="json"))
        ).hexdigest()
        if self.use_distribution_policy_sha256 != expected:
            raise ValueError("use/distribution policy hash is not canonically derived")
        return self


class BuildIdentityBinding(LockModel):
    path: Literal["share/arw/build-identity.json"]
    projection_algorithm: Literal["build-identity-metadata-v1"]
    projection_sha256: Sha256


class IntegrationLock(LockModel):
    schema_version: Literal["arw.integration-lock.v2"]
    dependency_model: Literal["bundled-pinned-adapter"]
    arw_runtime: ARWRuntimeBinding
    ars: ARSBinding
    file_base: FileBaseBinding
    codex_host: CodexHostBinding
    hook: HookBinding
    license: LicenseBinding
    build_identity: BuildIdentityBinding
    technical_qualification: Literal["PASS"]
    release_qualification: Literal["BLOCKED"]

    @model_validator(mode="after")
    def dependency_model_is_explicit(self) -> Self:
        if self.ars.dependency_model != self.dependency_model or not self.ars.bundled:
            raise ValueError("staged ARW must declare and verify the bundled exact ARS")
        return self


class IntegrationVerification(LockModel):
    schema_version: Literal["arw.integration-verification.v1"]
    integration_lock_sha256: Sha256
    codex_host_tuple_sha256: Sha256
    hook_definition_sha256: Sha256
    ars_tree_sha256: Sha256
    technical_qualification: Literal["PASS"]
    release_qualification: Literal["BLOCKED"]


DiagnosticLayerName = Literal[
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
DiagnosticReasonCode = Literal[
    "integration_inputs_incomplete",
    "lock_document_invalid",
    "lock_document_noncanonical",
    "staged_arw_drift",
    "ars_bundle_drift",
    "file_base_drift",
    "codex_host_drift",
    "hook_definition_drift",
    "hook_execution_evidence_drift",
    "legal_state_drift",
    "exact_lock_drift",
]
DiagnosticDetail = Literal[
    "required integration inputs are absent or unsafe",
    "integration lock is invalid strict JSON",
    "integration lock bytes are not canonical JSON",
    "staged ARW runtime differs from the lock",
    "bundled ARS bytes differ from the lock",
    "file-base bytes or patch evidence differ from the lock",
    "Codex host tuple differs from the lock",
    "root hook definition differs from the lock",
    "retained hook evidence differs from the lock",
    "legal policy differs from the qualified blocked state",
    "complete exact integration verification failed",
]

DIAGNOSTIC_LAYER_ORDER: tuple[DiagnosticLayerName, ...] = (
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
)
DIAGNOSTIC_FAILURE_CONTRACTS: frozenset[
    tuple[DiagnosticLayerName, DiagnosticReasonCode, DiagnosticDetail]
] = frozenset(
    {
        (
            "inputs",
            "integration_inputs_incomplete",
            "required integration inputs are absent or unsafe",
        ),
        (
            "lock_document",
            "lock_document_invalid",
            "integration lock is invalid strict JSON",
        ),
        (
            "lock_document",
            "lock_document_noncanonical",
            "integration lock bytes are not canonical JSON",
        ),
        ("staged_arw", "staged_arw_drift", "staged ARW runtime differs from the lock"),
        ("ars_bundle", "ars_bundle_drift", "bundled ARS bytes differ from the lock"),
        (
            "file_base",
            "file_base_drift",
            "file-base bytes or patch evidence differ from the lock",
        ),
        ("codex_host", "codex_host_drift", "Codex host tuple differs from the lock"),
        (
            "hook_definition",
            "hook_definition_drift",
            "root hook definition differs from the lock",
        ),
        (
            "hook_execution_evidence",
            "hook_execution_evidence_drift",
            "retained hook evidence differs from the lock",
        ),
        (
            "legal_state",
            "legal_state_drift",
            "legal policy differs from the qualified blocked state",
        ),
        (
            "exact_lock",
            "exact_lock_drift",
            "complete exact integration verification failed",
        ),
    }
)


class IntegrationDiagnosticLayer(LockModel):
    """One bounded, read-only observation of the exact integration boundary."""

    name: DiagnosticLayerName
    status: Literal["PASS", "BLOCKED", "NOT_EVALUATED"]
    reason_code: DiagnosticReasonCode | None
    detail: DiagnosticDetail | None
    expected_sha256: Sha256 | None
    observed_sha256: Sha256 | None

    @model_validator(mode="after")
    def status_fields_are_consistent(self) -> Self:
        if self.status == "BLOCKED":
            if self.reason_code is None or self.detail is None:
                raise ValueError("blocked diagnostic layers require a closed reason")
            failure_contract = (self.name, self.reason_code, self.detail)
            if failure_contract not in DIAGNOSTIC_FAILURE_CONTRACTS:
                raise ValueError(
                    "blocked diagnostic layer reason and detail do not match its name"
                )
            digests = (self.expected_sha256, self.observed_sha256)
            no_digest_reason = self.reason_code in {
                "integration_inputs_incomplete",
                "lock_document_invalid",
            }
            if no_digest_reason:
                if any(value is not None for value in digests):
                    raise ValueError("blocked diagnostic reason cannot carry digests")
            elif self.expected_sha256 is None:
                raise ValueError("blocked drift layer requires an expected digest")
            elif (
                self.reason_code == "lock_document_noncanonical"
                and self.observed_sha256 is None
            ):
                raise ValueError(
                    "noncanonical lock diagnostic requires an observed digest"
                )
            elif (
                self.observed_sha256 is not None
                and self.expected_sha256 == self.observed_sha256
            ):
                raise ValueError("blocked diagnostic layer digests must show drift")
        elif any(value is not None for value in (self.reason_code, self.detail)):
            raise ValueError("non-blocked diagnostic layers cannot carry a reason")
        if self.status == "NOT_EVALUATED" and any(
            value is not None for value in (self.expected_sha256, self.observed_sha256)
        ):
            raise ValueError("unevaluated diagnostic layers cannot carry digests")
        return self


class IntegrationDiagnosticReport(LockModel):
    """Safe diagnostic projection; only exact verification may produce PASS."""

    schema_version: Literal["arw.integration-diagnostic.v1"]
    status: Literal["PASS", "BLOCKED"]
    technical_qualification: Literal["PASS", "BLOCKED"]
    release_qualification: Literal["BLOCKED"]
    experiment_execution: Literal["disabled"]
    integration_lock_sha256: Sha256 | None
    reason_codes: tuple[DiagnosticReasonCode, ...] = Field(max_length=1)
    layers: tuple[IntegrationDiagnosticLayer, ...] = Field(
        min_length=len(DIAGNOSTIC_LAYER_ORDER),
        max_length=len(DIAGNOSTIC_LAYER_ORDER),
    )

    @model_validator(mode="after")
    def layer_order_and_status_are_exact(self) -> Self:
        if tuple(layer.name for layer in self.layers) != DIAGNOSTIC_LAYER_ORDER:
            raise ValueError(
                "integration diagnostic layers are incomplete or reordered"
            )
        blocked = [
            index
            for index, layer in enumerate(self.layers)
            if layer.status == "BLOCKED"
        ]
        for layer in self.layers:
            if layer.status != "PASS":
                continue
            digests = (layer.expected_sha256, layer.observed_sha256)
            if layer.name == "inputs":
                if any(value is not None for value in digests):
                    raise ValueError("diagnostic input PASS cannot carry digests")
            elif (
                layer.expected_sha256 is None
                or layer.observed_sha256 is None
                or layer.expected_sha256 != layer.observed_sha256
            ):
                raise ValueError("diagnostic PASS layer digests must match")
        if self.status == "PASS":
            if (
                self.technical_qualification != "PASS"
                or self.integration_lock_sha256 is None
                or self.reason_codes
                or any(layer.status != "PASS" for layer in self.layers)
            ):
                raise ValueError("diagnostic PASS requires complete exact verification")
            exact_lock = self.layers[-1]
            if (
                exact_lock.expected_sha256 != self.integration_lock_sha256
                or exact_lock.observed_sha256 != self.integration_lock_sha256
            ):
                raise ValueError(
                    "diagnostic exact-lock digests must bind the report lock"
                )
            return self
        if (
            self.technical_qualification != "BLOCKED"
            or self.integration_lock_sha256 is not None
            or len(blocked) != 1
        ):
            raise ValueError("blocked diagnostics require one first failing layer")
        first = blocked[0]
        if any(layer.status != "PASS" for layer in self.layers[:first]):
            raise ValueError("layers before the first failure must pass")
        if any(layer.status != "NOT_EVALUATED" for layer in self.layers[first + 1 :]):
            raise ValueError("layers after the first failure must not be evaluated")
        if self.reason_codes != (self.layers[first].reason_code,):
            raise ValueError("report reason must equal the blocked layer reason")
        return self


def _digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise IntegrationLockError(f"cannot hash {path}: {error}") from error


def _safe_root(root: Path, *, label: str) -> Path:
    if root.is_symlink() or not root.is_dir():
        raise IntegrationLockError(f"{label} root must be a direct directory")
    try:
        resolved = root.resolve(strict=True)
    except OSError as error:
        raise IntegrationLockError(f"{label} root is unavailable: {error}") from error
    return resolved


def _regular_file_under(root: Path, relative: str) -> Path:
    try:
        _relative_path(relative)
    except ValueError as error:
        raise IntegrationLockError(str(error)) from error
    root = _safe_root(root, label="integration")
    cursor = root
    for part in PurePosixPath(relative).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise IntegrationLockError(f"bound path contains a symlink: {relative}")
    try:
        resolved = cursor.resolve(strict=True)
        mode = resolved.stat().st_mode
    except OSError as error:
        raise IntegrationLockError(
            f"bound file is missing: {relative}: {error}"
        ) from error
    if not resolved.is_relative_to(root) or not stat.S_ISREG(mode):
        raise IntegrationLockError(f"bound path is not a regular file: {relative}")
    return resolved


def _read_object(path: Path, *, label: str) -> dict[str, object]:
    try:
        value = strict_json_loads(path.read_bytes())
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise IntegrationLockError(
            f"{label} is not valid strict JSON: {error}"
        ) from error
    if not isinstance(value, dict):
        raise IntegrationLockError(f"{label} must be a JSON object")
    return value


def _bound_file(root: Path, binding: FileBinding) -> Path:
    path = _regular_file_under(root, binding.path)
    if _digest(path) != binding.sha256:
        raise IntegrationLockError(f"digest drift: {binding.path}")
    return path


def _load_canonical_bound_model(
    root: Path,
    binding: FileBinding,
    model: type[EvidenceModel],
    *,
    label: str,
) -> EvidenceModel:
    path = _bound_file(root, binding)
    try:
        raw = path.read_bytes()
        value = model.model_validate_json(raw, strict=True)
    except (OSError, UnicodeError, ValueError, ValidationError) as error:
        raise IntegrationLockError(f"{label} is invalid: {error}") from error
    canonical = canonical_json_bytes(value.model_dump(mode="json"))
    if raw != canonical:
        raise IntegrationLockError(f"{label} bytes are not canonical JSON")
    return value


def _tree_sha256(root: Path, *, ignore_runtime_caches: bool = False) -> str:
    root = _safe_root(root, label="tree")
    digest = hashlib.sha256()
    ignored_parts = {".pytest_cache", "__pycache__", ".mypy_cache", ".ruff_cache"}
    ignored_suffixes = {".pyc", ".pyo", ".DS_Store"}
    files: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if ignore_runtime_caches and (
            any(part in ignored_parts for part in relative.parts)
            or path.name in ignored_suffixes
            or path.suffix in {".pyc", ".pyo"}
        ):
            continue
        if path.is_symlink():
            raise IntegrationLockError(f"tree contains symlink: {relative.as_posix()}")
        if path.is_file():
            files.append(path)
        elif not path.is_dir():
            raise IntegrationLockError(
                f"tree contains a non-file entry: {relative.as_posix()}"
            )
    if not files:
        raise IntegrationLockError("qualified tree is empty")
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        executable = "1" if path.stat().st_mode & 0o111 else "0"
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(executable.encode("ascii"))
        digest.update(b"\0")
        digest.update(_digest(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def observe_stage_identity(stage_root: Path) -> str:
    """Hash stage content, excluding metadata finalized after the lock.

    Final inventory and build identity bind the excluded lock/SBOM/metadata
    bytes.  Excluding them here prevents a lock -> SBOM -> stage identity ->
    lock digest cycle while retaining every executable and runtime input.
    """

    stage_root = _safe_root(stage_root, label="stage")
    files: list[dict[str, object]] = []
    for path in stage_root.rglob("*"):
        relative = path.relative_to(stage_root).as_posix()
        if relative in STAGE_IDENTITY_EXCLUDED_PATHS:
            continue
        if any(
            relative.startswith(prefix) for prefix in STAGE_IDENTITY_EXCLUDED_PREFIXES
        ):
            continue
        if path.is_symlink():
            raise IntegrationLockError(f"stage identity rejects symlink: {relative}")
        if path.is_file():
            files.append(
                {
                    "executable": bool(path.stat().st_mode & 0o111),
                    "path": relative,
                    "sha256": _digest(path),
                }
            )
        elif not path.is_dir():
            raise IntegrationLockError(
                f"stage identity rejects non-file entry: {relative}"
            )
    if not files:
        raise IntegrationLockError("stage identity cannot cover an empty stage")
    payload = {
        "algorithm": "content-tree-excluding-cycle-metadata-v1",
        "excluded_paths": sorted(
            set(STAGE_IDENTITY_EXCLUDED_PATHS) | set(STAGE_IDENTITY_EXCLUDED_PREFIXES)
        ),
        "files": sorted(files, key=lambda item: str(item["path"])),
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _zip_tree_sha256(path: Path) -> tuple[str, tuple[str, ...]]:
    digest = hashlib.sha256()
    members: dict[str, tuple[bytes, bool]] = {}
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                name = info.filename
                if name.endswith("/"):
                    continue
                pure = PurePosixPath(name)
                if (
                    not name
                    or "\\" in name
                    or pure.is_absolute()
                    or any(part in {"", ".", ".."} for part in pure.parts)
                    or name in members
                ):
                    raise IntegrationLockError(
                        "ARW wheel contains an unsafe or duplicate path"
                    )
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise IntegrationLockError("ARW wheel contains a symlink")
                members[name] = (archive.read(info), bool(mode & 0o111))
    except (OSError, zipfile.BadZipFile) as error:
        raise IntegrationLockError(f"ARW wheel is invalid: {error}") from error
    if not members:
        raise IntegrationLockError("ARW wheel is empty")
    for name in sorted(members):
        value, executable = members[name]
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(b"1" if executable else b"0")
        digest.update(b"\0")
        digest.update(hashlib.sha256(value).hexdigest().encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest(), tuple(sorted(members))


def _host_tuple_sha256(host: CodexHostBinding) -> str:
    value = host.model_dump(mode="json", exclude={"tuple_sha256"})
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _hook_definition_sha256(stage_root: Path) -> str:
    components: list[bytes] = []
    for relative in ("hooks/hooks.json", "hooks/arw_hook.py"):
        path = _regular_file_under(stage_root, relative)
        components.extend((relative.encode("utf-8"), b"\0", path.read_bytes(), b"\0"))
    return hashlib.sha256(b"".join(components)).hexdigest()


def observe_hook_definition(stage_root: Path) -> tuple[FileBinding, FileBinding, str]:
    """Return the digest-derived staged hook definition without asserting trust."""

    stage_root = _safe_root(stage_root, label="stage")
    config = FileBinding.from_path(stage_root, "hooks/hooks.json")
    handler = FileBinding.from_path(stage_root, "hooks/arw_hook.py")
    return config, handler, _hook_definition_sha256(stage_root)


def _observed_codex_cli_version(result: subprocess.CompletedProcess[str]) -> str:
    """Extract one stable version record from a bounded Codex observation.

    A nested Codex invocation can emit observational plugin-hook diagnostics
    around its normal ``--version`` line.  Those diagnostics are not part of
    the host identity.  Admission therefore requires exactly one complete,
    stable version line on stdout, a successful process exit, and bounded
    captured output; it never accepts a prefix match, a prerelease, or an
    ambiguous multi-version result.
    """

    stdout = result.stdout or ""
    stderr = result.stderr or ""
    if (
        result.returncode != 0
        or "\x00" in stdout
        or "\x00" in stderr
        or len(stdout.encode("utf-8", errors="replace")) > 16 * 1024
        or len(stderr.encode("utf-8", errors="replace")) > 16 * 1024
    ):
        raise IntegrationLockError(
            "Codex version observation was not a bounded successful result"
        )
    candidates = [
        line.strip()
        for line in stdout.splitlines()
        if _CODEX_CLI_STABLE_VERSION_RE.fullmatch(line.strip()) is not None
    ]
    if len(candidates) != 1:
        raise IntegrationLockError(
            "Codex version observation requires exactly one stable version line"
        )
    return candidates[0]


def _executable(path: Path) -> ExecutableBinding:
    if not path.is_absolute():
        raise IntegrationLockError("Codex executable paths must be absolute")
    try:
        resolved = path.resolve(strict=True)
        mode = resolved.stat().st_mode
        executable = os.access(resolved, os.X_OK)
    except OSError as error:
        raise IntegrationLockError(
            f"Codex executable is unavailable: {error}"
        ) from error
    if not stat.S_ISREG(mode) or not executable:
        raise IntegrationLockError(
            "Codex executable must resolve to an executable file"
        )
    return ExecutableBinding(
        invoked_path=str(path), resolved_path=str(resolved), sha256=_digest(resolved)
    )


def observe_codex_host(launcher: Path, native_binary: Path) -> CodexHostBinding:
    """Derive the precise installed host tuple from executable bytes and output."""

    launcher_binding = _executable(launcher)
    native_binding = _executable(native_binary)
    environment = {
        "PATH": os.environ.get("PATH", os.defpath),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "NO_COLOR": "1",
    }
    try:
        result = subprocess.run(
            [launcher_binding.invoked_path, "--version"],
            cwd="/",
            env=environment,
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise IntegrationLockError(
            f"Codex version observation failed: {error}"
        ) from error
    version = _observed_codex_cli_version(result)
    preliminary = {
        "cli_version": version,
        "platform_system": platform.system(),
        "platform_release": platform.release(),
        "platform_machine": platform.machine(),
        "launcher": launcher_binding,
        "native_binary": native_binding,
    }
    digest = hashlib.sha256(
        canonical_json_bytes(
            {
                key: value.model_dump(mode="json")
                if isinstance(value, LockModel)
                else value
                for key, value in preliminary.items()
            }
        )
    ).hexdigest()
    try:
        return CodexHostBinding(**preliminary, tuple_sha256=digest)
    except ValidationError as error:
        raise IntegrationLockError(f"Codex host tuple is invalid: {error}") from error


def is_supported_codex_cli_version(value: str) -> bool:
    """Return whether a stable Codex CLI release satisfies the minimum range.

    The range determines admission only.  A lock still records the observed
    version and exact executable bytes, so a different qualifying release must
    provide a canary for its own host tuple.
    """

    match = _CODEX_CLI_STABLE_VERSION_RE.fullmatch(value)
    if match is None:
        return False
    try:
        observed = tuple(int(match.group(name)) for name in ("major", "minor", "patch"))
    except (TypeError, ValueError) as error:
        raise IntegrationLockError(
            "Codex CLI version components are invalid"
        ) from error
    return observed >= MINIMUM_CODEX_CLI_VERSION


def discover_codex_native_binary(launcher: Path) -> Path:
    """Locate the one native binary shipped beside the installed Codex JS launcher."""

    try:
        resolved = launcher.resolve(strict=True)
        if resolved.name != "codex.js":
            return resolved
        package_root = resolved.parent.parent
        candidates = tuple(
            sorted(
                path
                for path in package_root.glob(
                    "node_modules/@openai/codex-*/vendor/*/bin/codex"
                )
                if path.is_file() and os.access(path, os.X_OK)
            )
        )
    except OSError as error:
        raise IntegrationLockError(
            f"the installed Codex package is unavailable: {error}"
        ) from error
    if len(candidates) != 1:
        raise IntegrationLockError(
            "the installed Codex package must expose exactly one native host binary"
        )
    return candidates[0]


def _skill_metadata_version(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise IntegrationLockError(f"ARS router is unreadable: {error}") from error
    in_metadata = False
    for line in lines:
        if line == "metadata:":
            in_metadata = True
            continue
        if in_metadata and line and not line.startswith((" ", "\t")):
            break
        if in_metadata:
            match = re.fullmatch(r"\s+version:\s*[\"']?([^\"'\s]+)[\"']?\s*", line)
            if match:
                return match.group(1)
    raise IntegrationLockError("ARS router metadata version is missing")


def _component(manifest: Mapping[str, object], component_id: str) -> dict[str, object]:
    components = manifest.get("components")
    if not isinstance(components, list):
        raise IntegrationLockError("source manifest components are missing")
    matches = [
        item
        for item in components
        if isinstance(item, dict) and item.get("id") == component_id
    ]
    if len(matches) != 1:
        raise IntegrationLockError(f"source manifest must contain one {component_id}")
    return matches[0]


def _source_binding(
    component: Mapping[str, object],
    component_id: Literal["academic-research-skills", "experiment-agent"],
) -> SourceRepositoryBinding:
    try:
        return SourceRepositoryBinding.model_validate(
            {
                "component_id": component_id,
                "upstream_url": component["upstream_url"],
                "commit": component["revision"],
                "git_tree": component["git_tree"],
                "source_tree_sha256": component["tree_sha256"],
            },
            strict=True,
        )
    except (KeyError, ValidationError) as error:
        raise IntegrationLockError(
            f"invalid source identity for {component_id}: {error}"
        ) from error


def _validate_bundled_ars(
    stage_root: Path, source_manifest: Mapping[str, object]
) -> ARSBinding:
    root = _safe_root(
        stage_root / "skills/academic-research-suite", label="bundled ARS"
    )
    manifest_binding = FileBinding.from_path(root, "manifest.json")
    version_binding = FileBinding.from_path(root, "VERSION")
    router_binding = FileBinding.from_path(root, "SKILL.md")
    manifest = _read_object(root / "manifest.json", label="bundled ARS manifest")
    try:
        version = (root / "VERSION").read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as error:
        raise IntegrationLockError(
            f"bundled ARS version is unreadable: {error}"
        ) from error
    if (
        manifest.get("name") != "academic-research-suite"
        or manifest.get("adapter_version") != EXPECTED_ARS_ADAPTER_VERSION
        or version != EXPECTED_ARS_ADAPTER_VERSION
        or _skill_metadata_version(root / "SKILL.md") != EXPECTED_ARS_ADAPTER_VERSION
    ):
        raise IntegrationLockError("bundled ARS adapter version identities disagree")
    repository_rows = manifest.get("source_repositories")
    if not isinstance(repository_rows, list):
        raise IntegrationLockError(
            "bundled ARS source repository identities are missing"
        )
    bundled_commits = {
        row.get("name"): row.get("commit")
        for row in repository_rows
        if isinstance(row, dict)
    }
    source_bindings = (
        _source_binding(
            _component(source_manifest, "academic-research-skills"),
            "academic-research-skills",
        ),
        _source_binding(
            _component(source_manifest, "experiment-agent"), "experiment-agent"
        ),
    )
    if any(
        bundled_commits.get(item.component_id) != item.commit
        for item in source_bindings
    ):
        raise IntegrationLockError(
            "bundled ARS commits do not match the pinned source identities"
        )
    ars_root = root / "ars"
    try:
        return ARSBinding(
            dependency_model="bundled-pinned-adapter",
            bundled=True,
            adapter_name="academic-research-suite",
            adapter_version=EXPECTED_ARS_ADAPTER_VERSION,
            adapter_tree_sha256=_tree_sha256(root, ignore_runtime_caches=True),
            upstream_content_tree_sha256=_tree_sha256(
                ars_root, ignore_runtime_caches=True
            ),
            manifest=manifest_binding,
            version_file=version_binding,
            router=router_binding,
            source_repositories=source_bindings,
        )
    except ValidationError as error:
        raise IntegrationLockError(
            f"bundled ARS identity is invalid: {error}"
        ) from error


def _validate_arw_runtime(stage_root: Path) -> ARWRuntimeBinding:
    pyproject = FileBinding.from_path(stage_root, "pyproject.toml")
    plugin_manifest = FileBinding.from_path(stage_root, ".codex-plugin/plugin.json")
    cli_launcher = FileBinding.from_path(stage_root, "bin/arw")
    try:
        project = tomllib.loads(
            _bound_file(stage_root, pyproject).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise IntegrationLockError(f"staged pyproject is invalid: {error}") from error
    if project.get("project", {}).get("name") != "academic-research-workbench":
        raise IntegrationLockError("staged ARW package name is invalid")
    if project.get("project", {}).get("version") != "0.1.0":
        raise IntegrationLockError("staged ARW package version is not qualified")
    plugin = _read_object(
        _bound_file(stage_root, plugin_manifest), label="staged plugin manifest"
    )
    plugin_version = plugin.get("version")
    if plugin.get("name") != "academic-research-workbench" or not isinstance(
        plugin_version, str
    ):
        raise IntegrationLockError("staged plugin identity is invalid")
    if not re.fullmatch(r"0\.1\.0(?:\+codex\.[a-z0-9-]+)?", plugin_version):
        raise IntegrationLockError("staged plugin version is not qualified")
    wheels = tuple(
        sorted(
            (stage_root / "vendor/python/wheelhouse").glob(
                "academic_research_workbench-*.whl"
            )
        )
    )
    if len(wheels) != 1 or wheels[0].is_symlink():
        raise IntegrationLockError("stage must contain exactly one direct ARW wheel")
    wheel_relative = wheels[0].relative_to(stage_root).as_posix()
    wheel = FileBinding.from_path(stage_root, wheel_relative)
    wheel_tree, members = _zip_tree_sha256(wheels[0])
    if any(name.startswith(("ars/", "academic_research_suite/")) for name in members):
        raise IntegrationLockError(
            "ARW wheel unexpectedly includes the standalone ARS runtime"
        )
    if "arw/kernel/policy/integration_lock.py" not in members:
        raise IntegrationLockError("ARW wheel omits the integration-lock runtime")
    metadata_names = [name for name in members if name.endswith(".dist-info/METADATA")]
    if len(metadata_names) != 1:
        raise IntegrationLockError("ARW wheel distribution metadata is ambiguous")
    with zipfile.ZipFile(wheels[0]) as archive:
        metadata = archive.read(metadata_names[0]).decode("utf-8")
    if (
        "\nName: academic-research-workbench\n" not in f"\n{metadata}"
        or "\nVersion: 0.1.0\n" not in f"\n{metadata}"
    ):
        raise IntegrationLockError(
            "ARW wheel metadata does not match the staged runtime"
        )
    return ARWRuntimeBinding(
        package="academic-research-workbench",
        version="0.1.0",
        pyproject=pyproject,
        plugin_manifest=plugin_manifest,
        cli_launcher=cli_launcher,
        wheel=wheel,
        wheel_tree_sha256=wheel_tree,
    )


def _validate_file_base(
    stage_root: Path, source_manifest: Mapping[str, object]
) -> FileBaseBinding:
    source_binding = FileBinding.from_path(stage_root, "vendor/source-manifest.json")
    mcp_manifest_binding = FileBinding.from_path(stage_root, "vendor/mcp-manifest.json")
    evidence_binding = FileBinding.from_path(
        stage_root, ".file-base/build-evidence.json"
    )
    binary_binding = FileBinding.from_path(stage_root, "libexec/file-base-mcp")
    component = _component(source_manifest, "file-base")
    mcp_manifest = _read_object(
        _bound_file(stage_root, mcp_manifest_binding), label="MCP integration manifest"
    )
    if (
        mcp_manifest.get("schema_version") != "arw.mcp-integration-manifest.v1"
        or mcp_manifest.get("name") != "codebase-memory-mcp"
        or mcp_manifest.get("arw_component_id") != "file-base"
        or mcp_manifest.get("upstream_url") != component.get("upstream_url")
        or mcp_manifest.get("upstream_commit") != component.get("revision")
        or mcp_manifest.get("upstream_git_tree") != component.get("git_tree")
        or mcp_manifest.get("upstream_source_tree_sha256")
        != component.get("tree_sha256")
        or mcp_manifest.get("source_materialization") != "vendor/sources/file-base"
        or mcp_manifest.get("protocol") != "MCP-2025-11-25-stdio"
        or mcp_manifest.get("license") != "MIT"
    ):
        raise IntegrationLockError(
            "MCP manifest does not bind the qualified codebase-memory-mcp source"
        )
    mcp_binary = mcp_manifest.get("binary")
    if (
        not isinstance(mcp_binary, dict)
        or mcp_binary.get("path") != ".file-base/bin/file-base"
        or mcp_binary.get("staged_path") != "libexec/file-base-mcp"
        or mcp_binary.get("sha256") != binary_binding.sha256
    ):
        raise IntegrationLockError(
            "MCP manifest does not bind the staged file-base binary"
        )
    evidence = _read_object(
        _bound_file(stage_root, evidence_binding), label="file-base build evidence"
    )
    if component.get("revision") != EXPECTED_FILE_BASE_COMMIT:
        raise IntegrationLockError("file-base source commit is not qualified")
    evidence_component = evidence.get("component")
    if (
        not isinstance(evidence_component, dict)
        or evidence_component.get("id") != "file-base"
        or evidence_component.get("revision") != EXPECTED_FILE_BASE_COMMIT
    ):
        raise IntegrationLockError("file-base build evidence commit drift")
    if evidence.get("schema_version") != "1.0.0":
        raise IntegrationLockError("file-base build evidence schema is not qualified")
    manifest_patches = source_manifest.get("patches")
    evidence_patches = evidence.get("patches")
    if not isinstance(manifest_patches, list) or not manifest_patches:
        raise IntegrationLockError("ordered file-base patch series is missing")
    expected_rows: list[dict[str, object]] = []
    bindings: list[OrderedPatchBinding] = []
    for index, row in enumerate(manifest_patches, start=1):
        if not isinstance(row, dict) or row.get("order") != index:
            raise IntegrationLockError("file-base patch order is not contiguous")
        if row.get("component") != "file-base":
            raise IntegrationLockError("file-base patch component identity is invalid")
        try:
            binding = OrderedPatchBinding(
                order=row["order"], path=row["path"], sha256=row["sha256"]
            )
        except (KeyError, ValidationError) as error:
            raise IntegrationLockError(
                f"invalid file-base patch identity: {error}"
            ) from error
        bindings.append(binding)
        patch_file = _regular_file_under(stage_root, binding.path)
        if _digest(patch_file) != binding.sha256:
            raise IntegrationLockError(f"file-base patch bytes drifted: {binding.path}")
        expected_rows.append(binding.model_dump(mode="json"))
    if evidence_patches != expected_rows:
        raise IntegrationLockError("file-base build evidence patch series drift")
    mcp_patches = mcp_manifest.get("patches")
    if mcp_patches != expected_rows:
        raise IntegrationLockError("MCP manifest patch series drift")
    post_patch = manifest_patches[-1].get("post_tree_sha256")
    if evidence.get("post_patch_tree_sha256") != post_patch:
        raise IntegrationLockError("file-base post-patch tree drift")
    binary = evidence.get("binary")
    if (
        not isinstance(binary, dict)
        or binary.get("path") != ".file-base/bin/file-base"
        or binary.get("sha256") != binary_binding.sha256
    ):
        raise IntegrationLockError("file-base binary differs from build evidence")
    try:
        return FileBaseBinding.model_validate(
            {
                "component_id": "file-base",
                "commit": component["revision"],
                "git_tree": component["git_tree"],
                "source_tree_sha256": component["tree_sha256"],
                "source_manifest": source_binding,
                "build_evidence": evidence_binding,
                "binary": binary_binding,
                "ordered_patches": tuple(bindings),
                "post_patch_tree_sha256": post_patch,
            },
            strict=True,
        )
    except (KeyError, ValidationError) as error:
        raise IntegrationLockError(f"invalid file-base binding: {error}") from error


def _validate_hook_status_evidence(
    evidence_root: Path,
    bundle: CodexHostEvidenceBundle,
    *,
    hook_definition_sha256: str,
    stage_sha256: str,
) -> None:
    reference_parity: HookParityMatrix | None = None
    for classification in bundle.hook_status_classifications:
        binding = classification.evidence
        if PurePosixPath(binding.path).name != f"{binding.sha256}.json":
            raise IntegrationLockError(
                "hook parity evidence filename is not content addressed"
            )
        record = _load_canonical_bound_model(
            evidence_root,
            binding,
            HookParityEvidenceRecord,
            label=f"{classification.hook_state} hook parity evidence",
        )
        if (
            record.hook_state != classification.hook_state
            or record.observation != classification.observation
        ):
            raise IntegrationLockError(
                "hook classification differs from its retained parity evidence"
            )
        if (
            record.hook_definition_sha256 != hook_definition_sha256
            or record.stage_sha256 != stage_sha256
        ):
            raise IntegrationLockError(
                "hook parity evidence covered another hook definition or stage"
            )
        if reference_parity is None:
            reference_parity = record.parity
        else:
            try:
                reference_parity.assert_parity(record.parity)
            except ValueError as error:
                raise IntegrationLockError(
                    "hook status changed the parent authority projection"
                ) from error

        receipt_binding = record.official_hook_receipt
        if receipt_binding is None:
            continue
        receipt = _load_canonical_bound_model(
            evidence_root,
            receipt_binding,
            CodexHookReceipt,
            label="trusted/enabled official hook receipt",
        )
        if PurePosixPath(receipt_binding.path).name != f"{receipt.receipt_sha256}.json":
            raise IntegrationLockError(
                "official hook receipt filename is not receipt-addressed"
            )
        if receipt.hook_definition_sha256 != hook_definition_sha256:
            raise IntegrationLockError(
                "official hook receipt covered another hook definition"
            )
        if receipt.permission_mode != "bypassPermissions":
            raise IntegrationLockError(
                "official hook receipt did not use the vetted automation bypass"
            )


def _validate_hook(
    stage_root: Path,
    canary_path: Path,
    host: CodexHostBinding,
    arw_runtime: ARWRuntimeBinding,
) -> HookBinding:
    config, handler, definition = observe_hook_definition(stage_root)
    if canary_path.is_symlink() or not canary_path.is_file():
        raise IntegrationLockError("Codex host canary must be a direct regular file")
    try:
        canary_raw = canary_path.read_bytes()
        evidence = CodexHostCanaryEvidence.model_validate_json(canary_raw, strict=True)
    except (OSError, UnicodeError, ValueError, ValidationError) as error:
        raise IntegrationLockError(f"Codex host canary is invalid: {error}") from error
    if canary_raw != canonical_json_bytes(evidence.model_dump(mode="json")):
        raise IntegrationLockError("Codex host canary bytes are not canonical JSON")
    canary_digest = hashlib.sha256(canary_raw).hexdigest()
    if evidence.codex_host_tuple_sha256 != host.tuple_sha256:
        raise IntegrationLockError(
            "Codex host canary was produced by another host tuple"
        )
    if evidence.arw_runtime_sha256 != arw_runtime.wheel.sha256:
        raise IntegrationLockError("Codex host canary covered another ARW runtime")
    if evidence.hook_definition_sha256 != definition:
        raise IntegrationLockError("Codex host canary covered another hook definition")
    if evidence.stage_sha256 != observe_stage_identity(stage_root):
        raise IntegrationLockError(
            "Codex host canary covered another live stage identity"
        )
    if evidence.credential_policy_sha256 != EXPECTED_CODEX_CREDENTIAL_POLICY_SHA256:
        raise IntegrationLockError(
            "Codex host canary credential policy is not qualified"
        )
    evidence_root = _safe_root(canary_path.parent, label="Codex host evidence")
    bundle = _load_canonical_bound_model(
        evidence_root,
        evidence.evidence_bundle,
        CodexHostEvidenceBundle,
        label="Codex host evidence bundle",
    )
    if bundle.fresh_home_receipts != evidence.fresh_home_receipts:
        raise IntegrationLockError(
            "canary and bundle fresh-home receipt bindings differ"
        )
    expected_tuple = (
        evidence.codex_host_tuple_sha256,
        evidence.arw_runtime_sha256,
        evidence.stage_sha256,
        evidence.hook_definition_sha256,
        evidence.hook_execution_admission,
        evidence.credential_policy_sha256,
    )
    bundle_tuple = (
        bundle.codex_host_tuple_sha256,
        bundle.arw_runtime_sha256,
        bundle.stage_sha256,
        bundle.hook_definition_sha256,
        bundle.hook_execution_admission,
        bundle.credential_policy_sha256,
    )
    if bundle_tuple != expected_tuple:
        raise IntegrationLockError("canary and bundle qualification tuples differ")
    if (
        bundle.live_hook_execution != evidence.live_hook_execution
        or bundle.fresh_home_default_trust != evidence.fresh_home_default_trust
    ):
        raise IntegrationLockError("canary and bundle hook admission facts differ")

    _validate_hook_status_evidence(
        evidence_root,
        bundle,
        hook_definition_sha256=definition,
        stage_sha256=evidence.stage_sha256,
    )

    receipts = tuple(
        _load_canonical_bound_model(
            evidence_root,
            binding,
            FreshHomeReceipt,
            label=f"fresh-home receipt {index}",
        )
        for index, binding in enumerate(evidence.fresh_home_receipts, start=1)
    )
    if tuple(receipt.home_ordinal for receipt in receipts) != (1, 2, 3):
        raise IntegrationLockError(
            "fresh-home receipt ordinals must be exactly 1, 2, 3"
        )
    for receipt in receipts:
        receipt_tuple = (
            receipt.codex_host_tuple_sha256,
            receipt.arw_runtime_sha256,
            receipt.stage_sha256,
            receipt.hook_definition_sha256,
            receipt.hook_execution_admission,
            receipt.credential_policy_sha256,
        )
        if receipt_tuple != expected_tuple:
            raise IntegrationLockError("fresh-home qualification tuple drift")
    distinct_fields = {
        "HOME identities": {item.home_identity_sha256 for item in receipts},
        "CODEX_HOME identities": {item.codex_home_identity_sha256 for item in receipts},
        "Codex thread IDs": {item.codex_thread_id for item in receipts},
        "host agent IDs": {item.host_agent_id for item in receipts},
        "attempt IDs": {item.expected_attempt_id for item in receipts},
        "proposal nonces": {item.expected_proposal_nonce for item in receipts},
        "proposal digests": {item.result_channel.proposal_sha256 for item in receipts},
        "result-channel scopes": {
            item.result_channel.channel_scope_sha256 for item in receipts
        },
    }
    for label, values in distinct_fields.items():
        if len(values) != 3:
            raise IntegrationLockError(f"fresh-home {label} are not distinct")
    return HookBinding(
        config=config,
        handler=handler,
        definition_algorithm="relative-name-nul-bytes-nul-v1",
        definition_sha256=definition,
        hook_execution_admission=evidence.hook_execution_admission,
        live_hook_execution=evidence.live_hook_execution,
        fresh_home_default_trust=evidence.fresh_home_default_trust,
        host_canary_evidence_sha256=canary_digest,
        evidence_bundle_sha256=evidence.evidence_bundle.sha256,
        fresh_home_receipt_sha256=(
            evidence.fresh_home_receipts[0].sha256,
            evidence.fresh_home_receipts[1].sha256,
            evidence.fresh_home_receipts[2].sha256,
        ),
        arw_runtime_sha256=evidence.arw_runtime_sha256,
        stage_identity_algorithm="content-tree-excluding-cycle-metadata-v1",
        stage_sha256=evidence.stage_sha256,
        credential_policy_sha256=evidence.credential_policy_sha256,
    )


def _technical_provenance_digest(stage_root: Path, relative: str) -> str:
    target = _regular_file_under(stage_root, relative)
    if relative != "SBOM.cdx.json":
        return _digest(target)
    sbom = _read_object(target, label="technical provenance SBOM")
    try:
        sbom_bytes = target.read_bytes()
    except OSError as error:
        raise IntegrationLockError(
            f"technical provenance SBOM is unreadable: {error}"
        ) from error
    canonical_sbom_bytes = (json.dumps(sbom, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    if sbom_bytes != canonical_sbom_bytes:
        raise IntegrationLockError("technical provenance SBOM bytes are not canonical")
    components = sbom.get("components")
    if not isinstance(components, list) or not all(
        isinstance(component, dict) for component in components
    ):
        raise IntegrationLockError("technical provenance SBOM components are malformed")
    lock_relative = "supply-chain/integration-lock.json"
    lock_ref = f"artifact:{lock_relative}"
    lock_components = [
        component for component in components if component.get("bom-ref") == lock_ref
    ]
    lock_candidate = stage_root / lock_relative
    if lock_candidate.is_symlink() or lock_candidate.exists():
        lock_path = _regular_file_under(stage_root, lock_relative)
        expected_component = {
            "bom-ref": lock_ref,
            "hashes": [{"alg": "SHA-256", "content": _digest(lock_path)}],
            "name": lock_relative,
            "type": "file",
            "version": "1",
        }
        if lock_components != [expected_component]:
            raise IntegrationLockError(
                "technical provenance SBOM integration lock component is not exact"
            )
    else:
        if lock_components:
            raise IntegrationLockError(
                "technical provenance SBOM claims an absent integration lock component"
            )
        return _digest(target)
    base_sbom = dict(sbom)
    base_sbom["components"] = [
        component for component in components if component.get("bom-ref") != lock_ref
    ]
    base_bytes = (json.dumps(base_sbom, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    return hashlib.sha256(base_bytes).hexdigest()


def _validate_license(stage_root: Path) -> LicenseBinding:
    verdict_binding = FileBinding.from_path(
        stage_root, "supply-chain/license-verdict.json"
    )
    verdict = _read_object(
        _bound_file(stage_root, verdict_binding), label="license verdict"
    )
    use_path = "supply-chain/use-distribution.json"
    use_file = _regular_file_under(stage_root, use_path)
    use_distribution_sha256 = _digest(use_file)
    use_distribution = _read_object(use_file, label="use and distribution declaration")
    if verdict.get("use_distribution_path") != use_path:
        raise IntegrationLockError(
            "license verdict does not reference the staged use declaration"
        )
    expected_keys = {
        "accountable_approval",
        "distribution_class",
        "evidence_hashes",
        "intended_use",
        "permission_references",
        "private_repository_is_noncommercial_evidence",
        "repository_visibility",
        "schema_version",
    }
    if set(use_distribution) != expected_keys:
        raise IntegrationLockError(
            "use and distribution declaration fields do not match the qualified policy"
        )
    expected_statuses = {
        "intended_use": {"status": "unknown"},
        "distribution_class": {"status": "unknown"},
        "accountable_approval": {"status": "missing"},
    }
    if any(
        use_distribution.get(key) != value for key, value in expected_statuses.items()
    ):
        raise IntegrationLockError(
            "use and distribution declaration does not support the exact legal blockers"
        )
    private_repository_evidence = use_distribution.get(
        "private_repository_is_noncommercial_evidence"
    )
    if (
        use_distribution.get("schema_version") != "1.0.0"
        or use_distribution.get("repository_visibility") != "public"
        or use_distribution.get("permission_references") != []
        or not isinstance(private_repository_evidence, bool)
        or private_repository_evidence
    ):
        raise IntegrationLockError(
            "use and distribution declaration does not support the exact legal blockers"
        )
    evidence_hashes = use_distribution.get("evidence_hashes")
    if not isinstance(evidence_hashes, list):
        raise IntegrationLockError(
            "use and distribution evidence hashes must be a list"
        )
    seen_evidence_paths: set[str] = set()
    for row in evidence_hashes:
        if not isinstance(row, dict) or set(row) != {"path", "purpose", "sha256"}:
            raise IntegrationLockError(
                "use and distribution evidence hash is malformed"
            )
        path = row.get("path")
        digest = row.get("sha256")
        try:
            if not isinstance(path, str):
                raise ValueError("evidence path must be a string")
            _relative_path(path)
        except ValueError as error:
            raise IntegrationLockError(
                "use and distribution evidence path is unsafe"
            ) from error
        if (
            path in seen_evidence_paths
            or row.get("purpose") != "technical-provenance-only"
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise IntegrationLockError(
                "use and distribution evidence hash is malformed"
            )
        seen_evidence_paths.add(path)
        if path not in EXPECTED_TECHNICAL_PROVENANCE_PATHS:
            raise IntegrationLockError(
                "technical provenance path set contains an unexpected entry"
            )
        if digest != _technical_provenance_digest(stage_root, path):
            raise IntegrationLockError(f"technical provenance digest mismatch: {path}")
    if seen_evidence_paths != EXPECTED_TECHNICAL_PROVENANCE_PATHS:
        raise IntegrationLockError("technical provenance path set is incomplete")

    policy = UseDistributionPolicyProjection(
        schema_version="arw.use-distribution-policy-projection.v1",
        source_path=use_path,
        declaration_schema_version="1.0.0",
        repository_visibility="public",
        intended_use_status="unknown",
        distribution_class_status="unknown",
        accountable_approval_status="missing",
        permission_reference_count=0,
        private_repository_is_noncommercial_evidence=False,
    )
    policy_sha256 = hashlib.sha256(
        canonical_json_bytes(policy.model_dump(mode="json"))
    ).hexdigest()
    technical_qualification = verdict.get("technical_qualification")
    release_qualification = verdict.get("release_qualification")
    raw_reason_codes = verdict.get("reason_codes")
    if (
        technical_qualification != "PASS"
        or release_qualification != "BLOCKED"
        or raw_reason_codes != list(EXPECTED_LEGAL_BLOCKERS)
    ):
        raise IntegrationLockError("license verdict is not the qualified blocked state")
    reason_codes = EXPECTED_LEGAL_BLOCKERS
    try:
        return LicenseBinding(
            verdict=verdict_binding,
            use_distribution_path=use_path,
            use_distribution_sha256=use_distribution_sha256,
            use_distribution_policy=policy,
            use_distribution_policy_sha256=policy_sha256,
            technical_qualification="PASS",
            release_qualification="BLOCKED",
            reason_codes=reason_codes,
        )
    except ValidationError as error:
        raise IntegrationLockError(
            f"license verdict is not the qualified blocked state: {error}"
        ) from error


def build_integration_lock(
    *,
    stage_root: Path,
    codex_launcher: Path,
    codex_native_binary: Path,
    host_canary_evidence: Path,
) -> IntegrationLock:
    """Build a lock from the stage's bundled ARS bytes.

    The staged ``skills/academic-research-suite`` tree is the only ARS input.
    """

    stage_root = _safe_root(stage_root, label="stage")
    source_path = _regular_file_under(stage_root, "vendor/source-manifest.json")
    source_manifest = _read_object(source_path, label="source manifest")
    arw_runtime = _validate_arw_runtime(stage_root)
    ars = _validate_bundled_ars(stage_root, source_manifest)
    file_base = _validate_file_base(stage_root, source_manifest)
    host = observe_codex_host(codex_launcher, codex_native_binary)
    if not is_supported_codex_cli_version(host.cli_version):
        raise IntegrationLockError(
            "Codex CLI version is unsupported; requires a stable Codex CLI "
            f"{CODEX_CLI_VERSION_REQUIREMENT} and host-specific canary evidence"
        )
    hook = _validate_hook(stage_root, host_canary_evidence, host, arw_runtime)
    license_binding = _validate_license(stage_root)
    build_identity = observe_build_identity_binding(stage_root, source_manifest)
    return IntegrationLock(
        schema_version="arw.integration-lock.v2",
        dependency_model="bundled-pinned-adapter",
        arw_runtime=arw_runtime,
        ars=ars,
        file_base=file_base,
        codex_host=host,
        hook=hook,
        license=license_binding,
        build_identity=build_identity,
        technical_qualification="PASS",
        release_qualification="BLOCKED",
    )


def integration_lock_bytes(lock: IntegrationLock) -> bytes:
    return canonical_json_bytes(lock.model_dump(mode="json"))


def _direct_file_matches(path: Path, expected: bytes) -> bool:
    try:
        if path.is_symlink() or not path.is_file():
            return False
        return path.read_bytes() == expected
    except OSError:
        return False


def write_integration_lock(path: Path, lock: IntegrationLock) -> str:
    """Write canonical lock bytes atomically without replacing different bytes."""

    value = integration_lock_bytes(lock)
    digest = hashlib.sha256(value).hexdigest()
    if path.is_symlink():
        raise IntegrationLockError("integration lock path must not be a symlink")
    if path.exists():
        if not _direct_file_matches(path, value):
            raise IntegrationLockError(
                "integration lock is immutable and already differs"
            )
        return digest
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as collision:
            if _direct_file_matches(path, value):
                return digest
            raise IntegrationLockError(
                "integration lock publication collided"
            ) from collision
        return digest
    except OSError as error:
        raise IntegrationLockError(
            f"cannot publish integration lock: {error}"
        ) from error
    finally:
        temporary.unlink(missing_ok=True)


def load_integration_lock(path: Path) -> IntegrationLock:
    if path.is_symlink() or not path.is_file():
        raise IntegrationLockError("integration lock must be a direct regular file")
    raw = path.read_bytes()
    try:
        # Pydantic's strict JSON boundary correctly maps JSON arrays to tuple
        # fields while still rejecting Python-side list coercion.
        lock = IntegrationLock.model_validate_json(raw, strict=True)
    except (UnicodeError, ValueError, ValidationError) as error:
        raise IntegrationLockError(f"integration lock is invalid: {error}") from error
    if raw != integration_lock_bytes(lock):
        raise IntegrationLockError("integration lock bytes are not canonical")
    return lock


def _audit_inventory_source(relative: str) -> str:
    """Recompute the canonical inventory_source label for a stage-relative path.

    Mirrors the helper embedded in ``scripts/stage-plugin`` so the live audit
    gate and the stage builder label files identically.
    """

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


def _read_pretty_sorted_json(stage_root: Path, relative: str, *, label: str) -> object:
    """Read a stage-relative JSON document written as pretty-sorted + newline.

    The audit manifests are emitted by ``scripts/stage-plugin`` with
    ``json.dumps(..., indent=2, sort_keys=True) + "\n"``.  They are not the
    compact canonical form used by ``canonical_json_bytes``; rejecting the
    compact form here keeps the manifest's recomputable file set aligned with
    its on-disk bytes.
    """

    path = _regular_file_under(stage_root, relative)
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise IntegrationLockError(f"{label} is unreadable: {error}") from error
    try:
        decoded = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise IntegrationLockError(
            f"{label} is not valid strict JSON: {error}"
        ) from error
    expected = (json.dumps(decoded, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if raw != expected:
        raise IntegrationLockError(
            f"{label} bytes are not pretty-sorted canonical JSON"
        )
    return decoded


def _validate_build_identity_schema(stage_root: Path) -> dict[str, object]:
    """Validate the staged build identity against its declared JSON Schema.

    The schema document itself is the staged copy at
    ``share/arw/schemas/build-identity.schema.json``; we do not trust any
    off-tree mirror.
    """

    schema_path = _regular_file_under(stage_root, AUDIT_BUILD_IDENTITY_SCHEMA_RELATIVE)
    try:
        schema_document = json.loads(schema_path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise IntegrationLockError(
            f"build identity schema is not valid strict JSON: {error}"
        ) from error
    if not isinstance(schema_document, dict):
        raise IntegrationLockError("build identity schema must be a JSON object")
    try:
        jsonschema.Draft202012Validator.check_schema(schema_document)
    except jsonschema.SchemaError as error:
        raise IntegrationLockError(
            f"build identity schema is not a valid Draft 2020-12 schema: {error}"
        ) from error
    return schema_document


_CYCLE_METADATA_PATHS: frozenset[str] = frozenset(
    {
        AUDIT_BUILD_IDENTITY_RELATIVE,
        AUDIT_STAGE_INVENTORY_RELATIVE,
    }
)


def _verify_digest_path(
    stage_root: Path,
    entry: object,
    *,
    label: str,
    staged_payloads: frozenset[str] | None = None,
) -> None:
    """Verify a ``digestPath`` entry has live bytes that match its declared sha256.

    The path MUST resolve to a regular file under ``stage_root``, MUST NOT be a
    cycle-forming metadata path, and MUST have a current sha256 equal to the
    declared value.  When ``staged_payloads`` is supplied the path must also
    appear in that closed set so every live claim remains bound to the staged
    payload manifest.
    """

    if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
        raise IntegrationLockError(
            f"{label} digestPath must declare exactly {{path, sha256}}"
        )
    relative = entry["path"]
    digest = entry["sha256"]
    if not isinstance(relative, str) or not isinstance(digest, str):
        raise IntegrationLockError(f"{label} digestPath fields must be strings")
    if relative in _CYCLE_METADATA_PATHS:
        raise IntegrationLockError(
            f"{label} digestPath cannot point at cycle-forming metadata: {relative}"
        )
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise IntegrationLockError(
            f"{label} digestPath sha256 is malformed: {relative}"
        )
    try:
        path = _regular_file_under(stage_root, relative)
    except IntegrationLockError as error:
        raise IntegrationLockError(
            f"{label} digestPath target is missing or unsafe: {relative}"
        ) from error
    if _digest(path) != digest:
        raise IntegrationLockError(
            f"{label} digestPath live bytes do not match declared digest: {relative}"
        )
    if staged_payloads is not None and relative not in staged_payloads:
        raise IntegrationLockError(
            f"{label} digestPath is not covered by staged_payloads: {relative}"
        )


def _verify_aggregate_sha256(
    stage_root: Path,
    entries: object,
    claimed: object,
    *,
    label: str,
    staged_payloads: frozenset[str] | None = None,
) -> list[tuple[str, str]]:
    """Verify a derived aggregate digest equals ``aggregate_schema_sha256``.

    Returns the ordered ``(path, sha256)`` tuples that produced the verified
    aggregate so callers can chain subsequent derivations off the already
    verified primitives.
    """

    # Lazy import to avoid a circular dependency with ``arw.schema_registry``.
    from arw.kernel.policy.schema_registry import aggregate_schema_sha256

    if not isinstance(claimed, str) or re.fullmatch(r"[0-9a-f]{64}", claimed) is None:
        raise IntegrationLockError(f"{label} aggregate sha256 is malformed")
    if not isinstance(entries, list) or not all(
        isinstance(item, dict) for item in entries
    ):
        raise IntegrationLockError(f"{label} aggregate entries must be a list")
    materialized: list[tuple[str, str]] = []
    for index, item in enumerate(entries):
        _verify_digest_path(
            stage_root,
            item,
            label=f"{label} entry #{index}",
            staged_payloads=staged_payloads,
        )
        materialized.append((item["path"], item["sha256"]))
    if aggregate_schema_sha256(materialized) != claimed:
        raise IntegrationLockError(
            f"{label} aggregate sha256 does not match derived digest"
        )
    return materialized


# ---------------------------------------------------------------------------
# Phase 01 evidence producer contracts.
#
# These strict Pydantic models capture the full producer contracts for each
# phase-01 evidence surface (network verdicts, legal release verdict, pre-vendor
# license receipt).  They are the SINGLE source of truth for both the
# installed verifier (``_verify_evidence_pass``) and the producer
# (``stage-plugin`` ``staged_evidence`` helper) - no mirrored logic.
#
# ``derive_qualification`` is the producer-defined semantic gate; the
# verifier requires ``technical_qualification`` to equal this derived value
# so a self-asserted field cannot be used to bypass semantic validation.
# ---------------------------------------------------------------------------


_NET_NAMESPACE_PATTERN = re.compile(r"^net:\[\d+\]$")
_NATIVE_EVIDENCE_RELATIVE = re.compile(
    r"^share/arw/evidence/(?P<surface>upstream|asan_ubsan|tsan)_(?P<kind>"
    r"command|sanitizer_verdict|test_suite_sha256|status)\.json$"
)
# Surface-pinned argv used by ``scripts/build-file-base``.  The producer
# passes one of these to the sandbox; the receiver fails if the argv is
# not the exact closed tuple.
_NATIVE_ARGV_BY_SURFACE: dict[str, tuple[str, ...]] = {
    "upstream": (
        "./scripts/build-file-base",
        "--clean",
        "--run-upstream-tests",
    ),
    "asan_ubsan": (
        "./scripts/build-file-base",
        "--clean",
        "--sanitizers",
        "asan,ubsan",
        "--run-upstream-tests",
    ),
    "tsan": (
        "./scripts/build-file-base",
        "--clean",
        "--sanitizers",
        "tsan",
        "--run-upstream-tests",
    ),
}
# Surface-pinned environment keys that MUST appear with the right value.
# Each surface shares three common keys; sanitizer surfaces additionally
# pin ``ARW_SANITIZER_RUNTIME_DIR`` and the upstream surface MUST NOT
# carry it.
_NATIVE_ENV_REQUIRED: dict[str, dict[str, str | None]] = {
    "upstream": {
        "ARW_NETWORK_DENIAL_MECHANISM": "bwrap-unshare-net",
        "ARW_OFFLINE_EXEC_ACTIVE": "1",
    },
    "asan_ubsan": {
        "ARW_NETWORK_DENIAL_MECHANISM": "bwrap-unshare-net",
        "ARW_OFFLINE_EXEC_ACTIVE": "1",
        "ARW_SANITIZER_RUNTIME_DIR": None,  # presence required, value
        #             checked by path suffix at validation time
    },
    "tsan": {
        "ARW_NETWORK_DENIAL_MECHANISM": "bwrap-unshare-net",
        "ARW_OFFLINE_EXEC_ACTIVE": "1",
        "ARW_SANITIZER_RUNTIME_DIR": None,
    },
}
_NATIVE_ENV_FORBIDDEN: dict[str, frozenset[str]] = {
    "upstream": frozenset({"ARW_SANITIZER_RUNTIME_DIR"}),
    "asan_ubsan": frozenset(),
    "tsan": frozenset(),
}
_NATIVE_EVIDENCE_ROOT_TAIL: dict[str, str] = {
    "upstream": "/native/upstream",
    "asan_ubsan": "/native/asan-ubsan",
    "tsan": "/native/tsan",
}


class NetworkVerdict(LockModel):
    """Contract for ``scripts/offline-exec`` network-verdict surfaces.

    ``passed`` semantics: ``command_status == 0`` AND
    ``network_namespace_denied is True`` AND ``network_syscall_attempts is []``.
    """

    schema_version: Literal["1.0.0"]
    command_status: Literal[0]
    network_namespace_denied: Literal[True]
    network_syscall_attempts: list[object]
    strace_network_audit: Literal[True]
    child_network_namespace: str
    host_network_namespace: str
    network_denial_mechanism: Literal["bwrap-unshare-net"]
    namespace_local_network_syscall_count: int
    technical_qualification: str

    @model_validator(mode="after")
    def _validate_namespaces(self) -> Self:
        if not _NET_NAMESPACE_PATTERN.fullmatch(self.child_network_namespace):
            raise ValueError("child_network_namespace must match ^net:\\[\\d+\\]$")
        if not _NET_NAMESPACE_PATTERN.fullmatch(self.host_network_namespace):
            raise ValueError("host_network_namespace must match ^net:\\[\\d+\\]$")
        if self.child_network_namespace == self.host_network_namespace:
            raise ValueError(
                "child_network_namespace must differ from host_network_namespace"
            )
        if self.namespace_local_network_syscall_count < 0:
            raise ValueError(
                "namespace_local_network_syscall_count must be a non-negative int"
            )
        return self

    def derive_qualification(self) -> str:
        if self.command_status != 0:
            return "BLOCKED"
        if not self.network_namespace_denied:
            return "BLOCKED"
        if self.network_syscall_attempts:
            return "BLOCKED"
        return "PASS"


class _LegalComponentRow(LockModel):
    component_id: Literal["academic-research-skills", "experiment-agent", "file-base"]
    license: Literal["CC-BY-NC-4.0", "MIT"]
    release_status: Literal["BLOCKED", "SATISFIED"]
    source_path: str
    source_sha256: Sha256
    staged_path: str
    staged_sha256: Sha256

    @model_validator(mode="after")
    def _validate_pinned(self) -> Self:
        pinned = _PINNED_LEGAL_ROWS.get(self.component_id)
        if pinned is None:
            raise ValueError(f"legal verdict has no pinned row for {self.component_id}")
        # Exact equality on every closed field; ``staged_sha256`` must
        # equal ``source_sha256`` AND the pinned source_sha256.
        for field_name, expected in pinned.items():
            observed = getattr(self, field_name)
            if observed != expected:
                raise ValueError(
                    f"legal verdict row {self.component_id}.{field_name} "
                    f"must equal pinned {expected!r}: got {observed!r}"
                )
        if self.staged_sha256 != self.source_sha256:
            raise ValueError(
                f"legal verdict row {self.component_id} staged_sha256 "
                f"must equal source_sha256"
            )
        if self.license == "CC-BY-NC-4.0" and self.release_status != "BLOCKED":
            raise ValueError(
                f"legal verdict row {self.component_id} is CC-BY-NC-4.0 "
                "and must be release_status=BLOCKED"
            )
        return self


class LegalVerdict(LockModel):
    """Contract for ``scripts/license-gate classify_release`` output."""

    schema_version: Literal["1.0.0"]
    release_qualification: Literal["BLOCKED"]
    reason_codes: list[str]
    evidence_needed: list[str]
    components: list[_LegalComponentRow]
    use_distribution_path: Literal["supply-chain/use-distribution.json"]
    private_repository_is_noncommercial_evidence: Literal[False]
    technical_qualification: str

    @model_validator(mode="after")
    def _validate_exact(self) -> Self:
        if tuple(self.reason_codes) != EXPECTED_LEGAL_BLOCKERS:
            raise ValueError(
                "legal verdict reason_codes must equal the qualified blockers"
            )
        expected_needed = (
            "Declare intended use and distribution class.",
            "Record accountable approval with evidence hashes.",
            "Record authentic owner permission or establish compatible CC BY-NC use.",
        )
        if tuple(self.evidence_needed) != expected_needed:
            raise ValueError(
                "legal verdict evidence_needed must equal the producer strings"
            )
        seen_ids: set[str] = set()
        for row in self.components:
            if row.component_id in seen_ids:
                raise ValueError(
                    f"legal verdict has duplicate component_id: {row.component_id}"
                )
            seen_ids.add(row.component_id)
        if seen_ids != {"academic-research-skills", "experiment-agent", "file-base"}:
            raise ValueError(
                "legal verdict must declare exactly the three qualified components"
            )
        return self

    def derive_qualification(self) -> str:
        return "PASS"


class NativeCommandReceipt(LockModel):
    """Producer contract for the offline-exec command receipt per surface.

    The producer (scripts/offline-exec) runs ``scripts/build-file-base`` with
    one of three surface-pinned argv tuples inside a network-isolated
    sandbox; the receiver (this model) requires the exact closed argv,
    the exact sandbox/network pinning fields, and strict real UTC
    calendar timestamps.  The exit status is NOT carried here - it
    lives in the per-surface ``status.txt`` file (pinned to ``"0\\n"``).
    """

    model_config = ConfigDict(extra="forbid")

    argv: list[str]
    cwd: str
    started_at: str
    ended_at: str
    environment: dict[str, str]
    network_denial_mechanism: Literal["bwrap-unshare-net"]
    strace: str

    @field_validator("started_at", "ended_at")
    @classmethod
    def _validate_timestamp(cls, value: str) -> str:
        _parse_strict_rfc3339_z(value)
        return value

    @model_validator(mode="after")
    def _validate_exact(self) -> Self:
        if not self.argv:
            raise ValueError("native command receipt argv must be non-empty")
        if not self.cwd:
            raise ValueError("native command receipt cwd must be non-empty")
        if not self.strace:
            raise ValueError("native command receipt strace path must be non-empty")
        started = _parse_strict_rfc3339_z(self.started_at)
        ended = _parse_strict_rfc3339_z(self.ended_at)
        if started > ended:
            raise ValueError("native command receipt started_at must be <= ended_at")
        return self


class NativeSanitizerVerdict(LockModel):
    """Producer contract for the per-surface sanitizer verdict file.

    The producer writes the suite name verbatim from the offline-exec
    run (e.g. ``asan-ubsan`` for the asan-ubsan surface), so the verifier
    accepts the canonical surface keys (``upstream``/``asan_ubsan``/
    ``tsan``) AND the producer-emitted path-style names
    (``upstream``/``asan-ubsan``/``tsan``).
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"]
    suite: str
    test_status: Literal[0]
    fatal_diagnostic_patterns_absent: Literal[True]
    technical_qualification: Literal["PASS"]

    @field_validator("suite")
    @classmethod
    def _validate_suite(cls, value: str) -> str:
        accepted = frozenset(NATIVE_SURFACES) | frozenset(
            s.replace("_", "-") for s in NATIVE_SURFACES
        )
        if value not in accepted:
            raise ValueError(
                f"sanitizer verdict suite must be one of {sorted(accepted)}; "
                f"got {value!r}"
            )
        return value


_NATIVE_TEST_SUITE_SHA256_BYTES: bytes = (
    EXPECTED_FILE_BASE_TEST_TREE.encode("ascii") + b"\n"
)
_NATIVE_STATUS_ZERO_BYTES: bytes = b"0\n"


_NATIVE_VERDICT_SHA256_BY_SURFACE = {
    "upstream": "8b30b76aea2732abdf52cf8f28c27d6670cb1c1dc57bafcd0cdb4bfb59244cac",
    "asan_ubsan": "672741e6f3db1c9a056f82fc5a6947f5b2be5cfb777a8b28f89c88cefa983e0e",
    "tsan": "849724d83b199b2ef124c28e22e007227ab1937f33085e9c1985d6459b51d269",
}
_NATIVE_COMMAND_SHA256_BY_SURFACE = {
    "upstream": "0b3ac7a4f01a6e7516b4e8dbf9f6464fa8bc2240f2ff90c9ffbff01d2ac7d083",
    "asan_ubsan": "f3642356554e51454b60e54d671f89e1d42006cd899d3af0a685fa2adc2afd65",
    "tsan": "7c150b5d52556404fae2ea5fb0a3624c8578a5151397588e2d729cbc67f582f4",
}


def _verify_native_surface_bundle(
    stage_root: Path, *, surface: str, label: str
) -> None:
    """Validate the four per-surface evidence files for one native surface.

    The bundle is the authoritative surface identity: ``command`` carries
    the surface-pinned argv; ``sanitizer_verdict`` carries the suite +
    test_status; ``test_suite_sha256.txt`` carries the upstream test tree
    digest; ``status.txt`` is exactly ``"0\\n"``.  The verifier rejects on
    any drift because two native surfaces are otherwise interchangeable
    (both verdicts claim PASS; the bundle distinguishes them).
    """

    if surface not in NATIVE_SURFACES:
        raise IntegrationLockError(
            f"{label} native surface must be one of {NATIVE_SURFACES}"
        )

    command_path = _regular_file_under(
        stage_root, native_evidence_path(surface, "command")
    )
    try:
        command_raw = command_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise IntegrationLockError(
            f"{label} command file is unreadable: {error}"
        ) from error
    try:
        command_payload = strict_json_loads(command_raw)
    except ValueError as error:
        raise IntegrationLockError(
            f"{label} command file is not strict unambiguous JSON: {error}"
        ) from error
    if not isinstance(command_payload, dict):
        raise IntegrationLockError(f"{label} command file must be a JSON object")
    try:
        command = NativeCommandReceipt.model_validate(command_payload, strict=True)
    except ValidationError as error:
        raise IntegrationLockError(
            f"{label} command file fails the NativeCommandReceipt contract: {error}"
        ) from error
    observed_command_sha256 = _digest(command_path)
    expected_command_sha256 = _NATIVE_COMMAND_SHA256_BY_SURFACE[surface]
    if observed_command_sha256 != expected_command_sha256:
        raise IntegrationLockError(
            f"{label} command bytes do not match the canonical surface receipt: "
            f"observed={observed_command_sha256} "
            f"expected={expected_command_sha256}"
        )
    verdict_path = _regular_file_under(
        stage_root, native_evidence_path(surface, NATIVE_VERDICT_KIND)
    )
    observed_verdict_sha256 = _digest(verdict_path)
    expected_verdict_sha256 = _NATIVE_VERDICT_SHA256_BY_SURFACE[surface]
    if observed_verdict_sha256 != expected_verdict_sha256:
        raise IntegrationLockError(
            f"{label} verdict bytes do not match the canonical command surface: "
            f"observed={observed_verdict_sha256} "
            f"expected={expected_verdict_sha256}"
        )

    pinned_argv = _NATIVE_ARGV_BY_SURFACE[surface]
    if tuple(command.argv) != pinned_argv:
        raise IntegrationLockError(
            f"{label} native surface argv drift: expected {pinned_argv!r}; "
            f"got {tuple(command.argv)!r}"
        )

    evidence_root = command.environment.get("ARW_OFFLINE_EVIDENCE_ROOT")
    if not isinstance(evidence_root, str) or not evidence_root.endswith(
        _NATIVE_EVIDENCE_ROOT_TAIL[surface]
    ):
        raise IntegrationLockError(
            f"{label} native surface ARW_OFFLINE_EVIDENCE_ROOT must end "
            f"with {_NATIVE_EVIDENCE_ROOT_TAIL[surface]!r}; got {evidence_root!r}"
        )
    if command.environment.get("ARW_OFFLINE_EXEC_ACTIVE") != "1":
        raise IntegrationLockError(
            f"{label} native surface ARW_OFFLINE_EXEC_ACTIVE must be '1'; "
            f"got {command.environment.get('ARW_OFFLINE_EXEC_ACTIVE')!r}"
        )

    required_env = _NATIVE_ENV_REQUIRED[surface]
    forbidden_env = _NATIVE_ENV_FORBIDDEN[surface]
    for key, expected in required_env.items():
        observed = command.environment.get(key)
        if observed is None:
            raise IntegrationLockError(
                f"{label} native surface environment.{key} is required"
            )
        if expected is not None and observed != expected:
            raise IntegrationLockError(
                f"{label} native surface environment.{key} must equal "
                f"{expected!r}; got {observed!r}"
            )
    for forbidden in forbidden_env:
        if forbidden in command.environment:
            raise IntegrationLockError(
                f"{label} native surface environment.{forbidden} must not "
                "be present on the upstream surface"
            )

    if surface != "upstream":
        sanitizer_runtime = command.environment.get("ARW_SANITIZER_RUNTIME_DIR")
        if not isinstance(sanitizer_runtime, str) or not sanitizer_runtime:
            raise IntegrationLockError(
                f"{label} native surface ARW_SANITIZER_RUNTIME_DIR is "
                "required for sanitizer runs"
            )

    sanitizer_path = _regular_file_under(
        stage_root, native_evidence_path(surface, "sanitizer_verdict")
    )
    try:
        sanitizer_payload = strict_json_loads(sanitizer_path.read_bytes())
    except (OSError, UnicodeError, ValueError) as error:
        raise IntegrationLockError(
            f"{label} sanitizer_verdict file is not strict unambiguous JSON: {error}"
        ) from error
    try:
        sanitizer = NativeSanitizerVerdict.model_validate(
            sanitizer_payload, strict=True
        )
    except ValidationError as error:
        raise IntegrationLockError(
            f"{label} sanitizer_verdict file fails the "
            f"NativeSanitizerVerdict contract: {error}"
        ) from error
    expected_suite = surface.replace("_", "-")
    if sanitizer.suite != expected_suite:
        raise IntegrationLockError(
            f"{label} sanitizer verdict suite must equal current surface "
            f"{expected_suite!r}; got {sanitizer.suite!r}"
        )

    test_suite_path = _regular_file_under(
        stage_root, native_evidence_path(surface, "test_suite_sha256")
    )
    try:
        test_suite_bytes = test_suite_path.read_bytes()
    except (OSError, UnicodeError) as error:
        raise IntegrationLockError(
            f"{label} test_suite_sha256.txt is unreadable: {error}"
        ) from error
    if test_suite_bytes != _NATIVE_TEST_SUITE_SHA256_BYTES:
        raise IntegrationLockError(
            f"{label} test_suite_sha256.txt must equal the pinned upstream "
            f"test tree digest; got {test_suite_bytes!r}, expected "
            f"{_NATIVE_TEST_SUITE_SHA256_BYTES!r}"
        )

    status_path = _regular_file_under(
        stage_root, native_evidence_path(surface, "status")
    )
    try:
        status_bytes = status_path.read_bytes()
    except (OSError, UnicodeError) as error:
        raise IntegrationLockError(
            f"{label} status.txt is unreadable: {error}"
        ) from error
    if status_bytes != _NATIVE_STATUS_ZERO_BYTES:
        raise IntegrationLockError(
            f"{label} status.txt must be exactly b'0\\n'; got {status_bytes!r}"
        )


class _PreVendorComponentLicense(LockModel):
    component: Literal["academic-research-skills", "experiment-agent", "file-base"]
    sha256: Sha256
    source_path: Literal["LICENSE"]
    attribution_required: bool
    modification_marking_required: bool
    noncommercial_restriction: bool


class _PreVendorComponent(LockModel):
    id: Literal["academic-research-skills", "experiment-agent", "file-base"]
    clean: Literal[True]
    status_porcelain: Literal[""]
    revision: GitObjectId
    git_tree: GitObjectId
    tree_sha256: Sha256
    upstream_url: str
    version: str

    @model_validator(mode="after")
    def _validate_upstream(self) -> Self:
        if not self.upstream_url.startswith(("https://", "http://")):
            raise ValueError(f"component {self.id} upstream_url must be an http(s) URL")
        if not self.upstream_url or " " in self.upstream_url:
            raise ValueError(f"component {self.id} upstream_url is malformed")
        if not self.version:
            raise ValueError(f"component {self.id} version must be non-empty")
        return self


class _PreVendorLegalInput(LockModel):
    component: Literal["academic-research-skills", "experiment-agent", "file-base"]
    kind: Literal["license", "notice", "policy", "checker", "generator", "package-lock"]
    path: str
    sha256: Sha256


class _PreVendorCommand(LockModel):
    argv: list[str]
    cwd: str
    started_at: str
    ended_at: str
    status: Literal[0]
    stderr_path: str
    stdout_path: str


class _PreVendorGeneratedNotice(LockModel):
    path: str
    sha256: Sha256


class _PreVendorTool(LockModel):
    path: str
    sha256: Sha256


class _PreVendorNativeFileBaseGate(LockModel):
    unmodified: Literal[True]
    entrypoint: Literal["scripts/license-gate.sh"]
    commands: list[_PreVendorCommand]
    generated_notices: list[_PreVendorGeneratedNotice]
    tools: list[_PreVendorTool]

    @model_validator(mode="after")
    def _validate_nonempty(self) -> Self:
        expected_argv = (
            ("./scripts/license-gate.sh", "--selftest"),
            ("./scripts/license-gate.sh",),
        )
        if len(self.commands) != 3:
            raise ValueError(
                "native_file_base_gate.commands must contain exactly three "
                "ordered producer commands"
            )
        for index, expected in enumerate(expected_argv):
            command = self.commands[index]
            if tuple(command.argv) != expected:
                raise ValueError(
                    f"native_file_base_gate command #{index + 1} argv must equal "
                    f"{expected!r}"
                )
        notice_argv = tuple(self.commands[2].argv)
        if (
            len(notice_argv) != 2
            or notice_argv[0] != "./scripts/gen-third-party-notices.sh"
            or not notice_argv[1].endswith("/generated/THIRD_PARTY_NOTICES.md")
        ):
            raise ValueError(
                "native_file_base_gate command #3 argv must invoke the notice "
                "generator with generated/THIRD_PARTY_NOTICES.md"
            )
        expected_streams = (
            (
                "commands/001-native-gate-selftest/stdout.log",
                "commands/001-native-gate-selftest/stderr.log",
            ),
            (
                "commands/002-native-gate/stdout.log",
                "commands/002-native-gate/stderr.log",
            ),
            (
                "commands/003-notice-generator/stdout.log",
                "commands/003-notice-generator/stderr.log",
            ),
        )
        command_cwd = self.commands[0].cwd
        if not command_cwd.endswith("/sources/file-base"):
            raise ValueError(
                "native_file_base_gate command cwd must end with /sources/file-base"
            )
        for index, (command, streams) in enumerate(
            zip(self.commands, expected_streams, strict=True), start=1
        ):
            if command.cwd != command_cwd:
                raise ValueError(
                    "native_file_base_gate commands must share one source cwd"
                )
            if (command.stdout_path, command.stderr_path) != streams:
                raise ValueError(
                    f"native_file_base_gate command #{index} output paths drift"
                )
            started = _parse_strict_rfc3339_z(command.started_at)
            ended = _parse_strict_rfc3339_z(command.ended_at)
            if started > ended:
                raise ValueError(
                    f"native_file_base_gate command #{index} started after it ended"
                )
        expected_notice = (
            "generated/THIRD_PARTY_NOTICES.md",
            "310be73a18e18947faf03b375e67eb47dbd478aa6d9bdd031fe4135d78d259af",
        )
        observed_notices = tuple(
            (item.path, item.sha256) for item in self.generated_notices
        )
        if observed_notices != (expected_notice,):
            raise ValueError(
                "native_file_base_gate.generated_notices must equal the "
                "canonical producer notice"
            )
        expected_tools = (
            (
                "scripts/gen-third-party-notices.sh",
                "fba58ae1c2c4499c031a031759fa77d99d94e3b628b7dc30371e535c0a22d2f9",
            ),
            (
                "scripts/license-gate-check-npm.py",
                "a0456bf6f6f40b562417fffefa53657586193fbc240c8fede1ffbbb18b050417",
            ),
            (
                "scripts/license-gate-check.py",
                "9f4fc12b961565779dc2d2320099915ae444bce68e6e9e8da92b7a71d99b175d",
            ),
            (
                "scripts/license-gate.sh",
                "eac80b0cf31a2199a743ce59fab748b1a189c207acffa73fbd4b876549b9f67b",
            ),
            (
                "scripts/license-policy.json",
                "4c0f84f691e4b925d531979206a34c0b06387e193aa68bb9495f6c55b214d11a",
            ),
        )
        observed_tools = tuple(sorted((item.path, item.sha256) for item in self.tools))
        if observed_tools != expected_tools:
            raise ValueError(
                "native_file_base_gate.tools must equal the canonical five-tool "
                "producer inventory"
            )
        return self


class _PreVendorRawEvidence(LockModel):
    path: str
    sha256: Sha256


class _PreVendorToolIdentity(LockModel):
    git: str
    node: str
    npm: str
    python: str
    scancode: str

    @model_validator(mode="after")
    def _validate_nonempty(self) -> Self:
        expected = {
            "git": "git version 2.55.0",
            "node": "v24.13.0",
            "npm": "10.9.8",
            "python": "3.11.10",
            "scancode": (
                "ScanCode version: 32.5.0\n"
                "ScanCode Output Format version: 4.1.0\n"
                "SPDX License list version: 3.27"
            ),
        }
        for field, pinned in expected.items():
            value = getattr(self, field)
            if value != pinned:
                raise ValueError(
                    f"tool_identities.{field} must equal canonical producer "
                    f"identity {pinned!r}"
                )
        return self


class _PreVendorVendorObservation(LockModel):
    phase: Literal[
        "before",
        "during:fetch-academic-research-skills",
        "during:fetch-experiment-agent",
        "during:fetch-file-base",
        "during:native-gate-selftest",
        "during:native-gate",
        "during:notice-generator",
        "after",
    ]
    exists: Literal[False]


class PreVendorReceipt(LockModel):
    """Contract for ``scripts/pre-vendor-license-gate`` output.

    The ``created_at`` field is parsed by :func:`_parse_strict_rfc3339_z`
    so impossible calendar values (``2026-99-99T99:99:99Z``, non-leap
    ``2026-02-29T12:00:00Z``) are rejected at model validation time.
    Per-component cross-binding against the staged
    ``vendor/source-manifest.json`` happens in
    :func:`_bind_pre_vendor_components_to_manifest`, which is invoked
    from the shared :func:`verify_evidence_contract` helper so the
    installed verifier and the producer cannot drift.
    """

    schema_version: Literal["1.0.0"]
    component_licenses: list[_PreVendorComponentLicense]
    components: list[_PreVendorComponent]
    legal_inputs: list[_PreVendorLegalInput]
    native_file_base_gate: _PreVendorNativeFileBaseGate
    raw_evidence: list[_PreVendorRawEvidence]
    tool_identities: _PreVendorToolIdentity
    created_at: str
    vendor_sources_observations: list[_PreVendorVendorObservation]
    technical_qualification: str

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: str) -> str:
        # Strict parse rejects bad calendar / non-leap / non-UTC values.
        _parse_strict_rfc3339_z(value)
        return value

    @model_validator(mode="after")
    def _validate_exact(self) -> Self:
        if len(self.component_licenses) != 3:
            raise ValueError(
                "pre-vendor receipt must declare exactly 3 component_licenses"
            )
        if len(self.components) != 3:
            raise ValueError("pre-vendor receipt must declare exactly 3 components")
        if not self.legal_inputs:
            raise ValueError("pre-vendor receipt legal_inputs must be non-empty")
        if not self.raw_evidence:
            raise ValueError("pre-vendor receipt raw_evidence must be non-empty")
        expected_observation_phases = (
            "before",
            "during:fetch-academic-research-skills",
            "during:fetch-experiment-agent",
            "during:fetch-file-base",
            "during:native-gate-selftest",
            "during:native-gate",
            "during:notice-generator",
            "after",
        )
        observed_phases = tuple(item.phase for item in self.vendor_sources_observations)
        if observed_phases != expected_observation_phases:
            raise ValueError(
                "pre-vendor receipt vendor_sources_observations must equal the "
                "closed ordered producer phase sequence"
            )
        # Pin the two CC-BY-NC-4.0 license digests; file-base can be any
        # valid 64-hex sha256 because the producer does not pin it.
        expected = {
            "academic-research-skills": (
                "b3848009d12a173f549ef98d9ee486e64459e8eb5d9f895bff53782b4aa86d7c",
                True,
                True,
                True,
            ),
            "experiment-agent": (
                "f66a510318fa9c98534f64c844403bf54d9019613f5a818f9d92075b91133d25",
                True,
                True,
                True,
            ),
            "file-base": (
                "1f58f9911dc5e3bcb96de28bb28e7b6bb7eb323952d29569c5d7214a152146bb",
                True,
                False,
                False,
            ),
        }
        seen: set[str] = set()
        for license_row in self.component_licenses:
            seen.add(license_row.component)
            expected_sha, attribution, marking, noncommercial = expected[
                license_row.component
            ]
            if expected_sha is not None and license_row.sha256 != expected_sha:
                raise ValueError(
                    f"pre-vendor license sha256 drift for "
                    f"{license_row.component}: pinned={expected_sha} "
                    f"declared={license_row.sha256}"
                )
            if license_row.attribution_required is not attribution:
                raise ValueError(
                    f"pre-vendor license {license_row.component} "
                    f"attribution_required must be {attribution}"
                )
            if license_row.modification_marking_required is not marking:
                raise ValueError(
                    f"pre-vendor license {license_row.component} "
                    f"modification_marking_required must be {marking}"
                )
            if license_row.noncommercial_restriction is not noncommercial:
                raise ValueError(
                    f"pre-vendor license {license_row.component} "
                    f"noncommercial_restriction must be {noncommercial}"
                )
        if seen != {"academic-research-skills", "experiment-agent", "file-base"}:
            raise ValueError(
                "pre-vendor license set must cover the three qualified components"
            )
        return self

    def derive_qualification(self) -> str:
        return "PASS"


_EVIDENCE_MODEL_BY_SURFACE: dict[str, type[BaseModel]] = {
    "pre_vendor": PreVendorReceipt,
    "legal": LegalVerdict,
    "upstream": NetworkVerdict,
    "asan_ubsan": NetworkVerdict,
    "tsan": NetworkVerdict,
}


# Pinned exact row tuples for the LegalVerdict per-component contract.  Each
# row is the complete claim the verifier requires; partial or drifted rows
# are rejected.  Add new entries here only when the producer's pinned
# release evidence changes - the lock is intentional.
_PINNED_LEGAL_ROWS: dict[str, dict[str, str]] = {
    "academic-research-skills": {
        "license": "CC-BY-NC-4.0",
        "release_status": "BLOCKED",
        "source_path": "vendor/sources/academic-research-skills/LICENSE",
        "source_sha256": (
            "b3848009d12a173f549ef98d9ee486e64459e8eb5d9f895bff53782b4aa86d7c"
        ),
        "staged_path": "LICENSES/academic-research-skills-CC-BY-NC-4.0.txt",
    },
    "experiment-agent": {
        "license": "CC-BY-NC-4.0",
        "release_status": "BLOCKED",
        "source_path": "vendor/sources/experiment-agent/LICENSE",
        "source_sha256": (
            "f66a510318fa9c98534f64c844403bf54d9019613f5a818f9d92075b91133d25"
        ),
        "staged_path": "LICENSES/experiment-agent-CC-BY-NC-4.0.txt",
    },
    "file-base": {
        "license": "MIT",
        "release_status": "SATISFIED",
        "source_path": "vendor/sources/file-base/LICENSE",
        "source_sha256": (
            "1f58f9911dc5e3bcb96de28bb28e7b6bb7eb323952d29569c5d7214a152146bb"
        ),
        "staged_path": "LICENSES/file-base-MIT.txt",
    },
}


# Subset of fields that LegalVerdict rows MUST match against the staged
# vendor/source-manifest.json for PreVendorReceipt cross-binding.  The
# receipt's per-component row must equal the manifest's row values on
# these exact keys.
_PRE_VENDOR_MANIFEST_PIN_KEYS: tuple[str, ...] = (
    "version",
    "revision",
    "git_tree",
    "tree_sha256",
    "upstream_url",
)


def _parse_strict_rfc3339_z(value: str) -> datetime:
    """Parse ``YYYY-MM-DDTHH:MM:SS(.fff)Z`` strictly; reject bad calendar values.

    A loose ``datetime.fromisoformat`` accepts the impossible date
    ``2026-99-99T99:99:99Z`` because Python rolls invalid fields over
    silently in some interpreter builds; a leap-year check plus a
    round-trip ``strftime`` comparison guarantees the calendar values
    are real.
    """

    match = re.fullmatch(
        r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?Z",
        value,
    )
    if match is None:
        raise ValueError(
            "RFC3339 Z timestamp must match YYYY-MM-DDTHH:MM:SS(.fff)Z: " + value
        )
    year, month, day, hour, minute, second, fraction = match.groups()
    try:
        year_value = int(year)
        month_value = int(month)
        day_value = int(day)
        hour_value = int(hour)
        minute_value = int(minute)
        second_value = int(second)
    except ValueError as error:
        raise ValueError(
            f"RFC3339 Z timestamp has non-numeric fields: {value}"
        ) from error
    if not (
        1 <= month_value <= 12
        and 0 <= hour_value <= 23
        and 0 <= minute_value <= 59
        and 0 <= second_value <= 59
    ):
        raise ValueError(
            f"RFC3339 Z timestamp has out-of-range calendar/time fields: {value}"
        )
    microsecond = 0
    if fraction is not None:
        try:
            microsecond = int((fraction + "000000")[:6])
        except ValueError as error:
            raise ValueError(
                f"RFC3339 Z timestamp has a non-numeric fraction: {value}"
            ) from error
    try:
        parsed = datetime(
            year_value,
            month_value,
            day_value,
            hour_value,
            minute_value,
            second_value,
            microsecond,
            tzinfo=UTC,
        )
    except ValueError as error:
        raise ValueError(
            f"RFC3339 Z timestamp has invalid calendar date: {value}"
        ) from error
    # Round-trip the parsed datetime back through the same strict format
    # and compare; any silent roll-over (e.g. 2026-99-99 → some other
    # date) surfaces here.
    canonical = parsed.astimezone(UTC).strftime(
        "%Y-%m-%dT%H:%M:%S" + (".%f" if parsed.microsecond else "") + "Z"
    )
    if canonical != value:
        raise ValueError(
            "RFC3339 Z timestamp does not round-trip cleanly: "
            f"{value!r} != {canonical!r}"
        )
    return parsed


def _verify_legal_row_live_bytes(
    stage_root: Path, row: _LegalComponentRow, *, label: str
) -> None:
    """Read the staged ``staged_path`` and require its digest matches.

    The per-component row claims a ``staged_sha256`` that must equal both
    the ``source_sha256`` and the live digest of the file staged under
    ``row.staged_path``.  This binds the legal row to bytes the
    ``scripts/stage-plugin`` actually placed in the plugin tree.
    """

    staged_path = _regular_file_under(stage_root, row.staged_path)
    try:
        observed = _digest(staged_path)
    except IntegrationLockError:
        raise
    except (OSError, UnicodeError) as error:
        raise IntegrationLockError(
            f"{label} legal row {row.component_id} staged file is "
            f"unreadable: {row.staged_path}: {error}"
        ) from error
    if observed != row.staged_sha256:
        raise IntegrationLockError(
            f"{label} legal row {row.component_id} staged file digest "
            f"drift: declared={row.staged_sha256} observed={observed}"
        )
    if observed != row.source_sha256:
        raise IntegrationLockError(
            f"{label} legal row {row.component_id} source/staged digest "
            f"must be identical: source={row.source_sha256} staged={observed}"
        )


def _bind_pre_vendor_components_to_manifest(
    stage_root: Path,
    components: Sequence[_PreVendorComponent],
    legal_inputs: Sequence[_PreVendorLegalInput],
    *,
    label: str,
) -> None:
    """Cross-check PreVendorReceipt components against the staged vendor manifest.

    Each ``components[i]`` row must equal the matching ``components[i]``
    row in ``stage_root/vendor/source-manifest.json`` on the pinned keys
    (``version``, ``revision``, ``git_tree``, ``tree_sha256``,
    ``upstream_url``).  Any drift rejects.
    """

    manifest_path = _regular_file_under(stage_root, "vendor/source-manifest.json")
    try:
        manifest = strict_json_loads(manifest_path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise IntegrationLockError(
            f"{label} vendor/source-manifest.json is unreadable: {error}"
        ) from error
    if not isinstance(manifest, dict):
        raise IntegrationLockError(
            f"{label} vendor/source-manifest.json must be a JSON object"
        )
    manifest_components = manifest.get("components")
    if not isinstance(manifest_components, list):
        raise IntegrationLockError(
            f"{label} vendor/source-manifest.json has no components list"
        )
    manifest_by_id: dict[str, dict[str, object]] = {}
    for entry in manifest_components:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            manifest_by_id[entry["id"]] = cast(dict[str, object], entry)
    seen_ids: set[str] = set()
    for row in components:
        seen_ids.add(row.id)
        manifest_row = manifest_by_id.get(row.id)
        if manifest_row is None:
            raise IntegrationLockError(
                f"{label} pre-vendor component {row.id} is absent from "
                "the staged vendor/source-manifest.json"
            )
        for key in _PRE_VENDOR_MANIFEST_PIN_KEYS:
            expected = manifest_row.get(key)
            observed = getattr(row, key)
            if observed != expected:
                raise IntegrationLockError(
                    f"{label} pre-vendor component {row.id} field {key} "
                    f"drifts from staged vendor/source-manifest.json: "
                    f"declared={observed!r} manifest={expected!r}"
                )
    expected_ids = {"academic-research-skills", "experiment-agent", "file-base"}
    if seen_ids != expected_ids:
        raise IntegrationLockError(
            f"{label} pre-vendor components must be exactly "
            f"{sorted(expected_ids)}; got {sorted(seen_ids)}"
        )

    expected_legal_rows: list[tuple[str, str, str, str]] = []
    for component_id in sorted(expected_ids):
        manifest_row = manifest_by_id[component_id]
        manifest_legal = manifest_row.get("legal_inputs")
        if not isinstance(manifest_legal, list):
            raise IntegrationLockError(
                f"{label} staged manifest component {component_id} has no "
                "legal_inputs list"
            )
        prefix = f"vendor/sources/{component_id}/"
        for entry in manifest_legal:
            if not isinstance(entry, dict):
                raise IntegrationLockError(
                    f"{label} manifest legal input for {component_id} must be an object"
                )
            kind = entry.get("kind")
            path = entry.get("path")
            sha256 = entry.get("sha256")
            if (
                not isinstance(kind, str)
                or not isinstance(path, str)
                or not path.startswith(prefix)
                or not isinstance(sha256, str)
            ):
                raise IntegrationLockError(
                    f"{label} manifest legal input for {component_id} is malformed"
                )
            expected_legal_rows.append(
                (component_id, kind, path.removeprefix(prefix), sha256)
            )
    observed_legal_rows = [
        (item.component, item.kind, item.path, item.sha256) for item in legal_inputs
    ]
    if len(set(observed_legal_rows)) != len(observed_legal_rows) or sorted(
        observed_legal_rows
    ) != sorted(expected_legal_rows):
        raise IntegrationLockError(
            f"{label} pre-vendor legal_inputs drift from the exact closed "
            "staged source-manifest inventory"
        )


def verify_evidence_contract(
    stage_root: Path, payload: dict[str, object], *, surface: str
) -> BaseModel:
    """Shared semantic validator for one evidence surface.

    This is the SINGLE source of truth for ``_verify_evidence_pass`` (the
    installed verifier) and ``staged_evidence`` (the producer).  It
    validates the JSON against the strict Pydantic producer contract and
    performs every cross-check that requires ``stage_root`` (manifest
    cross-binding for ``pre_vendor``; live ``staged_path`` digest for
    ``legal``).  The declared ``technical_qualification`` must equal the
    model-derived value.
    """

    model = _EVIDENCE_MODEL_BY_SURFACE.get(surface)
    if model is None:
        raise IntegrationLockError(f"no producer contract for surface: {surface}")
    label = f"build identity evidence.{surface}"
    try:
        validated = model.model_validate(payload, strict=True)
    except ValidationError as error:
        raise IntegrationLockError(
            f"{label} evidence file fails the {model.__name__} producer "
            f"contract: {error}"
        ) from error
    if surface == "legal":
        legal = cast(LegalVerdict, validated)
        for row in legal.components:
            try:
                _verify_legal_row_live_bytes(stage_root, row, label=label)
            except IntegrationLockError as error:
                raise IntegrationLockError(
                    f"{label} live-bytes cross-check failed: {error}"
                ) from error
    elif surface == "pre_vendor":
        pre_vendor = cast(PreVendorReceipt, validated)
        try:
            _bind_pre_vendor_components_to_manifest(
                stage_root,
                pre_vendor.components,
                pre_vendor.legal_inputs,
                label=label,
            )
        except IntegrationLockError as error:
            raise IntegrationLockError(
                f"{label} manifest cross-check failed: {error}"
            ) from error
    contract = cast(
        "NetworkVerdict | LegalVerdict | PreVendorReceipt",
        validated,
    )
    derived = contract.derive_qualification()
    declared = contract.technical_qualification
    if declared != derived:
        raise IntegrationLockError(
            f"{label} evidence file declared technical_qualification="
            f"{declared!r} but the {model.__name__} semantics derive "
            f"{derived!r}"
        )
    return validated


def _verify_evidence_pass(
    stage_root: Path, path: str, *, label: str
) -> dict[str, object]:
    """Read a staged evidence file and DERIVE its qualification from full semantics.

    Each of the five phase-01 evidence files is staged into
    ``share/arw/evidence/*.json``.  This verifier delegates to the
    shared :func:`verify_evidence_contract` helper so the installed
    verifier and the producer (``stage-plugin`` ``staged_evidence``)
    share a single source of truth.  The helper parses the file against
    the matching strict Pydantic producer contract, runs every
    cross-binding check that requires ``stage_root`` (legal live digest,
    pre-vendor manifest cross-binding), and verifies the declared
    ``technical_qualification`` equals the model-derived value.
    """

    file_path = _regular_file_under(stage_root, path)
    try:
        payload = strict_json_loads(file_path.read_bytes())
    except (OSError, UnicodeError, ValueError) as error:
        raise IntegrationLockError(
            f"{label} evidence file is not strict unambiguous JSON: {path}: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise IntegrationLockError(
            f"{label} evidence file must be a JSON object: {path}"
        )
    surface = _evidence_surface_for(path)
    verify_evidence_contract(stage_root, payload, surface=surface)
    if surface == "pre_vendor":
        observed_sha256 = _digest(file_path)
        if observed_sha256 != EXPECTED_PRE_VENDOR_RECEIPT_SHA256:
            raise IntegrationLockError(
                f"{label} pre-vendor receipt raw bytes drift from canonical "
                f"reviewed evidence: observed={observed_sha256} "
                f"expected={EXPECTED_PRE_VENDOR_RECEIPT_SHA256}"
            )
    return payload


def _evidence_surface_for(path: str) -> str:
    """Map a staged evidence file path to its producer surface name."""

    basename = Path(path).name
    for surface in EVIDENCE_RELATIVE_PATHS:
        if Path(surface).name == basename:
            return Path(surface).stem
    raise ValueError(f"no evidence surface maps to {path}")


def _projection_patch_set_sha256(patches: list[Mapping[str, object]]) -> str:
    """Mirror the canonical compact-JSON derivation used by the producer."""

    materialized = [
        {key: patch[key] for key in ("order", "path", "sha256")} for patch in patches
    ]
    return hashlib.sha256(
        json.dumps(materialized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _projection_profile_patch_sha256(patches: list[Mapping[str, object]]) -> str:
    for patch in patches:
        if patch.get("order") == 4:
            value = patch.get("sha256")
            if (
                not isinstance(value, str)
                or re.fullmatch(r"[0-9a-f]{64}", value) is None
            ):
                raise IntegrationLockError(
                    "source manifest patch with order=4 has an invalid sha256"
                )
            return value
    raise IntegrationLockError("source manifest does not declare patch with order=4")


_CONTRACT_DEFINE_PATTERN = re.compile(
    r'#\s*define\s+ARW_FILES_CONTRACT_SHA256\s+"([0-9a-f]{64})"'
)
_PYTHON_VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def _strip_c_comments(source: str) -> str:
    """Strip C ``/* ... */`` block and ``// ...\\n`` line comments.

    The stripper intentionally does NOT honour string literals or preprocessor
    continuations - the file-contracts header we care about carries one
    directive per line and no string literals, so a naive character-level
    walk is both simpler and safer than a full C lexer.  Newlines inside
    block comments are preserved so reported line numbers stay stable.
    """

    out: list[str] = []
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        second = source[index + 1] if index + 1 < length else ""
        if char == "/" and second == "*":
            index += 2
            while index < length:
                if (
                    source[index] == "*"
                    and index + 1 < length
                    and source[index + 1] == "/"
                ):
                    index += 2
                    break
                if source[index] == "\n":
                    out.append("\n")
                index += 1
            continue
        if char == "/" and second == "/":
            while index < length and source[index] != "\n":
                index += 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


def parse_file_contract_contract_sha256(header_path: Path) -> str:
    """Return the embedded contract sha256 from the staged file-contracts header.

    The header MUST contain exactly one *active* (i.e. not commented out)
    ``#define ARW_FILES_CONTRACT_SHA256 "<64hex>"`` directive; zero or
    duplicate active defines are rejected.  String-aware ``/* */`` and
    ``//`` comment stripping ensures commented decoys cannot satisfy or
    shadow the directive.
    """

    try:
        header_bytes = header_path.read_bytes()
    except (OSError, UnicodeError) as error:
        raise IntegrationLockError(
            f"file-contracts header is unreadable: {error}"
        ) from error
    return parse_file_contract_contract_sha256_from_bytes(header_bytes)


def parse_file_contract_contract_sha256_from_bytes(header_bytes: bytes) -> str:
    """Bytes-based counterpart of :func:`parse_file_contract_contract_sha256`.

    This is the security-authority parser: the verifier regenerates the
    expected header from the staged checked schemas and parses the
    regenerated bytes directly so the staged header cannot influence the
    extracted semantic.
    """

    try:
        contract_header = header_bytes.decode("ascii")
    except UnicodeError as error:
        raise IntegrationLockError(
            f"file-contracts header is not ASCII: {error}"
        ) from error
    stripped = _strip_c_comments(contract_header)
    matches = tuple(_CONTRACT_DEFINE_PATTERN.finditer(stripped))
    if not matches:
        raise IntegrationLockError(
            "file-contracts header does not embed an active "
            "ARW_FILES_CONTRACT_SHA256 directive"
        )
    if len(matches) > 1:
        raise IntegrationLockError(
            "file-contracts header declares ARW_FILES_CONTRACT_SHA256 more "
            f"than once: {len(matches)} active definitions found"
        )
    for match in matches:
        return match.group(1)
    raise IntegrationLockError(
        "file-contracts header active definition disappeared during parsing"
    )


def _file_contract_contract_sha256(header_path: Path) -> str:
    """Backward-compatible wrapper around :func:`parse_file_contract_contract_sha256`."""

    return parse_file_contract_contract_sha256(header_path)


def observe_regenerated_file_contract(
    stage_root: Path, header_entry: dict[str, object]
) -> str:
    """Independently regenerate the file contract header from staged schemas.

    The staged ``share/arw/file-contracts.h`` is no longer the semantic
    authority: any attacker who can rewrite the header bytes can also lie
    about the embedded contract sha256.  The verifier instead regenerates
    the expected header from the staged checked schemas and requires the
    staged bytes to equal that regeneration byte-for-byte.  The expected
    ``ARW_FILES_CONTRACT_SHA256`` is then extracted from the regenerated
    bytes (NOT the staged bytes) and is the value the identity must claim.

    Returns the canonical ``contract_sha256`` derived from the regenerated
    header.
    """

    if not isinstance(header_entry, dict) or set(header_entry) != {"path", "sha256"}:
        raise IntegrationLockError(
            "build identity file_contract.header must be a digestPath"
        )
    header_relative = header_entry["path"]
    if not isinstance(header_relative, str):
        raise IntegrationLockError(
            "build identity file_contract.header path must be a string"
        )
    try:
        header_path = _regular_file_under(stage_root, header_relative)
    except IntegrationLockError as error:
        raise IntegrationLockError(
            f"file_contract.header target is missing or unsafe: {header_relative}"
        ) from error
    schema_root = _safe_root(stage_root / "share/arw/schemas", label="staged schemas")

    # Lazy import to keep ``arw.integration_lock`` importable in the schema
    # registry circular dance.  ``render_native_contract_header`` enforces
    # that each checked schema equals its model projection - this is the
    # security boundary that keeps the regenerated header trustworthy.
    try:
        from arw.file_contracts import (
            FileContractError,
            render_native_contract_header,
        )
    except ImportError as error:
        raise IntegrationLockError(
            f"file-contract renderer is unavailable: {error}"
        ) from error
    try:
        expected_bytes = render_native_contract_header(schema_root)
    except FileContractError as error:
        raise IntegrationLockError(
            f"regenerated file contract header is invalid: {error}"
        ) from error

    try:
        staged_bytes = header_path.read_bytes()
    except (OSError, UnicodeError) as error:
        raise IntegrationLockError(
            f"staged file contract header is unreadable: {error}"
        ) from error
    if staged_bytes != expected_bytes:
        raise IntegrationLockError(
            "staged file contract header does not match the bytes regenerated "
            "from the staged checked schemas; the staged header is no longer "
            "the semantic authority"
        )

    # Parse the regenerated bytes only - the staged bytes have already
    # been proven byte-equal to the regeneration above, so parsing them
    # or parsing the regeneration is equivalent.
    return parse_file_contract_contract_sha256_from_bytes(expected_bytes)


def observe_staged_python_version(stage_root: Path) -> str:
    """Read the staged ``.python-version`` and require strict x.y.z form.

    The producer pins the interpreter that built the wheel into this file;
    the verifier reads it back so the ``build_interpreter`` claim in the
    build identity is a live, content-addressable reference rather than a
    self-reported producer value.  A bare version without a patch component
    is rejected so callers cannot smuggle a partial ``3.13`` declaration.
    The pinned interpreter MUST be exactly Python 3.13.x or 3.14.x; future
    versions require an explicit binding update.
    """

    path = _regular_file_under(stage_root, ".python-version")
    try:
        raw = path.read_text(encoding="ascii")
    except (OSError, UnicodeError) as error:
        raise IntegrationLockError(f".python-version is unreadable: {error}") from error
    value = raw.strip()
    if "\n" in value or not _PYTHON_VERSION_PATTERN.fullmatch(value):
        raise IntegrationLockError(
            ".python-version must contain a single strict x.y.z version line"
        )
    _major, minor, _patch = value.split(".")
    try:
        minor_value = int(minor)
    except ValueError as error:
        raise IntegrationLockError(
            f".python-version has a non-numeric minor version: {value}"
        ) from error
    if minor_value not in {13, 14}:
        raise IntegrationLockError(
            f".python-version must be exactly 3.13.x or 3.14.x (got {value})"
        )
    return value


def _load_build_identity_binding(
    stage_root: Path,
    source_manifest: Mapping[str, object],
    *,
    staged_payloads: frozenset[str] | None = None,
) -> tuple[BuildIdentityBinding, dict[str, object]]:
    schema_document = _validate_build_identity_schema(stage_root)
    identity = _read_pretty_sorted_json(
        stage_root, AUDIT_BUILD_IDENTITY_RELATIVE, label="build identity"
    )
    if not isinstance(identity, dict):
        raise IntegrationLockError("build identity must be a JSON object")
    try:
        jsonschema.Draft202012Validator(schema_document).validate(identity)
    except jsonschema.ValidationError as error:
        raise IntegrationLockError(
            f"build identity is not schema-valid: {error.message}"
        ) from error

    try:
        components = source_manifest["components"]
        patches = source_manifest["patches"]
        native_test_suites = source_manifest["native_test_suites"]
        if (
            not isinstance(components, list)
            or not isinstance(patches, list)
            or not isinstance(native_test_suites, list)
            or not native_test_suites
        ):
            raise TypeError("source manifest projection fields are malformed")
        expected_components = [
            {
                key: component[key]
                for key in ("id", "version", "revision", "tree_sha256")
            }
            for component in components
        ]
        expected_patches = [
            {key: patch[key] for key in ("order", "path", "sha256")}
            for patch in patches
        ]
        ordered_patches = sorted(patches, key=lambda patch: patch["order"])
        expected_post_tree = ordered_patches[-1]["post_tree_sha256"]
        expected_test_tree = native_test_suites[0]["tree_sha256"]
    except (IndexError, KeyError, TypeError) as error:
        raise IntegrationLockError(
            f"source manifest cannot derive build identity: {error}"
        ) from error
    if identity.get("components") != expected_components:
        raise IntegrationLockError(
            "build identity components drift from the source manifest"
        )
    if identity.get("patches") != expected_patches:
        raise IntegrationLockError(
            "build identity patches drift from the source manifest"
        )
    native = identity.get("native")
    if not isinstance(native, dict):
        raise IntegrationLockError("build identity native projection is malformed")
    if expected_post_tree != EXPECTED_FILE_BASE_POST_PATCH_TREE:
        raise IntegrationLockError(
            "source manifest post-patch tree drifts from the pinned expectation"
        )
    if expected_test_tree != EXPECTED_FILE_BASE_TEST_TREE:
        raise IntegrationLockError(
            "source manifest native test tree drifts from the pinned expectation"
        )
    if native.get("patched_source_tree_sha256") != expected_post_tree:
        raise IntegrationLockError(
            "build identity native.patched_source_tree_sha256 drift"
        )
    if native.get("upstream_test_tree_sha256") != expected_test_tree:
        raise IntegrationLockError(
            "build identity native.upstream_test_tree_sha256 drift"
        )

    # ----- plugin.version must match the staged plugin manifest ---------------
    plugin = identity.get("plugin")
    if not isinstance(plugin, dict):
        raise IntegrationLockError("build identity plugin projection is malformed")
    declared_version = plugin.get("version")
    plugin_manifest_path = _regular_file_under(stage_root, ".codex-plugin/plugin.json")
    try:
        plugin_manifest = json.loads(plugin_manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise IntegrationLockError(
            f"staged plugin manifest is unreadable: {error}"
        ) from error
    if not isinstance(plugin_manifest, dict):
        raise IntegrationLockError("staged plugin manifest must be a JSON object")
    if plugin_manifest.get("version") != declared_version:
        raise IntegrationLockError(
            "build identity plugin.version drifts from staged plugin manifest"
        )
    if not re.fullmatch(r"0\.1\.0(?:\+[a-z0-9.-]+)?", str(declared_version)):
        raise IntegrationLockError(
            f"build identity plugin.version is not qualified: {declared_version}"
        )

    # ----- runtime.build_interpreter == staged .python-version --------------
    # The producer pins the interpreter that built the wheel into the staged
    # ``.python-version`` file; the verifier reads it back live so the
    # ``build_interpreter`` claim is content-addressable rather than
    # self-reported.  The verifier never compares against its own runtime
    # because installed verification can run on a different interpreter.
    runtime = identity.get("runtime")
    if not isinstance(runtime, dict):
        raise IntegrationLockError("build identity runtime is malformed")
    declared_build_interpreter = runtime.get("build_interpreter")
    if not isinstance(declared_build_interpreter, str):
        raise IntegrationLockError(
            "build identity runtime.build_interpreter must be a string"
        )
    staged_python_version = observe_staged_python_version(stage_root)
    if declared_build_interpreter != staged_python_version:
        raise IntegrationLockError(
            "build identity runtime.build_interpreter must equal staged "
            f".python-version: declared={declared_build_interpreter} "
            f"staged={staged_python_version}"
        )

    # ----- native.binary / native.build_evidence live bytes -------------------
    if native.get("compile_profile") != "release-o2":
        raise IntegrationLockError(
            "build identity native.compile_profile must be the qualified release-o2"
        )
    _verify_digest_path(
        stage_root,
        native.get("binary"),
        label="build identity native.binary",
        staged_payloads=staged_payloads,
    )
    _verify_digest_path(
        stage_root,
        native.get("build_evidence"),
        label="build identity native.build_evidence",
        staged_payloads=staged_payloads,
    )

    # ----- projection (query_launcher + derived aggregates) -------------------
    projection = identity.get("projection")
    if not isinstance(projection, dict):
        raise IntegrationLockError("build identity projection is malformed")
    if projection.get("algorithm") != "research-graph-projection-v1":
        raise IntegrationLockError(
            "build identity projection.algorithm is not the qualified projection"
        )
    if projection.get("native_profile") != "research-graph-builder-v1":
        raise IntegrationLockError(
            "build identity projection.native_profile is not the qualified profile"
        )
    if projection.get("oracle") != "research-graph-normalization-v1":
        raise IntegrationLockError(
            "build identity projection.oracle is not the qualified oracle"
        )
    if projection.get("query_profile") != "arw-graph-mcp-v1":
        raise IntegrationLockError(
            "build identity projection.query_profile is not the qualified profile"
        )
    _verify_digest_path(
        stage_root,
        projection.get("query_launcher"),
        label="build identity projection.query_launcher",
        staged_payloads=staged_payloads,
    )
    expected_patch_set = _projection_patch_set_sha256(list(patches))
    if projection.get("patch_set_sha256") != expected_patch_set:
        raise IntegrationLockError("build identity projection.patch_set_sha256 drift")
    expected_profile_patch = _projection_profile_patch_sha256(list(patches))
    if projection.get("profile_patch_sha256") != expected_profile_patch:
        raise IntegrationLockError(
            "build identity projection.profile_patch_sha256 drift"
        )

    # ----- file_contract.header live bytes + regenerated contract_sha256 -----
    file_contract = identity.get("file_contract")
    if not isinstance(file_contract, dict):
        raise IntegrationLockError("build identity file_contract is malformed")
    header_entry = file_contract.get("header")
    if not isinstance(header_entry, dict):
        raise IntegrationLockError("build identity file_contract.header is malformed")
    _verify_digest_path(
        stage_root,
        header_entry,
        label="build identity file_contract.header",
        staged_payloads=staged_payloads,
    )
    # The staged header is no longer the semantic authority: the verifier
    # regenerates the expected header bytes from the staged checked
    # schemas, requires the staged bytes to equal that regeneration
    # byte-for-byte, and then extracts the embedded ``contract_sha256``
    # from the *regenerated* bytes (so the staged header cannot influence
    # the extracted semantic even if its own embedded value was rewritten).
    expected_contract_sha = observe_regenerated_file_contract(stage_root, header_entry)
    declared_contract_sha = file_contract.get("contract_sha256")
    if not isinstance(declared_contract_sha, str):
        raise IntegrationLockError(
            "build identity file_contract.contract_sha256 must be a string"
        )
    # The contract_sha256 is the embedded semantic value derived from the
    # independently regenerated header; the staged bytes are no longer
    # authoritative.  A paired rebind attack (rewrite staged header +
    # update identity digestPath + update staged_payloads + update inventory)
    # is rejected by the regeneration step BEFORE the parser is consulted.
    if declared_contract_sha != expected_contract_sha:
        raise IntegrationLockError(
            "build identity file_contract.contract_sha256 must equal the "
            "ARW_FILES_CONTRACT_SHA256 embedded in the regenerated header"
        )

    # ----- wheelhouse lock / requirements / first_party live bytes ------------
    wheelhouse = identity.get("wheelhouse")
    if not isinstance(wheelhouse, dict):
        raise IntegrationLockError("build identity wheelhouse is malformed")
    for field in ("lock", "requirements", "first_party"):
        _verify_digest_path(
            stage_root,
            wheelhouse.get(field),
            label=f"build identity wheelhouse.{field}",
            staged_payloads=staged_payloads,
        )
    first_party = wheelhouse.get("first_party")
    if isinstance(first_party, dict) and first_party.get("path", "").startswith(
        "vendor/python/wheelhouse/"
    ):
        # Verify the wheelhouse.lock.json claims this exact first-party wheel
        # so the digestPath and the lockfile cannot be rebound independently.
        lock_path = _regular_file_under(stage_root, wheelhouse["lock"]["path"])
        try:
            lock_payload = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise IntegrationLockError(
                f"wheelhouse lock payload is unreadable: {error}"
            ) from error
        first_party_record = (
            lock_payload.get("first_party_wheel")
            if isinstance(lock_payload, dict)
            else None
        )
        if not isinstance(first_party_record, dict):
            raise IntegrationLockError(
                "wheelhouse.lock.json does not declare first_party_wheel"
            )
        expected_wheel_filename = first_party["path"].rsplit("/", 1)[-1]
        if first_party_record.get("file") != expected_wheel_filename:
            raise IntegrationLockError(
                "wheelhouse.first_party.path drifts from wheelhouse.lock.json"
            )
        if first_party_record.get("sha256") != first_party["sha256"]:
            raise IntegrationLockError(
                "wheelhouse.first_party.sha256 drifts from wheelhouse.lock.json"
            )

    # ----- schemas files + derived aggregate ---------------------------------
    schemas = identity.get("schemas")
    if not isinstance(schemas, dict):
        raise IntegrationLockError("build identity schemas is malformed")
    _verify_aggregate_sha256(
        stage_root,
        schemas.get("files"),
        schemas.get("aggregate_sha256"),
        label="build identity schemas",
        staged_payloads=staged_payloads,
    )

    # ----- evidence files (5 surfaces; pre_vendor+legal are single JSON, the
    # three native surfaces are bundles of 5 digestPaths that pin the
    # authoritative command, sanitizer verdict, test-suite digest, and
    # status for that surface) --------------------------------------------
    evidence = identity.get("evidence")
    if not isinstance(evidence, dict):
        raise IntegrationLockError("build identity evidence is malformed")
    simple_evidence_paths: dict[str, str] = {
        "pre_vendor": EVIDENCE_PATH_PRE_VENDOR,
        "legal": EVIDENCE_PATH_LEGAL,
    }
    declared_evidence_paths: dict[str, str] = {}
    for field, expected_path in simple_evidence_paths.items():
        entry = evidence.get(field)
        if entry is None:
            raise IntegrationLockError(f"build identity evidence.{field} is missing")
        _verify_digest_path(
            stage_root,
            entry,
            label=f"build identity evidence.{field}",
            staged_payloads=staged_payloads,
        )
        if entry["path"] != expected_path:
            raise IntegrationLockError(
                f"build identity evidence.{field}.path must be {expected_path}"
            )
        _verify_evidence_pass(
            stage_root, entry["path"], label=f"build identity evidence.{field}"
        )
        declared_evidence_paths[field] = entry["path"]

    for field in NATIVE_SURFACES:
        native_bundle = evidence.get(field)
        if not isinstance(native_bundle, dict):
            raise IntegrationLockError(
                f"build identity evidence.{field} must be a nativeEvidence "
                "object with 5 digestPath sub-fields"
            )
        expected_kinds = (
            NATIVE_VERDICT_KIND,
            *NATIVE_EVIDENCE_KINDS,
        )
        for kind in expected_kinds:
            sub_entry = native_bundle.get(kind)
            if not isinstance(sub_entry, dict):
                raise IntegrationLockError(
                    f"build identity evidence.{field}.{kind} must be a digestPath"
                )
            expected_path = native_evidence_path(field, kind)
            _verify_digest_path(
                stage_root,
                sub_entry,
                label=(f"build identity evidence.{field}.{kind}"),
                staged_payloads=staged_payloads,
            )
            if sub_entry["path"] != expected_path:
                raise IntegrationLockError(
                    f"build identity evidence.{field}.{kind}.path must be "
                    f"{expected_path}"
                )
        # The bundle-level verdict surface is the same NetworkVerdict
        # contract the per-surface verdict.json was bound to; the other
        # four files are validated by the shared contract helper.
        _verify_evidence_pass(
            stage_root,
            native_evidence_path(field, NATIVE_VERDICT_KIND),
            label=f"build identity evidence.{field}.{NATIVE_VERDICT_KIND}",
        )
        # Each native surface has its own authoritative surface-identity
        # bundle (command, sanitizer verdict, test-suite sha, status).
        _verify_native_surface_bundle(
            stage_root,
            surface=field,
            label=f"build identity evidence.{field}",
        )
        declared_evidence_paths[field] = native_evidence_path(
            field, NATIVE_VERDICT_KIND
        )
    if set(declared_evidence_paths) != (
        set(simple_evidence_paths) | set(NATIVE_SURFACES)
    ):
        raise IntegrationLockError(
            "build identity evidence block is missing a phase-01 surface"
        )

    projection_payload = {key: identity[key] for key in BUILD_IDENTITY_PROJECTION_KEYS}
    projection_sha256 = hashlib.sha256(
        canonical_json_bytes(projection_payload)
    ).hexdigest()
    return (
        BuildIdentityBinding(
            path=AUDIT_BUILD_IDENTITY_RELATIVE,
            projection_algorithm=BUILD_IDENTITY_PROJECTION_ALGORITHM,
            projection_sha256=projection_sha256,
        ),
        identity,
    )


def observe_build_identity_binding(
    stage_root: Path,
    source_manifest: Mapping[str, object],
    *,
    staged_payloads: frozenset[str] | None = None,
) -> BuildIdentityBinding:
    """Bind all build-identity metadata except cycle-forming staged_payloads.

    When ``staged_payloads`` is supplied, every ``digestPath`` must point at a
    file in that closed set so the staged payload manifest remains the sole
    authoritative source of live claims.
    """

    try:
        binding, _ = _load_build_identity_binding(
            stage_root,
            source_manifest,
            staged_payloads=staged_payloads,
        )
    except IntegrationLockError as error:
        raise IntegrationLockError(
            f"build identity validation failed: {error}"
        ) from error
    return binding


def _referenced_host_canary_paths(
    stage_root: Path, host_canary_evidence: Path
) -> frozenset[str]:
    """Return the closed set of stage-excluded files reachable from the canary."""

    stage_root = _safe_root(stage_root, label="stage")
    if host_canary_evidence.is_symlink() or not host_canary_evidence.is_file():
        raise IntegrationLockError("Codex host canary must be a direct regular file")
    resolved_canary = host_canary_evidence.resolve()
    if not resolved_canary.is_relative_to(stage_root):
        return frozenset()
    evidence_root = _safe_root(resolved_canary.parent, label="Codex host evidence")
    try:
        canary_raw = resolved_canary.read_bytes()
        canary = CodexHostCanaryEvidence.model_validate_json(canary_raw, strict=True)
    except (OSError, UnicodeError, ValueError, ValidationError) as error:
        raise IntegrationLockError(f"Codex host canary is invalid: {error}") from error
    if canary_raw != canonical_json_bytes(canary.model_dump(mode="json")):
        raise IntegrationLockError("Codex host canary bytes are not canonical JSON")

    referenced: set[str] = set()
    excluded_prefix = "supply-chain/host-canary/"
    excluded_single = "supply-chain/host-canary.json"

    def record(path: Path) -> None:
        relative = path.relative_to(stage_root).as_posix()
        if relative == excluded_single or relative.startswith(excluded_prefix):
            referenced.add(relative)

    def record_binding(binding: FileBinding) -> Path:
        path = _bound_file(evidence_root, binding)
        if not path.is_relative_to(stage_root):
            raise IntegrationLockError(
                "staged Codex host evidence escapes the plugin stage"
            )
        record(path)
        return path

    record(resolved_canary)
    bundle_path = record_binding(canary.evidence_bundle)
    bundle = _load_canonical_bound_model(
        evidence_root,
        canary.evidence_bundle,
        CodexHostEvidenceBundle,
        label="Codex host evidence bundle",
    )
    if bundle_path != _bound_file(evidence_root, canary.evidence_bundle):
        raise IntegrationLockError("Codex host evidence bundle path drift")
    for receipt in canary.fresh_home_receipts:
        record_binding(receipt)
    for receipt in bundle.fresh_home_receipts:
        record_binding(receipt)
    for classification in bundle.hook_status_classifications:
        record_binding(classification.evidence)
        parity = _load_canonical_bound_model(
            evidence_root,
            classification.evidence,
            HookParityEvidenceRecord,
            label=f"hook parity evidence {classification.hook_state}",
        )
        if parity.official_hook_receipt is not None:
            record_binding(parity.official_hook_receipt)
    return frozenset(referenced)


def validate_live_audit_manifests(
    stage_root: Path,
    expected_build_identity: BuildIdentityBinding | None = None,
    host_canary_evidence: Path | None = None,
) -> None:
    """Fail-closed gate over the live stage-inventory and build-identity manifests.

    The audit manifests are cycle-forming final metadata and therefore absent
    from the staged content tree; this gate recomputes every reported set and
    digest from the live ``stage_root`` bytes.  ``build_integration_lock`` does
    not call this gate because the stage may be inspected before the audit
    manifests exist; the gate runs in :func:`verify_integration_lock` after
    the rebuilt lock bytes equal the supplied lock, before PASS is returned.
    """

    stage_root = _safe_root(stage_root, label="stage")
    actual: set[str] = set()
    for path in stage_root.rglob("*"):
        if path.is_symlink():
            relative = path.relative_to(stage_root).as_posix()
            raise IntegrationLockError(
                f"audit manifest gate rejects symlink: {relative}"
            )
        if path.is_file():
            actual.add(path.relative_to(stage_root).as_posix())
        elif not path.is_dir():
            relative = path.relative_to(stage_root).as_posix()
            raise IntegrationLockError(
                f"audit manifest gate rejects non-file entry: {relative}"
            )
    if not actual:
        raise IntegrationLockError("audit manifest gate requires a non-empty stage")
    excluded_canary_paths = {
        relative
        for relative in actual
        if relative == "supply-chain/host-canary.json"
        or relative.startswith("supply-chain/host-canary/")
    }
    referenced_canary_paths = (
        _referenced_host_canary_paths(stage_root, host_canary_evidence)
        if host_canary_evidence is not None
        else frozenset()
    )
    if excluded_canary_paths != referenced_canary_paths:
        unreferenced = sorted(excluded_canary_paths - referenced_canary_paths)
        missing = sorted(referenced_canary_paths - excluded_canary_paths)
        raise IntegrationLockError(
            "Codex host canary evidence set is not closed: "
            f"unreferenced={unreferenced}; missing={missing}"
        )
    for relative in actual:
        if _AUDIT_PRIVATE_PATH_RE.search(relative):
            raise IntegrationLockError(
                f"audit manifest gate rejects private path class: {relative}"
            )
    if AUDIT_STAGE_INVENTORY_RELATIVE not in actual:
        raise IntegrationLockError(
            "audit manifest gate requires stage inventory at "
            f"{AUDIT_STAGE_INVENTORY_RELATIVE}"
        )
    if AUDIT_BUILD_IDENTITY_RELATIVE not in actual:
        raise IntegrationLockError(
            "audit manifest gate requires build identity at "
            f"{AUDIT_BUILD_IDENTITY_RELATIVE}"
        )

    source_manifest = _read_object(
        _regular_file_under(stage_root, "vendor/source-manifest.json"),
        label="source manifest",
    )

    # The staged_payloads list defines the closed set of files that every
    # ``digestPath`` claim must point at; resolve it first so the live
    # recompute of every digestPath/aggregate can require staged_payloads
    # membership as part of its verification.
    identity_for_payloads = _read_pretty_sorted_json(
        stage_root, AUDIT_BUILD_IDENTITY_RELATIVE, label="build identity"
    )
    raw_staged_payloads = (
        identity_for_payloads.get("staged_payloads")
        if isinstance(identity_for_payloads, dict)
        else None
    )
    declared_payload_paths: set[str] = set()
    if isinstance(raw_staged_payloads, list):
        for entry in raw_staged_payloads:
            if isinstance(entry, dict) and isinstance(entry.get("path"), str):
                declared_payload_paths.add(entry["path"])

    observed_build_identity, identity = _load_build_identity_binding(
        stage_root,
        source_manifest,
        staged_payloads=frozenset(declared_payload_paths),
    )
    if (
        expected_build_identity is not None
        and observed_build_identity != expected_build_identity
    ):
        raise IntegrationLockError(
            "build identity metadata projection differs from the integration lock"
        )

    inventory = _read_pretty_sorted_json(
        stage_root, AUDIT_STAGE_INVENTORY_RELATIVE, label="stage inventory"
    )
    if not isinstance(inventory, dict):
        raise IntegrationLockError("stage inventory must be a JSON object")
    if set(inventory) != AUDIT_STAGE_INVENTORY_REQUIRED_KEYS:
        raise IntegrationLockError(
            "stage inventory keys do not match the qualified contract: "
            f"{sorted(set(inventory) - AUDIT_STAGE_INVENTORY_REQUIRED_KEYS)}"
        )
    schema_version = inventory.get("schema_version")
    files_field = inventory.get("files")
    symlinks_field = inventory.get("symlinks")
    covered_field = inventory.get("covered_files")
    if schema_version != "1.0.0":
        raise IntegrationLockError(
            "stage inventory schema_version is not the qualified 1.0.0"
        )
    valid_files = (
        cast(list[str], files_field)
        if isinstance(files_field, list)
        and all(isinstance(item, str) for item in files_field)
        else None
    )
    reported_files = set(valid_files or ())
    if valid_files is None or valid_files != sorted(actual):
        missing = sorted(actual - reported_files)
        extra = sorted(reported_files - actual)
        raise IntegrationLockError(
            f"stage inventory files set drift: missing={missing}; extra={extra}"
        )
    if symlinks_field != []:
        raise IntegrationLockError("stage inventory symlinks must be an empty list")
    if not isinstance(covered_field, list) or not all(
        isinstance(item, dict) for item in covered_field
    ):
        raise IntegrationLockError("stage inventory covered_files must be a list")
    covered_required = {"inventory_source", "path", "sha256"}
    covered_by_path: dict[str, dict[str, object]] = {}
    for entry in covered_field:
        if set(entry) != covered_required:
            raise IntegrationLockError(
                "stage inventory covered_files entry has unexpected keys"
            )
        path = entry.get("path")
        digest = entry.get("sha256")
        source = entry.get("inventory_source")
        if (
            not isinstance(path, str)
            or not isinstance(digest, str)
            or not isinstance(source, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise IntegrationLockError(
                "stage inventory covered_files entry is malformed"
            )
        if path in covered_by_path:
            raise IntegrationLockError(
                f"stage inventory covered_files duplicates path: {path}"
            )
        covered_by_path[path] = {
            "path": path,
            "sha256": digest,
            "inventory_source": source,
        }
    expected_covered = actual - {AUDIT_STAGE_INVENTORY_RELATIVE}
    if set(covered_by_path) != expected_covered:
        missing = sorted(expected_covered - set(covered_by_path))
        extra = sorted(set(covered_by_path) - expected_covered)
        raise IntegrationLockError(
            f"stage inventory covered_files coverage drift: "
            f"missing={missing}; extra={extra}"
        )
    if [entry["path"] for entry in covered_field] != sorted(expected_covered):
        raise IntegrationLockError(
            "stage inventory covered_files order is not canonical"
        )
    for relative, record in covered_by_path.items():
        actual_digest = _digest(stage_root / relative)
        if actual_digest != record["sha256"]:
            raise IntegrationLockError(
                f"stage inventory coverage digest mismatch: {relative}"
            )
        expected_source = _audit_inventory_source(relative)
        if record["inventory_source"] != expected_source:
            raise IntegrationLockError(
                f"stage inventory coverage source drift: {relative} "
                f"reported={record['inventory_source']} computed={expected_source}"
            )

    staged_payloads = identity.get("staged_payloads")
    if not isinstance(staged_payloads, list) or not all(
        isinstance(item, dict) for item in staged_payloads
    ):
        raise IntegrationLockError("build identity staged_payloads must be a list")
    payloads_by_path: dict[str, str] = {}
    for entry in staged_payloads:
        if set(entry) != {"path", "sha256"}:
            raise IntegrationLockError(
                "build identity staged_payloads entry has unexpected keys"
            )
        path = entry.get("path")
        digest = entry.get("sha256")
        if (
            not isinstance(path, str)
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise IntegrationLockError(
                "build identity staged_payloads entry is malformed"
            )
        if path in payloads_by_path:
            raise IntegrationLockError(
                f"build identity staged_payloads duplicates path: {path}"
            )
        payloads_by_path[path] = digest
    expected_payloads = actual - {
        AUDIT_BUILD_IDENTITY_RELATIVE,
        AUDIT_STAGE_INVENTORY_RELATIVE,
    }
    if set(payloads_by_path) != expected_payloads:
        missing = sorted(expected_payloads - set(payloads_by_path))
        extra = sorted(set(payloads_by_path) - expected_payloads)
        raise IntegrationLockError(
            f"build identity staged_payloads coverage drift: "
            f"missing={missing}; extra={extra}"
        )
    for relative, declared in payloads_by_path.items():
        actual_digest = _digest(stage_root / relative)
        if actual_digest != declared:
            raise IntegrationLockError(
                f"build identity staged_payload digest mismatch: {relative}"
            )


def verify_integration_lock(
    lock: IntegrationLock,
    *,
    stage_root: Path,
    codex_launcher: Path,
    codex_native_binary: Path,
    host_canary_evidence: Path,
) -> IntegrationVerification:
    """Rebuild the lock from live bytes and fail on any missing or drifted field."""

    observed = build_integration_lock(
        stage_root=stage_root,
        codex_launcher=codex_launcher,
        codex_native_binary=codex_native_binary,
        host_canary_evidence=host_canary_evidence,
    )
    if integration_lock_bytes(observed) != integration_lock_bytes(lock):
        raise IntegrationLockError("live integration identity differs from the lock")
    validate_live_audit_manifests(stage_root, lock.build_identity, host_canary_evidence)
    lock_bytes = integration_lock_bytes(lock)
    return IntegrationVerification(
        schema_version="arw.integration-verification.v1",
        integration_lock_sha256=hashlib.sha256(lock_bytes).hexdigest(),
        codex_host_tuple_sha256=lock.codex_host.tuple_sha256,
        hook_definition_sha256=lock.hook.definition_sha256,
        ars_tree_sha256=lock.ars.adapter_tree_sha256,
        technical_qualification="PASS",
        release_qualification="BLOCKED",
    )


def load_and_verify_integration_lock(
    path: Path,
    *,
    stage_root: Path,
    codex_launcher: Path,
    codex_native_binary: Path,
    host_canary_evidence: Path,
) -> IntegrationVerification:
    return verify_integration_lock(
        load_integration_lock(path),
        stage_root=stage_root,
        codex_launcher=codex_launcher,
        codex_native_binary=codex_native_binary,
        host_canary_evidence=host_canary_evidence,
    )


def _diagnostic_digest(value: BaseModel) -> str:
    return hashlib.sha256(
        canonical_json_bytes(value.model_dump(mode="json"))
    ).hexdigest()


def _passed_diagnostic_layer(
    name: DiagnosticLayerName,
    *,
    expected_sha256: str | None = None,
    observed_sha256: str | None = None,
) -> IntegrationDiagnosticLayer:
    return IntegrationDiagnosticLayer(
        name=name,
        status="PASS",
        reason_code=None,
        detail=None,
        expected_sha256=expected_sha256,
        observed_sha256=observed_sha256,
    )


def _blocked_diagnostic_report(
    layers: list[IntegrationDiagnosticLayer],
    *,
    name: DiagnosticLayerName,
    reason_code: DiagnosticReasonCode,
    detail: DiagnosticDetail,
    expected_sha256: str | None = None,
    observed_sha256: str | None = None,
) -> IntegrationDiagnosticReport:
    layers.append(
        IntegrationDiagnosticLayer(
            name=name,
            status="BLOCKED",
            reason_code=reason_code,
            detail=detail,
            expected_sha256=expected_sha256,
            observed_sha256=observed_sha256,
        )
    )
    layers.extend(
        IntegrationDiagnosticLayer(
            name=remaining,
            status="NOT_EVALUATED",
            reason_code=None,
            detail=None,
            expected_sha256=None,
            observed_sha256=None,
        )
        for remaining in DIAGNOSTIC_LAYER_ORDER[len(layers) :]
    )
    return IntegrationDiagnosticReport(
        schema_version="arw.integration-diagnostic.v1",
        status="BLOCKED",
        technical_qualification="BLOCKED",
        release_qualification="BLOCKED",
        experiment_execution="disabled",
        integration_lock_sha256=None,
        reason_codes=(reason_code,),
        layers=tuple(layers),
    )


def diagnose_integration_lock(
    path: Path | None,
    *,
    stage_root: Path | None,
    codex_launcher: Path | None,
    codex_native_binary: Path | None,
    host_canary_evidence: Path | None,
) -> IntegrationDiagnosticReport:
    """Explain exact integration verification without gaining admission authority.

    Every layer is a bounded observation of the same validators used by
    :func:`load_and_verify_integration_lock`.  Only that complete final call can
    produce technical PASS; partial observations never create an
    :class:`IntegrationVerification` or mutate parent-owned state.
    """

    layers: list[IntegrationDiagnosticLayer] = []
    regular_file_inputs = (path, codex_native_binary, host_canary_evidence)
    if (
        stage_root is None
        or stage_root.is_symlink()
        or not stage_root.is_dir()
        or codex_launcher is None
        or not codex_launcher.is_file()
        or any(
            item is None or item.is_symlink() or not item.is_file()
            for item in regular_file_inputs
        )
    ):
        return _blocked_diagnostic_report(
            layers,
            name="inputs",
            reason_code="integration_inputs_incomplete",
            detail="required integration inputs are absent or unsafe",
        )
    layers.append(_passed_diagnostic_layer("inputs"))
    path = cast(Path, path)
    codex_launcher = cast(Path, codex_launcher)
    codex_native_binary = cast(Path, codex_native_binary)
    host_canary_evidence = cast(Path, host_canary_evidence)

    try:
        raw_lock = path.read_bytes()
        lock = IntegrationLock.model_validate_json(raw_lock, strict=True)
    except (OSError, UnicodeError, ValueError, ValidationError):
        return _blocked_diagnostic_report(
            layers,
            name="lock_document",
            reason_code="lock_document_invalid",
            detail="integration lock is invalid strict JSON",
        )
    observed_lock_sha256 = hashlib.sha256(raw_lock).hexdigest()
    expected_lock_bytes = integration_lock_bytes(lock)
    expected_lock_sha256 = hashlib.sha256(expected_lock_bytes).hexdigest()
    if raw_lock != expected_lock_bytes:
        return _blocked_diagnostic_report(
            layers,
            name="lock_document",
            reason_code="lock_document_noncanonical",
            detail="integration lock bytes are not canonical JSON",
            expected_sha256=expected_lock_sha256,
            observed_sha256=observed_lock_sha256,
        )
    layers.append(
        _passed_diagnostic_layer(
            "lock_document",
            expected_sha256=expected_lock_sha256,
            observed_sha256=observed_lock_sha256,
        )
    )

    expected_arw = _diagnostic_digest(lock.arw_runtime)
    try:
        observed_arw_model = _validate_arw_runtime(stage_root)
        observed_arw = _diagnostic_digest(observed_arw_model)
        if observed_arw_model != lock.arw_runtime:
            raise IntegrationLockError("staged ARW differs")
    except (IntegrationLockError, OSError, ValueError):
        return _blocked_diagnostic_report(
            layers,
            name="staged_arw",
            reason_code="staged_arw_drift",
            detail="staged ARW runtime differs from the lock",
            expected_sha256=expected_arw,
            observed_sha256=locals().get("observed_arw"),
        )
    layers.append(
        _passed_diagnostic_layer(
            "staged_arw",
            expected_sha256=expected_arw,
            observed_sha256=observed_arw,
        )
    )

    expected_ars = _diagnostic_digest(lock.ars)
    try:
        source_manifest = _read_object(
            _regular_file_under(stage_root, "vendor/source-manifest.json"),
            label="source manifest",
        )
        observed_ars_model = _validate_bundled_ars(stage_root, source_manifest)
        observed_ars = _diagnostic_digest(observed_ars_model)
        if observed_ars_model != lock.ars:
            raise IntegrationLockError("bundled ARS differs")
    except (IntegrationLockError, OSError, ValueError):
        return _blocked_diagnostic_report(
            layers,
            name="ars_bundle",
            reason_code="ars_bundle_drift",
            detail="bundled ARS bytes differ from the lock",
            expected_sha256=expected_ars,
            observed_sha256=locals().get("observed_ars"),
        )
    layers.append(
        _passed_diagnostic_layer(
            "ars_bundle",
            expected_sha256=expected_ars,
            observed_sha256=observed_ars,
        )
    )

    expected_file_base = _diagnostic_digest(lock.file_base)
    try:
        observed_file_base_model = _validate_file_base(stage_root, source_manifest)
        observed_file_base = _diagnostic_digest(observed_file_base_model)
        if observed_file_base_model != lock.file_base:
            raise IntegrationLockError("file-base differs")
    except (IntegrationLockError, OSError, ValueError):
        return _blocked_diagnostic_report(
            layers,
            name="file_base",
            reason_code="file_base_drift",
            detail="file-base bytes or patch evidence differ from the lock",
            expected_sha256=expected_file_base,
            observed_sha256=locals().get("observed_file_base"),
        )
    layers.append(
        _passed_diagnostic_layer(
            "file_base",
            expected_sha256=expected_file_base,
            observed_sha256=observed_file_base,
        )
    )

    expected_host = _diagnostic_digest(lock.codex_host)
    try:
        observed_host_model = observe_codex_host(codex_launcher, codex_native_binary)
        if not is_supported_codex_cli_version(observed_host_model.cli_version):
            raise IntegrationLockError("unsupported Codex host")
        observed_host = _diagnostic_digest(observed_host_model)
        if observed_host_model != lock.codex_host:
            raise IntegrationLockError("Codex host differs")
    except (IntegrationLockError, OSError, ValueError):
        return _blocked_diagnostic_report(
            layers,
            name="codex_host",
            reason_code="codex_host_drift",
            detail="Codex host tuple differs from the lock",
            expected_sha256=expected_host,
            observed_sha256=locals().get("observed_host"),
        )
    layers.append(
        _passed_diagnostic_layer(
            "codex_host",
            expected_sha256=expected_host,
            observed_sha256=observed_host,
        )
    )

    try:
        observed_config, observed_handler, observed_definition = (
            observe_hook_definition(stage_root)
        )
        if (
            observed_config != lock.hook.config
            or observed_handler != lock.hook.handler
            or observed_definition != lock.hook.definition_sha256
        ):
            raise IntegrationLockError("root hook definition differs")
    except (IntegrationLockError, OSError, ValueError):
        return _blocked_diagnostic_report(
            layers,
            name="hook_definition",
            reason_code="hook_definition_drift",
            detail="root hook definition differs from the lock",
            expected_sha256=lock.hook.definition_sha256,
            observed_sha256=locals().get("observed_definition"),
        )
    layers.append(
        _passed_diagnostic_layer(
            "hook_definition",
            expected_sha256=lock.hook.definition_sha256,
            observed_sha256=observed_definition,
        )
    )

    expected_hook = _diagnostic_digest(lock.hook)
    try:
        observed_hook_model = _validate_hook(
            stage_root,
            host_canary_evidence,
            observed_host_model,
            observed_arw_model,
        )
        observed_hook = _diagnostic_digest(observed_hook_model)
        if observed_hook_model != lock.hook:
            raise IntegrationLockError("hook evidence differs")
    except (IntegrationLockError, OSError, ValueError):
        return _blocked_diagnostic_report(
            layers,
            name="hook_execution_evidence",
            reason_code="hook_execution_evidence_drift",
            detail="retained hook evidence differs from the lock",
            expected_sha256=expected_hook,
            observed_sha256=locals().get("observed_hook"),
        )
    layers.append(
        _passed_diagnostic_layer(
            "hook_execution_evidence",
            expected_sha256=expected_hook,
            observed_sha256=observed_hook,
        )
    )

    expected_legal = _diagnostic_digest(lock.license)
    try:
        observed_legal_model = _validate_license(stage_root)
        observed_legal = _diagnostic_digest(observed_legal_model)
        if observed_legal_model != lock.license:
            raise IntegrationLockError("legal state differs")
    except (IntegrationLockError, OSError, ValueError):
        return _blocked_diagnostic_report(
            layers,
            name="legal_state",
            reason_code="legal_state_drift",
            detail="legal policy differs from the qualified blocked state",
            expected_sha256=expected_legal,
            observed_sha256=locals().get("observed_legal"),
        )
    layers.append(
        _passed_diagnostic_layer(
            "legal_state",
            expected_sha256=expected_legal,
            observed_sha256=observed_legal,
        )
    )

    try:
        verification = load_and_verify_integration_lock(
            path,
            stage_root=stage_root,
            codex_launcher=codex_launcher,
            codex_native_binary=codex_native_binary,
            host_canary_evidence=host_canary_evidence,
        )
    except (IntegrationLockError, OSError, ValueError):
        return _blocked_diagnostic_report(
            layers,
            name="exact_lock",
            reason_code="exact_lock_drift",
            detail="complete exact integration verification failed",
            expected_sha256=expected_lock_sha256,
        )
    layers.append(
        _passed_diagnostic_layer(
            "exact_lock",
            expected_sha256=verification.integration_lock_sha256,
            observed_sha256=verification.integration_lock_sha256,
        )
    )
    return IntegrationDiagnosticReport(
        schema_version="arw.integration-diagnostic.v1",
        status="PASS",
        technical_qualification="PASS",
        release_qualification="BLOCKED",
        experiment_execution="disabled",
        integration_lock_sha256=verification.integration_lock_sha256,
        reason_codes=(),
        layers=tuple(layers),
    )


def integration_diagnostic_schema_document() -> dict[str, object]:
    document = IntegrationDiagnosticReport.model_json_schema(mode="validation")
    document["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    document["title"] = "ARW Integration Diagnostic"
    return document


def integration_lock_schema_document() -> dict[str, object]:
    document = IntegrationLock.model_json_schema(mode="validation")
    document["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    document["$id"] = (
        "https://academic-research-workbench.local/"
        "schemas/v1/integration-lock.schema.json"
    )
    document["title"] = "ARW Integration Lock"
    return document


__all__ = (
    "CODEX_CLI_VERSION_REQUIREMENT",
    "EXPECTED_CODEX_CREDENTIAL_POLICY",
    "EXPECTED_CODEX_CREDENTIAL_POLICY_SHA256",
    "MINIMUM_CODEX_CLI_VERSION",
    "STAGE_IDENTITY_EXCLUDED_PATHS",
    "ARSBinding",
    "BuildIdentityBinding",
    "CodexCredentialPolicy",
    "CodexHostBinding",
    "CodexHostCanaryEvidence",
    "CodexHostEvidenceBundle",
    "ControlledResultChannelProof",
    "FileBinding",
    "FreshHomeReceipt",
    "HookParityEvidenceRecord",
    "HookStatusClassification",
    "IntegrationDiagnosticLayer",
    "IntegrationDiagnosticReport",
    "IntegrationLock",
    "IntegrationLockError",
    "IntegrationVerification",
    "IsolationProof",
    "LegalVerdict",
    "NetworkVerdict",
    "PreVendorReceipt",
    "UseDistributionPolicyProjection",
    "build_integration_lock",
    "diagnose_integration_lock",
    "discover_codex_native_binary",
    "integration_diagnostic_schema_document",
    "integration_lock_bytes",
    "integration_lock_schema_document",
    "is_supported_codex_cli_version",
    "load_and_verify_integration_lock",
    "load_integration_lock",
    "native_evidence_path",
    "observe_build_identity_binding",
    "observe_codex_host",
    "observe_hook_definition",
    "observe_stage_identity",
    "observe_staged_python_version",
    "parse_file_contract_contract_sha256",
    "validate_live_audit_manifests",
    "verify_integration_lock",
    "write_integration_lock",
)
