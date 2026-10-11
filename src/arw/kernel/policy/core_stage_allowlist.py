"""Positive path inventory for a complete staged ARW plugin.

Kept in sync with the stage builder. The bundled ARS file names are pinned
separately because that tree is copied dynamically.
"""

from __future__ import annotations

# The staged adapter digest covers names and bytes, including dynamic tree
# entries copied by stage-plugin.
ARS_STAGE_TREE_SHA256 = "83ea255519f97609dc4cb1b370f5a463a7da93a413f3911f5eb94f2e8be3f13a"

STATIC_STAGE_PATHS = frozenset({
    'schemas/v1/core-route.schema.json',
    '.codex-plugin/plugin.json',
    '.file-base/build-evidence.json',
    '.mcp.json',
    'LICENSES/academic-research-skills-CC-BY-NC-4.0.txt',
    'LICENSES/experiment-agent-CC-BY-NC-4.0.txt',
    'LICENSES/file-base-MIT.txt',
    'MODIFICATIONS.md',
    'SBOM.cdx.json',
    'THIRD_PARTY_NOTICES.md',
    'bin/arw',
    'docs/runtime/durable-provenance.md',
    'docs/runtime/execution-provenance-recording.md',
    'docs/runtime/files-first-data-plane.md',
    'docs/runtime/plugin-first-routing.md',
    'docs/runtime/research-graph.md',
    'docs/runtime/scientific-integrity.md',
    'docs/runtime/submission-workflow.md',
    'extensions/file-base-mcp/bin/provider',
    'hooks/arw_hook.py',
    'hooks/hooks.json',
    'libexec/file-base-mcp',
    'pyproject.toml',
    'schemas/v1/assignment.schema.json',
    'schemas/v1/audit-dossier.schema.json',
    'schemas/v1/build-identity.schema.json',
    'schemas/v1/evidence-access-decision.schema.json',
    'schemas/v1/experiment-provenance.schema.json',
    'schemas/v1/gate-decision.schema.json',
    'schemas/v1/hook-observation.schema.json',
    'schemas/v1/host-identity-receipt.schema.json',
    'schemas/v1/host-qualification.schema.json',
    'schemas/v1/human-authority.schema.json',
    'schemas/v1/integration-lock.schema.json',
    'schemas/v1/release-authority.schema.json',
    'schemas/v1/integrity-receipt.schema.json',
    'schemas/v1/lifecycle-evidence.schema.json',
    'schemas/v1/mcp-read-request.schema.json',
    'schemas/v1/mcp-read-result.schema.json',
    'schemas/v1/panel-manifest.schema.json',
    'schemas/v1/phase4-evaluation-verdict.schema.json',
    'schemas/v1/research-integrity-contracts.schema.json',
    'schemas/v1/review-finding-matrix.schema.json',
    'schemas/v1/role-catalog.schema.json',
    'schemas/v1/route-result.schema.json',
    'schemas/v1/source-manifest.schema.json',
    'schemas/v1/version-report.schema.json',
    'schemas/v1/worker-proposal.schema.json',
    'scripts/file-base-graph-mcp',
    'scripts/file-base-mcp',
    'scripts/verify-phase-2',
    'scripts/verify-phase-6',
    'share/arw/build-identity.json',
    'share/arw/evidence/asan_ubsan.json',
    'share/arw/evidence/asan_ubsan_command.json',
    'share/arw/evidence/asan_ubsan_sanitizer_verdict.json',
    'share/arw/evidence/asan_ubsan_status.txt',
    'share/arw/evidence/asan_ubsan_test_suite_sha256.txt',
    'share/arw/evidence/candidate-build.json',
    'share/arw/evidence/legal.json',
    'share/arw/evidence/license-inventory.json',
    'share/arw/evidence/pre_vendor.json',
    'share/arw/evidence/tsan.json',
    'share/arw/evidence/tsan_command.json',
    'share/arw/evidence/tsan_sanitizer_verdict.json',
    'share/arw/evidence/tsan_status.txt',
    'share/arw/evidence/tsan_test_suite_sha256.txt',
    'share/arw/evidence/upstream.json',
    'share/arw/evidence/upstream_command.json',
    'share/arw/evidence/upstream_sanitizer_verdict.json',
    'share/arw/evidence/upstream_status.txt',
    'share/arw/evidence/upstream_test_suite_sha256.txt',
    'share/arw/file-contracts.h',
    'skills/academic-research-workbench/SKILL.md',
    'skills/academic-research-workbench/references/control-plane-capabilities.md',
    'skills/academic-research-workbench/references/database-lookup-advisory.md',
    'skills/academic-research-workbench/references/writing-revisions.md',
    'skills/submission/SKILL.md',
    'supply-chain/license-verdict.json',
    'supply-chain/semantica-qualification.json',
    'supply-chain/stage-inventory.json',
    'supply-chain/use-distribution.json',
    'tests/integration/test_phase2_durable_runtime.py',
    'vendor/mcp-manifest.json',
    'vendor/patches/file-base/0001-file-base-server-name.patch',
    'vendor/patches/file-base/0002-phase1-confined-read.patch',
    'vendor/patches/file-base/0003-phase3-generation-builder.patch',
    'vendor/patches/file-base/0004-phase5-research-graph.patch',
    'vendor/source-manifest.json',
})


def allowed_stage_path(relative: str, wheel_name: str) -> bool:
    if relative.startswith("share/arw/schemas/"):
        # Import only during verification to avoid the core/registry import cycle.
        from arw.kernel.policy.schema_registry import SCHEMA_NAMES

        return relative.removeprefix("share/arw/schemas/") in SCHEMA_NAMES
    if relative in STATIC_STAGE_PATHS:
        return True
    if relative == f"share/arw/wheels/{wheel_name}":
        return True
    if relative == "supply-chain/integration-lock.json":
        return True
    # The ARS tree has its own pinned source-tree check in core_integrity.
    if relative.startswith("skills/academic-research-suite/"):
        return True
    # Host canary bytes are adapter metadata; only this known namespace is
    # accepted and every file is still hashed by both audit manifests.
    return relative == "supply-chain/host-canary.json" or relative.startswith(
        "supply-chain/host-canary/"
    )
