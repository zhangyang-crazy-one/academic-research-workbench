"""Opt-in MCP server: the method is listed only after actual qualification replay."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from arw.mcp_stdio import ProtocolError, StdioProtocol, run_stdio

from .method import MAX_INPUT_BYTES, canonical, digest, validate
from .qualification import (
    CAPSULE,
    QualificationError,
    environment,
    qualify,
    sha,
    validate_capsule,
    verify,
)
from .sandbox import SandboxError, run_worker

TOOL = "stable_matching_gale_shapley_1962"


def _tool() -> dict[str, Any]:
    return {
        "name": TOOL,
        "description": (
            "Qualified Gale-Shapley 1962 deferred acceptance for equal-sized, "
            "strict complete rankings (1–64 per side). No ties, quotas, "
            "roommates, or practical-market suitability claim. A plan is not execution."
        ),
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "required": ["proposers", "receivers"],
            "properties": {
                "proposers": {
                    "type": "object",
                    "minProperties": 1,
                    "maxProperties": 64,
                },
                "receivers": {
                    "type": "object",
                    "minProperties": 1,
                    "maxProperties": 64,
                },
                "mode": {"enum": ["plan", "execute"], "default": "execute"},
                "timeout_ms": {"type": "integer", "minimum": 1, "maximum": 2000},
            },
        },
        "outputSchema": json.loads(
            (
                Path(__file__).resolve().parents[2] / "schemas" / "output.schema.json"
            ).read_text()
        ),
    }


class PaperMethodServer:
    def __init__(self, receipt: Path, capsule: Path = CAPSULE) -> None:
        self.receipt_path = receipt
        self.capsule_path = capsule
        self.reason_code: str | None = None
        self.capsule_sha256: str | None = None
        self.receipt_sha256: str | None = None
        self.environment: dict | None = None
        try:
            verified = verify(receipt, capsule_path=capsule)
            self.capsule_sha256 = verified["source_capsule_sha256"]
            self.receipt_sha256 = sha(receipt.read_bytes())
            self.environment = verified["environment"]
        except (QualificationError, OSError, ValueError) as error:
            self.reason_code = getattr(error, "code", "qualification_unavailable")
        self.protocol = StdioProtocol(
            name="arw-paper-method-gale-shapley-1962",
            version="1.0.0",
            tools=self._tools,
            call_tool=self._call_tool,
            capabilities={"tools": {"listChanged": False}},
        )

    def _active(self) -> bool:
        if self.reason_code is not None:
            return False
        try:
            capsule_raw, _ = validate_capsule(self.capsule_path)
            if sha(capsule_raw) != self.capsule_sha256:
                raise QualificationError("capsule_drift")
            if sha(self.receipt_path.read_bytes()) != self.receipt_sha256:
                raise QualificationError("receipt_drift")
            if environment() != self.environment:
                raise QualificationError("environment_drift")
        except (QualificationError, OSError, ValueError) as error:
            self.reason_code = getattr(error, "code", "qualification_unavailable")
            return False
        return True

    def _tools(self) -> list[dict[str, Any]]:
        return [_tool()] if self._active() else []

    def handle(self, request: Mapping[str, Any]) -> dict[str, Any] | None:
        return self.protocol.handle(request)

    def _call_tool(self, params: Mapping[str, Any]) -> dict[str, Any]:
        if not self._active():
            raise ProtocolError(-32601, "paper method unqualified")
        if set(params) - {"name", "arguments", "_meta"} or params.get("name") != TOOL:
            raise ProtocolError(-32602, "unknown paper method tool")
        args = params.get("arguments")
        if not isinstance(args, Mapping):
            raise ProtocolError(-32602, "invalid arguments")
        result = self.invoke(dict(args))
        return {
            "content": [{"type": "text", "text": canonical(result).decode().strip()}],
            "structuredContent": result,
            "isError": result["status"] == "failed",
        }

    def invoke(self, args: dict) -> dict:
        try:
            raw_args = canonical(args)
        except (TypeError, ValueError):
            raise ProtocolError(-32602, "noncanonical arguments") from None
        base = {
            "schema_version": "arw.paper-method-result.v1",
            "input_sha256": digest(raw_args),
            "output_sha256": None,
            "source_capsule_sha256": self.capsule_sha256,
        }
        mode = args.get("mode", "execute")
        timeout_ms = args.get("timeout_ms", 2000)
        if set(args) - {"proposers", "receivers", "mode", "timeout_ms"} or mode not in (
            "plan",
            "execute",
        ):
            return {
                **base,
                "status": "failed",
                "execution_observed": False,
                "reason_code": "invalid_input_shape",
            }
        if type(timeout_ms) is not int or not 1 <= timeout_ms <= 2000:
            return {
                **base,
                "status": "failed",
                "execution_observed": False,
                "reason_code": "timeout_range",
            }
        method_input = {
            "proposers": args.get("proposers"),
            "receivers": args.get("receivers"),
        }
        if len(canonical(method_input)) > MAX_INPUT_BYTES:
            return {
                **base,
                "status": "failed",
                "execution_observed": False,
                "reason_code": "input_budget_exceeded",
            }
        if mode == "plan":
            try:
                validate(method_input)
            except ValueError as error:
                return {
                    **base,
                    "status": "failed",
                    "execution_observed": False,
                    "reason_code": getattr(error, "code", "invalid_input"),
                }
            return {**base, "status": "planned", "execution_observed": False}
        try:
            output = run_worker(canonical(method_input), timeout_ms=timeout_ms)
            value = json.loads(output)
        except SandboxError as error:
            return {
                **base,
                "status": "failed",
                "execution_observed": False,
                "reason_code": error.code,
            }
        except (ValueError, UnicodeError):
            return {
                **base,
                "status": "failed",
                "execution_observed": True,
                "reason_code": "invalid_worker_output",
            }
        base["output_sha256"] = sha(output)
        if value.get("status") != "executed":
            return {
                **base,
                "status": "failed",
                "execution_observed": True,
                "reason_code": value.get("reason_code", "method_failed"),
            }
        result = value["result"]
        return {
            **base,
            "status": "executed",
            "execution_observed": True,
            "matching": result["matching"],
            "proposal_count": result["proposal_count"],
            "stable_verified": result["stable_verified"],
        }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Opt-in qualified paper method")
    parser.add_argument("command", choices=("qualify", "status", "serve"))
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--capsule", type=Path, default=CAPSULE)
    parser.add_argument("--inject-test-failure", action="store_true")
    args = parser.parse_args(argv)
    if args.inject_test_failure and args.command != "qualify":
        parser.error("failure injection is only valid for qualify")
    if args.command == "qualify":
        try:
            result = qualify(
                args.receipt,
                capsule_path=args.capsule,
                inject_failure=args.inject_test_failure,
            )
        except (QualificationError, SandboxError, OSError) as error:
            print(
                json.dumps(
                    {
                        "status": "unqualified",
                        "reason_code": getattr(
                            error, "code", "qualification_unavailable"
                        ),
                    }
                ),
                file=sys.stderr,
            )
            return 2
        print(
            json.dumps(
                {
                    "status": "qualified"
                    if result["qualification"] == "PASS"
                    else "unqualified",
                    "receipt": str(args.receipt),
                    "receipt_sha256": result["receipt_sha256"],
                }
            )
        )
        return 0 if result["qualification"] == "PASS" else 2
    server = PaperMethodServer(args.receipt, args.capsule)
    if args.command == "status":
        print(
            json.dumps(
                {
                    "status": "qualified" if server._active() else "unqualified",
                    "reason_code": server.reason_code,
                }
            )
        )
        return 0 if server.reason_code is None else 2
    if server.reason_code:
        print(json.dumps({"paper_method_gate": server.reason_code}), file=sys.stderr)
    return run_stdio(server.handle)


if __name__ == "__main__":
    raise SystemExit(main())
