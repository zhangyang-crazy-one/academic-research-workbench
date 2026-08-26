"""Phase 7 installed-package and bundled ARS qualification probes.

The test deliberately executes the copied stage from a directory outside the
checkout. The modified local ARS adapter is copied into the installed package;
only bounded route evidence is retained in receipts.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from arw.audit_dossier import assemble_audit_dossier, replay_audit_dossier
from arw.canonical import canonical_json_bytes, sha256_hex
from arw.evidence_access import (
    EvidenceAccessDecision,
    LifecycleEvidenceRecord,
    evaluate_claim_capability,
)
from arw.faults import InjectedFault
from arw.integrity import IntegrityReceipt
from arw.experiment_provenance import QualificationReceipt
from arw.graph_models import GraphProjectionReceipt
from arw.integration_lock import (
    EXPECTED_ARS_ADAPTER_VERSION,
    _tree_sha256,
    discover_codex_native_binary,
    observe_hook_definition,
    observe_stage_identity,
)
from arw.journal import replay_run
from arw.models import LifecycleTransitionRequest
from arw.orchestration_models import (
    FORMAL_REVIEW_ROLE_IDS,
    GateDecision,
    HumanDecisionRecord,
    PanelManifest,
    PanelSeat,
    ReviewFinding,
    ReviewFindingMatrix,
    ReviewReport,
    ReviewSynthesis,
)

from .test_orchestration_lifecycle import _run as _init_run
from tests.qualification_support import discover_bundled_qualification


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_NAME = "academic-research-workbench"
def _retained_bundled_qualification() -> tuple[Path, Path, Path | None]:
    """Select only a lock/canary/stage tuple whose bytes are still bound.

    Discovery is content-addressed and host-verified (see
    ``tests.qualification_support``), so a Codex upgrade is handled by
    re-qualifying the host rather than hand-editing this candidate list.
    """

    discovered = discover_bundled_qualification()
    if discovered is not None:
        stage_root, lock_path, canary_path = discovered
        return lock_path, canary_path, stage_root
    return (
        REPOSITORY_ROOT / "build/evidence/phase-07-live-route-fix/integration-lock.json",
        REPOSITORY_ROOT / "build/evidence/phase-07-live-route-fix/canary.json",
        None,
    )


LOCK_PATH, CANARY_PATH, RETAINED_STAGE = _retained_bundled_qualification()
CODEX_LAUNCHER = Path(
    os.environ.get("ARW_CODEX_LAUNCHER") or shutil.which("codex") or "codex"
)
CODEX_NATIVE = Path(
    os.environ.get("ARW_CODEX_NATIVE_BINARY")
    or discover_codex_native_binary(CODEX_LAUNCHER)
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(command: list[str], *, cwd: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=180,
    )


def _publish_once(path: Path, payload: object) -> Path:
    encoded = canonical_json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == encoded:
            return path
        # Evidence is append-only.  A later plan may legitimately produce a
        # new stage/lock identity; retain the old receipt and publish the new
        # canonical bytes under a content-addressed sibling instead of
        # overwriting or failing the next qualification run.
        suffix = hashlib.sha256(encoded).hexdigest()[:16]
        path = path.with_name(f"{path.stem}-{suffix}{path.suffix}")
        if path.exists():
            assert path.read_bytes() == encoded, f"retained receipt drifted: {path}"
            return path
    path.write_bytes(encoded)
    return path


@pytest.fixture
def installed_stage(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    """Build one exact stage and copy it into a source-hidden marketplace."""

    outside = tmp_path / "outside-working-directory"
    outside.mkdir()
    stage = tmp_path / "stage" / PLUGIN_NAME
    stage_tmp = tmp_path / "stage-tmp"
    evidence = tmp_path / "stage-evidence"
    environment = {
        "HOME": str(tmp_path / "caller-home"),
        "CODEX_HOME": str(tmp_path / "caller-codex-home"),
        "PATH": os.environ.get("PATH", os.defpath),
        "PIP_NO_INDEX": "1",
        "PYTHONNOUSERSITE": "1",
        "UV_OFFLINE": "1",
        "TMPDIR": str(REPOSITORY_ROOT / "build/tmp/phase-07/ars-smoke"),
        "ARW_STAGE_TMP_ROOT": str(stage_tmp),
    }
    # Reuse the retained exact stage when it is available. Rebuilding a wheel
    # from a dirty checkout would produce a new runtime digest without a
    # matching host canary; that must remain a qualification failure rather
    # than silently weakening the lock. Clean environments still exercise the
    # normal stage-plugin path below.
    retained_stage = RETAINED_STAGE
    if (
        retained_stage is not None
        and retained_stage.is_dir()
        and (retained_stage / "skills/academic-research-suite/SKILL.md").is_file()
        and LOCK_PATH.is_file()
        and CANARY_PATH.is_file()
    ):
        shutil.copytree(retained_stage, stage)
    else:
        stage_command = [
            str(REPOSITORY_ROOT / "scripts/stage-plugin"),
            "--clean",
            "--stage-root",
            str(stage),
            "--evidence-root",
            str(evidence),
        ]
        staged = _run(stage_command, cwd=outside, environment=environment)
        assert staged.returncode == 0, staged.stderr

    marketplace_root = tmp_path / "marketplace/plugins" / PLUGIN_NAME
    shutil.copytree(stage, marketplace_root)
    assert (marketplace_root / "skills/academic-research-suite/SKILL.md").is_file()
    assert (marketplace_root / "skills/academic-research-suite/manifest.json").is_file()
    assert not any(
        path.is_symlink() for path in marketplace_root.rglob("*")
    )
    return marketplace_root, outside, environment


def test_source_hidden_installed_ars_route_and_bounded_receipt(
    installed_stage: tuple[Path, Path, dict[str, str]],
    tmp_path: Path,
) -> None:
    installed, outside, environment = installed_stage
    run_root = tmp_path / "run"
    run_root.mkdir()
    command_environment = {
        **environment,
        "HOME": str(run_root / "home"),
        "CODEX_HOME": str(run_root / "codex-home"),
        "PYTHONPATH": str(tmp_path / "source-checkout-must-not-be-imported"),
        "ARW_PLUGIN_ROOT": str(installed),
    }
    if (installed / "supply-chain/integration-lock.json").is_file():
        command_environment.update(
            {
                "ARW_INTEGRATION_LOCK": str(LOCK_PATH),
                "ARW_CODEX_LAUNCHER": str(CODEX_LAUNCHER),
                "ARW_CODEX_NATIVE_BINARY": str(CODEX_NATIVE),
                "ARW_HOST_CANARY_EVIDENCE": str(CANARY_PATH),
            }
        )

    result = _run(
        [str(installed / "bin/arw"), "route", "--json"],
        cwd=outside,
        environment=command_environment,
    )
    assert result.returncode == 0, result.stderr
    route = json.loads(result.stdout)
    assert route["workflow_family"] == "academic-pipeline"
    assert route["source_adapter_version"] == EXPECTED_ARS_ADAPTER_VERSION
    assert route["source_dependency_model"] == "bundled-pinned-adapter"
    assert route["source_bundled"] is True
    assert route["paper_ast_export"] == "deferred-v2"
    if (installed / "supply-chain/integration-lock.json").is_file():
        assert route["integration_status"] == "PASS"
        assert route["integration_lock_sha256"] == _digest(LOCK_PATH)
        assert route["reason_codes"] == []
    else:
        assert route["integration_status"] == "BLOCKED"
        assert route["reason_codes"] == ["integration_lock_not_verified"]

    workflow = installed / "skills/academic-research-suite/ars/academic-pipeline/WORKFLOW.md"
    assert workflow.is_file() and not workflow.is_symlink()
    fixture_input = canonical_json_bytes(
        {"fixture": "phase7-installed-ars-route", "claim": "bounded"}
    )
    route_output = canonical_json_bytes(route)
    # This is the retained ARS handoff boundary: identity and content digests
    # only.  Full workflow text, credentials, and absolute roots never enter
    # the receipt.
    ars_evidence = {
        "schema_version": "arw.bundled-ars-route-evidence.v1",
        "workflow": "academic-pipeline",
        "adapter_version": EXPECTED_ARS_ADAPTER_VERSION,
        "dependency_model": "bundled-pinned-adapter",
        "bundled": True,
        "workflow_sha256": _digest(workflow),
        "adapter_tree_sha256": _tree_sha256(installed / "skills/academic-research-suite", ignore_runtime_caches=True),
        "input_sha256": hashlib.sha256(fixture_input).hexdigest(),
        "output_sha256": hashlib.sha256(route_output).hexdigest(),
        "command_summary": ["academic-pipeline", "route"],
        "network": "disabled",
        "secret_material_retained": False,
        "absolute_path_material_retained": False,
    }
    ars_path = tmp_path / "ars-route-evidence.json"
    ars_path.write_bytes(canonical_json_bytes(ars_evidence))
    retained = ars_path.read_bytes()
    assert str(REPOSITORY_ROOT).encode() not in retained
    assert str(installed).encode() not in retained
    assert b"auth.json" not in retained
    assert b"OPENAI_API_KEY" not in retained

    lock_sha = _digest(LOCK_PATH) if LOCK_PATH.is_file() else None
    receipt = {
        "schema_version": "arw.installed-qualification.v1",
        "technical_qualification": "PASS" if route["integration_status"] == "PASS" else "BLOCKED",
        "release_qualification": "BLOCKED",
        "stage_sha256": observe_stage_identity(installed),
        "integration_lock_sha256": lock_sha,
        "ars_route_evidence_sha256": _digest(ars_path),
        "hook_definition_sha256": observe_hook_definition(installed)[2],
        "host_canary_sha256": _digest(CANARY_PATH) if CANARY_PATH.is_file() else None,
        "mcp_status": "not-invoked-in-route-smoke",
        "route_result_sha256": hashlib.sha256(route_output).hexdigest(),
        "reason_codes": list(route["reason_codes"]),
        "secret_material_retained": False,
        "absolute_path_material_retained": False,
    }
    _publish_once(
        REPOSITORY_ROOT / "build/evidence/phase-07/installed-qualification.json",
        receipt,
    )


def test_installed_route_requires_qualification_lock(
    installed_stage: tuple[Path, Path, dict[str, str]],
    tmp_path: Path,
) -> None:
    installed, outside, environment = installed_stage
    # Qualified stages now bundle their lock; a lock-less install has no
    # qualification input to verify and must fail closed instead of degrading to PASS.
    lock_file = installed / "supply-chain/integration-lock.json"
    if lock_file.is_file():
        lock_file.unlink()
    command_environment = {
        **environment,
        "HOME": str(tmp_path / "home"),
        "CODEX_HOME": str(tmp_path / "codex-home"),
        "ARW_PLUGIN_ROOT": str(installed),
    }
    result = _run(
        [str(installed / "bin/arw"), "route", "--json"],
        cwd=outside,
        environment=command_environment,
    )
    assert result.returncode == 0, result.stderr
    route = json.loads(result.stdout)
    assert route["integration_status"] == "BLOCKED"
    assert route["reason_codes"] == ["integration_lock_not_verified"]
    assert route["source_dependency_model"] == "bundled-pinned-adapter"
    assert route["source_bundled"] is True


def _lifecycle(decision: EvidenceAccessDecision, kind: str) -> LifecycleEvidenceRecord:
    body = {
        "schema_version": "arw.lifecycle-evidence.v1",
        "record_kind": kind,
        "receipt_id": f"receipt.{kind}.phase7",
        "subject_sha256": decision.subject_sha256,
        "input_sha256": list(decision.evidence_sha256),
        "observed_at": "2026-07-16T00:00:00Z",
        "fresh_until": "2026-07-16T01:00:00Z",
        "verdict": "PASS",
    }
    body["receipt_sha256"] = sha256_hex(canonical_json_bytes(body))
    return LifecycleEvidenceRecord.model_validate(body)


def _public_decision() -> EvidenceAccessDecision:
    return EvidenceAccessDecision.model_validate(
        json.loads(
            (
                REPOSITORY_ROOT
                / "tests/fixtures/phase6/representative-run/source/access-decision.json"
            ).read_text(encoding="utf-8")
        )
    )


def _integrity(decision: EvidenceAccessDecision) -> IntegrityReceipt:
    return IntegrityReceipt.model_validate(
        {
            "schema_version": "arw.integrity-receipt.v1",
            "receipt_id": "receipt.citation.phase7",
            "subject_kind": "source",
            "subject_id": decision.evidence_id,
            "subject_sha256": decision.subject_sha256,
            "input_sha256": list(decision.evidence_sha256),
            "method_id": "integrity.sha256",
            "method_version": "1.0.0",
            "tool_identity": {
                "name": "arw-integrity",
                "version": "0.1.0",
                "build_sha256": "f" * 64,
            },
            "observed_at": "2026-07-16T00:00:00Z",
            "freshness_policy": {
                "valid_until": "2026-07-16T01:00:00Z",
                "clock_skew_seconds": 30,
            },
            "verdict": "PASS",
            "reason_codes": ["verified"],
            "reason_text": "subject and input digests matched",
            "source_manifest_sha256": list(decision.source_manifest_sha256),
            "created_by": "parent.runtime",
        }
    )


def _qualification_receipts(provenance: object) -> dict[str, QualificationReceipt]:
    checked = provenance
    if not hasattr(checked, "provenance_sha256"):
        from arw.experiment_provenance import seal_experiment_provenance

        checked = seal_experiment_provenance(checked)
    result: dict[str, QualificationReceipt] = {}
    for kind in (
        "sandbox_approval",
        "accountable_approval",
        "environment_capture",
        "provenance_equivalence_probe",
    ):
        result[kind] = QualificationReceipt.model_validate(
            {
                "kind": kind,
                "subject_sha256": checked.provenance_sha256,
                "configuration_sha256": checked.configuration_sha256,
                "artifacts_sha256": checked.artifacts_sha256,
                "observed_at": "2026-07-16T00:00:00Z",
                "valid_until": "2026-07-16T01:00:00Z",
                "verdict": "PASS",
                "authority_sha256": "e" * 64 if kind == "accountable_approval" else None,
                "accountable_actor_id": "operator.user" if kind == "accountable_approval" else None,
                "probe_result": "equivalent" if kind == "provenance_equivalence_probe" else None,
            }
        )
    return result


def _representative_panel() -> tuple[PanelManifest, ReviewFindingMatrix, GateDecision]:
    """Build one strict four-seat panel with a retained minority stance."""

    subject = "a" * 64
    rubric = "b" * 64
    policy = "c" * 64
    seats: list[PanelSeat] = []
    reports: list[ReviewReport] = []
    for ordinal, role in enumerate(sorted(FORMAL_REVIEW_ROLE_IDS), start=1):
        assignment_id = f"assignment.phase7-{role}"
        seats.append(
            PanelSeat(
                assignment_id=assignment_id,
                attempt_id=f"attempt.{role}",
                role_id=role,
                worker_identity_id=f"worker.{role}",
                host_agent_id=f"host.{role}",
                identity_receipt_sha256=sha256_hex(role.encode()),
                acceptance_key=(1, ordinal, assignment_id),
                blind_envelope_sha256=sha256_hex(f"blind:{role}".encode()),
                required=True,
                round_number=1,
            )
        )
    synthesizer = PanelSeat(
        assignment_id="assignment.phase7-synthesizer",
        attempt_id="attempt.editorial-synthesizer",
        role_id="editorial_synthesizer",
        worker_identity_id="worker.editorial-synthesizer",
        host_agent_id="host.editorial-synthesizer",
        identity_receipt_sha256=sha256_hex(b"editorial-synthesizer"),
        acceptance_key=(1, 99, "assignment.phase7-synthesizer"),
        blind_envelope_sha256=sha256_hex(b"blind:editorial-synthesizer"),
        required=True,
        round_number=1,
        synthesizer=True,
    )
    panel = PanelManifest(
        schema_version="arw.panel-manifest.v1",
        panel_id="panel.phase7-representative-001",
        subject_sha256=subject,
        rubric_sha256=rubric,
        policy_sha256=policy,
        execution_mode="assignment_injected_subagent",
        status="ready",
        reviewer_seats=tuple(seats),
        synthesizer_seat=synthesizer,
        required_report_roles=tuple(sorted(FORMAL_REVIEW_ROLE_IDS)),
        blockers=(),
        limitations=("dissent retained in the finding matrix",),
    )
    for seat in seats:
        finding = ReviewFinding(
            finding_id=f"finding.{seat.role_id}",
            source_report_sha256=(sha256_hex(f"placeholder:{seat.role_id}".encode()),),
            evidence_sha256=("d" * 64,),
            severity="moderate",
            confidence=0.8,
            classification=(
                "split" if seat.role_id == "devils_advocate_reviewer" else "majority"
            ),
            resolution="resolved",
            rationale=f"{seat.role_id} retained a bounded observation",
        )
        reports.append(
            ReviewReport(
                report_id=f"report.{seat.role_id}",
                panel_manifest_sha256=panel.manifest_sha256,
                assignment_id=seat.assignment_id,
                attempt_id=seat.attempt_id,
                identity_receipt_sha256=seat.identity_receipt_sha256,
                role_id=seat.role_id,
                worker_identity_id=seat.worker_identity_id,
                host_agent_id=seat.host_agent_id,
                subject_sha256=subject,
                rubric_sha256=rubric,
                findings=(finding,),
            )
        )
    synthesis_findings = tuple(
        report.findings[0].model_copy(
            update={"source_report_sha256": (report.report_sha256,)}
        )
        for report in reports
    )
    synthesis = ReviewSynthesis(
        synthesis_id="synthesis.phase7-representative-001",
        panel_manifest_sha256=panel.manifest_sha256,
        identity_receipt_sha256=synthesizer.identity_receipt_sha256,
        worker_identity_id=synthesizer.worker_identity_id,
        host_agent_id=synthesizer.host_agent_id,
        source_report_sha256=tuple(report.report_sha256 for report in reports),
        findings=synthesis_findings,
        limitations=("minority dissent is preserved",),
    )
    matrix = ReviewFindingMatrix(
        schema_version="arw.review-finding-matrix.v1",
        panel_id=panel.panel_id,
        panel_manifest_sha256=panel.manifest_sha256,
        subject_sha256=subject,
        rubric_sha256=rubric,
        reports=tuple(reports),
        synthesis=synthesis,
        gate_verdict="PASS",
    )
    gate = GateDecision(
        schema_version="arw.gate-decision.v1",
        gate_id="gate.review.phase7",
        subject_sha256=subject,
        evidence_sha256=("b" * 64, "d" * 64),
        verdict="PASS",
        rationale="all required independent reports and dissent were retained",
        fresh_until="2026-07-16T01:00:00Z",
        required=True,
        human_decision=None,
    )
    return panel, matrix, gate


def _graph_receipt() -> GraphProjectionReceipt:
    return GraphProjectionReceipt.model_validate(
        {
            "schema_version": "1.0.0",
            "root_id": "graph.phase7",
            "candidate_generation_id": "generation.phase7-001",
            "previous_generation_id": None,
            "selected_generation_id": "generation.phase7-001",
            "projection_manifest_sha256": "e" * 64,
            "input_sha256": "f" * 64,
            "ledger_watermark": 2,
            "status": "PASS",
            "reason_codes": [],
        }
    )


def test_phase7_representative_fixture_has_every_bounded_scientific_stage() -> None:
    fixture_root = REPOSITORY_ROOT / "tests/fixtures/phase6/representative-run"
    required = (
        "source/source.json",
        "source/access-decision.json",
        "claim/claim.json",
        "experiment/provenance.json",
        "result/figure-001.json",
        "review/reports.json",
        "gate/failed-gate.json",
        "human/resolution.json",
        "recovery/checkpoint.json",
        "ars/route-evidence.json",
        "dossier/manifest.json",
    )
    assert all((fixture_root / relative).is_file() for relative in required)
    all_bytes = b"".join((fixture_root / relative).read_bytes() for relative in required)
    assert b"OPENAI_API_KEY" not in all_bytes
    assert b"private full text" not in all_bytes.lower()
    assert b"/home/" not in all_bytes
    decision = _public_decision()
    assert decision.access_state == "publicly_verified"
    failed_gate = GateDecision.model_validate(
        json.loads((fixture_root / "gate/failed-gate.json").read_text(encoding="utf-8"))
    )
    human_resolution = HumanDecisionRecord.model_validate(
        json.loads((fixture_root / "human/resolution.json").read_text(encoding="utf-8"))
    )
    assert failed_gate.verdict == "BLOCKED"
    assert human_resolution.blocker_action == "release"
    with pytest.raises(ValueError):
        HumanDecisionRecord.model_validate(
            {**human_resolution.model_dump(mode="json"), "verdict_rewrite": True}
        )
    panel, matrix, gate = _representative_panel()
    assert panel.status == "ready"
    assert matrix.gate_verdict == "PASS"
    assert len(matrix.reports) == 4
    assert matrix.synthesis.source_report_sha256 == tuple(
        report.report_sha256 for report in matrix.reports
    )
    assert any(
        finding.classification == "split"
        for finding in matrix.synthesis.findings
    )
    assert gate.verdict == "PASS"
    forged_report = matrix.reports[0].model_dump(mode="json")
    forged_report["report_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="derived from canonical report body"):
        ReviewReport.model_validate(forged_report)
    stale_gate = GateDecision.model_validate(
        {**gate.model_dump(mode="json"), "fresh_until": "2026-07-15T00:00:00Z"}
    )
    stale_review = evaluate_claim_capability(
        "independent_review_complete",
        _public_decision(),
        panel_manifest=panel,
        review_matrix=matrix,
        gate_decision=stale_gate,
        now="2026-07-16T00:30:00Z",
    )
    assert stale_review.status == "BLOCKED"
    assert "review_gate_stale" in stale_review.reason_codes


def test_installed_ars_journey_cold_replay_survives_checkpoint_and_builds_dossier(
    installed_stage: tuple[Path, Path, dict[str, str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed, outside, environment = installed_stage
    if not (installed / "supply-chain/integration-lock.json").is_file() or not (
        LOCK_PATH.is_file() and CANARY_PATH.is_file()
    ):
        pytest.skip("retained exact bundled host qualification evidence is absent")
    run_root, _ = _init_run(tmp_path)
    command_environment = {
        **environment,
        "HOME": str(tmp_path / "journey-home"),
        "CODEX_HOME": str(tmp_path / "journey-codex-home"),
        "ARW_PLUGIN_ROOT": str(installed),
        "ARW_INTEGRATION_LOCK": str(LOCK_PATH),
        "ARW_CODEX_LAUNCHER": str(CODEX_LAUNCHER),
        "ARW_CODEX_NATIVE_BINARY": str(CODEX_NATIVE),
        "ARW_HOST_CANARY_EVIDENCE": str(CANARY_PATH),
    }
    route_run = _run([str(installed / "bin/arw"), "route", "--json"], cwd=outside, environment=command_environment)
    assert route_run.returncode == 0, route_run.stderr
    route = json.loads(route_run.stdout)
    assert route["workflow_family"] == "academic-pipeline"
    assert route["source_adapter_version"] == EXPECTED_ARS_ADAPTER_VERSION
    assert route["source_bundled"] is True
    assert route["source_dependency_model"] == "bundled-pinned-adapter"
    assert route["integration_status"] == "PASS"

    # The fsync fault occurs after the canonical claim/checkpoint event is
    # durable. A fresh parent process can replay it; no hook or adapter output
    # is allowed to append dossier authority.
    request = LifecycleTransitionRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": "run-00000000-0000-4000-8000-000000000404",
            "event_id": "evt-00000000-0000-4000-8000-000000000901",
            "command_id": "cmd-00000000-0000-4000-8000-000000000901",
            "expected_revision": 1,
            "occurred_at": "2026-07-16T00:10:00Z",
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
            "transition_id": "prepare",
            "from_stage": "initialized",
        }
    )
    from arw.runtime import RuntimeCommandService

    monkeypatch.setenv("ARW_TEST_MODE", "1")
    monkeypatch.setenv("ARW_TEST_FAULT_ID", "phase7.journal-fsync")
    with pytest.raises(InjectedFault):
        RuntimeCommandService(run_root).execute_transition(request)
    monkeypatch.delenv("ARW_TEST_FAULT_ID")
    monkeypatch.delenv("ARW_TEST_MODE")
    replayed = RuntimeCommandService(run_root).read_state()
    assert replayed.accepted_revision == 2

    decision = _public_decision()
    integrity = _integrity(decision)
    provenance = json.loads(
        (
            REPOSITORY_ROOT
            / "tests/fixtures/phase6/representative-run/experiment/provenance.json"
        ).read_text(encoding="utf-8")
    )
    panel, matrix, gate = _representative_panel()
    human_record = HumanDecisionRecord.model_validate(
        json.loads(
            (
                REPOSITORY_ROOT
                / "tests/fixtures/phase6/representative-run/human/resolution.json"
            ).read_text(encoding="utf-8")
        )
    )
    human_decision_sha256 = sha256_hex(
        canonical_json_bytes(human_record.model_dump(mode="json"))
    )
    evidence = {
        "access": (decision,),
        "integrity": (integrity,),
        "provenance": (provenance,),
        "qualification_receipts": _qualification_receipts(provenance),
        "reproduction_decision": {"decision": "parent-import-accepted"},
        "run_replay_receipt": _lifecycle(decision, "run_replay"),
        "passport_receipts": (_lifecycle(decision, "passport"),),
        "graph_projection_receipt": _lifecycle(decision, "graph_projection"),
        "test_receipts": (_lifecycle(decision, "test"),),
        "benchmark_receipts": (_lifecycle(decision, "benchmark"),),
        "build_receipt": _lifecycle(decision, "build"),
        "citation_lifecycle_receipt": _lifecycle(decision, "citation"),
    }
    dossier = assemble_audit_dossier(
        run_root=run_root,
        generated_at="2026-07-16T00:30:00Z",
        evidence=evidence,
        review={
            "panel_manifest": panel,
            "panel_manifest_sha256": panel.manifest_sha256,
            "review_matrix": matrix,
            "review_matrix_sha256": sha256_hex(canonical_json_bytes(matrix.model_dump(mode="json"))),
            "review_report_sha256": tuple(report.report_sha256 for report in matrix.reports),
            "dissent_refs": (matrix.reports[-1].report_sha256,),
            "gate_decision": gate,
            "human_decision_sha256": (human_decision_sha256,),
        },
        graph={"status": "available", "receipts": (_graph_receipt(),)},
        source_identity_sha256=(decision.subject_sha256,),
        integration_lock_sha256=_digest(LOCK_PATH),
    )
    assert dossier.technical_qualification.verdict == "PASS"
    assert dossier.release_qualification.verdict == "BLOCKED"
    assert set(dossier.release_qualification.reason_codes) >= {
        "SUP-04",
        "P04-09",
        "CC_BY_NC_PERMISSION_UNRESOLVED",
    }
    assert dossier.dissent_refs
    cold = replay_audit_dossier(dossier, projection_available=False)
    assert cold.technical_qualification.verdict == "PASS"
    assert cold.release_qualification.verdict == "BLOCKED"
    assert cold.dissent_refs == dossier.dissent_refs
    assert cold.review_report_sha256 == dossier.review_report_sha256
    assert any(item.code == "projection_unavailable" for item in cold.blockers)
    target = REPOSITORY_ROOT / "build/evidence/phase-07/representative-dossier.json"
    published_dossier = _publish_once(target, dossier.model_dump(mode="json"))
    assert published_dossier.is_file()
    assert published_dossier.read_bytes() == dossier.canonical_bytes()
    replay_comparison = {
        "schema_version": "arw.phase7-dossier-replay-comparison.v1",
        "warm_dossier_sha256": dossier.dossier_sha256,
        "cold_dossier_sha256": cold.dossier_sha256,
        "warm_technical_qualification": dossier.technical_qualification.verdict,
        "cold_technical_qualification": cold.technical_qualification.verdict,
        "release_qualification": cold.release_qualification.verdict,
        "projection_loss_blocker": "projection_unavailable",
        "report_hashes": list(cold.review_report_sha256),
        "dissent_refs": list(cold.dissent_refs),
    }
    _publish_once(
        REPOSITORY_ROOT / "build/evidence/phase-07/representative-dossier-replay.json",
        replay_comparison,
    )
    assert replay_run(run_root).validated is True
