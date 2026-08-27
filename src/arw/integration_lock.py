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
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Self, TypeVar, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from arw.canonical import canonical_json_bytes, strict_json_loads
from arw.hook_contracts import CodexHookReceipt, HookParityMatrix

EXPECTED_ARS_ADAPTER_VERSION = "0.1.26"
MINIMUM_CODEX_CLI_VERSION = (0, 144, 4)
CODEX_CLI_VERSION_REQUIREMENT = ">=0.144.4"
_CODEX_CLI_STABLE_VERSION_RE = re.compile(
    r"^codex-cli (?P<major>[0-9]+)\.(?P<minor>[0-9]+)\.(?P<patch>[0-9]+)(?:\+[0-9A-Za-z.-]+)?$"
)
EXPECTED_CODEX_CLI_VERSION = "codex-cli 0.144.4"
EXPECTED_ARS_UPSTREAM_COMMIT = "8cc7f8f4cccda721646d9df590b42721c93cba31"
EXPECTED_EXPERIMENT_AGENT_COMMIT = "e291e7dc7ca268b2de7e1a9cf23bc2eef5dc0651"

EXPECTED_FILE_BASE_COMMIT = "ee68144af5453addda995a27cce8142999f318fb"
EXPECTED_UPSTREAM_URLS = {
    "academic-research-skills": "https://github.com/Imbad0202/academic-research-skills.git",
    "experiment-agent": "https://github.com/Imbad0202/experiment-agent.git",
}
EXPECTED_SOURCE_IDENTITIES = {
    "academic-research-skills": {
        "commit": EXPECTED_ARS_UPSTREAM_COMMIT,
        "git_tree": "43b7ad965778b363b3ba1cfe3d5f3884dd29b417",
        "source_tree_sha256": "a401bec5f0bda52d256ee1792cbea8cf63ce6cbe02eb363ed4b790212d0c853e",
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
    adapter_version: Literal["0.1.26"]
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
    """Cycle-free legal meaning derived from the mutable evidence declaration.

    Technical evidence hashes in ``use-distribution.json`` may include the
    final SBOM, so the lock deliberately binds only these exact legal facts.
    The final inventory and build identity remain responsible for binding the
    declaration's raw bytes.
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


class IntegrationLock(LockModel):
    schema_version: Literal["arw.integration-lock.v1"]
    dependency_model: Literal["bundled-pinned-adapter"]
    arw_runtime: ARWRuntimeBinding
    ars: ARSBinding
    file_base: FileBaseBinding
    codex_host: CodexHostBinding
    hook: HookBinding
    license: LicenseBinding
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
                    raise ValueError(
                        "blocked diagnostic reason cannot carry digests"
                    )
            elif self.expected_sha256 is None:
                raise ValueError("blocked drift layer requires an expected digest")
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
            adapter_version="0.1.26",
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
    if "arw/integration_lock.py" not in members:
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
    components = sbom.get("components")
    if not isinstance(components, list) or not all(
        isinstance(component, dict) for component in components
    ):
        raise IntegrationLockError("technical provenance SBOM components are malformed")
    lock_ref = "artifact:supply-chain/integration-lock.json"
    lock_components = [
        component for component in components if component.get("bom-ref") == lock_ref
    ]
    if len(lock_components) > 1:
        raise IntegrationLockError("technical provenance SBOM repeats the lock component")
    if not lock_components:
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
    use_distribution = _read_object(
        _regular_file_under(stage_root, use_path),
        label="use and distribution declaration",
    )
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
            raise IntegrationLockError(
                f"technical provenance digest mismatch: {path}"
            )
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
    return IntegrationLock(
        schema_version="arw.integration-lock.v1",
        dependency_model="bundled-pinned-adapter",
        arw_runtime=arw_runtime,
        ars=ars,
        file_base=file_base,
        codex_host=host,
        hook=hook,
        license=license_binding,
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
    "observe_codex_host",
    "observe_hook_definition",
    "observe_stage_identity",
    "verify_integration_lock",
    "write_integration_lock",
)
