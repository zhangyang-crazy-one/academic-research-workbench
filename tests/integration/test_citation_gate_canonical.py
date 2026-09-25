"""Citation gates use parent-accepted manifests and the canonical gate journal."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from arw.cli import main
from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger.journal import replay_run
from arw.kernel.policy.citations import (
    ReferenceRecord,
    ReferenceUse,
    check_response,
    publish_check,
)
from arw.kernel.state.models import ArtifactAcceptanceRequest

from .test_orchestration_lifecycle import _run


def _request(root: Path, number: int, *, role: str = "parent_control_plane") -> dict:
    return {
        "schema_version": "1.0.0",
        "run_id": RuntimeCommandService(root).read_state().run_id,
        "event_id": f"evt-00000000-0000-4000-8000-{number:012x}",
        "command_id": f"cmd-00000000-0000-4000-8000-{number:012x}",
        "expected_revision": replay_run(root).revision,
        "occurred_at": "2026-09-25T01:00:00Z",
        "actor_id": "parent.runtime",
        "actor_role": role,
    }


def _accept(root: Path, number: int, kind: str, path: str, raw: bytes):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    request = ArtifactAcceptanceRequest.model_validate(
        {
            **_request(root, number),
            "artifact_id": f"artifact.citation-{number}",
            "artifact_kind": kind,
            "media_type": "application/json",
            "content_path": path,
            "content_sha256": sha256_hex(raw),
            "base_revision": RuntimeCommandService(root).read_state().accepted_revision,
            "consumed_sha256": [],
        }
    )
    outcome = RuntimeCommandService(root).accept_artifact(request)
    assert outcome.accepted, outcome.rejection
    return outcome.event.payload.manifest_sha256


def _fixture(tmp_path: Path, *, role: str = "supporting"):
    root, _ = _run(tmp_path)
    ref = ReferenceRecord(
        reference_id="ref.alpha",
        citation_key="Alpha2024",
        title="Alpha",
        authors=("Smith",),
        year=2024,
        doi="10.1234/alpha",
    )
    use = ReferenceUse(
        use_id=f"use.{role}",
        reference_id=ref.reference_id,
        claim_id="claim.alpha",
        role=role,
    )
    ref_raw = canonical_json_bytes(ref.model_dump(mode="json"))
    use_raw = canonical_json_bytes(use.model_dump(mode="json"))
    ref_manifest = _accept(
        root, 100, "reference-record", "citations/reference.json", ref_raw
    )
    use_manifest = _accept(root, 101, "reference-use", "citations/use.json", use_raw)
    return root, ref, use, ref_manifest, use_manifest


def _receipt(
    root: Path, ref: ReferenceRecord, number: int, status: str, *, accept: bool = True
):
    item = {
        "DOI": ref.doi,
        "title": [ref.title],
        "published": {"date-parts": [[ref.year]]},
        "author": [{"family": "Smith"}],
        "update-to": [{"type": "retraction"}] if status == "retracted" else [],
    }
    items = (
        []
        if status == "not_found"
        else [item, item]
        if status == "ambiguous"
        else [item]
    )
    raw = (
        b"invalid json"
        if status == "unknown"
        else b"busy"
        if status == "unavailable"
        else json.dumps({"message": {"items": items}}).encode()
    )
    receipt = check_response(
        ref,
        "crossref",
        raw,
        observed_at=f"2026-09-{number:02d}T00:00:00Z",
        http_status=503 if status == "unavailable" else 200,
    )
    publish_check(root, receipt, raw)
    manifest = None
    if accept:
        path = f"citations/receipts/sha256/{receipt.receipt_sha256}.json"
        manifest = _accept(
            root,
            200 + number,
            "citation-check-receipt",
            path,
            (root / path).read_bytes(),
        )
    return receipt, manifest


def _gate(
    root: Path,
    tmp_path: Path,
    number: int,
    capsys,
    *,
    role: str = "parent_control_plane",
    receipt: str | None = None,
    stale: bool = False,
    use_path: Path | None = None,
):
    request = _request(root, 300 + number, role=role)
    if stale:
        request["expected_revision"] -= 1
    request_file = tmp_path / f"request-{number}.json"
    request_file.write_bytes(canonical_json_bytes(request))
    args = [
        "citation",
        "gate",
        "--reference",
        str(root / "citations/reference.json"),
        "--use",
        str(use_path or root / "citations/use.json"),
        "--store",
        str(root),
        "--provider",
        "crossref",
        "--run-root",
        str(root),
        "--request",
        str(request_file),
    ]
    if receipt:
        args.extend(["--receipt", receipt])
    code = main(args)
    return code, json.loads(capsys.readouterr().out)


def test_only_parent_accepted_replayable_evidence_writes_gate(tmp_path, capsys):
    root, ref, _, ref_manifest, use_manifest = _fixture(tmp_path)
    receipt, receipt_manifest = _receipt(root, ref, 25, "verified")
    code, result = _gate(root, tmp_path, 1, capsys)
    assert code == 0 and result["accepted"] is True
    decision = result["event"]["payload"]["decision"]
    assert decision["verdict"] == "PASS"
    assert decision["subject_sha256"] == use_manifest
    assert set(decision["evidence_sha256"]) == {
        ref_manifest,
        use_manifest,
        receipt_manifest,
    }
    assert receipt.receipt_sha256 in decision["rationale"]
    replayed = replay_run(root)
    assert replayed.events[-1].event_type == "gate.evaluated"
    assert RuntimeCommandService(root).read_state().gates[-1].decision.verdict == "PASS"


def test_local_receipt_cannot_make_canonical_pass(tmp_path, capsys):
    root, ref, *_ = _fixture(tmp_path)
    receipt, _ = _receipt(root, ref, 25, "verified", accept=False)
    code, result = _gate(root, tmp_path, 1, capsys, receipt=receipt.receipt_sha256)
    assert code == 65 and result["status"] == "error"
    assert not any(
        event.event_type == "gate.evaluated" for event in replay_run(root).events
    )
    code, result = _gate(root, tmp_path, 2, capsys)
    assert code == 0 and result["event"]["payload"]["decision"]["verdict"] == "BLOCKED"


def test_unaccepted_reference_use_cannot_make_canonical_pass(tmp_path, capsys):
    root, ref, *_ = _fixture(tmp_path)
    _receipt(root, ref, 25, "verified")
    other_use = ReferenceUse(
        use_id="use.unaccepted",
        reference_id=ref.reference_id,
        claim_id="claim.alpha",
        role="supporting",
    )
    path = root / "citations/unaccepted-use.json"
    path.write_bytes(canonical_json_bytes(other_use.model_dump(mode="json")))
    code, result = _gate(root, tmp_path, 1, capsys, use_path=path)
    assert code == 65 and result["status"] == "error"
    assert not any(
        event.event_type == "gate.evaluated" for event in replay_run(root).events
    )


@pytest.mark.parametrize("status", ["retracted", "not_found"])
def test_supporting_conclusive_failure(tmp_path, capsys, status):
    root, ref, *_ = _fixture(tmp_path)
    _receipt(root, ref, 25, status)
    code, result = _gate(root, tmp_path, 1, capsys)
    assert code == 0 and result["event"]["payload"]["decision"]["verdict"] == "FAIL"
    assert RuntimeCommandService(root).read_state().blockers


def test_retracted_research_object_requires_human_review(tmp_path, capsys):
    root, ref, *_ = _fixture(tmp_path, role="research_object")
    _receipt(root, ref, 25, "retracted")
    code, result = _gate(root, tmp_path, 1, capsys)
    decision = result["event"]["payload"]["decision"]
    assert code == 0 and decision["verdict"] == "BLOCKED"
    assert "human_review" in decision["rationale"]


@pytest.mark.parametrize("status", ["unknown", "unavailable", "ambiguous"])
def test_inconclusive_states_block_without_not_found(tmp_path, capsys, status):
    root, ref, *_ = _fixture(tmp_path)
    _receipt(root, ref, 25, status)
    code, result = _gate(root, tmp_path, 1, capsys)
    decision = result["event"]["payload"]["decision"]
    assert code == 0 and decision["verdict"] == "BLOCKED"
    assert status in decision["rationale"] and "not_found" not in decision["rationale"]


def test_historical_blocker_survives_later_verified(tmp_path, capsys):
    root, ref, *_ = _fixture(tmp_path)
    bad, _ = _receipt(root, ref, 25, "not_found")
    assert _gate(root, tmp_path, 1, capsys)[0] == 0
    _receipt(root, ref, 26, "verified")
    code, result = _gate(root, tmp_path, 2, capsys)
    decision = result["event"]["payload"]["decision"]
    assert code == 0 and decision["verdict"] == "FAIL"
    assert bad.receipt_sha256 in decision["rationale"]
    assert len(RuntimeCommandService(root).read_state().gates) == 2
    assert len(RuntimeCommandService(root).read_state().blockers) >= 2


def test_rejects_tampering_unknown_and_stale_evidence(tmp_path, capsys):
    root, ref, *_ = _fixture(tmp_path)
    receipt, _ = _receipt(root, ref, 25, "verified")
    assert _gate(root, tmp_path, 1, capsys, stale=True)[0] == 65
    assert _gate(root, tmp_path, 2, capsys, receipt="f" * 64)[0] == 65
    assert _gate(root, tmp_path, 3, capsys, role="worker")[0] == 65
    (root / "citations/responses/sha256" / receipt.response_sha256).write_bytes(
        b"forged"
    )
    assert _gate(root, tmp_path, 4, capsys)[0] == 65
    assert not any(
        event.event_type == "gate.evaluated" for event in replay_run(root).events
    )


def test_parent_accept_rejects_forged_receipt_verdict(tmp_path):
    root, ref, *_ = _fixture(tmp_path)
    genuine, _ = _receipt(root, ref, 25, "verified", accept=False)
    forged_body = genuine.model_dump(mode="json", exclude={"receipt_sha256"})
    forged_body["status"] = "not_found"
    forged_body["matched_id"] = None
    forged_body.pop("batch_id")
    forged_body["receipt_sha256"] = sha256_hex(canonical_json_bytes(forged_body))
    forged_raw = canonical_json_bytes(forged_body)
    path = f"citations/receipts/sha256/{forged_body['receipt_sha256']}.json"
    (root / path).write_bytes(forged_raw)
    request = ArtifactAcceptanceRequest.model_validate(
        {
            **_request(root, 250),
            "artifact_id": "artifact.citation-forged",
            "artifact_kind": "citation-check-receipt",
            "media_type": "application/json",
            "content_path": path,
            "content_sha256": sha256_hex(forged_raw),
            "base_revision": RuntimeCommandService(root).read_state().accepted_revision,
            "consumed_sha256": [],
        }
    )
    outcome = RuntimeCommandService(root).accept_artifact(request)
    assert not outcome.accepted
    assert outcome.rejection.code == "citation-artifact-invalid"
    assert not any(
        event.event_type == "gate.evaluated" for event in replay_run(root).events
    )


@pytest.mark.parametrize("command", ["citation", "pdf", "artifact"])
def test_launcher_routes_scholarly_commands(command):
    launcher = Path(__file__).resolve().parents[2] / "bin/arw"
    result = subprocess.run(
        [str(launcher), command, "--help"], capture_output=True, text=True, check=False
    )
    assert "unknown-command" not in result.stderr
    assert result.returncode != 64
