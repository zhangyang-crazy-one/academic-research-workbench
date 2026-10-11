"""Actual local processes/HTTP transport, without invoking a paid model."""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from arw.kernel.core.canonical import canonical_json_bytes
from arw.kernel.execution.configured_harness import (
    ConfiguredHarnessAdapter,
    identity_receipt_from_observation,
)
from arw.kernel.execution.execution import ExecutionPolicySnapshot
from arw.kernel.execution.harness_config import HarnessConfiguration, HarnessEntry
from arw.kernel.execution.orchestration import OrchestrationService
from arw.kernel.ledger.journal import replay_run
from arw.kernel.state.models import RuntimeCommandRequest

from .test_orchestration_lifecycle import RUN_ID, AssignmentSpec, _run

pytestmark = pytest.mark.requires_harness_isolation


def _envelope(request):
    artifact = "actual local transport result\n"
    proposal = {
        **request["proposal_template"],
        "status": "completed",
        "requested_next_action": "accept",
        "summary": "local synthetic test",
        "artifacts": [
            {
                "relative_path": "report.txt",
                "sha256": hashlib.sha256(artifact.encode()).hexdigest(),
                "media_type": "text/plain",
                "schema_id": "arw.test-report.v1",
                "byte_count": len(artifact.encode()),
            }
        ],
    }
    return {
        "schema_version": "arw.harness-output.v1",
        "proposal": proposal,
        "artifacts": {"report.txt": artifact},
    }


def _prepared(tmp_path, entry, *, timeout=10):
    root, prepare_request = _run(tmp_path)
    config = HarnessConfiguration(
        schema_version="arw.harness-config.v1",
        default="selected",
        harnesses={"selected": entry},
    )
    adapter = ConfiguredHarnessAdapter(
        entry,
        config_sha256=config.config_sha256,
        config_snapshot=canonical_json_bytes(config.model_dump(mode="json")),
        config_base=tmp_path,
        environment={"TEST_MODEL_KEY": "test-only-secret-123456"},
    )
    service = OrchestrationService(
        root,
        adapter=adapter,
        policy=ExecutionPolicySnapshot(
            attempt_timeout_s=timeout, cancel_grace_s=0.1, max_attempts_per_assignment=1
        ),
    )
    prepared = service.prepare(
        prepare_request,
        assignments=(
            AssignmentSpec(
                assignment_id="assignment.harness-001",
                stage_id="preparing",
                task_id="task.harness-001",
                role_id="research_architect",
                worker_identity_id="worker.harness-001",
                acceptance_key=(0, 0),
            ),
        ),
    )
    request = RuntimeCommandRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": RUN_ID,
            "event_id": "evt-00000000-0000-4000-8000-000000000409",
            "command_id": "cmd-00000000-0000-4000-8000-000000000409",
            "expected_revision": prepared.state.accepted_revision,
            "occurred_at": "2026-07-15T01:05:00Z",
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
        }
    )
    return root, adapter, service, prepared, request


@pytest.fixture
def model_server():
    records = []
    state = {"mode": "ok"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            records.append((body, dict(self.headers)))
            if state["mode"] == "redirect":
                self.send_response(307)
                self.send_header("Location", self.path)
                self.end_headers()
                return
            if "input" in body:
                request = json.loads(body["input"])
            else:
                request = json.loads(body["messages"][1]["content"])
            envelope = _envelope(request)
            if state["mode"] == "forged":
                envelope["proposal"]["attempt_id"] = "attempt.someone-else"
            if state["mode"] == "path":
                envelope["proposal"]["artifacts"][0]["relative_path"] = "../escape"
            if state["mode"] == "digest":
                envelope["artifacts"]["report.txt"] = "altered bytes"
            text = json.dumps(envelope)
            if state["mode"] == "secret":
                text = text.replace("local synthetic test", "test-only-secret-123456")
            if "input" in body:
                reply = {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": text}],
                        }
                    ],
                }
            else:
                reply = {
                    "choices": [{"finish_reason": "stop", "message": {"content": text}}]
                }
            if state["mode"] == "tool":
                reply = {
                    "status": "completed",
                    "output": [{"type": "function_call", "name": "evil"}],
                }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(reply).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/model", records, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("protocol", ["responses", "chat_completions"])
def test_real_http_transport_parent_admission_and_neutral_identity(
    tmp_path, model_server, protocol
):
    endpoint, records, _state = model_server
    entry = HarnessEntry(
        kind="api",
        endpoint=endpoint,
        model="synthetic-test-model",
        protocol=protocol,
        api_key_env="TEST_MODEL_KEY",
    )
    root, adapter, service, prepared, request = _prepared(tmp_path, entry)
    report = asyncio.run(service.dispatch(request, prepared))
    assert report.outcomes[0].status == "completed"
    assert len(report.state.accepted_proposals) == 1
    assert len(records) == 1
    body, headers = records[0]
    assert body["store"] is False and body["stream"] is False
    assert headers["Authorization"] == "Bearer test-only-secret-123456"
    assert "test-only-secret-123456" not in json.dumps(body)
    assert "phase four input" in json.dumps(body)
    assert not {"tools", "conversation", "previous_response_id"}.intersection(body)
    outcome = report.outcomes[0].attempts[0]
    path = (
        root / "attempts" / outcome.attempt_id / "observations/harness-observation.json"
    )
    receipt = identity_receipt_from_observation(
        path,
        receipt_id="receipt.harness-001",
        evidence_sha256=(report.state.ledger_head_sha256,),
    )
    assert receipt.harness_kind == "api" and not hasattr(receipt, "codex_version")
    identity_request = request.model_copy(
        update={
            "event_id": "evt-00000000-0000-4000-8000-000000000410",
            "command_id": "cmd-00000000-0000-4000-8000-000000000410",
            "expected_revision": report.state.accepted_revision,
        }
    )
    accepted = service.record_host_identity(identity_request, receipt)
    assert accepted.accepted
    assert (
        replay_run(root).events[-1].payload.receipt.receipt_sha256
        == receipt.receipt_sha256
    )
    assert not adapter._processes
    assert not list(root.glob("attempts/*/scratch/harness-*"))
    assert all(
        b"test-only-secret-123456" not in p.read_bytes()
        for p in root.rglob("*")
        if p.is_file()
    )
    wire = path.parent / "wire-request.json"
    observed = json.loads(path.read_bytes())
    assert (
        hashlib.sha256(wire.read_bytes()).hexdigest() == observed["wire_request_sha256"]
    )
    assert json.loads(wire.read_bytes()) == body
    (path.parent / "wire-response.json").write_text("{}")
    assert replay_run(root).recovery_health != "healthy"


@pytest.mark.parametrize(
    "mode", ["forged", "path", "digest", "secret", "redirect", "tool"]
)
def test_http_failures_never_admitted(tmp_path, model_server, mode):
    endpoint, records, state = model_server
    state["mode"] = mode
    entry = HarnessEntry(
        kind="api",
        endpoint=endpoint,
        model="synthetic-test-model",
        api_key_env="TEST_MODEL_KEY",
    )
    root, _adapter, service, prepared, request = _prepared(tmp_path, entry)
    report = asyncio.run(service.dispatch(request, prepared))
    assert report.outcomes[0].status != "completed"
    assert not report.state.accepted_proposals
    assert len(records) == 1  # no redirects or implicit retries
    assert not list(root.glob("attempts/*/result/proposal.json"))
    assert all(
        b"test-only-secret-123456" not in p.read_bytes()
        for p in root.rglob("*")
        if p.is_file()
    )


def test_command_driver_actual_namespace_and_parent_admission(tmp_path):
    driver = tmp_path / "driver.py"
    driver.write_text("""import json, sys, hashlib, os
r = json.load(sys.stdin)
assert not os.path.exists(sys.argv[1])
assert os.environ["HOME"] == "/work/home"
assert "TEST_MODEL_KEY" not in os.environ
assert r["inputs"][0]["text"] == "phase four input\\n"
assert r["harness_parameters"] == {"platform_model": "platform-authenticated-model"}
p = r["proposal_template"]
a = "driver result\\n"
p.update(status="completed", requested_next_action="accept", summary="driver result",
    artifacts=[dict(relative_path="report.txt", sha256=hashlib.sha256(a.encode()).hexdigest(),
    byte_count=len(a.encode()), schema_id="arw.test-report.v1", media_type="text/plain")])
print(json.dumps(dict(schema_version="arw.harness-output.v1", proposal=p, artifacts={"report.txt":a})))
""")
    entry = HarnessEntry(
        kind="command",
        command=("/usr/bin/python3", str(driver), str(tmp_path / "run")),
        runtime_roots=(str(driver),),
        parameters={"platform_model": "platform-authenticated-model"},
    )
    root, adapter, service, prepared, request = _prepared(tmp_path, entry)
    report = asyncio.run(service.dispatch(request, prepared))
    assert report.outcomes[0].status == "completed"
    assert len(report.state.accepted_proposals) == 1
    assert not adapter._processes
    assert not list(root.glob("attempts/*/scratch/harness-*"))


@pytest.mark.parametrize("mode", ["stall", "oversize"])
def test_command_deadline_and_output_bound(tmp_path, mode):
    driver = tmp_path / "driver.py"
    driver.write_text(
        "import sys,time\nsys.stdin.read()\n"
        + ("time.sleep(100)" if mode == "stall" else 'sys.stdout.write("x" * 9000000)')
    )
    entry = HarnessEntry(
        kind="command",
        command=("/usr/bin/python3", str(driver)),
        runtime_roots=(str(driver),),
    )
    root, adapter, service, prepared, request = _prepared(
        tmp_path, entry, timeout=0.5 if mode == "stall" else 10
    )
    report = asyncio.run(service.dispatch(request, prepared))
    assert report.outcomes[0].status != "completed"
    assert not report.state.accepted_proposals and not adapter._processes
    assert not list(root.glob("attempts/*/scratch/harness-*"))


def test_force_termination_reaps_real_process_when_cooperative_signal_unavailable(
    tmp_path,
):
    driver = tmp_path / "driver.py"
    driver.write_text(
        "import signal,time,sys,subprocess\n"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN)\nsys.stdin.read()\n"
        'subprocess.Popen([sys.executable,"-c","import time; time.sleep(100)"])\n'
        "time.sleep(100)\n"
    )
    entry = HarnessEntry(
        kind="command",
        command=("/usr/bin/python3", str(driver)),
        runtime_roots=(str(driver),),
    )
    root, adapter, service, prepared, request = _prepared(tmp_path, entry, timeout=0.5)

    async def unavailable_cooperative_signal(_spec):
        # Model a lost cooperative request; the force operation remains the real adapter.
        return None

    adapter.request_cancel = unavailable_cooperative_signal

    async def run():
        dispatched = asyncio.create_task(service.dispatch(request, prepared))
        for _ in range(100):
            if adapter._processes:
                break
            await asyncio.sleep(0.01)
        process = next(iter(adapter._processes.values()))
        report = await dispatched
        assert process.returncode is not None
        return report

    report = asyncio.run(run())
    outcome = report.outcomes[0].attempts[0]
    assert outcome.force_termination_requested and outcome.status == "force_terminated"
    assert not adapter._processes and not report.state.accepted_proposals
    assert not list(root.glob("attempts/*/scratch/harness-*"))


def test_cli_mixes_external_command_and_api_without_codex(
    tmp_path, model_server, monkeypatch, capfd
):
    from arw.cli import main
    from arw.kernel.core.canonical import canonical_json_bytes
    from arw.kernel.execution.execution import DeterministicFakeAdapter
    from arw.kernel.execution.harness_config import load_harness_configuration

    endpoint, records, _ = model_server
    driver = tmp_path / "driver.py"
    driver.write_text(
        'import sys,json,hashlib\nr=json.load(sys.stdin)\np=r["proposal_template"]\n'
        'a="command result"\np.update(status="completed",requested_next_action="accept",summary="actual driver",'
        'artifacts=[dict(relative_path="report.txt",sha256=hashlib.sha256(a.encode()).hexdigest(),'
        'byte_count=len(a.encode()),media_type="text/plain",schema_id="arw.test-report.v1")])\n'
        'print(json.dumps(dict(schema_version="arw.harness-output.v1",proposal=p,artifacts={"report.txt":a})))'
    )
    root, prepare_request = _run(tmp_path)
    service = OrchestrationService(root, adapter=DeterministicFakeAdapter({}))
    prepared = service.prepare(
        prepare_request,
        assignments=tuple(
            AssignmentSpec(
                assignment_id=f"assignment.mixed-{index}",
                stage_id="preparing",
                task_id=f"task.mixed-{index}",
                role_id=role,
                worker_identity_id=f"worker.mixed-{index}",
                acceptance_key=(0, index),
            )
            for index, role in enumerate(("research_architect", "domain_reviewer"))
        ),
    )
    request = RuntimeCommandRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": RUN_ID,
            "event_id": "evt-00000000-0000-4000-8000-000000000409",
            "command_id": "cmd-00000000-0000-4000-8000-000000000409",
            "expected_revision": prepared.state.accepted_revision,
            "occurred_at": "2026-07-15T01:05:00Z",
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
        }
    )
    request_file = tmp_path / "request.json"
    request_file.write_bytes(canonical_json_bytes(request.model_dump(mode="json")))
    config_file = tmp_path / "harnesses.json"
    config_file.write_text(
        json.dumps(
            {
                "schema_version": "arw.harness-config.v1",
                "default": "driver",
                "harnesses": {
                    "driver": {
                        "kind": "command",
                        "command": ["/usr/bin/python3", str(driver)],
                        "runtime_roots": [str(driver)],
                    },
                    "api": {
                        "kind": "api",
                        "endpoint": endpoint,
                        "model": "synthetic-test-model",
                    },
                },
                "roles": {"domain_reviewer": "api"},
            }
        )
    )

    def forbidden(*_):
        raise AssertionError("non-Codex run must not discover native Codex")

    monkeypatch.setattr("arw.cli._verified_dispatch_adapter", forbidden)
    config = load_harness_configuration(config_file)
    assert (
        main(
            [
                "orchestration-dispatch",
                "--run-root",
                str(root),
                "--request",
                str(request_file),
                "--harness-config",
                str(config_file),
                "--harness-config-sha256",
                config.config_sha256,
            ]
        )
        == 0
    )
    result = json.loads(capfd.readouterr().out)
    assert result["harness_config_sha256"] == config.config_sha256
    assert "integration_lock_sha256" not in result
    assert len(result["outcomes"]) == 2 and len(records) == 1
    assert len(service.runtime.read_state().accepted_proposals) == 2


def test_missing_credentials_make_zero_http_requests(tmp_path, model_server):
    endpoint, records, _ = model_server
    entry = HarnessEntry(
        kind="api",
        endpoint=endpoint,
        model="synthetic-test-model",
        api_key_env="TEST_MODEL_KEY",
    )
    _root, adapter, service, prepared, request = _prepared(tmp_path, entry)
    adapter.environment = {}
    report = asyncio.run(service.dispatch(request, prepared))
    assert not report.state.accepted_proposals and not records
    assert "TEST_MODEL_KEY" in report.outcomes[0].attempts[0].error


def test_drifted_input_is_blocked_before_http(tmp_path, model_server):
    endpoint, records, _ = model_server
    entry = HarnessEntry(kind="api", endpoint=endpoint, model="synthetic-test-model")
    root, _adapter, service, prepared, request = _prepared(tmp_path, entry)
    (root / "input/source.txt").write_text("unfrozen replacement")
    report = asyncio.run(service.dispatch(request, prepared))
    assert not report.state.accepted_proposals and not records


def test_real_v2_observations_prepare_formal_panel_without_codex_fields(
    tmp_path, model_server
):
    from .test_orchestration_panels import ROLES, _request

    endpoint, records, _ = model_server
    root, prepare_request = _run(tmp_path)
    entry = HarnessEntry(kind="api", endpoint=endpoint, model="synthetic-test-model")
    config = HarnessConfiguration(
        schema_version="arw.harness-config.v1",
        default="selected",
        harnesses={"selected": entry},
    )
    adapter = ConfiguredHarnessAdapter(
        entry,
        config_sha256=config.config_sha256,
        config_snapshot=canonical_json_bytes(config.model_dump(mode="json")),
        config_base=tmp_path,
        environment={},
    )
    service = OrchestrationService(root, adapter=adapter)
    prepared = service.prepare(
        prepare_request,
        assignments=tuple(
            AssignmentSpec(
                assignment_id=f"assignment.identity-{index}",
                stage_id="preparing",
                task_id=f"task.identity-{index}",
                role_id=role,
                worker_identity_id=(
                    "worker.editorial-synthesizer"
                    if role == "editorial_synthesizer"
                    else f"worker.{role}"
                ),
                acceptance_key=(0, index),
            )
            for index, role in enumerate((*ROLES, "editorial_synthesizer"))
        ),
    )
    report = asyncio.run(
        service.dispatch(_request(prepared.state.accepted_revision, 600), prepared)
    )
    assert len(report.state.accepted_proposals) == 5 and len(records) == 5
    receipts = {}
    identities = {}
    for index, outcome in enumerate(report.outcomes, 610):
        state = service.runtime.read_state()
        receipt = identity_receipt_from_observation(
            root
            / "attempts"
            / outcome.attempts[0].attempt_id
            / "observations/harness-observation.json",
            receipt_id=f"receipt.identity-{index}",
            evidence_sha256=(state.ledger_head_sha256,),
        )
        assert service.record_host_identity(
            _request(state.accepted_revision, index), receipt
        ).accepted
        receipts[receipt.role_id] = receipt.receipt_sha256
        identities[receipt.role_id] = {
            "worker_identity_id": receipt.worker_identity_id,
            "host_agent_id": receipt.host_agent_id,
            "isolated": True,
            "role_ids": [receipt.role_id],
            "identity_receipt_sha256": receipt.receipt_sha256,
        }
    state = service.runtime.read_state()
    panel = service.prepare_formal_panel(
        _request(state.accepted_revision, 620),
        panel_id="panel.api-test",
        subject_sha256="a" * 64,
        rubric_sha256="b" * 64,
        reviewer_identities={role: identities[role] for role in ROLES},
        synthesizer_identity=identities["editorial_synthesizer"],
    )
    assert len(panel.reviewer_assignments) == 4
    assert all(
        seat.identity_receipt_sha256 in receipts.values()
        for seat in panel.reviewer_assignments
    )


def test_v2_identity_rejects_forged_observation_binding(tmp_path, model_server):
    endpoint, _records, _ = model_server
    entry = HarnessEntry(kind="api", endpoint=endpoint, model="synthetic-test-model")
    root, _adapter, service, prepared, request = _prepared(tmp_path, entry)
    report = asyncio.run(service.dispatch(request, prepared))
    attempt_id = report.outcomes[0].attempts[0].attempt_id
    receipt = identity_receipt_from_observation(
        root / "attempts" / attempt_id / "observations/harness-observation.json",
        receipt_id="receipt.forged",
        evidence_sha256=(report.state.ledger_head_sha256,),
    )
    receipt = receipt.model_copy(update={"request_sha256": "b" * 64})
    identity_request = request.model_copy(
        update={
            "event_id": "evt-00000000-0000-4000-8000-000000000410",
            "command_id": "cmd-00000000-0000-4000-8000-000000000410",
            "expected_revision": report.state.accepted_revision,
        }
    )
    outcome = service.record_host_identity(identity_request, receipt)
    assert (
        not outcome.accepted and outcome.rejection.code == "host-observation-mismatch"
    )
