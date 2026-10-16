"""Source adapter changes must retain the installed core's exact tree pin."""

from pathlib import Path

from arw.kernel.policy.core_stage_allowlist import ARS_STAGE_TREE_SHA256
from arw.kernel.policy.integration_lock import _tree_sha256


def test_bundled_source_adapter_matches_installed_core_pin():
    root = Path(__file__).resolve().parents[2] / "skills/academic-research-suite"
    assert _tree_sha256(root, ignore_runtime_caches=True) == ARS_STAGE_TREE_SHA256
