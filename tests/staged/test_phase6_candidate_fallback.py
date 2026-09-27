"""A stale lock diagnostic cannot replace the accepted Phase 6 stage."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_unlocked_diagnostic_uses_separate_stage_and_evidence(tmp_path, monkeypatch) -> None:
    namespace = runpy.run_path(str(ROOT / "scripts/verify-phase-6"))
    main = namespace["main"]
    verification_error = namespace["VerificationError"]
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    candidate = tmp_path / "candidate"
    (candidate / "supply-chain").mkdir(parents=True)
    (candidate / "supply-chain/license-verdict.json").write_text(
        json.dumps({"technical_qualification": "PASS", "release_qualification": "BLOCKED"}),
        encoding="utf-8",
    )
    lock = tmp_path / "integration-lock.json"
    lock.write_text("{}\n", encoding="utf-8")
    calls: list[tuple[str, list[str]]] = []

    def command(_root: Path, name: str, argv: list[str], **_kwargs: object) -> None:
        calls.append((name, argv))
        if name == "stage-build":
            raise verification_error("stale lock")

    monkeypatch.setenv("ARW_CANDIDATE_EVIDENCE_ROOT", str(candidate))
    monkeypatch.setattr("sys.argv", ["verify-phase-6", "--evidence-root", str(evidence)])
    main.__globals__.update({
        "owned_root": lambda *_args, **_kwargs: evidence,
        "observed_identities": lambda _root: {"integration_lock": {"path": str(lock)}},
        "candidate_stage_args": list,
        "command": command,
        "compare_lock_to_stage": lambda _lock, _stage: {"mismatches": ["stale lock"]},
    })
    assert main() == 70
    diagnostic = next(argv for name, argv in calls if name == "stage-build-unlocked-diagnostic")
    accepted = next(argv for name, argv in calls if name == "stage-build")
    assert diagnostic[diagnostic.index("--stage-root") + 1] != accepted[accepted.index("--stage-root") + 1]
    assert diagnostic[diagnostic.index("--evidence-root") + 1] != accepted[accepted.index("--evidence-root") + 1]
    assert "--clean" not in diagnostic
