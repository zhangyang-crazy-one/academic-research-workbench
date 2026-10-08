"""Issue #80: a paper method is callable only after actual sandbox qualification."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest
from arw_paper_method.method import (
    MAX_INPUT_BYTES,
    MethodError,
    canonical,
    parse,
    solve,
)
from arw_paper_method.qualification import (
    EXT,
    FIXTURE,
    ROOT,
    QualificationError,
    build_capsule,
    qualify,
    run_cases,
    verify,
)
from arw_paper_method.sandbox import probe_namespace, run_worker
from arw_paper_method.server import TOOL, PaperMethodServer

from arw.mcp_stdio import MODERN_VERSION


def _fixture():
    return json.loads(FIXTURE.read_text())


def _committed_capsule(tmp_path: Path) -> Path:
    commit = (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    )
    path = tmp_path / "capsule.json"
    path.write_bytes(canonical(build_capsule(commit)))
    return path


def _qualified(tmp_path: Path):
    capsule = _committed_capsule(tmp_path)
    receipt_path = tmp_path / "receipt.json"
    receipt = qualify(receipt_path, capsule_path=capsule)
    assert receipt["qualification"] == "PASS"
    assert verify(receipt_path, capsule_path=capsule) == receipt
    return capsule, receipt_path


def _request(method, identifier, params=None):
    return {
        "jsonrpc": "2.0",
        "id": identifier,
        "method": method,
        "params": params or {},
    }


def test_author_example_exact_matching_and_independent_stability():
    fixture = _fixture()
    result = solve(fixture["input"])
    assert result["matching"] == fixture["expected_matching"]
    assert result["stable_verified"] is True
    assert 1 <= result["proposal_count"] <= 16
    assert canonical(result) == canonical(solve(fixture["input"]))
    assert json.loads(run_worker(canonical(fixture["input"]))) == {
        "status": "executed",
        "result": result,
    }


@pytest.mark.parametrize(
    "value,code",
    [
        ({"proposers": [], "receivers": {}}, "invalid_type"),
        ({"proposers": {}, "receivers": {}}, "participant_range"),
        ({"proposers": {"x": ["A"]}, "receivers": {"A": ["y"]}}, "invalid_ranking"),
        (
            {"proposers": {"x": ["A"]}, "receivers": {"A": ["x"], "B": ["x"]}},
            "participant_range",
        ),
        (
            {"proposers": {"bad name": ["A"]}, "receivers": {"A": ["bad name"]}},
            "invalid_name",
        ),
    ],
)
def test_typed_domain_rejections(value, code):
    with pytest.raises(MethodError, match=code):
        solve(value)
    assert json.loads(run_worker(canonical(value))) == {
        "status": "failed",
        "reason_code": code,
    }


def test_duplicate_json_key_nonfinite_and_input_bound():
    with pytest.raises(MethodError, match="duplicate_json_key"):
        parse(b'{"proposers":{},"proposers":{},"receivers":{}}')
    with pytest.raises(MethodError, match="nonfinite_value"):
        parse(b'{"value":NaN}')
    with pytest.raises(MethodError, match="input_budget_exceeded"):
        parse(b" " * (MAX_INPUT_BYTES + 1))


def test_maximum_participants_bounded_and_namespace_real():
    names = [f"p{i}" for i in range(64)]
    receivers = [f"r{i}" for i in range(64)]
    case = {
        "proposers": {name: receivers for name in names},
        "receivers": {name: names for name in receivers},
    }
    result = json.loads(run_worker(canonical(case)))
    assert result["status"] == "executed"
    assert len(result["result"]["matching"]) == 64
    assert result["result"]["proposal_count"] <= 64 * 64
    namespaces = probe_namespace()
    assert namespaces["host_network_namespace"] != namespaces["child_network_namespace"]


def test_qualification_cases_and_injected_failure(tmp_path):
    assert all(case["status"] == "PASS" for case in run_cases())
    capsule = _committed_capsule(tmp_path)
    failed = tmp_path / "failed.json"
    result = qualify(failed, capsule_path=capsule, inject_failure=True)
    assert result["qualification"] == "FAIL"
    with pytest.raises(QualificationError, match="qualification_not_passed"):
        verify(failed, capsule_path=capsule)
    assert (
        PaperMethodServer(failed, capsule).handle(_request("tools/list", 1))["result"][
            "tools"
        ]
        == []
    )


def test_missing_receipt_and_metadata_tamper_hide_tool(tmp_path):
    capsule = _committed_capsule(tmp_path)
    missing = PaperMethodServer(tmp_path / "missing.json", capsule)
    assert missing.handle(_request("tools/list", 1))["result"]["tools"] == []
    assert (
        missing.handle(
            _request("tools/call", 2, {"name": TOOL, "arguments": _fixture()["input"]})
        )["error"]["code"]
        == -32601
    )
    receipt = tmp_path / "receipt.json"
    qualify(receipt, capsule_path=capsule)
    data = json.loads(capsule.read_text())
    data["paper"]["doi"] = "10.0000/tampered"
    capsule.write_bytes(canonical(data))
    hidden = PaperMethodServer(receipt, capsule)
    assert hidden.reason_code == "capsule_metadata_or_source_drift"
    assert hidden.handle(_request("tools/list", 3))["result"]["tools"] == []


def test_receipt_tamper_source_drift_and_environment_drift(tmp_path, monkeypatch):
    capsule, receipt = _qualified(tmp_path)
    server = PaperMethodServer(receipt, capsule)
    assert server.handle(_request("tools/list", 1))["result"]["tools"]
    original = receipt.read_bytes()
    receipt.write_bytes(original + b" ")
    assert server.handle(_request("tools/list", 2))["result"]["tools"] == []
    with pytest.raises(QualificationError, match="receipt_noncanonical"):
        verify(receipt, capsule_path=capsule)
    receipt.write_bytes(original)
    # A separate server sees environment drift even with unchanged receipt bytes.
    new_server = PaperMethodServer(receipt, capsule)
    import arw_paper_method.server as server_module

    monkeypatch.setattr(server_module, "environment", lambda: {"drift": True})
    assert new_server.handle(_request("tools/list", 3))["result"]["tools"] == []

    from arw_paper_method import qualification

    different = tmp_path / "different-root"
    relative = qualification.SOURCE_PATHS[0]
    altered = different / relative
    altered.parent.mkdir(parents=True)
    altered.write_bytes((ROOT / relative).read_bytes() + b"# drift\n")
    monkeypatch.setattr(qualification, "ROOT", different)
    with pytest.raises(QualificationError, match="source_file_unavailable"):
        qualification.validate_capsule(capsule)


def test_declared_pass_without_reexecuted_cases_cannot_enable(tmp_path, monkeypatch):
    capsule, receipt = _qualified(tmp_path)
    from arw_paper_method import qualification

    actual = qualification.run_cases

    def failing_cases():
        cases = actual()
        cases[0] = {
            "name": "network_namespace",
            "status": "FAIL",
            "reason_code": "injected_test_failure",
        }
        return cases

    monkeypatch.setattr(qualification, "run_cases", failing_cases)
    server = PaperMethodServer(receipt, capsule)
    assert server.reason_code == "qualification_replay_failed"
    assert server.handle(_request("tools/list", 1))["result"]["tools"] == []


def test_qualified_plan_execute_failed_and_output_schema(tmp_path):
    capsule, receipt = _qualified(tmp_path)
    server = PaperMethodServer(receipt, capsule)
    schema = json.loads((EXT / "schemas" / "output.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    input_case = _fixture()["input"]
    planned = server.invoke({**input_case, "mode": "plan"})
    executed = server.invoke(input_case)
    bad = deepcopy(input_case)
    bad["proposers"]["alpha"] = ["A"] * 4
    failed = server.invoke(bad)
    for value in (planned, executed, failed):
        jsonschema.validate(value, schema)
        assert value["input_sha256"]
        assert value["source_capsule_sha256"]
    assert planned["status"] == "planned" and planned["execution_observed"] is False
    assert planned["output_sha256"] is None
    assert executed["status"] == "executed" and executed["execution_observed"] is True
    assert executed["matching"] == _fixture()["expected_matching"]
    assert executed["output_sha256"]
    assert failed["status"] == "failed" and failed["execution_observed"] is True
    assert failed["reason_code"] == "invalid_ranking"


def test_real_stdio_old_and_new_protocol_and_base_opt_in(tmp_path):
    capsule, receipt = _qualified(tmp_path)
    assert (
        "extensions/paper-method/src/arw_paper_method"
        not in (ROOT / "pyproject.toml").read_text()
    )
    assert "stable_matching_gale_shapley_1962" not in (ROOT / ".mcp.json").read_text()
    arguments = _fixture()["input"]
    meta = {
        "io.modelcontextprotocol/protocolVersion": MODERN_VERSION,
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    frames = [
        _request("initialize", 1, {"protocolVersion": "2025-11-25"}),
        _request("tools/list", 2),
        _request("tools/call", 3, {"name": TOOL, "arguments": arguments}),
        _request("server/discover", 4, {"_meta": meta}),
        _request("tools/list", 5, {"_meta": meta}),
        _request(
            "tools/call",
            6,
            {"name": TOOL, "arguments": {**arguments, "mode": "plan"}, "_meta": meta},
        ),
    ]
    env = dict(os.environ, PYTHONPATH=f"{ROOT / 'src'}:{EXT / 'src'}")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "arw_paper_method.server",
            "serve",
            "--receipt",
            str(receipt),
            "--capsule",
            str(capsule),
        ],
        input=b"".join(canonical(frame) for frame in frames),
        capture_output=True,
        env=env,
        cwd=ROOT,
        timeout=10,
        check=True,
    )
    responses = [json.loads(line) for line in completed.stdout.splitlines()]
    assert [item["id"] for item in responses] == list(range(1, 7))
    assert responses[0]["result"]["protocolVersion"] == "2025-11-25"
    assert responses[1]["result"]["tools"][0]["name"] == TOOL
    assert responses[2]["result"]["structuredContent"]["status"] == "executed"
    assert responses[3]["result"]["supportedVersions"][0] == MODERN_VERSION
    assert responses[4]["result"]["tools"][0]["name"] == TOOL
    assert responses[5]["result"]["structuredContent"]["status"] == "planned"
    assert responses[5]["result"]["resultType"] == "complete"
