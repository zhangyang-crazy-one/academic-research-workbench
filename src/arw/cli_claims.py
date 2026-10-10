"""Explicit claims registration and read-only advisory graph commands."""

from pathlib import Path


def configure(subparsers):
    parser = subparsers.add_parser(
        "claims", help="Project accepted claims and evidence at explicit log prefixes."
    )
    actions = parser.add_subparsers(dest="claims_command", required=True)
    for name in ("graph", "register", "evidence", "attest", "anchor"):
        action = actions.add_parser(name)
        action.add_argument("--project-root", required=True, type=Path)
        action.add_argument("--run-root", action="append", type=Path, default=[])
        if name != "anchor":
            action.add_argument("--expected-head", required=name != "graph")
        if name == "graph":
            action.add_argument(
                "--as-of",
                type=Path,
                help="Saved snapshot manifest or graph JSON, never a single revision.",
            )
            action.add_argument("--hard-check", action="store_true")
            action.add_argument(
                "--at-time",
                help="Explicit UTC time for applicability; historical authority uses anchor time.",
            )
            action.add_argument("--json", action="store_true")
        if name in ("register", "evidence"):
            action.add_argument("--registration", required=True, type=Path)
            action.add_argument("--author-confirmed", action="store_true")
        if name == "attest":
            action.add_argument("--claim-id", required=True)
            action.add_argument("--author-id")
            action.add_argument(
                "--authority",
                type=Path,
                help="Accepted authority identity for an authenticated intent.",
            )
            action.add_argument(
                "--request", type=Path, help="Parent anchor RuntimeCommandRequest JSON."
            )
            action.add_argument("--statement", required=True)
            action.add_argument("--scope", required=True)
            action.add_argument("--policy-version", required=True)
            action.add_argument("--author-confirmed", action="store_true")
        if name == "anchor":
            action.add_argument("--sequence", required=True, type=int)
            action.add_argument("--request", required=True, type=Path)
            action.add_argument("--author-confirmed", action="store_true")


def _read(path):
    from arw.kernel.core.canonical import strict_json_loads
    from arw.kernel.ledger.claim_graph import ClaimGraphError

    with path.open("rb") as handle:
        raw = handle.read(2_097_153)
    if len(raw) > 2_097_152:
        raise ClaimGraphError("limit_exceeded", "claims input exceeds byte budget")
    return strict_json_loads(raw)


def handle(args):
    from arw.kernel.ledger.claim_graph import (
        ClaimGraphError,
        attest_declared,
        graph,
        register_claim,
    )
    from arw.kernel.state.claim_graph import ClaimRegistration, SnapshotManifest

    roots = tuple(args.run_root)
    if args.claims_command == "graph":
        vector = _read(args.as_of) if args.as_of else None
        if isinstance(vector, dict) and "snapshot_manifest" in vector:
            vector = vector["snapshot_manifest"]
        return graph(
            args.project_root,
            run_roots=roots,
            as_of=SnapshotManifest.model_validate(vector) if vector else None,
            expected_head=args.expected_head,
            hard_check=args.hard_check,
            evaluation_time=args.at_time,
            figure_verifier=_figure_verifier(),
        )
    if not args.author_confirmed:
        raise ClaimGraphError(
            "author_confirmation_missing",
            "claim writes require an explicit author assertion",
        )
    if args.claims_command == "anchor":
        from arw.kernel.ledger.claim_authority import anchor_attestation
        from arw.kernel.state.models import RuntimeCommandRequest

        return anchor_attestation(
            args.project_root,
            run_roots=roots,
            sequence=args.sequence,
            request=RuntimeCommandRequest.model_validate(_read(args.request)),
        )
    if args.claims_command == "attest":
        if args.authority:
            from arw.kernel.ledger.claim_authority import attest_authenticated
            from arw.kernel.state.claim_authentication import AuthenticatedAuthority
            from arw.kernel.state.models import RuntimeCommandRequest

            if not args.request:
                raise ClaimGraphError(
                    "anchor_request_missing",
                    "authenticated intent requires a parent anchor request",
                )
            return attest_authenticated(
                args.project_root,
                run_roots=roots,
                expected_head=args.expected_head,
                claim_id=args.claim_id,
                authority=AuthenticatedAuthority.model_validate(_read(args.authority)),
                statement=args.statement,
                scope=args.scope,
                policy_version=args.policy_version,
                request=RuntimeCommandRequest.model_validate(_read(args.request)),
            )
        if not args.author_id:
            raise ClaimGraphError(
                "author_id_missing", "declared confirmation requires an asserted author"
            )
        return attest_declared(
            args.project_root,
            run_roots=roots,
            expected_head=args.expected_head,
            claim_id=args.claim_id,
            author_id=args.author_id,
            statement=args.statement,
            scope=args.scope,
            policy_version=args.policy_version,
        )
    return register_claim(
        args.project_root,
        ClaimRegistration.model_validate(_read(args.registration)),
        run_roots=roots,
        expected_head=args.expected_head,
        evidence_update=args.claims_command == "evidence",
    )


def _figure_verifier():
    """Optional renderer wiring stays at the composition boundary."""
    import os

    from arw.composition import default_router
    from arw.kernel.capabilities import CapabilityUnavailable

    value = os.environ.get("ARW_PLUGIN_MANIFEST")
    if value:
        manifest = Path(value)
    elif os.environ.get("ARW_PLUGIN_ROOT"):
        raise ValueError("plugin_manifest_missing")
    else:
        candidate = Path(__file__).resolve().parents[2] / ".codex-plugin/plugin.json"
        manifest = candidate if candidate.is_file() else None
    try:
        provider = default_router(plugin_manifest=manifest).resolve(
            "research.artifact.inspect"
        )
    except CapabilityUnavailable:
        return None
    return getattr(provider, "verify_plot_receipt", None)
