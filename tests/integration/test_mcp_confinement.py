from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests/fixtures/confinement"
ALLOWED_ROOT = FIXTURE_ROOT / "allowed"
OUTSIDE_SECRET = FIXTURE_ROOT / "outside/secret.txt"
NATIVE_BINARY = REPOSITORY_ROOT / ".file-base/bin/file-base"
SCHEMA_ROOT = REPOSITORY_ROOT / "schemas/v1"
EVIDENCE_ROOT = REPOSITORY_ROOT / "build/evidence/phase-01/confinement"
ROOT_CAPABILITY = "phase1-fixture"


@dataclass(frozen=True)
class ReadCase:
    case_id: str
    request: dict[str, object]
    denial_reason: str | None


def _request(**overrides: object) -> dict[str, object]:
    request: dict[str, object] = {
        "schema_version": "1.0.0",
        "allowed_root": ROOT_CAPABILITY,
        "relative_path": "paper.tex",
        "max_bytes": 4096,
        "max_lines": 200,
    }
    request.update(overrides)
    return request


CASES = [
    ReadCase("bounded-cjk-latex", _request(), None),
    ReadCase("parent-traversal", _request(relative_path="../outside/secret.txt"), "path_traversal"),
    ReadCase("absolute-outside", _request(relative_path=str(OUTSIDE_SECRET)), "absolute_path"),
    ReadCase("symlink-escape", _request(relative_path="escape-link"), "symlink_escape"),
    ReadCase(
        "unconfigured-root",
        _request(allowed_root="unconfigured-root", relative_path="allowed.md"),
        "root_denied",
    ),
    ReadCase("sensitive-env", _request(relative_path=".env"), "sensitive_path"),
    ReadCase(
        "byte-budget-over-ceiling",
        _request(relative_path="oversize.txt", max_bytes=4097),
        "budget_exceeded",
    ),
    ReadCase(
        "line-budget-over-ceiling",
        _request(relative_path="oversize.txt", max_lines=201),
        "budget_exceeded",
    ),
]


def _load_schema(name: str) -> dict[str, Any]:
    schema = json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return schema


def _rpc(identifier: int, method: str, params: dict[str, object]) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _write_evidence(
    case: ReadCase,
    result: subprocess.CompletedProcess[str],
    responses: list[dict[str, Any]],
    payload: dict[str, Any] | None,
) -> Path:
    case_root = EVIDENCE_ROOT / case.case_id
    shutil.rmtree(case_root, ignore_errors=True)
    case_root.mkdir(parents=True)
    (case_root / "command.json").write_text(
        json.dumps(
            {
                "argv": [".file-base/bin/file-base"],
                "cwd": "<isolated-working-directory>",
                "environment": {
                    "CBM_ALLOWED_ROOT": "<phase1-fixture-root>",
                    "CBM_ALLOWED_ROOT_ID": ROOT_CAPABILITY,
                    "CBM_CACHE_DIR": "<isolated-cache>",
                    "CBM_LOG_LEVEL": "error",
                },
                "transport": "json-rpc-2.0-line-delimited-stdio",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (case_root / "request.json").write_text(
        json.dumps(case.request, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (case_root / "stdout.log").write_text(result.stdout, encoding="utf-8")
    (case_root / "stderr.log").write_text(result.stderr, encoding="utf-8")
    (case_root / "status.txt").write_text(f"{result.returncode}\n", encoding="utf-8")
    (case_root / "responses.json").write_text(
        json.dumps(responses, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    verdict = {
        "case_id": case.case_id,
        "direct_native_process": True,
        "expected": "ok" if case.denial_reason is None else case.denial_reason,
        "observed_reason": None if payload is None else payload.get("reason"),
        "observed_status": None if payload is None else payload.get("status"),
        "platform_claim": "linux",
        "technical_qualification": (
            "PASS"
            if payload is not None
            and (
                (case.denial_reason is None and payload.get("status") == "ok")
                or (
                    case.denial_reason is not None
                    and payload.get("status") == "denied"
                    and payload.get("reason") == case.denial_reason
                )
            )
            else "FAIL"
        ),
    }
    (case_root / "verdict.json").write_text(
        json.dumps(verdict, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return case_root


def _invoke_native(case: ReadCase, tmp_path: Path) -> tuple[dict[str, Any], Path]:
    assert NATIVE_BINARY.is_file() and os.access(NATIVE_BINARY, os.X_OK)
    environment = {
        "CBM_ALLOWED_ROOT": str(ALLOWED_ROOT.resolve()),
        "CBM_ALLOWED_ROOT_ID": ROOT_CAPABILITY,
        "CBM_CACHE_DIR": str(tmp_path / "cache"),
        "CBM_LOG_LEVEL": "error",
        "HOME": str(tmp_path / "home"),
        "PATH": os.environ["PATH"],
    }
    requests = [
        _rpc(1, "tools/list", {}),
        _rpc(2, "tools/call", {"name": "read_file", "arguments": case.request}),
    ]
    result = subprocess.run(
        [str(NATIVE_BINARY)],
        cwd=tmp_path,
        env=environment,
        input="\n".join(requests) + "\n",
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )
    try:
        responses = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    except json.JSONDecodeError as error:
        pytest.fail(
            "invalid RED: direct native JSON-RPC framing failed instead of exposing the "
            f"missing confinement behavior: {error}\nstdout={result.stdout!r}"
        )
    payload: dict[str, Any] | None = None
    if len(responses) >= 2:
        text_items = responses[1].get("result", {}).get("content", [])
        if text_items and isinstance(text_items[0].get("text"), str):
            try:
                candidate = json.loads(text_items[0]["text"])
                if isinstance(candidate, dict):
                    payload = candidate
            except json.JSONDecodeError:
                pass
    evidence = _write_evidence(case, result, responses, payload)
    assert result.returncode == 0, (
        "invalid RED: native process failed before exercising the confinement capability\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert len(responses) == 2 and responses[0].get("id") == 1 and responses[1].get("id") == 2, (
        "invalid RED: native JSON-RPC request/response framing is not operational"
    )
    tools = responses[0].get("result", {}).get("tools", [])
    assert any(tool.get("name") == "read_file" for tool in tools), (
        "expected RED: the 0001-only native binary lacks the confined read_file capability"
    )
    assert payload is not None, (
        "expected RED: native read_file did not return the schema-shaped confinement payload"
    )
    return payload, evidence


def test_confinement_schemas_are_strict_and_phase1_budgeted() -> None:
    request_schema = _load_schema("mcp-read-request.schema.json")
    result_schema = _load_schema("mcp-read-result.schema.json")
    request_validator = jsonschema.Draft202012Validator(request_schema)
    result_validator = jsonschema.Draft202012Validator(result_schema)

    request_validator.validate(_request())
    assert list(request_validator.iter_errors(_request(max_bytes=4097)))
    assert list(request_validator.iter_errors(_request(max_lines=201)))
    assert list(request_validator.iter_errors({**_request(), "unknown": True}))

    denied = {
        "schema_version": "1.0.0",
        "status": "denied",
        "error_type": "access_denied",
        "reason": "path_traversal",
        "message": "request path leaves the configured root",
        "allowed_root": ROOT_CAPABILITY,
        "relative_path": "../outside/secret.txt",
        "platform_claim": "linux",
    }
    result_validator.validate(denied)
    assert list(result_validator.iter_errors({**denied, "content": "forbidden"}))


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.case_id)
def test_direct_native_confinement_matrix(case: ReadCase, tmp_path: Path) -> None:
    assert platform.system() == "Linux", "Phase 1 claims only the Linux confinement baseline"
    payload, evidence = _invoke_native(case, tmp_path)
    _load_schema("mcp-read-result.schema.json")
    jsonschema.Draft202012Validator(
        _load_schema("mcp-read-result.schema.json")
    ).validate(payload)
    assert payload["platform_claim"] == "linux"

    if case.denial_reason is None:
        expected = (ALLOWED_ROOT / "paper.tex").read_text(encoding="utf-8")
        assert payload == {
            "schema_version": "1.0.0",
            "status": "ok",
            "allowed_root": ROOT_CAPABILITY,
            "relative_path": "paper.tex",
            "content": expected,
            "bytes_read": len(expected.encode("utf-8")),
            "lines_read": len(expected.splitlines()),
            "truncated": False,
            "platform_claim": "linux",
        }
    else:
        assert payload["status"] == "denied"
        assert payload["error_type"] == "access_denied"
        assert payload["reason"] == case.denial_reason
        assert "content" not in payload

    canary = OUTSIDE_SECRET.read_text(encoding="utf-8").strip().encode()
    assert canary
    for path in evidence.rglob("*"):
        if path.is_file():
            assert canary not in path.read_bytes(), f"outside secret leaked into {path}"
