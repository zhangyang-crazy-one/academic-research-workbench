"""Full CLI subprocess workflow, with network calls denied in every process."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.ledger.journal import replay_run
from arw.kernel.ledger.workflows import PHASE4_WORKFLOW
from arw.kernel.policy.citations import ReferenceRecord, ReferenceUse

from .test_citation_gate_canonical import _request

# Process-local deny guard: any attempted Python socket/HTTP connection fails
# the test, including in CLI init/admission/gate/replay, not only policy helpers.
_OFFLINE_CLI = """
import socket, sys, urllib.request

def denied(*args, **kwargs):
    raise AssertionError('unexpected network access')
socket.create_connection = denied
socket.socket.connect = denied
socket.socket.connect_ex = denied
urllib.request.urlopen = denied
from arw.cli import main
raise SystemExit(main(sys.argv[1:]))
"""


class Workflow:
    def __init__(self, tmp_path):
        self.root = tmp_path / "run"
        self.root.mkdir()
        self.number = 1000
        source = self.root / "input.txt"
        source.write_bytes(b"local research input")
        init = {
            "schema_version": "1.0.0",
            "run_id": "run-00000000-0000-4000-8000-000000000404",
            "occurred_at": "2026-07-15T01:00:00Z",
            "immutable_input": {"path": "input.txt", "sha256": sha256_hex(source.read_bytes())},
            "workflow_family": "academic-pipeline", "workflow_mode": "inline-role-prompts",
            "workflow_definition_id": PHASE4_WORKFLOW.definition_id,
            "workflow_definition_sha256": PHASE4_WORKFLOW.sha256,
            "journal_layout": "segmented-v1", "capabilities": ["canonical-journal"],
            "event_id": "evt-00000000-0000-4000-8000-000000000404",
            "command_id": "cmd-00000000-0000-4000-8000-000000000404",
            "actor_id": "parent.runtime",
        }
        request_file = self.write("init.json", init)
        self.cli("init", "--run-root", self.root, "--request", request_file)
        self.reference = ReferenceRecord(
            reference_id="ref.alpha", citation_key="Alpha2024", title="Alpha",
            authors=("Smith",), year=2024, doi="10.1234/alpha",
        )
        use = ReferenceUse(use_id="use.alpha", reference_id="ref.alpha", claim_id="claim.alpha", role="supporting")
        self.ref_path = self.write("reference.json", self.reference.model_dump(mode="json"))
        self.use_path = self.write("use.json", use.model_dump(mode="json"))
        self.accept(self.ref_path, "reference-record")
        self.accept(self.use_path, "reference-use")

    def write(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(canonical_json_bytes(value))
        return target

    def cli(self, *args, code=0, http_status=None):
        script = _OFFLINE_CLI
        if http_status is not None:
            # Fixture HTTP error at the transport seam; no real provider call.
            script = script.replace("from arw.cli import main", f"""
import io
from urllib.error import HTTPError
import arw.cli_scholarly
def fixture_http_error(*args, **kwargs):
    raise HTTPError('https://api.crossref.org/works/10.1234/alpha',
                    {http_status}, 'fixture failure', {{}}, io.BytesIO(b'busy'))
arw.cli_scholarly.fetch_response = fixture_http_error
from arw.cli import main""")
        result = subprocess.run(
            [sys.executable, "-c", script, *map(str, args)],
            capture_output=True, text=True, check=False, timeout=20,
        )
        assert result.returncode == code, (result.stdout, result.stderr)
        return json.loads(result.stdout)

    def request(self, **extra):
        self.number += 1
        return self.write(f"requests/{self.number}.json", {**_request(self.root, self.number), **extra})

    def accept(self, path, kind):
        request = self.request(
            artifact_id=f"artifact.citation-{self.number}", artifact_kind=kind,
            media_type="application/json", content_path=path.relative_to(self.root).as_posix(),
            content_sha256=sha256_hex(path.read_bytes()),
            base_revision=replay_run(self.root).revision, consumed_sha256=[],
        )
        result = self.cli("artifact-accept", "--run-root", self.root, "--request", request)
        assert result["accepted"]
        return result["event"]["payload"]["manifest_sha256"]

    def entry(self, *, reported=None, accept=True, **extra):
        entry = {
            "citation_key": "Alpha2024", "title": "Alpha",
            "authors": [{"family": "Smith"}], "year": 2024,
            "doi": "10.1234/alpha", "source_pointer": "missing-paper.pdf",
            "source_acquired": False, "description_last_audit": "none",
            "user_notes": "人工批注：原文尚未取得，不据索引裁定论断。", **extra,
        }
        if reported is not None:
            entry["contamination_signals"] = {"crossref_unmatched": reported}
        path = self.write(f"entries/entry-{self.number}.json", entry)
        manifest = self.accept(path, "ars-literature-entry") if accept else None
        return path, manifest

    def check(self, status="verified", *, day=25):
        item = {"DOI": self.reference.doi, "title": [self.reference.title]}
        raw = {"message": {"items": [] if status == "not_found" else [item]}}
        response = self.write(f"response-{day}.json", raw)
        args = ["citation", "check", "--reference", self.ref_path, "--provider", "crossref",
                "--store", self.root, "--observed-at", f"2026-09-{day}T00:00:00Z"]
        args.extend(["--allow-network"] if status == "unavailable" else ["--response", response])
        result = self.cli(*args, http_status=503 if status == "unavailable" else None)
        receipt = result["receipt"]
        assert receipt["status"] == status
        path = self.root / f"citations/receipts/sha256/{receipt['receipt_sha256']}.json"
        manifest = self.accept(path, "citation-check-receipt")
        return receipt, manifest

    def gate(self, entry=None, *, canonical=True, code=0):
        args = ["citation", "gate", "--reference", self.ref_path, "--use", self.use_path,
                "--store", self.root, "--provider", "crossref"]
        if entry is not None:
            args.extend(["--literature-entry", entry])
        if canonical:
            args.extend(["--run-root", self.root, "--request", self.request()])
        return self.cli(*args, code=code)


@pytest.mark.parametrize("status,reported,verdict", [
    ("not_found", False, "FAIL"), ("verified", True, "PASS"),
    ("not_found", True, "FAIL"), ("verified", False, "PASS"),
])
def test_full_cli_retains_conflict_and_never_overwrites_self_report(tmp_path, status, reported, verdict):
    work = Workflow(tmp_path)
    entry, entry_manifest = work.entry(reported=reported)
    before = entry.read_bytes()
    receipt, receipt_manifest = work.check(status)
    result = work.gate(entry)
    observation = result["contamination_observation"]
    expected = status == "not_found"
    assert observation["contamination_signals"] == {"crossref_unmatched": expected}
    assert observation["self_reported"]["contamination_signals"] == {"crossref_unmatched": reported}
    assert len(observation["conflicts"]) == int(expected != reported)
    if expected != reported:
        assert observation["conflicts"] == [{
            "signal": "crossref_unmatched", "reported_value": reported,
            "resolver_value": expected, "receipt_sha256": receipt["receipt_sha256"],
        }]
    decision = result["event"]["payload"]["decision"]
    assert decision["verdict"] == verdict and decision["human_decision"] is None
    assert {entry_manifest, receipt_manifest}.issubset(decision["evidence_sha256"])
    replayed = replay_run(work.root).events[-1].payload.decision
    assert json.loads(replayed.rationale.rsplit("; contamination=", 1)[1]) == observation
    assert work.cli("replay", "--run-root", work.root)
    assert entry.read_bytes() == before
    assert b'"source_acquired":false' in before
    assert json.loads(before)["user_notes"].startswith("人工批注")


def test_full_cli_legacy_missing_self_report_and_manual_annotations(tmp_path):
    work = Workflow(tmp_path)
    work.check()
    legacy = work.gate()
    assert legacy["event"]["payload"]["decision"]["verdict"] == "PASS"
    assert legacy["contamination_observation"]["self_reported"] is None
    for extra in ({}, {"obtained_via": "manual"},
                  {"contamination_signal_omissions": {"crossref_unmatched": "api_degraded"}}):
        entry, _ = work.entry(**extra)
        before = entry.read_bytes()
        result = work.gate(entry)
        assert result["contamination_observation"]["conflicts"] == []
        assert entry.read_bytes() == before


def test_full_cli_historical_conflict_survives_later_agreement(tmp_path):
    work = Workflow(tmp_path)
    entry, _ = work.entry(reported=False)
    bad, _ = work.check("not_found")
    first = work.gate(entry)
    first_event = canonical_json_bytes(first["event"])
    work.check("verified", day=26)
    second = work.gate(entry)
    observation = second["contamination_observation"]
    assert observation["contamination_signals"] == {"crossref_unmatched": False}
    assert observation["conflicts"][0]["receipt_sha256"] == bad["receipt_sha256"]
    assert second["event"]["payload"]["decision"]["verdict"] == "FAIL"
    gates = [e for e in replay_run(work.root).events if e.event_type == "gate.evaluated"]
    assert len(gates) == 2
    assert canonical_json_bytes(gates[0].model_dump(mode="json")) == first_event


def test_full_cli_rejects_unaccepted_changed_or_wrong_entry(tmp_path):
    work = Workflow(tmp_path)
    work.check()
    entry, _ = work.entry(reported=True, accept=False)
    assert work.gate(entry, code=65)["status"] == "error"
    work.accept(entry, "ars-literature-entry")
    entry.write_bytes(entry.read_bytes().replace(b'"Alpha"', b'"Another"'))
    assert work.gate(entry, code=65)["status"] == "error"
    wrong, _ = work.entry(reported=True, title="Another")
    assert work.gate(wrong, code=65)["status"] == "error"
    assert not any(e.event_type == "gate.evaluated" for e in replay_run(work.root).events)


def test_full_cli_local_proposal_has_same_observation_without_admission(tmp_path):
    work = Workflow(tmp_path)
    entry, _ = work.entry(reported=True, accept=False)
    work.check()
    result = work.gate(entry, canonical=False)
    assert result["parent_admission"] == "required"
    assert len(result["contamination_observation"]["conflicts"]) == 1
    assert not any(e.event_type == "gate.evaluated" for e in replay_run(work.root).events)


@pytest.mark.parametrize("reported", [True, False])
def test_full_cli_service_unavailable_is_degraded_not_missing_or_retracted(tmp_path, reported):
    work = Workflow(tmp_path)
    entry, _ = work.entry(reported=reported)
    receipt, _ = work.check("unavailable")
    result = work.gate(entry)
    observation = result["contamination_observation"]
    assert receipt["http_status"] == 503 and receipt["retraction_evidence"] is None
    assert observation["lookup_states"] == {"crossref": "unavailable"}
    assert observation["contamination_signals"] == {} and observation["conflicts"] == []
    assert observation["contamination_signal_omissions"] == {"crossref_unmatched": "api_degraded"}
    decision = result["event"]["payload"]["decision"]
    assert decision["verdict"] == "BLOCKED"
    assert "status=unavailable" in decision["rationale"]
    assert "not_found" not in decision["rationale"] and "retracted" not in decision["rationale"]
    assert work.cli("replay", "--run-root", work.root)


def test_full_cli_bound_source_requires_accepted_exact_passport_entry(tmp_path):
    from arw.kernel.policy.citations import reference_from_source_manifest
    from arw.kernel.policy.research_integrity import research_source_from_ars_entry

    work = Workflow(tmp_path)
    entry, entry_manifest = work.entry(reported=True)
    source = research_source_from_ars_entry(
        json.loads(entry.read_bytes()), source_id="ref.alpha",
        source_sha256=sha256_hex((work.root / "input.txt").read_bytes()),
        imported_at="2026-09-25T00:00:00Z", imported_by="parent.runtime",
    )
    work.reference = reference_from_source_manifest(source)
    work.ref_path = work.write("bound-reference.json", work.reference.model_dump(mode="json"))
    work.accept(work.ref_path, "reference-record")
    work.check()
    assert work.gate(entry, code=65)["status"] == "error"
    source_path = work.write("source-manifest.json", source.model_dump(mode="json"))
    source_manifest = work.accept(source_path, "research-source-manifest")
    result = work.gate(entry)
    assert {entry_manifest, source_manifest}.issubset(result["event"]["payload"]["decision"]["evidence_sha256"])
    changed, _ = work.entry(reported=True, user_notes="different snapshot")
    assert work.gate(changed, code=65)["status"] == "error"


def test_full_cli_unchecked_provider_keeps_unknown_even_if_model_reports_match(tmp_path):
    work = Workflow(tmp_path)
    entry, _ = work.entry(reported=False)
    result = work.gate(entry)
    assert result["event"]["payload"]["decision"]["verdict"] == "BLOCKED"
    observation = result["contamination_observation"]
    assert observation["lookup_states"] == {}
    assert observation["contamination_signals"] == {}
    assert observation["contamination_signal_omissions"] == {}
    assert observation["conflicts"] == []
