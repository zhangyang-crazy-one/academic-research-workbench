"""The clean CI notice must exist and match the pinned source manifest."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/verify-pinned-notice"
NOTICE = "build/evidence/phase-01/pre-vendor-license/generated/THIRD_PARTY_NOTICES.md"


def test_clean_package_boundary_restores_notice_before_source_verification() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    section = workflow.split("- name: Restore pinned legal receipt and materialize source snapshots", 1)[1]
    assert section.index("npm ci --ignore-scripts") < section.index("gen-third-party-notices.sh")
    assert section.index("gen-third-party-notices.sh") < section.index("scripts/verify-pinned-notice")
    assert section.index("scripts/verify-pinned-notice") < section.index("./scripts/verify-sources --inputs-only")


def test_missing_or_wrong_pinned_notice_is_rejected(tmp_path: Path) -> None:
    notice_bytes = b"Generated notice for an isolated test\n"
    manifest = {"declared_artifacts": [{
        "path": NOTICE,
        "class": "build-evidence",
        "sha256": hashlib.sha256(notice_bytes).hexdigest(),
    }]}
    target = tmp_path / "vendor/source-manifest.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(manifest), encoding="utf-8")
    command = [sys.executable, str(SCRIPT), "--project-root", str(tmp_path)]
    missing = subprocess.run(command, capture_output=True, text=True, check=False)
    assert missing.returncode != 0 and "missing" in missing.stderr
    notice = tmp_path / NOTICE
    notice.parent.mkdir(parents=True)
    notice.write_bytes(b"unrelated notice\n")
    wrong = subprocess.run(command, capture_output=True, text=True, check=False)
    assert wrong.returncode != 0 and "digest mismatch" in wrong.stderr
    notice.write_bytes(notice_bytes)
    valid = subprocess.run(command, capture_output=True, text=True, check=False)
    assert valid.returncode == 0, valid.stderr
