"""Offline experiment-claim acceptance over provenance already stored in a run."""

from pathlib import Path

from arw.kernel.core.canonical import strict_json_loads

MAX_CONTRACT_FILE_BYTES = 262_144


def configure(subparsers):
    parser = subparsers.add_parser(
        "experiment",
        help="Accept numeric experiment claims against a versioned contract (offline, no execution).",
    )
    actions = parser.add_subparsers(dest="experiment_command", required=True)
    accept = actions.add_parser(
        "accept",
        help="Evaluate one contract version against stored provenance and its raw CSV outputs.",
    )
    accept.add_argument("--run-root", type=Path, required=True)
    accept.add_argument("--contract", type=Path, required=True, help="ExperimentContract JSON (at most 256 KiB).")
    accept.add_argument("--provenance-sha256", required=True)
    accept.add_argument(
        "--publish",
        action="store_true",
        help="Write the contract and result write-once under experiment/ in the run root.",
    )
    replay = actions.add_parser("replay", help="Re-evaluate a published result and require identical bytes.")
    replay.add_argument("--run-root", type=Path, required=True)
    replay.add_argument("--result-sha256", required=True)


def _read_contract(path: Path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("contract file is missing or unsafe")
    data = path.read_bytes()
    if len(data) > MAX_CONTRACT_FILE_BYTES:
        raise ValueError("contract file exceeds 256 KiB")
    return strict_json_loads(data)


def handle(args):
    from arw.kernel.artifacts.experiment_acceptance import (
        evaluate_experiment_acceptance,
        load_experiment_acceptance,
        load_experiment_contract,
        publish_experiment_acceptance,
        publish_experiment_contract,
        replay_experiment_acceptance,
        seal_experiment_contract,
    )
    from arw.kernel.artifacts.experiment_provenance import load_experiment_provenance

    root = args.run_root
    if args.experiment_command == "accept":
        contract = seal_experiment_contract(_read_contract(args.contract))
        provenance = load_experiment_provenance(root, args.provenance_sha256)
        # Ledger-ordered timing evidence is not available from the CLI, so a
        # "predeclared" contract is reported as unverified rather than trusted.
        result = evaluate_experiment_acceptance(contract, provenance, root)
        output = {
            "status": "evaluated",
            "contract_sha256": contract.contract_sha256,
            "result_sha256": result.result_sha256,
            "result": result.model_dump(mode="json", exclude_none=True),
        }
        if args.publish:
            output["contract_path"] = publish_experiment_contract(root, contract).relative_to(root).as_posix()
            output["result_path"] = publish_experiment_acceptance(root, result).relative_to(root).as_posix()
        return output
    recorded = load_experiment_acceptance(root, args.result_sha256)
    contract = load_experiment_contract(root, recorded.contract_sha256)
    provenance = load_experiment_provenance(root, recorded.provenance_sha256)
    replay_experiment_acceptance(recorded, contract, provenance, root)
    return {
        "status": "replayed",
        "result_sha256": recorded.result_sha256,
        "overall_status": recorded.overall_status,
    }
