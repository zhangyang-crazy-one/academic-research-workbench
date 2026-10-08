"""Bounded, read-only selection audit CLI."""
from pathlib import Path

from arw.kernel.core.canonical import (
    canonical_json_bytes,
    sha256_hex,
    strict_json_loads,
)
from arw.selection_audit import (
    MAX_INPUT,
    PoolFixture,
    SelectionAuditError,
    SelectionReceipt,
    export,
    replay_fixture,
)


def configure(subparsers):
    parser = subparsers.add_parser("selection-audit", help="Export or replay retained candidate selection evidence.")
    actions = parser.add_subparsers(dest="selection_audit_command", required=True)
    e = actions.add_parser("export")
    e.add_argument("--run-root", required=True, type=Path)
    e.add_argument("--expected-head", required=True)
    e.add_argument("--plan-artifact", required=True)
    e.add_argument("--retrieval-artifact", required=True)
    e.add_argument("--ledger-artifact", required=True)
    e.add_argument("--reading-artifact")
    r = actions.add_parser("replay")
    r.add_argument("--fixture", type=Path)
    r.add_argument("--receipt", type=Path)
    r.add_argument("--run-root", type=Path)


def _read(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INPUT:
        raise SelectionAuditError("input is missing, unsafe, or over budget")
    raw = path.read_bytes()
    if len(raw) > MAX_INPUT:
        raise SelectionAuditError("input exceeds byte budget")
    value = strict_json_loads(raw)
    if not isinstance(value, dict):
        raise SelectionAuditError("input must be a JSON object")
    return value


def handle(args):
    if args.selection_audit_command == "export":
        return export(args.run_root, expected_head=args.expected_head,
                      plan_id=args.plan_artifact, retrieval_id=args.retrieval_artifact,
                      ledger_id=args.ledger_artifact, trace_id=args.reading_artifact)
    if (args.fixture is None) == (args.receipt is None):
        raise SelectionAuditError("replay requires exactly one fixture or receipt")
    if args.fixture is not None:
        fixture = PoolFixture.model_validate(_read(args.fixture))
        return replay_fixture(fixture)
    if args.run_root is None:
        raise SelectionAuditError("receipt replay requires a run root")
    receipt = SelectionReceipt.model_validate(_read(args.receipt))
    body = receipt.model_dump(mode="json", exclude={"receipt_sha256"})
    if sha256_hex(canonical_json_bytes(body)) != receipt.receipt_sha256:
        raise SelectionAuditError("receipt digest mismatch")
    result = export(args.run_root, expected_head=receipt.run_head_sha256,
                    plan_id=receipt.query_plan.artifact_id,
                    retrieval_id=receipt.retrieval_input.artifact_id,
                    ledger_id=receipt.candidate_ledger.artifact_id,
                    trace_id=receipt.reading_trace.artifact_id if receipt.reading_trace else None)
    if result != receipt.model_dump(mode="json"):
        raise SelectionAuditError("receipt is stale or does not replay")
    return result
